"""Characters (CAIHuman): model template resolution, default attachments, sockets, skin export."""
import os
import struct

import numpy as np
import pytest

import export_models
import ltb


def human(template, **props):
    """A CAIHuman level object as export_level encodes it."""
    ps = [{"k": "ModelTemplate", "t": "s", "s": template, "v": []}]
    for k, v in props.items():
        if isinstance(v, bool):
            ps.append({"k": k, "t": "b", "s": "", "v": [1.0 if v else 0.0]})
        else:
            ps.append({"k": k, "t": "s", "s": v, "v": []})
    return {"cls": "CAIHuman", "name": "ai", "pos": [0, 0, 0], "rot": [0, 0, 0], "props": ps}


def test_character_resolves_its_model_template(extracted):
    r = export_models.Resolver(extracted)
    file, skins, styles = r.resolve(human("IC_Regular"))
    assert file == "chars/models/ic_regular.ltb"
    assert skins == ["chars/skins/ic_torso.dtx", "chars/skins/ic_legs.dtx", "chars/skins/specular.dtx"]
    assert styles == ["chars/rs/ic_rs.ltb", "rs/fullbrighton_alpha.ltb"]


def test_hidden_character_is_not_shown(extracted):
    r = export_models.Resolver(extracted)
    assert r.resolve(human("IC_Regular", StartHidden=True)) is None
    assert r.resolve(human("IC_Regular", StartHidden=False)) is not None


def test_character_gets_its_template_default_attachments(extracted):
    r = export_models.Resolver(extracted)
    atts = r.attachments(human("IC_Regular"))
    assert len(atts) == 13
    assert atts[0] == ("LeftFoot", "attachments/models/ic_l_foot_1.ltb",
                       ["chars/skins/ic_sheilds.dtx", "tex/chrome.dtx"], ["chars/rs/kernel_shell.ltb"])
    assert [a[0] for a in atts][-2:] == ["LeftHand2", "RightHand2"]


def test_level_attachments_take_their_position_before_the_defaults(extracted):
    r = export_models.Resolver(extracted)
    # Head = SoftHat from the level; IC_Shield's default Head attachment (IC_L2_Head) is then skipped
    # (CAttachments::Attach: position already occupied). A weapon takes its position too.
    atts = r.attachments(human("IC_Shield", Head="SoftHat", RightHand2="ICRegularDisc", LeftHand="<none>"))
    by_pos = {a[0]: a[1] for a in atts}
    assert by_pos["Head"] == "attachments/models/softhat.ltb"
    assert by_pos["RightHand2"] == "weapons/disc/models_hh/ic_disk_hh.ltb"
    assert by_pos["LeftHand2"] == r.attachments(human("IC_Shield"))[15][1]


def test_attached_explosions_are_not_drawn(extracted):
    # Seeker's defaults are AttachedExplosion objects (an Explosion: OT_NORMAL, no model drawn).
    r = export_models.Resolver(extracted)
    assert r.attachments(human("Seeker")) == []


def test_use_default_attachments_off(extracted):
    r = export_models.Resolver(extracted)
    assert r.attachments(human("IC_Regular", UseDefaultAttachments=False)) == []


def read_skin(out_root, rel):
    """The exported model's skin: per vertex [(bone, weight), ...] from the .bin's skin stream."""
    with open(os.path.join(out_root, "models", rel + ".bin"), "rb") as f:
        b = f.read()
    assert b[:4] == b"TRMD"
    _version, nv, ni, ninf, nanim = struct.unpack_from("<5I", b, 4)
    p = 24 + nv * 44 + ni * 4
    counts = np.frombuffer(b, np.uint8, nv, p)
    w = np.frombuffer(b, np.dtype([("weight", "<f4"), ("bone", "<i4")]), ninf, p + nv)
    assert p + nv + ninf * 8 + nanim * 4 == len(b)
    starts = [0] + np.cumsum(counts, dtype=np.int64).tolist()
    return [[(int(b), float(x)) for b, x in w[starts[i]:starts[i + 1]][["bone", "weight"]].tolist()]
            for i in range(nv)]


