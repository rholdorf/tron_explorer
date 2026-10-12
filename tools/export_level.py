"""Export a DAT v85 world to the viewer's runtime format.

<out>/level.json  metadata (materials, meshes, colliders, world models, objects)
<out>/level.bin   binary payload:
    char[4] 'TRLV', u32 version,
    u32 nVerts, u32 nIdx, u32 nColVerts, u32 nColIdx,
    render verts  (nVerts * 36 bytes: pos f32x3, normal f32x3, rgba u8x4, uv f32x2)
    render idx    (u32, relative to the owning mesh's first vertex)
    collider verts (f32x3)
    collider idx  (u32, relative to the owning collider's first vertex)
All positions are raw LithTech units/space (left-handed, Y up — same handedness as Unity).
"""
import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import dat85  # noqa: E402

FORMAT_VERSION = 2
RENDERED_SHADERS = {1, 4, 5, 8, 9}  # gouraud, lightmap_texture, skypan, dualtexture, lightmap_dualtexture

# Unity's canonical attribute order: Position, Normal, Color, TexCoord0
OUT_VERTEX = np.dtype([("pos", "<f4", 3), ("normal", "<f4", 3), ("rgba", "u1", 4), ("uv", "<f4", 2)])
assert OUT_VERTEX.itemsize == 36


class Writer:
    def __init__(self):
        self.verts, self.idx, self.cverts, self.cidx = [], [], [], []
        self.nv = self.ni = self.ncv = self.nci = 0
        self.materials, self.mat_index = [], {}
        self.meshes, self.colliders = [], []

    def material(self, s):
        key = (s.textures[0].replace("\\", "/").lower(), s.textures[1].replace("\\", "/").lower(),
               s.shader, s.effect.lower())
        if key not in self.mat_index:
            self.mat_index[key] = len(self.materials)
            self.materials.append({"tex": key[0], "tex2": key[1], "shader": key[2], "effect": key[3]})
        return self.mat_index[key]

    def add_mesh(self, name, blocks):
        """Merge render blocks into one mesh with one submesh per material."""
        vparts, by_mat = [], {}
        base = 0
        for b in blocks:
            if len(b.verts) == 0:
                continue
            start = 0
            for s in b.sections:
                tris = b.tris[start:start + s.tri_count]
                start += s.tri_count
                if s.shader not in RENDERED_SHADERS or len(tris) == 0:
                    continue
                by_mat.setdefault(self.material(s), []).append(tris.astype(np.uint32) + base)
            vparts.append(b.verts)
            base += len(b.verts)
        if not by_mat:
            return -1
        src = np.concatenate(vparts)
        out = np.zeros(len(src), OUT_VERTEX)
        out["pos"] = src["pos"]
        out["normal"] = src["normal"]
        out["uv"] = np.nan_to_num(src["uv0"], nan=0.0, posinf=0.0, neginf=0.0)
        c = src["color"]  # D3DCOLOR 0xAARRGGBB
        out["rgba"][:, 0] = (c >> 16) & 0xFF
        out["rgba"][:, 1] = (c >> 8) & 0xFF
        out["rgba"][:, 2] = c & 0xFF
        out["rgba"][:, 3] = (c >> 24) & 0xFF
        subs, local = [], 0
        idx_parts = []
        for mat, parts in by_mat.items():
            ids = np.concatenate(parts).reshape(-1)
            subs.append({"mat": mat, "start": local, "count": int(len(ids))})
            idx_parts.append(ids)
            local += len(ids)
        idx = np.concatenate(idx_parts)
        pos = out["pos"]
        mesh = {"name": name, "vtxOffset": self.nv, "vtxCount": int(len(out)), "idxOffset": self.ni,
                "subs": subs, "min": pos.min(0).tolist(), "max": pos.max(0).tolist()}
        self.verts.append(out)
        self.idx.append(idx)
        self.nv += len(out)
        self.ni += len(idx)
        self.meshes.append(mesh)
        return len(self.meshes) - 1

    def add_collider(self, name, points, tris):
        if len(tris) == 0:
            return -1
        used, remap = np.unique(tris, return_inverse=True)
        pts = np.asarray(points, dtype=np.float32)[used]
        idx = remap.astype(np.uint32).reshape(-1)
        self.colliders.append({"name": name, "vtxOffset": self.ncv, "vtxCount": int(len(pts)),
                               "idxOffset": self.nci, "idxCount": int(len(idx)),
                               "min": pts.min(0).tolist(), "max": pts.max(0).tolist()})
        self.cverts.append(pts)
        self.cidx.append(idx)
        self.ncv += len(pts)
        self.nci += len(idx)
        return len(self.colliders) - 1

    def write_bin(self, path):
        with open(path, "wb") as f:
            f.write(b"TRLV")
            f.write(struct.pack("<5I", FORMAT_VERSION, self.nv, self.ni, self.ncv, self.nci))
            for a in self.verts + self.idx + self.cverts + self.cidx:
                f.write(np.ascontiguousarray(a).tobytes())


