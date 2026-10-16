"""Bench glTF (bench_gltf.py): a level's world geometry as a .glb, one primitive per surface family x texture x
animated x overlay with its render roles in extras, read back here the way a glTF importer would."""
import json
import math
import struct

import numpy as np
import pytest

import bench_gltf
import surfaces
from baseline import METRES
from conftest import EXTRACTED

LEVEL = "retailsingleplayer/fin"


def read_glb(data):
    magic, version, length = struct.unpack_from("<III", data)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    n, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(data[20:20 + n])
    m, kind = struct.unpack_from("<II", data, 20 + n)
    assert kind == 0x004E4942
    return doc, data[28 + n:28 + n + m]


def attribute(doc, blob, index):
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    return np.frombuffer(blob, np.float32, acc["count"] * 3, view["byteOffset"]).reshape(-1, 3)


@pytest.fixture(scope="module")
def bench(world):
    w = world(LEVEL)
    doc, blob, counts = bench_gltf.build(w, LEVEL, EXTRACTED)
    doc, blob = read_glb(bench_gltf.glb(doc, blob))
    return w, doc, blob, counts


def test_triangles_per_family_match_the_classifier_over_drawn_triangles(bench):
    w, doc, blob, _counts = bench
    fams, _area = surfaces.classify(w)
    fams = fams[surfaces.world_drawn(w)]
    names = [m["name"] for m in doc["materials"]]
    assert names == list(surfaces.FAMILIES)
    got = {f: 0 for f in surfaces.FAMILIES}
    for p in doc["meshes"][0]["primitives"]:
        got[names[p["material"]]] += doc["accessors"][p["attributes"]["POSITION"]]["count"] // 3
    assert got == {f: int((fams == f).sum()) for f in surfaces.FAMILIES}
    assert doc["asset"]["extras"]["trianglesPerFamily"] == got


def test_positions_are_the_world_in_metres_with_x_mirrored(bench):
    w, doc, blob, _counts = bench
    v, _vn, _t, _m = surfaces.world_triangles(w)
    v = v[surfaces.world_drawn(w)]
    pos = np.concatenate([attribute(doc, blob, p["attributes"]["POSITION"]) for p in doc["meshes"][0]["primitives"]])
    lt = v.reshape(-1, 3) * (-METRES, METRES, METRES)
    np.testing.assert_allclose(pos.min(0), lt.min(0), atol=1e-3)
    np.testing.assert_allclose(pos.max(0), lt.max(0), atol=1e-3)


def test_floors_face_up_and_ceilings_down_wound_counter_clockwise(bench):
    _w, doc, blob, _counts = bench
    names = [m["name"] for m in doc["materials"]]
    for p in doc["meshes"][0]["primitives"]:
        v = attribute(doc, blob, p["attributes"]["POSITION"]).reshape(-1, 3, 3).astype(np.float64)
        n = attribute(doc, blob, p["attributes"]["NORMAL"])[::3]
        np.testing.assert_allclose(np.linalg.norm(n, axis=1), 1, atol=1e-5)
        up = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])[:, 1]   # counter-clockwise: the normal's y sign
        fam = names[p["material"]]
        if fam.startswith("floor"):
            assert (n[:, 1] >= surfaces.WALKABLE - 1e-5).all() and (up > 0).all()
        elif fam == "ceiling":
            assert (n[:, 1] <= -surfaces.WALKABLE + 1e-5).all() and (up < 0).all()


def test_game_start_point_is_a_named_node_in_metres(bench):
    w, doc, _blob, _counts = bench
    start = next(o["props"] for o in w.objects if o["class"] == "GameStartPoint")
    node = next(n for n in doc["nodes"] if n["name"] == "GameStartPoint")
    x, y, z = start["Pos"]
    np.testing.assert_allclose(node["translation"], [-x * METRES, y * METRES, z * METRES], rtol=1e-6)


def test_start_rotation_is_yaw_mirrored():
    # Yaw 90 degrees in LithTech (forward +z turns to +x) is -90 degrees about y once x is mirrored.
    q = bench_gltf._start_rotation([0, math.pi / 2, 0])
    np.testing.assert_allclose(q, [0, -math.sin(math.pi / 4), 0, math.cos(math.pi / 4)], atol=1e-12)
    assert bench_gltf._start_rotation([0, 0, 0]) == [0, -0.0, -0.0, 1.0]