def test_skeletal_vertices_carry_their_bone_set_weights(extracted, tmp_path):
    meta = export_models.export_model(extracted, "chars/models/ic_regular.ltb", str(tmp_path))
    skin = read_skin(str(tmp_path), "chars/models/ic_regular.ltb")
    m = ltb.load(os.path.join(extracted, "chars/models/ic_regular.ltb"))
    for piece, mp in zip(meta["pieces"], m.pieces):
        mesh = mp.lods[0][3]
        for s in mesh.bone_sets:
            set_bones = {int(x) for x in s["bones"] if x != 0xFF}
            for v in range(s["first"], s["first"] + s["count"]):
                infl = skin[piece["vtxOffset"] + v]
                ws = [w for _, w in infl]
                assert 1 <= len(infl) <= 4
                assert abs(sum(ws) - 1) < 1e-5
                assert ws == sorted(ws, reverse=True) and min(ws) > 0
                assert {b for b, _ in infl} <= set_bones
    assert len(meta["nodes"]) == len(m.nodes)


def test_rigid_pieces_are_one_bone_skins(extracted, tmp_path):
    rel = "attachments/models/ic_l_foot_1.ltb"
    meta = export_models.export_model(extracted, rel, str(tmp_path))
    skin = read_skin(str(tmp_path), rel)
    assert meta["pieces"][0]["kind"] == ltb.RIGID
    assert {tuple(v) for v in skin} == {((1, 1.0),)}   # node 1 = L_Foot


def quat_matrix(x, y, z, w):
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def tr(pos, rot):
    m = np.eye(4)
    m[:3, :3] = quat_matrix(*rot)
    m[:3, 3] = pos
    return m


def pose_globals(meta, key):
    """Model-space node matrices: 'transform' (bind, global) or 'pose' (local pos + quat, chained)."""
    out = []
    for n in meta["nodes"]:
        if key == "transform":
            out.append(np.array(n["transform"]).reshape(4, 4))
        else:
            local = tr(n["pose"][:3], n["pose"][3:])
            out.append(local if n["parent"] < 0 else out[n["parent"]] @ local)
    return out


def test_attachment_sits_on_the_body_at_its_socket(extracted, tmp_path):
    """IC_Regular's LeftFoot armor drawn the way the viewer composes it: character bone (bind) x socket x
    attachment pose (its animation 0, frame 0) x inverse attachment bind. It must land on the foot."""
    char = export_models.export_model(extracted, "chars/models/ic_regular.ltb", str(tmp_path))
    att = export_models.export_model(extracted, "attachments/models/ic_l_foot_1.ltb", str(tmp_path))
    sock = next(s for s in char["sockets"] if s["name"].lower() == "leftfoot")
    socket_m = pose_globals(char, "transform")[sock["node"]] @ tr(sock["pos"], sock["rot"]) @ np.diag(
        sock["scale"] + [1])
    pose, bind = pose_globals(att, "pose"), pose_globals(att, "transform")
    m = ltb.load(os.path.join(extracted, "attachments/models/ic_l_foot_1.ltb"))
    av = m.pieces[0].lods[0][3].field("pos").astype(np.float64)
    bone = m.pieces[0].lods[0][3].bone
    placed = (socket_m @ pose[bone] @ np.linalg.inv(bind[bone]) @ np.c_[av, np.ones(len(av))].T).T[:, :3]
    cm = ltb.load(os.path.join(extracted, "chars/models/ic_regular.ltb"))
    body = np.concatenate([p.lods[0][3].field("pos") for p in cm.pieces])
    nearest = np.sqrt(((placed[:, None, :] - body[None, :, :]) ** 2).sum(-1)).min(1)
    assert nearest.mean() < 4   # armor shell hugs the foot (it would float ~45 units off at its bind pose)


def test_other_unsupported_styles_still_stop_the_export(extracted):
    st = export_models.Styles(extracted)
    try:
        st.compile("chars/rs/glow_teambossweapons.ltb")
    except ValueError:
        return
    raise AssertionError("garbage TextureParam style compiled")