def polys_to_tris(polys):
    pts, tris = [], []
    for _plane, verts in polys:
        b = len(pts)
        pts.extend(verts.tolist())
        for k in range(1, len(verts) - 1):
            tris.append((b, b + k, b + k + 1))
    return np.array(pts, np.float32).reshape(-1, 3), np.array(tris, np.uint32).reshape(-1, 3)


def encode_prop(k, v):
    if isinstance(v, str):
        return {"k": k, "t": "s", "s": v, "v": []}
    if isinstance(v, bool):
        return {"k": k, "t": "b", "s": "", "v": [1.0 if v else 0.0]}
    if isinstance(v, list):
        return {"k": k, "t": "v", "s": "", "v": [float(x) for x in v]}
    return {"k": k, "t": "n", "s": "", "v": [float(v)]}


def export(dat_path, out_dir, rel_name):
    w = dat85.load(dat_path)
    wr = Writer()

    # Main world render blocks: one mesh per block (keeps culling granular).
    world_meshes = []
    for i, b in enumerate(w.render.blocks):
        m = wr.add_mesh(f"block{i}", [b])
        if m >= 0:
            world_meshes.append(m)

    bsp_by_name = {b.name: b for b in w.bsps}
    physics = next(b for b in w.bsps if b.flags & dat85.WIF_PHYSICSBSP)
    world_collider = wr.add_collider("PhysicsBSP", *physics.solid_triangles())
    blocker_collider = wr.add_collider("Blockers", *polys_to_tris(w.blockers))

    world_models = []
    render_wm = {rw.name: rw for rw in w.render.world_models}
    for b in w.bsps:
        if b is physics:
            continue
        rw = render_wm.get(b.name)
        mesh = wr.add_mesh(b.name, rw.blocks) if rw else -1
        col = wr.add_collider(b.name, *b.solid_triangles())
        world_models.append({"name": b.name, "flags": b.flags, "mesh": mesh, "collider": col})

    objects = []
    for o in w.objects:
        p = o["props"]
        objects.append({
            "cls": o["class"],
            "name": p.get("Name", ""),
            "pos": p.get("Pos", [0, 0, 0]),
            "rot": (p.get("Rotation") or [0, 0, 0, 0])[:3],
            "props": [encode_prop(k, v) for k, v in p.items() if k not in ("Name", "Pos", "Rotation")],
        })

    meta = {
        "version": FORMAT_VERSION,
        "name": rel_name,
        "info": w.info,
        "extMin": list(w.ext_min), "extMax": list(w.ext_max), "offset": list(w.offset),
        "materials": wr.materials,
        "meshes": wr.meshes,
        "colliders": wr.colliders,
        "worldMeshes": world_meshes,
        "worldCollider": world_collider,
        "blockerCollider": blocker_collider,
        "worldModels": world_models,
        "objects": objects,
    }
    os.makedirs(out_dir, exist_ok=True)
    wr.write_bin(os.path.join(out_dir, "level.bin"))
    with open(os.path.join(out_dir, "level.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    return meta


def main():
    import glob
    root, out_root = sys.argv[1], sys.argv[2]   # extracted dir, export dir
    only = sys.argv[3:]
    index = []
    worlds_dir = os.path.join(root, "worlds")
    for dat in sorted(glob.glob(os.path.join(worlds_dir, "**", "*.dat"), recursive=True)):
        rel = os.path.relpath(dat, worlds_dir)[:-4]
        if only and not any(s in rel for s in only):
            continue
        meta = export(dat, os.path.join(out_root, "levels", rel), rel)
        tris = sum(s["count"] for m in meta["meshes"] for s in m["subs"]) // 3
        print(f"{rel:45} meshes={len(meta['meshes']):4} tris={tris:7} colliders={len(meta['colliders']):4} "
              f"objects={len(meta['objects'])}")
        index.append(rel)
    if not only:
        with open(os.path.join(out_root, "levels.json"), "w") as f:
            json.dump({"levels": index}, f, indent=1)


if __name__ == "__main__":
    main()
