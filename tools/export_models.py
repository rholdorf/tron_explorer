"""Model instances for the viewer: resolve which .ltb + skins each level object shows, and export
those models to the runtime format.

export/models/<model path>.json  pieces, nodes
export/models/<model path>.bin   'TRMD', u32 version, u32 nVerts, u32 nIdx,
                                 verts (nVerts * 44 bytes, same layout as level.bin),
                                 idx (u32, relative to the piece's first vertex)
Only LOD 0 is exported, at the bind pose (vertices are stored in model space).
"""
import json
import os
import struct

import numpy as np

import butes
import ltb

FORMAT_VERSION = 1

OUT_VERTEX = np.dtype([("pos", "<f4", 3), ("normal", "<f4", 3), ("rgba", "u1", 4), ("uv", "<f4", 2),
                       ("uv2", "<f4", 2)])


def norm(path):
    return path.replace("\\", "/").strip().lower()


class Resolver:
    """Maps a level object to (model file, skins, render styles), following the game's sources:
    the object's own Filename/Skin, a PropType entry (proptypes.txt) or a ModelTemplate
    (modelbutes.txt)."""

    def __init__(self, extracted):
        a = os.path.join(extracted, "attributes")
        self.templates = {s["name"].lower(): s for s in butes.load(os.path.join(a, "modelbutes.txt")).values()
                          if "name" in s}
        self.proptypes = {s["type"].lower(): s for s in butes.load(os.path.join(a, "proptypes.txt")).values()
                          if "type" in s}

    @staticmethod
    def _skins(value):
        return [norm(s) for s in value.split(";") if s.strip()] if value else []

    def resolve(self, obj):
        p = {q["k"]: q for q in obj["props"]}

        def s(key):
            q = p.get(key)
            return q["s"] if q and q["t"] == "s" else ""

        def b(key, default=True):
            q = p.get(key)
            return bool(q["v"][0]) if q and q["t"] == "b" and q["v"] else default

        if not b("Visible"):
            return None
        cls = obj["cls"]
        if cls in ("ArchiveBin", "SecRezzer"):
            t = self.templates.get(s("ModelTemplate").lower())
            if not t or "modelfile" not in t:
                return None
            return norm(t["modelfile"]), [norm(x) for x in butes.indexed(t, "skin")], \
                [norm(x) for x in butes.indexed(t, "renderstyle")]
        if cls in ("PropType", "Finder"):
            t = self.proptypes.get(s("Type").lower())
            if not t or "filename" not in t:
                return None
            return norm(t["filename"]), [norm(x) for x in butes.indexed(t, "skin")], \
                [norm(x) for x in butes.indexed(t, "renderstyle")]
        if cls in ("Prop", "Alarm") and s("Filename"):
            return norm(s("Filename")), self._skins(s("Skin")), []
        return None


def export_model(extracted, rel, out_root):
    m = ltb.load(os.path.join(extracted, rel))
    verts, idx, pieces = [], [], []
    nv = ni = 0
    for p in m.pieces:
        textures, style, _prio, mesh, _used = p.lods[0]
        if mesh.indices is None or not mesh.streams or mesh.field("pos") is None:
            continue
        pos = mesh.field("pos")
        out = np.zeros(len(pos), OUT_VERTEX)
        out["pos"] = pos
        normal = mesh.field("normal")
        if normal is not None:
            out["normal"] = normal
        uv = mesh.field("uv")
        if uv is not None:
            out["uv"] = uv[:, 0]
        out["rgba"] = (128, 128, 128, 255)  # neutral lighting (x2 in the shader)
        tris = mesh.indices.astype(np.uint32).reshape(-1)
        pieces.append({"name": p.name, "textures": textures, "style": style, "kind": mesh.kind,
                       "bone": mesh.bone, "vtxOffset": nv, "vtxCount": int(len(out)), "idxOffset": ni,
                       "idxCount": int(len(tris)), "min": pos.min(0).tolist(), "max": pos.max(0).tolist()})
        verts.append(out)
        idx.append(tris)
        nv += len(out)
        ni += len(tris)
    meta = {"version": FORMAT_VERSION, "file": rel, "pieces": pieces,
            "nodes": [{"name": n.name, "parent": n.parent, "transform": n.transform.reshape(-1).tolist()}
                      for n in m.nodes]}
    base = os.path.join(out_root, "models", rel)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    with open(base + ".bin", "wb") as f:
        f.write(b"TRMD")
        f.write(struct.pack("<3I", FORMAT_VERSION, nv, ni))
        for a in verts + idx:
            f.write(np.ascontiguousarray(a).tobytes())
    with open(base + ".json", "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    return meta