def test_level_lists_the_character_skinned_with_its_attachments(extracted):
    import export_level
    objects = [human("IC_Regular"), human("IC_Regular", StartHidden=True)]
    models, styles = export_level.model_instances(objects, export_models.Resolver(extracted),
                                                  export_models.Styles(extracted), extracted)
    char, atts = models[0], models[1:]
    assert (char["obj"], char["file"], char["skinned"], char["parent"]) == (0, "chars/models/ic_regular.ltb", 1, -1)
    assert len(atts) == 13
    assert all(a["obj"] == 0 and a["parent"] == 0 and a["skinned"] == 1 for a in atts)
    assert atts[0]["socket"] == "LeftFoot" and atts[0]["file"] == "attachments/models/ic_l_foot_1.ltb"
    assert {styles[p["style"]]["name"] for a in atts for p in a["pieces"]} == {"chars/rs/kernel_shell.ltb"}


def test_model_sockets_are_read_past_the_animations(extracted):
    m = ltb.load(os.path.join(extracted, "chars/models/ic_regular.ltb"))
    names = {s.name.lower() for s in m.sockets}
    assert {"leftfoot", "righthand", "uppertorso2", "head"} <= names
    for s in m.sockets:
        assert 0 <= s.node < len(m.nodes)
        assert len(s.pos) == 3 and len(s.rot) == 4 and len(s.scale) == 3
    assert m.end == len(m.data)   # sockets and animation bindings consume the rest of the file


def test_spawner_templates_are_never_created(extracted):
    # GameBase::ReadProp: Template = TRUE saves the object as a spawner template, it isn't created.
    r = export_models.Resolver(extracted)
    assert r.resolve(human("IC_Regular", Template=True)) is None
    assert r.resolve(human("IC_Regular", Template=False)) is not None


def test_objects_off_in_single_player_are_skipped(extracted):
    # GameBase::ReadProp, eGameTypeSingle: SinglePlayer = FALSE returns false (not created).
    r = export_models.Resolver(extracted)
    assert r.resolve(human("IC_Regular", SinglePlayer=False)) is None
    assert r.resolve(human("IC_Regular", SinglePlayer=True)) is not None


def test_spawner_template_props_are_never_created(extracted):
    r = export_models.Resolver(extracted)
    prop = {"cls": "Prop", "name": "p", "pos": [0, 0, 0], "rot": [0, 0, 0],
            "props": [{"k": "Filename", "t": "s", "s": "props/models/chair.ltb", "v": []},
                      {"k": "Template", "t": "b", "s": "", "v": [1.0]}]}
    assert r.resolve(prop) is None


def test_hand_held_weapon_is_drawn_at_its_position(extracted):
    # CAttachments::CreateWeaponAttachment: a CHHWeaponModel with the weapon's HHModel, HHSkinN and
    # HHRenderStyleN, attached at the position's socket with no offset (HHModelScale isn't used).
    r = export_models.Resolver(extracted)
    by_pos = {a[0]: a[1:] for a in r.attachments(human("IC_Regular", RightHand="ICRegularDisc"))}
    assert by_pos["RightHand"] == ("weapons/disc/models_hh/ic_disk_hh.ltb", ["weapons/disc/skins_hh/disc_red.dtx"],
                                   ["chars/rs/ic_rs.ltb"])


def test_hand_held_skin_slots_keep_their_positions(extracted):
    # SeekerBlaster's HHSkin0 = "": slot 0 stays, empty (CopySkinFilenames copies each slot as it is).
    r = export_models.Resolver(extracted)
    by_pos = {a[0]: a[1:] for a in r.attachments(human("IC_Regular", RightHand="SeekerBlaster"))}
    assert by_pos["RightHand"] == ("weapons/mesh/models_hh/seekerblaster_hh.ltb", [""], [])


def test_weapon_without_hand_held_model_is_hidden(extracted):
    # DiscSmack has HHModel = "": CHHWeaponModel::Setup hides the weapon (HideWeapon(true)).
    r = export_models.Resolver(extracted)
    assert "LeftHand" not in {a[0] for a in r.attachments(human("IC_Regular", LeftHand="DiscSmack"))}


