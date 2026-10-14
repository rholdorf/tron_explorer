"""Bench glTF: one level's drawn world geometry as a .glb, one primitive per surface family, for the sibling
project mus-y-sinak, which tries its world-space shaders on it. No UVs, textures or lightmaps: positions
and flat normals only, in metres.

Axes: LithTech is left-handed (x right, y up, z forward) like Unity; glTF is right-handed. x is negated
on the way out, which is the inverse of what Unity's glTF importers do, so the bench gets the viewer's
coordinates (LithTech units * METRES) back on import. Triangles are wound counter-clockwise seen from the
side their vertex normals face.

The output is the game's geometry: write it under export/, never into a repository.

Usage: python tools/bench_gltf.py <extracted dir> <level> [out.glb]   (level e.g. retailsingleplayer/m01-01)"""
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

import dat85  # noqa: E402
import surfaces  # noqa: E402
from baseline import METRES  # noqa: E402

FLIP = np.array([-1.0, 1.0, 1.0])
COLOURS = {   # display colours only, so the file reads in any viewer; the bench replaces the materials
    "floor-interior": (0.20, 0.45, 0.80), "floor-exterior": (0.20, 0.70, 0.40), "wall": (0.60, 0.60, 0.65),
    "ceiling": (0.80, 0.60, 0.20), "glass": (0.50, 0.85, 0.95), "emissive": (1.00, 1.00, 1.00),
    "unclassified": (0.90, 0.10, 0.60),
}


def _start_rotation(rot):
    """glTF quaternion (x, y, z, w) of a LithTech Rotation (Euler pitch, yaw, roll in radians, applied as
    Unity's Quaternion.Euler does: z, then x, then y)."""
    def axis(i, a):
        q = [0.0, 0.0, 0.0, math.cos(a / 2)]
        q[i] = math.sin(a / 2)
        return q

    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]
    x, y, z, w = mul(mul(axis(1, rot[1]), axis(0, rot[0])), axis(2, rot[2]))
    return [x, -y, -z, w]   # the x mirror


def build(w, level):
    """(glTF JSON dict, binary buffer, triangles per family) for a loaded level."""
    v, vn, _texs, _modes = surfaces.world_triangles(w)
    fams, _area = surfaces.classify(w)
    v = v * FLIP * METRES
    vn = vn * FLIP
    cross = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    back = (cross * vn).sum(1) < 0
    v[back] = v[back][:, ::-1]
    cross[back] *= -1
    # A degenerate triangle (the unclassified ones) has no face normal: its vertex normals stand in.
    flat = np.linalg.norm(cross, axis=1) < 1e-9
    cross[flat] = vn[flat] + (np.linalg.norm(vn[flat], axis=1) < 1e-9)[:, None] * (0.0, 1.0, 0.0)
    normal = cross / np.linalg.norm(cross, axis=1)[:, None]

    blob, views, accessors, primitives, counts = bytearray(), [], [], [], {}
    for m, fam in enumerate(surfaces.FAMILIES):
        sel = fams == fam
        counts[fam] = int(sel.sum())
        if not counts[fam]:
            continue
        pos = v[sel].reshape(-1, 3).astype(np.float32)
        nrm = np.repeat(normal[sel], 3, axis=0).astype(np.float32)
        attrs = {}
        for name, data in (("POSITION", pos), ("NORMAL", nrm)):
            views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": data.nbytes, "target": 34962})
            blob += data.tobytes()
            acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": len(data), "type": "VEC3"}
            if name == "POSITION":
                acc["min"], acc["max"] = pos.min(0).tolist(), pos.max(0).tolist()
            accessors.append(acc)
            attrs[name] = len(accessors) - 1
        primitives.append({"attributes": attrs, "material": m, "mode": 4})

    start = next((o["props"] for o in w.objects if o["class"] == "GameStartPoint"), None)
    nodes = [{"name": "world", "mesh": 0}]
    if start is not None:
        rot = (start.get("Rotation") or [0, 0, 0])[:3]
        nodes.append({"name": "GameStartPoint", "translation": (np.array(start["Pos"]) * FLIP * METRES).tolist(),
                      "rotation": _start_rotation(rot)})
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    doc = {
        "asset": {"version": "2.0", "generator": "tron_explorer tools/bench_gltf.py",
                  "extras": {"repo": "rholdorf/tron_explorer", "commit": commit, "level": level,
                             "metresPerUnit": METRES, "trianglesPerFamily": counts}},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": [{"name": "world", "primitives": primitives}],
        "materials": [{"name": f, "pbrMetallicRoughness": {"baseColorFactor": [*COLOURS[f], 1.0],
                                                          "metallicFactor": 0.0, "roughnessFactor": 1.0}}
                      for f in surfaces.FAMILIES],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    return doc, bytes(blob), counts


def glb(doc, blob):
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def main():
    extracted, level = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join("export", "bench", os.path.basename(level) + ".glb")
    doc, blob, counts = build(dat85.load(os.path.join(extracted, "worlds", level + ".dat")), level)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(glb(doc, blob))
    print(out, " ".join(f"{k} {n}" for k, n in counts.items()))


if __name__ == "__main__":
    main()
