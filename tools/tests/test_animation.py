"""LTB animations (ltb.py), child models, clips and the idle sampler (animation.py)."""
import glob
import os

import numpy as np
import pytest

import animation
import ltb


def chars(extracted, name):
    return os.path.join(extracted, "chars", "models", name)


def test_animation_table_and_bindings(extracted):
    m = ltb.load(chars(extracted, "base_zlot.ltb"))
    assert len(m.anims) == 77
    by_name = {a.name.lower(): a for a in m.anims}
    # Bindings (LoadAnimBindings): the root translation each animation adds to the root node.
    assert by_name["zlt_walkunarmed"].translation == pytest.approx((0, 4, 0))
    assert by_name["zlt_idle4"].translation == pytest.approx((0, 0, 0))
    assert all(len(a.times) >= 1 and a.times[0] == 0 for a in m.anims)


def test_frame0_of_base_rebuilds_the_bind_pose(extracted):
    # Research #4: zlot3 'base' (compression 2) frame 0, chained parent x TR(q, p), gives every
    # node's bind matrix within i16 precision (0.01 units), shifted by the animation's root translation.
    m = ltb.load(chars(extracted, "zlot3.ltb"))
    clip = animation.clip(m, [], "base")
    shift = np.asarray(ltb.find_anim(m.anims, "base").translation)
    assert shift == pytest.approx((0, 3, 0))
    pose = animation.sample(clip, 0.0)
    glob_ = animation.globals_(m, pose)
    for n, g in zip(m.nodes, glob_):
        assert np.abs(g[:3, 3] - n.transform[:3, 3] - shift).max() < 0.01
        assert np.abs(g[:3, :3] - n.transform[:3, :3]).max() < 0.003


def test_every_compression_decodes_to_unit_quaternions(extracted):
    seen = set()
    for path in sorted(glob.glob(os.path.join(extracted, "chars", "**", "*.ltb"), recursive=True)):
        try:
            m = ltb.load(path)
        except ltb.Unsupported:
            continue
        for a in m.anims:
            if a.compression in seen:
                continue
            seen.add(a.compression)
            channels = ltb.decode_anim(m, a)
            assert len(channels) == len(m.nodes)
            for pos, rot in channels:
                assert len(pos) in (0, 1, len(a.times)) and len(rot) in (0, 1, len(a.times))
                if len(rot):
                    assert np.allclose(np.linalg.norm(rot, axis=1), 1, atol=2e-3)
        if seen >= {0, 1, 2, 3}:
            break
    assert seen >= {0, 1, 2, 3}


def test_first_pose_is_frame0_of_animation0(extracted):
    m = ltb.load(chars(extracted, "zlot3.ltb"))
    pose = animation.sample(animation.clip(m, [], m.anims[0].name), 0.0)
    for (p, q), (fp, fq) in zip(pose, m.first_pose):
        assert p == pytest.approx(fp, abs=1e-4)
        assert q == pytest.approx(fq, abs=1e-4)


def test_child_animations_follow_the_parent_by_name(extracted):
    m = ltb.load(chars(extracted, "zlot3.ltb"))
    children = animation.load_children(extracted, "chars/models/zlot3.ltb", m)
    assert [os.path.basename(c.path) for c in children] == \
        ["base_zlot.ltb", "base_general_recoil.ltb", "base_death.ltb"]
    clip = animation.clip(m, children, "ZLT_IDLE4")   # case-insensitive, first match
    assert clip.name == "Zlt_Idle4" and len(clip.times) > 1
    # A parent's own animation shadows a child's of the same name (Model::FindAnim).
    assert animation.find_anim(m, children, "base")[0] is m


def test_clip_resolves_rotation_only_and_root_translation(extracted):
    m = ltb.load(chars(extracted, "zlot3.ltb"))
    children = animation.load_children(extracted, "chars/models/zlot3.ltb", m)
    clip = animation.clip(m, children, "Zlt_WalkUnarmed")
    walk = animation.find_anim(m, children, "Zlt_WalkUnarmed")[1]
    raw = ltb.decode_anim(children[0], walk)
    # Root: keyed position + the binding's translation (0, 4, 0).
    raw_root = raw[0][0] if len(raw[0][0]) else np.zeros((1, 3))
    assert np.allclose(clip.pos[0], raw_root + (0, 4, 0), atol=1e-5)
    # MNODE_ROTATIONONLY (Torso, flag 2): one constant key, the bind offset from its parent.
    torso = next(n for n in m.nodes if n.name == "Torso")
    off = (np.linalg.inv(m.nodes[torso.parent].transform.astype(np.float64)) @ torso.transform)[:3, 3]
    assert len(clip.pos[torso.index]) == 1
    assert np.allclose(clip.pos[torso.index][0], off, atol=1e-4)


def test_sampler_interpolates_wraps_and_skips_duplicate_key_times():
    c = animation.Clip("t", np.array([0, 100, 100, 200], np.float64),
                       [np.array([[0, 0, 0], [10, 0, 0], [20, 0, 0], [40, 0, 0]], np.float64)],
                       [np.array([[0, 0, 0, 1]], np.float64)])
    assert c.length == 200
    assert animation.sample(c, 50)[0][0] == pytest.approx((5, 0, 0))
    # 1001 key pairs share a time: the zero-length interval is never used (the later key wins).
    assert animation.sample(c, 100)[0][0] == pytest.approx((20, 0, 0))
    assert animation.sample(c, 150)[0][0] == pytest.approx((30, 0, 0))
    # Looping wraps at the last key's time (t %= lastKeyTime): no blend back to key 0.
    assert animation.sample(c, 250)[0][0] == pytest.approx((5, 0, 0))
    assert animation.sample(c, 200)[0][0] == pytest.approx((0, 0, 0))