def holstered(template, **props):
    obj = human(template, **props)
    obj["props"].append({"k": "HolsterWeapons", "t": "b", "s": "", "v": [1.0]})
    return obj


def test_holster_weapons_empties_both_hands(extracted):
    # CAIHuman::InitialUpdate: with HolsterWeapons and a RightHand/LeftHand weapon set on the object,
    # both hand positions are detached (KEY_DETACH RIGHTHAND/LEFTHAND, whatever they hold). Tron's
    # weapons have no HolsterAttachment, so nothing is attached in their place.
    r = export_models.Resolver(extracted)
    positions = {a[0] for a in r.attachments(holstered("IC_Regular", RightHand="ICRegularDisc", LeftHand="Ball"))}
    assert not positions & {"RightHand", "LeftHand"}
    assert "RightHand2" in positions   # other positions keep theirs


def test_level_lists_hand_held_weapons_on_their_socket(extracted):
    # The weapons placed characters hold: disc (IC_RS), suffusion rod (Jet_RS), ball (HH_Ball_Glow).
    import export_level
    objects = [human("IC_Regular", RightHand="ICRegularDisc", LeftHand="Ball"),
               human("ResourceHog", RightHand="HogSuffusion")]
    models, styles = export_level.model_instances(objects, export_models.Resolver(extracted),
                                                  export_models.Styles(extracted), extracted)
    weapons = {(m["obj"], m["socket"]): m for m in models if m["file"].startswith("weapons/")}
    assert {k: m["file"] for k, m in weapons.items()} == {
        (0, "RightHand"): "weapons/disc/models_hh/ic_disk_hh.ltb",
        (0, "LeftHand"): "weapons/ball/models_hh/ball_hh.ltb",
        (1, "RightHand"): "weapons/rod/models_hh/suffusion_hh.ltb"}
    assert all(m["parent"] >= 0 and m["skinned"] == 1 and m["scale"] == [1, 1, 1] for m in weapons.values())
    assert {styles[p["style"]]["name"] for m in weapons.values() for p in m["pieces"]} == {
        "chars/rs/ic_rs.ltb", "weapons/ball/rs/hh_ball_glow.ltb", "chars/rs/jet_rs.ltb"}


def test_holster_weapons_without_hand_weapons_on_the_object_does_nothing(extracted):
    # The holster string is built only from the object's RightHand/LeftHand properties; empty, nothing
    # is detached (a template default in a hand stays).
    r = export_models.Resolver(extracted)
    assert r.attachments(holstered("IC_Regular", RightHand="<none>")) == r.attachments(human("IC_Regular"))
    assert r.weapon_at(holstered("IC_Regular", RightHand2="ICRegularDisc"), "RightHand2") == "ICRegularDisc"


M06_GEN = "chars/models/cinematic/mission06/m06_gen.ltb"
M04_MP = "chars/models/cinematic/mission04/m04_maleprogram.ltb"


def character_entry(extracted, obj, named=()):
    import export_level
    models, _styles = export_level.model_instances([obj], export_models.Resolver(extracted),
                                                   export_models.Styles(extracted), extracted, named_anims=named)
    return models[0]


def test_character_plays_the_animations_of_its_child_model_files(extracted):
    # CAI puts ChildModel_1..3 in ObjectCreateStruct.m_Filenames[1..3]: their animations join the model's,
    # found by name (docs/research/cutscene-actors.md).
    ch = character_entry(extracted, human("Male_Program", ChildModel_1="Chars\\Models\\Cinematic\\Mission06\\M06_Gen.ltb"))
    assert ch["childModels"] == [M06_GEN]
    plays = {a["name"]: a["from"] for a in ch["anims"]}
    assert plays["M06MpTalking"] == M06_GEN and plays["M06DancerCompiler"] == M06_GEN
    assert plays[ch["anim"]] == ""   # the idle, in the model's .ltb children


