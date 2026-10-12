"""Characters (CAIHuman): model template resolution, default attachments, sockets, skin export."""
import os
import struct

import numpy as np

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
    # (CAttachments::Attach: position already occupied). A weapon only occupies its position.
    atts = r.attachments(human("IC_Shield", Head="SoftHat", RightHand2="ICRegularDisc", LeftHand="<none>"))
    by_pos = {a[0]: a[1] for a in atts}
    assert by_pos["Head"] == "attachments/models/softhat.ltb"
    assert "RightHand2" not in by_pos
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
    _version, nv, ni, ninf = struct.unpack_from("<4I", b, 4)
    p = 20 + nv * 44 + ni * 4
    counts = np.frombuffer(b, np.uint8, nv, p)
    w = np.frombuffer(b, np.dtype([("weight", "<f4"), ("bone", "<i4")]), ninf, p + nv)
    assert p + nv + ninf * 8 == len(b)
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


def test_two_pass_character_styles_draw_their_first_pass_until_ticket_11(extracted):
    st = export_models.Styles(extracted)
    for rel, blend in [("chars/rs/thorn_body.ltb", [3, 2]), ("chars/rs/rector_cloak.ltb", [3, 2]),
                       ("chars/rs/thorn_corruption.ltb", [3, 6]), ("rs/alpha_transparent.ltb", [1, 0])]:
        c = st.compile(rel)
        assert len(c["passes"]) == 1 and list(c["blend"]) == blend
    assert set(st.pass0_only) == {"chars/rs/thorn_body.ltb", "chars/rs/rector_cloak.ltb",
                                  "chars/rs/thorn_corruption.ltb", "rs/alpha_transparent.ltb"}


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
