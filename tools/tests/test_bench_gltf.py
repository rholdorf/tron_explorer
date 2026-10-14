"""Bench glTF (bench_gltf.py): a level's world geometry as a .glb, one primitive per surface family, read
back here the way a glTF importer would."""
import json
import math
import struct

import numpy as np
import pytest

import bench_gltf
import surfaces
from baseline import METRES

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
    doc, blob, counts = bench_gltf.build(w, LEVEL)
    doc, blob = read_glb(bench_gltf.glb(doc, blob))
    return w, doc, blob, counts


def test_triangles_per_family_match_the_classifier(bench):
    w, doc, blob, _counts = bench
    fams, _area = surfaces.classify(w)
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