def test_each_primitive_is_one_family_texture_animated_overlay(bench):
    _w, doc, _blob, _counts = bench
    keys = []
    for p in doc["meshes"][0]["primitives"]:
        x = p["extras"]
        assert set(x) == {"texture", "blend", "animated", "effect", "overlay", "glow", "glowCoverage", "glowSpread",
                          "glowColor", "color",
                          "lightmap", "vertexLight", "triangles"}
        assert x["triangles"] == doc["accessors"][p["attributes"]["POSITION"]]["count"] // 3
        assert x["animated"] == (x["texture"].lower().endswith(".spr") or x["effect"] is not None)
        assert 0 <= x["glow"] <= 1 and 0 <= x["glowCoverage"] <= 1 and 0 <= x["glowSpread"] <= 0.5 + 1e-9
        assert x["lightmap"] is None or 0 <= x["lightmap"] <= 2
        assert x["lightmap"] is not None or x["vertexLight"] is not None
        keys.append((p["material"], x["texture"].lower(), x["animated"], x["overlay"]))
    assert len(keys) == len(set(keys))


def test_world_models_not_drawn_at_start_are_left_out(world):
    # m01-01's EndlessFall volumes (Visible False) are the only users of occluder.dtx.
    w = world("retailsingleplayer/m01-01")
    doc, _blob, counts = bench_gltf.build(w, "retailsingleplayer/m01-01", EXTRACTED)
    textures = {p["extras"]["texture"].lower() for p in doc["meshes"][0]["primitives"]}
    assert "tex\\occluder.dtx" not in textures
    assert sum(counts.values()) == int(surfaces.world_drawn(w).sum()) < len(surfaces.world_drawn(w))


def test_glow_is_the_alpha_of_fullbright_textures_only():
    base = "tex\\prototype\\m01\\geoff\\serverp\\"
    dark = bench_gltf.texture_stats(EXTRACTED, base + "base\\m01p_b01.dtx")    # not fullbright
    lit = bench_gltf.texture_stats(EXTRACTED, base + "base\\m01p_b03.dtx")     # fullbright
    assert dark[1] == 0 and not dark[2].any()
    assert 0 < lit[1] <= 1 and (lit[2] <= lit[0] + 1e-9).all()


def test_an_overlay_is_a_decal_just_in_front_of_another_texture():
    floor = [[0, 0, 0], [0, 0, 10], [10, 0, 0]]
    decal = [[1, 0.5, 1], [1, 0.5, 3], [3, 0.5, 1]]        # half a unit above, inside the floor's outline
    beside = [[20, 0.5, 1], [20, 0.5, 3], [22, 0.5, 1]]    # same height, but over nothing
    high = [[1, 5, 1], [1, 5, 3], [3, 5, 1]]               # too far above to be a decal
    v = np.array([floor, decal, beside, high], np.float64)
    n = np.tile([0.0, 1.0, 0.0], (4, 1))
    got = bench_gltf.overlays(v, n, np.array(["floor", "decal", "decal", "decal"], object))
    assert got.tolist() == [False, True, False, False]


def test_glow_coverage_and_spread_tell_a_sheet_of_light_from_a_pattern():
    sheet = np.full((8, 8, 4), 200, np.uint8)                      # alpha the same everywhere
    pattern = np.zeros((8, 8, 4), np.uint8)
    pattern[:, :4, 3] = 255                                        # half the texels lit, half not
    _c, glow, _gc, coverage, spread = bench_gltf.frame_stats(sheet, True)
    assert spread < 1e-9 and coverage == 1 and glow == pytest.approx(200 / 255)
    _c, glow, _gc, coverage, spread = bench_gltf.frame_stats(pattern, True)
    assert coverage == pytest.approx(0.5) and spread == pytest.approx(0.5) and glow == pytest.approx(0.5)
    assert bench_gltf.frame_stats(pattern, False)[1:2] + bench_gltf.frame_stats(pattern, False)[3:] == (0, 0, 0)