def test_each_character_plays_its_first_child_model_with_the_name(extracted):
    # M06MpTalking is in both files (a 200 ms blend in m06_gen, a cut in m04_maleprogram): per character,
    # the first ChildModel_N that has it.
    ch = character_entry(extracted, human("Male_Program", ChildModel_1="chars\\models\\cinematic\\mission04\\M04_MaleProgram.ltb",
                                          ChildModel_2="chars\\models\\cinematic\\mission06\\M06_Gen.ltb"))
    assert ch["childModels"] == [M04_MP, M06_GEN]
    names = [x["name"].lower() for x in ch["anims"]]
    assert len(names) == len(set(names))
    plays = {x["name"]: x["from"] for x in ch["anims"]}
    assert plays["M06MpTalking"] == M04_MP and plays["M06DancerCompiler"] == M06_GEN


def test_the_model_shadows_its_child_model_files(extracted):
    # Model::FindAnim order: the model, its .ltb children, then the ChildModel_N files. m09_gen's 'Base'
    # loses to civmale's own.
    ch = character_entry(extracted, human("Male_Program", ChildModel_1="chars\\models\\cinematic\\mission09\\m09_gen.ltb"))
    plays = {x["name"].lower(): x["from"] for x in ch["anims"]}
    assert plays["base"] == "" and plays["m09mpfirstday"] == "chars/models/cinematic/mission09/m09_gen.ltb"


def test_animations_the_level_names_in_the_model_are_playable(extracted):
    # A goal script can name an animation of the model's .ltb children (Base_General's Gen_PointRight);
    # those the level names come along, the others don't. A name found nowhere is left out.
    ch = character_entry(extracted, human("Male_Program"), named={"gen_pointright", "NoSuchAnim"})
    plays = {x["name"].lower(): x["from"] for x in ch["anims"]}
    assert plays["gen_pointright"] == "" and "nosuchanim" not in plays
    assert "gen_halt" not in plays


def test_model_exports_child_model_clips_with_their_blend_time(extracted, tmp_path):
    # The same name from two files is two clips, told apart by `from`. interp: the clip's interpMS (s), the
    # blend from the previous pose into its first frame (trk_ScanToKeyFrame); 0 is a cut.
    rel = "chars/models/civmale.ltb"
    meta = export_models.export_model(extracted, rel, str(tmp_path),
                                      ["Gen_Idle01", ("M06MpTalking", M06_GEN), ("M06MpTalking", M04_MP)])
    clips = [(a["name"], a["from"], a["interp"], a["keys"]) for a in meta["anims"]]
    assert clips == [("Gen_Idle01", "", pytest.approx(0.2), 24), ("M06MpTalking", M06_GEN, 0.2, 153),
                     ("M06MpTalking", M04_MP, 0.0, 153)]
    talk = meta["anims"][1]
    assert talk["length"] == pytest.approx(15.133)
    assert len(talk["channels"]) == 4 * len(meta["nodes"])


def test_child_model_clip_is_the_file_s_not_the_model_s(extracted, tmp_path):
    # m09_gen has its own 'Base': exported from the file, it is the file's animation, posed on civmale.
    m09 = "chars/models/cinematic/mission09/m09_gen.ltb"
    meta = export_models.export_model(extracted, "chars/models/civmale.ltb", str(tmp_path),
                                      ["base", ("Base", m09)])
    own, file_base = meta["anims"]
    assert (own["from"], file_base["from"]) == ("", m09)
    m = ltb.load(os.path.join(extracted, m09))
    assert file_base["keys"] == len(ltb.find_anim(m.anims, "Base").times)


def test_level_names_the_animations_its_goal_scripts_play(world):
    # m06-03's Ma3a: goalscript animate anim=Launch animate anim=Landing loop=0 / anim=Fly loop=1, in its
    # props and keyframer keys alike; compared case-insensitively.
    import export_level
    names = {n.lower() for n in export_level.scripted_anims(world("retailsingleplayer/m06-03"))}
    assert {"launch", "landing", "fly", "base", "m06jetpointing"} <= names
    assert "loop" not in names and "1" not in names


def test_missing_child_model_files_are_skipped(extracted):
    ch = character_entry(extracted, human("IC_Regular", ChildModel_1="Chars\\models\\Base_IC.lta", ChildModel_2=""))
    assert ch["childModels"] == []