def test_slerp_rotation():
    h = np.sqrt(0.5)
    c = animation.Clip("r", np.array([0, 100], np.float64), [np.zeros((1, 3))],
                       [np.array([[0, 0, 0, 1], [0, h, 0, h]], np.float64)])
    q = np.array(animation.sample(c, 50)[0][1])
    ang = np.deg2rad(45) / 2
    assert q == pytest.approx((0, np.sin(ang), 0, np.cos(ang)), abs=1e-6)


def human(template, **props):
    ps = [{"k": "ModelTemplate", "t": "s", "s": template, "v": []}]
    ps += [{"k": k, "t": "s", "s": v, "v": []} for k, v in props.items()]
    return {"cls": "CAIHuman", "name": "ai", "pos": [0, 0, 0], "rot": [0, 0, 0], "props": ps}


@pytest.fixture(scope="module")
def idle(extracted):
    import export_models
    return animation.IdleSelector(extracted, export_models.Resolver(extracted))


@pytest.mark.parametrize("template, props, expected", [
    ("Zealot", {}, {"Zlt_Idle4"}),
    ("Zealot3", {"RightHand": "ICRegularDisc"}, {"Zlt_Idle4"}),
    ("IC_Regular", {"RightHand": "ICRegularDisc"}, {"IC_IdleUnarmed"}),   # Ranged: Weapon1
    ("IC_Regular", {}, {"IC_IdleUnarmed"}),
    ("IC_Regular", {"RightHand": "RiotShield"}, {"Base"}),                # no row: the Base fallback
    ("IC_Shield", {"RightHand": "RiotShield"},                         # Melee: Weapon2, random tie
     {f"IC_ShieldIdle{i}" for i in range(1, 6)}),
    ("IC_Shield", {}, {"IC_ShieldIdle1"}),
    ("IC_Kernel", {"RightHand": "RiotShield"}, {"Launcher_Idle"}),
    ("Male_Program", {}, {"Gen_Idle01"}),
    ("ResourceHog", {}, {"Rhog_Idle0"}),
    ("Rectorscript", {}, {"Rect_ClosedIdle"}),
    ("Ma3a", {}, {"Hover"}),                                           # hovering: Movement=Hover
    ("Alan_Bradley", {}, {"Base"}),                                    # AnimationsTemp: the Base row
])
def test_idle_animation_follows_the_animation_table(idle, template, props, expected):
    names = {idle.idle(human(template, **props), seed) for seed in range(8)}
    assert {n.lower() for n in names} == {e.lower() for e in expected}


def test_holstered_weapons_leave_the_hands_empty(idle):
    # HolsterWeapons: CAIHuman detaches the hand weapons at init (aihuman.cpp), so no primary weapon.
    obj = human("IC_Shield", RightHand="RiotShield")
    obj["props"].append({"k": "HolsterWeapons", "t": "b", "s": "", "v": [1.0]})
    assert idle.idle(obj, 3) == "IC_ShieldIdle1"


def test_right_hand_weapon_comes_from_the_level_object(extracted):
    import export_models
    r = export_models.Resolver(extracted)
    assert r.weapon_at(human("IC_Regular", RightHand="ICRegularDisc"), "RightHand") == "ICRegularDisc"
    assert r.weapon_at(human("IC_Regular"), "RightHand") is None


def read_exported_clip(base, name):
    """Rebuilds a clip from export/models/<file>.json + .bin (the viewer's ModelLibrary layout)."""
    import json
    import struct
    meta = json.load(open(base + ".json"))
    data = open(base + ".bin", "rb").read()
    _magic, version, nv, ni, ninf, nanim = struct.unpack_from("<4s5I", data)
    assert version == meta["version"] == 3
    off = 24 + nv * 44 + ni * 4 + nv + ninf * 8
    floats = np.frombuffer(data, "<f4", nanim, off)
    assert off + nanim * 4 == len(data)
    a = next(x for x in meta["anims"] if x["name"] == name)
    times = floats[a["times"]:a["times"] + a["keys"]] * 1000.0
    ch = np.array(a["channels"]).reshape(-1, 4)
    pos = [floats[o:o + 3 * n].reshape(n, 3).astype(np.float64) for o, n, _, _ in ch]
    rot = [floats[o:o + 4 * n].reshape(n, 4).astype(np.float64) for _, _, o, n in ch]
    return a, animation.Clip(name, times, pos, rot)


def test_exported_clip_round_trips(extracted, tmp_path):
    import export_models
    rel = "chars/models/zlot3.ltb"
    export_models.export_model(extracted, rel, str(tmp_path), ["Zlt_Idle4"])
    a, got = read_exported_clip(str(tmp_path / "models" / rel), "Zlt_Idle4")
    m = ltb.load(chars(extracted, "zlot3.ltb"))
    want = animation.clip(m, animation.load_children(extracted, rel, m), "Zlt_Idle4")
    assert a["length"] == pytest.approx(want.length / 1000.0)
    assert a["keys"] == len(want.times)
    assert sum(len(p) > 1 for p in got.pos) + sum(len(q) > 1 for q in got.rot) > 0   # it moves
    for t in np.linspace(0, want.length, 13):
        for (p1, q1), (p2, q2) in zip(animation.sample(got, t), animation.sample(want, t)):
            assert p1 == pytest.approx(p2, abs=1e-3)
            assert q1 == pytest.approx(q2, abs=1e-4)
