"""Export a DAT v85 world to the viewer's runtime format.

<out>/level.json  metadata (materials, meshes, colliders, world models, spinners, SoundFX, keyframers, objects)
<out>/level.bin   binary payload:
    char[4] 'TRLV', u32 version,
    u32 nVerts, u32 nIdx, u32 nColVerts, u32 nColIdx, u32 lmWidth, u32 lmHeight,
    render verts  (nVerts * 44 bytes: pos f32x3, normal f32x3, rgba u8x4, uv f32x2, lightmap uv f32x2)
    render idx    (u32, relative to the owning mesh's first vertex)
    collider verts (f32x3)
    collider idx  (u32, relative to the owning collider's first vertex)
    lightmap atlas (lmWidth * lmHeight * 4 bytes RGBA32, first row = v 0)
    light grid    (lightGrid.dims x*y*z RGB u8, x fastest then y then z; no light groups)
    light groups  (lightGroupPools: vertices x u32 global vertex index, vertices x u8 intensity,
                   texels x u8 lightmap intensity, gridSamples x u8; see Writer.light_groups)

Lightmapping (d3d_renderblock.cpp): a lightmapped polygon is stored twice in its render block, once
in a "lightmap" section (shader 2: uv0 = lightmap coords, one RLE RGB lightmap per section) and once
in a "lightmap_texture" section (shader 4: the texture pass). The game draws the lightmap and then
multiplies the texture over it; here the lightmap texels are packed into one atlas per level and
the texture-pass triangles get the matching lightmap uv (matched by vertex position), so the
viewer draws both in one pass. Light groups (switchable lights) are kept apart: the vertex colours,
lightmaps and light grid hold none, and the viewer adds each group at its live colour.
All positions are raw LithTech units/space (left-handed, Y up — same handedness as Unity).
"""
import collections
import json
import os
import re
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import activate  # noqa: E402
import ambient  # noqa: E402
import clientfx  # noqa: E402
import commands  # noqa: E402
import animation  # noqa: E402
import dat85  # noqa: E402
import export_models  # noqa: E402
import floor  # noqa: E402
import keyframer  # noqa: E402
import ltb  # noqa: E402
import modellight  # noqa: E402
import dialogue  # noqa: E402
import sounds  # noqa: E402
import hudtext  # noqa: E402
import spinner  # noqa: E402

FORMAT_VERSION = 27
RENDERED_SHADERS = {1, 4, 5, 8, 9}  # gouraud, lightmap_texture, skypan, dualtexture, lightmap_dualtexture
LIGHTMAP_SHADER = 2
LIGHTMAPPED_SHADERS = {4, 9}
# Without a second texture the engine draws these as plain texture sections (AllocShader falls back
# to Gouraud_Texture / Lightmap_Texture, ignoring EnvMap/DetailTex); every retail one is like that.
DUAL_TEXTURE_SHADERS = {8, 9}
NO_LIGHTMAP = -1      # lmid: vertex has no lightmap uv
NEUTRAL_LIGHTMAP = 0  # lmid of the 50% grey patch (x2 = unlit texture) for unmatched texture-pass tris

# Unity's canonical attribute order: Position, Normal, Color, TexCoord0, TexCoord1
OUT_VERTEX = np.dtype([("pos", "<f4", 3), ("normal", "<f4", 3), ("rgba", "u1", 4), ("uv", "<f4", 2),
                       ("uv2", "<f4", 2)])
assert OUT_VERTEX.itemsize == 44


def apply_vertex_light_groups(colors, light_groups):
    """Add each light group's per-vertex intensities (RLE: value, or 0 + skip count) times its
    color to the D3DCOLOR vertex colors, clamped per channel (CD3D_RenderBlock lighting)."""
    if not light_groups:
        return colors
    rgb = np.stack([(colors >> 16) & 0xFF, (colors >> 8) & 0xFF, colors & 0xFF], 1).astype(np.int64)
    for lg in light_groups:
        col = np.array(lg.color, np.float32)
        if not (col * 255).astype(np.uint32).any():
            continue
        vi, i, v = lg.vertex_intensities, 0, 0
        while v < len(colors) and i < len(vi):
            val = vi[i]
            i += 1
            if val == 0:
                v += vi[i] + 1
                i += 1
                continue
            rgb[v] = np.minimum(rgb[v] + (col * np.float32(val)).astype(np.uint32), 255)
            v += 1
    rgb = rgb.astype(np.uint32)
    return (colors & 0xFF000000) | (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]


def section_lightmap(s, sub_lms, light_groups):
    """Decompressed RGB lightmap of a shader-2 section with the light groups' sub-lightmaps added
    (CD3D_RenderBlock::UpdateShaderLightmaps)."""
    img = np.frombuffer(dat85.decompress_lightmap(s.lm_data, s.lm_w, s.lm_h), np.uint8)
    img = img.reshape(s.lm_h, s.lm_w, 3).astype(np.int64)
    for lg, subs in zip(light_groups, sub_lms):
        col = np.array(lg.color, np.float32)
        if not (col * 255).astype(np.uint32).any():
            continue
        for left, top, w, h, data in subs:
            i, run, run_val = 0, 0, None
            for y in range(top, top + h):
                for x in range(left, left + w):
                    if run:
                        add = run_val
                        run -= 1
                    else:
                        if data[i] == 0xFF:
                            run = data[i + 1]
                            i += 2
                        add = (col * np.float32(data[i])).astype(np.uint32)
                        i += 1
                        if run:
                            run_val = np.minimum(add, 255)
                    img[y, x] = np.minimum(img[y, x] + add, 255)
    return img.astype(np.uint8)


def vertex_light_group_intensities(lg, n):
    """A light group's per-vertex intensities (RLE: value, or 0 + skip count) as n uint8s."""
    out = np.zeros(n, np.uint8)
    vi, i, v = lg.vertex_intensities, 0, 0
    while v < n and i < len(vi):
        val = vi[i]
        i += 1
        if val == 0:
            v += vi[i] + 1
            i += 1
            continue
        out[v] = val
        v += 1
    return out


def lightmap_patch_intensities(left, top, w, h, data):
    """A light group's sub-lightmap (RLE intensities: value, or 0xFF + run count + value for run + 1
    texels) as an (h, w) uint8 array, as section_lightmap reads it."""
    out = np.zeros((h, w), np.uint8)
    i, run, run_val = 0, 0, 0
    for y in range(h):
        for x in range(w):
            if run:
                out[y, x] = run_val
                run -= 1
                continue
            if data[i] == 0xFF:
                run = data[i + 1]
                i += 2
            out[y, x] = run_val = data[i]
            i += 1
    return out


def pack_atlas(images, pad=1):
    """Shelf-pack lightmaps (edges replicated by `pad` texels so bilinear filtering never bleeds).
    Returns (atlas RGBA, list of (x, y) of each image's first texel)."""
    area = sum((w + 2 * pad) * (h + 2 * pad) for h, w, _ in (i.shape for i in images))
    width = 256
    widest = max(i.shape[1] for i in images) + 2 * pad
    while width < 4096 and (width * width < area * 1.3 or width < widest):
        width *= 2
    order = sorted(range(len(images)), key=lambda k: -images[k].shape[0])
    pos, x, y, shelf = [None] * len(images), 0, 0, 0
    for k in order:
        h, w = images[k].shape[0] + 2 * pad, images[k].shape[1] + 2 * pad
        if x + w > width:
            x, y, shelf = 0, y + shelf, 0
        pos[k] = (x + pad, y + pad)
        x += w
        shelf = max(shelf, h)
    height = max(4, (y + shelf + 3) // 4 * 4)
    atlas = np.zeros((height, width, 4), np.uint8)
    atlas[..., 3] = 255
    for img, (px, py) in zip(images, pos):
        padded = np.pad(img, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        h, w = padded.shape[:2]
        atlas[py - pad:py - pad + h, px - pad:px - pad + w, :3] = padded
    return atlas, pos


class Writer:
    def __init__(self):
        self.verts, self.idx, self.cverts, self.cidx = [], [], [], []
        self.nv = self.ni = self.ncv = self.nci = 0
        self.materials, self.mat_index = [], {}
        self.meshes, self.colliders = [], []
        self.lightmaps = [np.full((2, 2, 3), 128, np.uint8)]  # NEUTRAL_LIGHTMAP
        self.lm_fixups = []  # (vertex array, lmid array): local lightmap uv -> atlas uv at write time
        self.lm_atlas = None
        self.lm_pos = None
        self.light_grid = None
        self.grid_light_groups = []
        self.unmatched_lm_tris = 0
        # Light groups, kept apart from the base lighting (the viewer adds them at their live colour):
        # name -> DAT colour (first seen), per-vertex (global index, intensity) and lightmap patches
        # (lmid, left, top, intensities (h, w)).
        self.lg_color = {}
        self.lg_verts = collections.defaultdict(list)
        self.lg_patches = collections.defaultdict(list)

    def material(self, s):
        key = (s.textures[0].replace("\\", "/").lower(), s.textures[1].replace("\\", "/").lower(),
               s.shader, s.effect.lower())
        if s.shader in DUAL_TEXTURE_SHADERS and key[1]:
            raise ValueError(f"dual-texture section with a second texture ({key[1]}): not supported")
        if key not in self.mat_index:
            self.mat_index[key] = len(self.materials)
            self.materials.append({"tex": key[0], "tex2": key[1], "shader": key[2], "effect": key[3]})
        return self.mat_index[key]

    def block_lightmaps(self, b):
        """Register the block's lightmaps; map each lightmap triangle (by its sorted vertex
        positions) to {position: (lmid, u, v)}."""
        by_tri = {}
        start = 0
        for si, s in enumerate(b.sections):
            n = s.tri_count
            tris = b.tris[start:start + n]
            start += n
            if s.shader != LIGHTMAP_SHADER or not s.lm_data:
                continue
            lmid = len(self.lightmaps)
            self.lightmaps.append(section_lightmap(s, [], []))
            for lg in b.light_groups:
                self.lg_color.setdefault(lg.name, tuple(lg.color))
                for left, top, w, h, data in (lg.section_lms[si] if si < len(lg.section_lms) else []):
                    self.lg_patches[lg.name].append((lmid, left, top, lightmap_patch_intensities(left, top, w, h, data)))
            for t in tris:
                pts = [b.verts["pos"][i].tobytes() for i in t]
                by_tri[tuple(sorted(pts))] = {p: (lmid, *b.verts["uv0"][i]) for p, i in zip(pts, t)}
        return by_tri

    def add_mesh(self, name, blocks):
        """Merge render blocks into one mesh with one submesh per material."""
        parts, lmids, srcs, by_mat = [], [], [], {}
        lit_blocks = []   # (block number in srcs, block) of the blocks with light groups
        base = 0
        for bn, b in enumerate(blocks):
            if len(b.verts) == 0:
                continue
            if b.light_groups:
                lit_blocks.append((bn, b))
            v = np.zeros(len(b.verts), OUT_VERTEX)
            v["pos"] = b.verts["pos"]
            v["normal"] = b.verts["normal"]
            v["uv"] = np.nan_to_num(b.verts["uv0"], nan=0.0, posinf=0.0, neginf=0.0)
            c = b.verts["color"]  # D3DCOLOR 0xAARRGGBB, light groups apart
            v["rgba"][:, 0] = (c >> 16) & 0xFF
            v["rgba"][:, 1] = (c >> 8) & 0xFF
            v["rgba"][:, 2] = c & 0xFF
            v["rgba"][:, 3] = (c >> 24) & 0xFF
            block_parts, block_lmids = [v], [np.full(len(v), NO_LIGHTMAP, np.int32)]
            block_srcs = [np.stack([np.full(len(v), bn, np.int32), np.arange(len(v), dtype=np.int32)], 1)]
            nv = len(v)
            lm_tris = None
            start = 0
            for s in b.sections:
                tris = b.tris[start:start + s.tri_count]
                start += s.tri_count
                if s.shader not in RENDERED_SHADERS or len(tris) == 0:
                    continue
                if s.shader in LIGHTMAPPED_SHADERS:
                    if lm_tris is None:
                        lm_tris = self.block_lightmaps(b)
                    # Unshared copies of the texture-pass vertices carrying the lightmap uv.
                    flat = tris.reshape(-1)
                    nv_extra = v[flat]
                    ids = np.full(len(flat), NEUTRAL_LIGHTMAP, np.int32)
                    for k, t in enumerate(tris):
                        pts = [b.verts["pos"][i].tobytes() for i in t]
                        m = lm_tris.get(tuple(sorted(pts)))
                        if m is None:
                            self.unmatched_lm_tris += 1
                            nv_extra["uv2"][3 * k:3 * k + 3] = 0.5
                            continue
                        for j, p in enumerate(pts):
                            ids[3 * k + j], u, vv = m[p]
                            nv_extra["uv2"][3 * k + j] = (u, vv)
                    block_parts.append(nv_extra)
                    block_lmids.append(ids)
                    block_srcs.append(np.stack([np.full(len(flat), bn, np.int32), flat.astype(np.int32)], 1))
                    tris = np.arange(nv, nv + len(flat), dtype=np.uint32).reshape(-1, 3)
                    nv += len(flat)
                by_mat.setdefault(self.material(s), []).append(tris.astype(np.uint32) + base)
            parts += block_parts
            lmids += block_lmids
            srcs += block_srcs
            base += nv
        if not by_mat:
            return -1
        subs, local = [], 0
        idx_parts = []
        for mat, tri_parts in by_mat.items():
            ids = np.concatenate(tri_parts).reshape(-1)
            subs.append({"mat": mat, "start": local, "count": int(len(ids))})
            idx_parts.append(ids)
            local += len(ids)
        # Keep only referenced vertices (drops the originals of the copied texture-pass vertices).
        used, remap = np.unique(np.concatenate(idx_parts), return_inverse=True)
        out, lmid, idx = np.concatenate(parts)[used], np.concatenate(lmids)[used], remap.astype(np.uint32)
        if (lmid != NO_LIGHTMAP).any():
            self.lm_fixups.append((out, lmid))
        src = np.concatenate(srcs)[used]
        for bn, b in lit_blocks:
            mask = src[:, 0] == bn
            local = np.nonzero(mask)[0]
            for lg in b.light_groups:
                self.lg_color.setdefault(lg.name, tuple(lg.color))
                vals = vertex_light_group_intensities(lg, len(b.verts))[src[mask, 1]]
                keep = vals > 0
                if keep.any():
                    self.lg_verts[lg.name].append(((self.nv + local[keep]).astype(np.uint32), vals[keep]))
        pos = out["pos"]
        mesh = {"name": name, "vtxOffset": self.nv, "vtxCount": int(len(out)), "idxOffset": self.ni,
                "subs": subs, "min": pos.min(0).tolist(), "max": pos.max(0).tolist()}
        self.verts.append(out)
        self.idx.append(idx)
        self.nv += len(out)
        self.ni += len(idx)
        self.meshes.append(mesh)
        return len(self.meshes) - 1

    def finish_lightmaps(self):
        """Pack the lightmap atlas and turn local lightmap uvs into atlas uvs."""
        if not self.lm_fixups:
            return
        atlas, pos = pack_atlas(self.lightmaps)
        self.lm_pos = pos
        height, width = atlas.shape[:2]
        org = np.array(pos, np.float32)
        size = np.array([(i.shape[1], i.shape[0]) for i in self.lightmaps], np.float32)
        for out, lmid in self.lm_fixups:
            m = lmid != NO_LIGHTMAP
            k = lmid[m]
            out["uv2"][m] = (org[k] + out["uv2"][m] * size[k]) / np.array([width, height], np.float32)
        self.lm_atlas = atlas

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

    def light_groups(self):
        """The light groups' table for level.json and their pools for level.bin, in the order the DAT
        names them (render blocks, then grid groups): per group its DAT colour, its vertices
        [vtxStart, +vtxCount) in the vertex pools, its lightmap patches (rect in the section's lightmap,
        `lm` into lightmapRects: that lightmap's place in the atlas, texels from `start` in the texel
        pool, row-major) and its grid box (min node, ext nodes, samples from `start`, x fastest)."""
        names = list(self.lg_color)
        for g in self.grid_light_groups:
            if g.name not in self.lg_color:
                self.lg_color[g.name] = tuple(g.color)
                names.append(g.name)
        grid = {g.name: g for g in self.grid_light_groups}
        rects, rect_of = [], {}
        vidx, vval, texels, samples = [], [], [], []
        nv = nt = ns = 0
        table = []
        for name in names:
            entry = {"name": name, "color": [float(c) for c in self.lg_color[name]], "vtxStart": nv}
            for idx, vals in self.lg_verts.get(name, []):
                vidx.append(idx)
                vval.append(vals)
                nv += len(idx)
            entry["vtxCount"] = nv - entry["vtxStart"]
            patches = []
            for lmid, left, top, vals in self.lg_patches.get(name, []):
                if lmid not in rect_of:
                    rect_of[lmid] = len(rects)
                    x, y = self.lm_pos[lmid]
                    h, w = self.lightmaps[lmid].shape[:2]
                    rects.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h)})
                patches.append({"lm": rect_of[lmid], "x": int(left), "y": int(top), "w": int(vals.shape[1]),
                                "h": int(vals.shape[0]), "start": nt})
                texels.append(vals.reshape(-1))
                nt += vals.size
            entry["patches"] = patches
            g = grid.get(name)
            if g is not None:
                entry["grid"] = {"min": [int(v) for v in g.min], "ext": [int(v) for v in g.ext], "start": ns}
                samples.append(g.samples.reshape(-1))
                ns += g.samples.size
            table.append(entry)

        def cat(parts, dtype):
            return np.concatenate(parts).astype(dtype) if parts else np.zeros(0, dtype)
        self.lg_pools = [cat(vidx, np.uint32), cat(vval, np.uint8), cat(texels, np.uint8), cat(samples, np.uint8)]
        return table, rects, {"vertices": nv, "texels": nt, "gridSamples": ns}

    def write_bin(self, path):
        with open(path, "wb") as f:
            f.write(b"TRLV")
            lm = self.lm_atlas
            lm_h, lm_w = lm.shape[:2] if lm is not None else (0, 0)
            f.write(struct.pack("<7I", FORMAT_VERSION, self.nv, self.ni, self.ncv, self.nci, lm_w, lm_h))
            for a in self.verts + self.idx + self.cverts + self.cidx:
                f.write(np.ascontiguousarray(a).tobytes())
            if lm is not None:
                f.write(np.ascontiguousarray(lm).tobytes())
            if self.light_grid is not None:
                f.write(np.ascontiguousarray(self.light_grid.data).tobytes())
            for a in getattr(self, "lg_pools", []):
                f.write(np.ascontiguousarray(a).tobytes())


def polys_to_tris(polys):
    pts, tris = [], []
    for _plane, verts in polys:
        b = len(pts)
        pts.extend(verts.tolist())
        tris.extend(dat85.fan(range(b, b + len(verts))))
    return np.array(pts, np.float32).reshape(-1, 3), np.array(tris, np.uint32).reshape(-1, 3)


def encode_prop(k, v):
    if isinstance(v, str):
        return {"k": k, "t": "s", "s": v, "v": []}
    if isinstance(v, bool):
        return {"k": k, "t": "b", "s": "", "v": [1.0 if v else 0.0]}
    if isinstance(v, list):
        return {"k": k, "t": "v", "s": "", "v": [float(x) for x in v]}
    return {"k": k, "t": "n", "s": "", "v": [float(v)]}


def moves_to_floor(o, resolver):
    """Whether the object runs MoveToFloor when it spawns: CCharacter and Prop read the object's
    MoveToFloor (default TRUE, character.cpp / prop.cpp); a PropType (and Finder) takes its type's
    proptypes.txt entry. ArchiveBin / SecRezzer (Tron classes without source) aren't moved."""
    p = export_models.props(o)
    if o["cls"] in ("CAIHuman", "Prop", "Alarm"):
        q = p.get("movetofloor")
        return bool(q["v"][0]) if q and q["t"] == "b" and q["v"] else True
    if o["cls"] in ("PropType", "Finder"):
        t = resolver.proptypes.get(export_models.string(p, "type").lower())
        return bool(t.get("movetofloor", 1)) if t else False
    return False


# Models whose look follows a state the viewer runs (docs/research/secrezzer-binarybit.md): the clips the
# class plays, and its looks, each a full set of instance pieces: BinaryBit swaps render style slot 0
# (Idle / Yes / No), SecRezzer skin slot 0 (its template's Skin0..Skin3: idle, off, on, spawn).
STATE_CLIPS = {"BinaryBit": ["PoweredDown", "Idle", "Yes", "No"], "SecRezzer": ["Idle", "Disable", "Disabled"]}


def state_looks(cls, skins, rs):
    """[(look name, skins, render styles)] of a state model."""
    if cls == "BinaryBit":
        return [(name, skins, [rs[k]] + rs[1:]) for k, name in enumerate(("idle", "yes", "no"))]
    return [(name, [skins[k]] + skins[1:], rs) for k, name in enumerate(("idle", "off", "on", "spawn")) if k < len(skins)]


def bute_sound_keys(styles, models):
    """The soundbutes the state models' clips name in BUTE_SOUND_KEY animation keys, in order."""
    names = []
    for m in models:
        anims = {a.name.lower(): a for a in styles.model(m["file"]).anims}
        for clip in m.get("clips", []):
            for _t, cmd in anims[clip.lower()].commands:
                for statement in cmd.split(";"):
                    words = statement.split()
                    if len(words) >= 2 and words[0].lower() == "bute_sound_key" and words[1] not in names:
                        names.append(words[1])
    return names


def shake_sounds(objects):
    """The ShakeSound names of a level's ScreenShake objects (level.json form), once each, in order."""
    names = []
    for o in objects:
        if o["cls"] != "ScreenShake":
            continue
        name = next((p["s"] for p in o["props"] if p["k"] == "ShakeSound" and p["t"] == "s"), "").strip()
        if name and name not in names:
            names.append(name)
    return names


def bute_sounds(names, soundbutes):
    """Each soundbute an animation key or a ScreenShake plays: its files and radii (inherited through its
    Parent)."""
    return [{"name": n, "files": soundbutes.files(n), "inner": float(soundbutes.get(n, "innerradius", 0.0)),
             "outer": float(soundbutes.get(n, "outerradius", 0.0))} for n in names if soundbutes.is_soundbute(n)]


def model_instances(objects, resolver, styles, extracted, sun_amount=None, floor_caster=None, idle=None,
                    templates=(), named_anims=()):
    """Objects that show an .ltb the exporter can find (see export_models.Resolver), and the render
    styles their pieces use. Characters are skinned (bones = the model's nodes) and are followed by
    their attachments: parent = the character's entry, socket = the parent model socket they sit at.

    pos: where the instance spawns, after MoveToFloor (floor.py) against floor_caster with its model's
    dims (animation 0's, times its scale). anim (characters): the animation it loops, the idle that
    idle (animation.IdleSelector) picks, else animation 0, the one a model spawns in.
    childModels (characters): its ChildModel_N files (animation.child_model_files). anims (characters):
    every animation it can play by name, {name, from} (animation.playable: its idle, the `named_anims`
    the level's commands name and DXBLoop where its model has them, from = ""; then every animation of
    its childModels, from = the file). lookAt (characters): the nodes it turns to look at something
    (Resolver.look_at_nodes).

    Every instance carries its lighting inputs (modellight.py): dims (its model's, times its scale),
    the model's visRadius and sunAmount = sun_amount(object, dims) (0 without one), at pos. Attachments
    and the ArchiveBin frame use their own model's dims at their object's (the character's, the bin's)
    position: the exporter doesn't pose sockets, so the parent object's position stands in for theirs.

    templates: indices of CAIHuman templates a Spawner copies (spawn_sites). They and their attachments
    are listed with template = 1, at the template's own position, unlit: the viewer builds them only when
    spawned, at a spawn site (place_sites)."""
    models, render_styles, style_index = [], [], {}

    def add(i, r, scale, skinned, parent=-1, socket="", pos=None):
        if not os.path.isfile(os.path.join(extracted, r[0])):
            return False
        try:
            styles.model(r[0])
        except ltb.Unsupported:  # the engine refuses it too: the game draws nothing there
            return False
        except Exception as e:  # noqa: BLE001 - report and leave the instance out
            print(f"model {r[0]}: {e}")
            return False
        pieces = styles.instance_pieces(r[0], r[1], r[2], render_styles, style_index)
        m = styles.model(r[0])
        dims = [d * s for d, s in zip(export_models.model_dims(m), scale)]
        o = objects[i]
        template = i in templates
        if pos is None:
            pos = list(o["pos"])
            if floor_caster is not None and not template and moves_to_floor(o, resolver):
                pos = floor.move_to_floor(pos, dims[1], floor_caster)
        models.append({"obj": i, "file": r[0], "skins": r[1], "styles": r[2], "scale": scale,
                       "pieces": pieces, "skinned": int(skinned), "parent": parent, "socket": socket,
                       "pos": [float(x) for x in pos], "anim": "",
                       "dims": dims, "visRadius": m.vis_radius,
                       "sunAmount": sun_amount(dict(o, pos=pos), dims) if sun_amount and not template else 0.0})
        if template:
            models[-1]["template"] = 1
        if parent < 0 and o["cls"] in STATE_CLIPS:
            models[-1].update(skinned=1, clips=STATE_CLIPS[o["cls"]], looks=[
                {"name": name, "pieces": styles.instance_pieces(r[0], sk, rs, render_styles, style_index)}
                for name, sk, rs in state_looks(o["cls"], r[1], r[2])])
        return True

    def attach(i, parent, atts, skinned, sockets):
        """atts: (socket, model file, skins, render styles) on models[parent], at one of `sockets` (its
        model's). One whose socket isn't there is dropped: CreateAttachment fails, "unable to create socket"."""
        names = {s.name.lower() for s in sockets}
        for socket, *att in atts:
            if socket.lower() not in names:
                key = (models[parent]["file"], socket)
                resolver.missing_sockets[key] = resolver.missing_sockets.get(key, 0) + 1
                continue
            add(i, att, [1, 1, 1], skinned, parent, socket, pos=models[parent]["pos"])

    by_name, turrets = {}, []
    for i, o in enumerate(objects):
        r = resolver.resolve(o, spawned=i in templates)
        if not r:
            continue
        scale = next((q["v"] for q in o["props"] if q["k"] == "Scale" and q["t"] == "v"), [1, 1, 1])
        if o["cls"] == "TronTurret":   # attached to another object's model: once all of them exist
            turrets.append((i, r, scale))
            continue
        character = o["cls"] == "CAIHuman"
        if not add(i, r, scale, character):
            continue
        if i not in templates:
            by_name.setdefault(o["name"].lower(), len(models) - 1)
        placed = models[-1]["pos"]
        # ArchiveBin's setup (object.lto 0x1000f360, called from 0x1000d23e) creates a second object from
        # the hard-coded template "ArchiveBin_Frame" and attaches it to the bin's "Frame" socket, which
        # is the identity: the frame sits at the bin's position and rotation, scale 1. It is the dark
        # border the game shows around the bin's glass.
        if o["cls"] == "ArchiveBin":
            bin_index = len(models) - 1
            add(i, resolver.template("ArchiveBin_Frame"), [1, 1, 1], False, pos=placed)
            # Then (0x1000f800) one "Berry" object per item, from the item type's template, attached to an
            # item socket: the model's sockets but the last (Frame). The game deals the items to them in a
            # random order (rand() shuffle, 0x1000f730); the exporter keeps item order: item k at Socket{k}.
            attach(i, bin_index, [(s, *resolver.template(t)) for s, t in resolver.bin_items(o)], False,
                   styles.model(r[0]).sockets[:-1])
        if not character:
            continue
        parent = len(models) - 1
        models[parent]["anim"] = character_anim(styles, extracted, r[0], idle.idle(o, i) if idle else None)
        models[parent].update(character_anims(styles, extracted, o, r[0], [models[parent]["anim"], *named_anims]))
        models[parent]["lookAt"] = resolver.look_at_nodes(o)
        attach(i, parent, resolver.attachments(o), True, styles.model(r[0]).sockets)
    parents = {name: (m, {s.name.lower() for s in styles.model(models[m]["file"]).sockets})
               for name, m in by_name.items()}
    for i, r, scale in turrets:
        mount = resolver.turret_mount(objects[i], parents)
        if mount is None:
            add(i, r, scale, False)   # "could not find a parent": it stays where it was placed
            continue
        add(i, r, scale, False, *mount, pos=models[mount[0]]["pos"])
    return models, render_styles


MISSING_ANIMS = {}   # (model file, animation) -> characters falling back to animation 0


def character_anim(styles, extracted, rel, name):
    """The animation a character model loops: `name` if the model or its child models have it, else
    animation 0."""
    m = styles.model(rel)
    if name:
        children = animation.load_children(extracted, rel, m, styles.model)
        _owner, a = animation.find_anim(m, children, name)
        if a is not None:
            return a.name
        MISSING_ANIMS[(rel, name)] = MISSING_ANIMS.get((rel, name), 0) + 1
    return m.anims[0].name if m.anims else ""


def spawn_sites(w):
    """Where the level's Spawners can create characters (ltjs spawner.cpp): [{"spawner", "at", "template"}]
    as object indices. A live Spawner whose Target names a CAIHuman template (FindTemplate: the last
    template with that name, AddTemplate overwriting) spawns it at its own position and rotation (`spawn`),
    or at those of the object a `spawnfrom <object>` names when exactly one object has that name (else at
    its own again). Other Targets create nothing a cutscene shows (light cycles, effects) or nothing at all
    (not a template)."""
    templates, named = {}, collections.defaultdict(list)
    for i, o in enumerate(w.objects):
        name = str(o["props"].get("Name", "")).lower()
        if o["props"].get("Template"):
            templates[name] = i
        else:
            named[name].append(i)
    sites, spawners = [], {}
    for i, o in enumerate(w.objects):
        if o["class"] != "Spawner" or o["props"].get("Template"):
            continue
        t = templates.get(str(o["props"].get("Target", "")).lower())
        if t is None or w.objects[t]["class"] != "CAIHuman":
            continue
        spawners[id(o)] = (i, t)
        sites.append({"spawner": i, "at": i, "template": t})
    for s, m in commands.spawn_messages(w):
        if id(s) not in spawners or len(m) < 2 or m[0].lower() != "spawnfrom":
            continue
        at = named.get(m[1].lower(), [])
        i, t = spawners[id(s)]
        site = {"spawner": i, "at": at[0] if len(at) == 1 else i, "template": t}
        if site not in sites:
            sites.append(site)
    return sites


def place_sites(sites, objects, models, floor_caster, sun_amount):
    """Each spawn site with where its character stands: the template's root model ("model", -1 when it
    draws none), "pos" (the place's position after the character's MoveToFloor with its model's dims, as
    CCharacter does when created), "rot" (the place's) and its "sunAmount" there."""
    root = {m["obj"]: k for k, m in enumerate(models) if m.get("template") and m["parent"] < 0}
    out = []
    for s in sites:
        at, template = objects[s["at"]], objects[s["template"]]
        k = root.get(s["template"], -1)
        pos, sun = [float(x) for x in at["pos"]], 0.0
        if k >= 0:
            dims = models[k]["dims"]
            if floor_caster is not None and moves_to_floor(template, None):
                pos = [float(x) for x in floor.move_to_floor(pos, dims[1], floor_caster)]
            if sun_amount:
                sun = float(sun_amount(dict(template, pos=pos, rot=at["rot"]), dims))
        out.append(dict(s, model=k, pos=pos, rot=[float(x) for x in at["rot"]], sunAmount=sun))
    return out


ANIM_PARAM = re.compile(r"(?i)\banim\s*=\s*([^\s();\"]+)")


def scripted_anims(w):
    """The animations the level's goal scripts name (goalscript animate anim=X, CAIGoalAnimate's ANIM),
    in its command strings (commands.level_commands), sorted, one per name (any case)."""
    names = {}
    for _cls, _prop, text in commands.level_commands(w):
        for m in ANIM_PARAM.finditer(text):
            names.setdefault(m.group(1).lower(), m.group(1))
    return [names[k] for k in sorted(names)]


def character_anims(styles, extracted, obj, rel, names):
    """A character's childModels and anims (see model_instances); names: the model-side names to look up."""
    m = styles.model(rel)
    children = animation.load_children(extracted, rel, m, styles.model)
    files = []
    for f in animation.child_model_files(extracted, obj):
        try:
            files.append((f, styles.model(f)))
        except Exception as e:  # noqa: BLE001 - the engine can't add it either
            print(f"child model {f}: {e}")
    plays = animation.playable(m, children, files, [n for n in [*names, "DXBLoop"] if n])
    return {"childModels": [f for f, _ in files], "anims": [{"name": n, "from": f} for n, f in plays]}


def attach_names(w):
    """The attachments the level's commands hang on characters (`msg <character> (attach <position> <name>)`,
    character.cpp ATTACH), sorted, one per name (any case). A character is a placed CAIHuman or a spawn name
    of a CAIHuman template."""
    characters = {o["props"].get("Name", "").lower() for o in w.objects
                  if o["class"] == "CAIHuman" and not o["props"].get("Template")}
    characters |= {s["name"].lower() for s in commands.spawn_names(w) if s["cls"] == "CAIHuman"}
    names = {}
    for _cls, prop, text in commands.level_commands(w):
        for words in commands.executed(prop, text):
            if words[0].upper() != "MSG" or commands.target_name(words[1]).lower() not in characters:
                continue
            for st in commands.statements(words[2]):
                if len(st) >= 3 and st[0].upper() == "ATTACH":
                    names.setdefault(st[2].lower(), st[2])
    return [names[k] for k in sorted(names)]


def key_attach_names(models, styles, extracted):
    """The attachments characters' animations hang on them by animation key (CCharacter::HandleModelString:
    `ATTACH <position> <name>`): the keys of every animation each character can play by name (its anims),
    sorted, one per name (any case)."""
    names = {}
    for m in models:
        if not m.get("anims"):
            continue
        own = styles.model(m["file"])
        mine = list(own.anims) + [a for c in animation.load_children(extracted, m["file"], own, styles.model)
                                  for a in c.anims]
        for ref in m["anims"]:
            pool = styles.model(ref["from"]).anims if ref["from"] else mine
            anim = next((a for a in pool if a.name.lower() == ref["name"].lower()), None)
            for _t, text in getattr(anim, "commands", []):
                for st in commands.statements(text):
                    if len(st) == 3 and st[0].upper() == "ATTACH":
                        names.setdefault(st[2].lower(), st[2])
    return [names[k] for k in sorted(names)]


def attachables(names, resolver, styles, extracted, render_styles):
    """What each attach name draws (Resolver.attachable), as a model instance the viewer builds on the
    character's socket when the message comes: {name, file, skins, styles, pieces, skinned 1, dims, visRadius}.
    Names that draw nothing are left out. Its pieces' styles join render_styles."""
    index = {c["name"]: i for i, c in enumerate(render_styles)}
    out = []
    for name in names:
        r = resolver.attachable(name)
        if not r or not os.path.isfile(os.path.join(extracted, r[0])):
            continue
        try:
            m = styles.model(r[0])
        except Exception as e:  # noqa: BLE001 - the engine can't create it either
            print(f"attachable {name} {r[0]}: {e}")
            continue
        out.append({"name": name, "file": r[0], "skins": r[1], "styles": r[2],
                    "pieces": styles.instance_pieces(r[0], r[1], r[2], render_styles, index),
                    "skinned": 1, "parent": -1, "socket": "", "scale": [1, 1, 1],
                    "dims": export_models.model_dims(m), "visRadius": m.vis_radius})
    return out


def fx_models(groups, styles, extracted, render_styles):
    """Each LTBModel key's look (CLTBModelFX::Init: Model, Skin0..4, RenderStyle0..3): its pieces' styles
    (added to the level's style table) and textures as for placed models, the clip it plays (AniName, or
    animation 0 when empty or not in the model: GetAnimIndex fails and the model keeps its first), and its
    lighting inputs (dims, visRadius). LTBBouncyChunk keys too (CLTBBouncyChunkFX::Init: Model and one
    Skin, no render styles, so every piece takes the engine's backup style), with no clip. A model that
    can't load gets no pieces: nothing draws."""
    index = {c["name"]: i for i, c in enumerate(render_styles)}
    for g in groups:
        for k in g["fx"]:
            if k["type"] not in ("LTBModel", "LTBBouncyChunk"):
                continue
            chunk = k["type"] == "LTBBouncyChunk"
            rel = clientfx.prop(k, "Model", "")
            k["pieces"], k["anim"], k["dims"], k["visRadius"] = [], "", [0.0, 0.0, 0.0], 0.0
            if not rel or not os.path.isfile(os.path.join(extracted, rel)):
                continue
            try:
                m = styles.model(rel)
            except Exception as e:  # noqa: BLE001 - the engine refuses it too: nothing draws
                print(f"effect model {rel}: {e}")
                continue
            if chunk:
                skins, rs = [clientfx.prop(k, "Skin", "")], []
            else:
                skins = [clientfx.prop(k, f"Skin{i}", "") for i in range(5)]
                rs = [clientfx.prop(k, f"RenderStyle{i}", "") for i in range(4)]
            k["pieces"] = styles.instance_pieces(rel, skins, rs, render_styles, index)
            if not chunk:
                k["anim"] = character_anim(styles, extracted, rel, clientfx.prop(k, "AniName", ""))
            k["dims"] = [float(x) for x in export_models.model_dims(m)]
            k["visRadius"] = float(m.vis_radius)


TALK_ICONS = {"LISTENICON", "SAYICON", "ASKICON"}
TALK_ICON_GROUP = "AI_TALKICON"   # cshell.dll 0x10169720: every talk icon is this group on the character


def talk_icon_groups(w):
    """[TALK_ICON_GROUP] when a command of the level (or a character's own Initial) turns a talk icon on
    (`listenicon` / `sayicon` / `askicon` with a true value, IsTrueChar), else []."""
    def on(words):
        return len(words) >= 2 and words[0].upper() in TALK_ICONS and words[1][:1] in "tTyY1" and words[1] != ""

    for cls, prop, text in commands.level_commands(w):
        if cls == "CAIHuman" and prop in commands.AI_MIXED:
            if any(on(st) for part in commands.mixed_parts(text) for st in commands.statements(part)):
                return [TALK_ICON_GROUP]
        for words in commands.executed(prop, text):
            if words[0].upper() == "MSG" and any(on(st) for st in commands.statements(words[2])):
                return [TALK_ICON_GROUP]
    return []


def fx_groups(objects, library, extra=()):
    """The effect groups a level's SpecialFX objects reach (with the groups their CreateFX and splats
    start), and the `extra` names its objects start themselves, in the viewer's form
    (clientfx.export_group), and the names that find no group."""
    names = [p["s"] for o in objects if o["cls"] == "SpecialFX" for p in o["props"] if p["k"] == "FxName"]
    names += list(extra)
    groups, missing = library.reached(names)
    return [clientfx.export_group(g) for g in groups], [n for n in missing if n.strip().lower() != "<none>"]


def export(dat_path, out_dir, rel_name, resolver, styles, extracted, idle=None, fx_library=None):
    w = dat85.load(dat_path)
    floor.place_world_models(w)
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

    # Model lighting (modellight.py): the light grid, the static object lights and the sun; the
    # viewer lights each instance from these. The sun's sky visibility needs the world polygons, so
    # it's computed here per instance.
    wr.light_grid = w.light_grid   # the light groups apart (Writer.light_groups)
    wr.grid_light_groups = w.grid_light_groups
    lights = modellight.static_lights(w.objects, {})   # each at its own colour; the viewer scales by its group
    sun = modellight.sun_light(w.objects)
    sky = modellight.SkyCaster.from_bsp(physics) if sun else None

    def sun_amount(o, dims):
        if not sky:
            return 0.0
        return sky.sun_amount(o["pos"], sun["dir"], modellight.euler_right(o["rot"]), float(np.linalg.norm(dims)))

    # Characters and props that ask for it stand on the floor (floor.py); characters loop their idle.
    # Spawned characters: their templates as template models, built where a Spawner creates them.
    caster = floor.FloorCaster.from_world(w)
    sites = spawn_sites(w)
    models, render_styles = model_instances(objects, resolver, styles, extracted, sun_amount, caster,
                                            idle or animation.IdleSelector(extracted, resolver),
                                            templates={s["template"] for s in sites},
                                            named_anims=scripted_anims(w))

    names = {n.lower(): n for n in key_attach_names(models, styles, extracted) + attach_names(w)}
    attached = attachables([names[k] for k in sorted(names)], resolver, styles, extracted, render_styles)
    soundbutes = sounds.soundbutes(extracted)
    fx, fx_missing = fx_groups(objects, fx_library or clientfx.Library(extracted), talk_icon_groups(w))
    fx_models(fx, styles, extracted, render_styles)
    key_sounds = bute_sound_keys(styles, models)
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
        "spinners": spinner.spinners(w.objects),
        "soundFX": ambient.sound_fx(w.objects, soundbutes),
        "soundButeFX": ambient.sound_bute_fx(w.objects, soundbutes),
        "keyframers": keyframer.keyframers(w.objects, w.blind),
        "activateTypes": activate.level_types(w.objects, extracted),
        "spawns": commands.spawn_names(w),
        "dialogues": dialogue.dialogues(objects, extracted),
        "speakers": dialogue.speakers(objects, extracted),
        "spawnSites": place_sites(sites, objects, models, caster, sun_amount),
        "fxGroups": fx,
        "fxMissing": fx_missing,
        "objects": objects,
        "models": models,
        "attachables": attached,
        "buteSounds": bute_sounds(key_sounds + [n for n in shake_sounds(objects) if n not in key_sounds], soundbutes),
        "renderStyles": render_styles,
        "lightGrid": {"origin": list(w.light_grid.base), "cell": list(w.light_grid.cell),
                      "dims": list(w.light_grid.dims)},
        "lights": lights,
        "sun": sun or {"dir": [0.0, -1.0, 0.0], "color": [0.0, 0.0, 0.0], "toAmbient": 0.0},
    }
    wr.finish_lightmaps()
    meta["lightmap"] = list(wr.lm_atlas.shape[1::-1]) if wr.lm_atlas is not None else [0, 0]
    meta["unmatchedLightmapTris"] = wr.unmatched_lm_tris
    meta["lightGroups"], meta["lightmapRects"], meta["lightGroupPools"] = wr.light_groups()
    os.makedirs(out_dir, exist_ok=True)
    wr.write_bin(os.path.join(out_dir, "level.bin"))
    with open(os.path.join(out_dir, "level.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    return meta


def clip_order(a):
    """Model clips (a name) before ChildModel_N clips ((name, file)), each by name."""
    return ("", a) if isinstance(a, str) else (a[1], a[0])


def main():
    import glob
    root, out_root = sys.argv[1], sys.argv[2]   # extracted dir, export dir
    only = sys.argv[3:]
    index = []
    resolver = export_models.Resolver(root)
    styles = export_models.Styles(root)
    idle = animation.IdleSelector(root, resolver)
    fx_library = clientfx.Library(root)
    fx_missing = {}     # effect group name -> levels naming it
    model_files = {}   # model file -> the animations its instances play
    level_objects = {}  # level -> its objects, for the sound files they name
    level_sounds = {}   # level -> the soundbutes its models' clips play
    worlds_dir = os.path.join(root, "worlds")
    for dat in sorted(glob.glob(os.path.join(worlds_dir, "**", "*.dat"), recursive=True)):
        rel = os.path.relpath(dat, worlds_dir)[:-4]
        if only and not any(s in rel for s in only):
            continue
        meta = export(dat, os.path.join(out_root, "levels", rel), rel, resolver, styles, root, idle, fx_library)
        tris = sum(s["count"] for m in meta["meshes"] for s in m["subs"]) // 3
        print(f"{rel:45} meshes={len(meta['meshes']):4} tris={tris:7} colliders={len(meta['colliders']):4} "
              f"objects={len(meta['objects'])} models={len(meta['models'])}")
        index.append(rel)
        level_objects[rel] = meta["objects"]
        fx_files, fx_sounds = clientfx.assets(meta["fxGroups"])
        level_sounds[rel] = [b["name"] for b in meta["buteSounds"]] + fx_sounds + dialogue.voices(meta["dialogues"])
        for f in fx_files:
            model_files.setdefault(f, set())
        for g in meta["fxGroups"]:
            for k in g["fx"]:
                if k.get("anim"):   # the clip an effect model plays (fx_models)
                    model_files[clientfx.prop(k, "Model")].add(k["anim"])
        for name in meta["fxMissing"]:
            fx_missing.setdefault(name, []).append(rel)
        for a in meta["attachables"]:
            model_files.setdefault(a["file"], set())
        for m in meta["models"]:
            anims = model_files.setdefault(m["file"], set())
            if m["anim"]:
                anims.add(m["anim"])
            anims.update(m.get("clips", []))
            # A character's playable animations: names in its model ("") or (name, ChildModel_N file).
            anims.update(a["name"] if not a["from"] else (a["name"], a["from"]) for a in m.get("anims", []))
    for rel, anims in sorted(model_files.items()):
        try:
            export_models.export_model(root, rel, out_root, sorted(anims, key=clip_order), styles.model)
        except Exception as e:  # noqa: BLE001 - report and keep exporting the rest
            print(f"model {rel}: {e}")
    print(f"{len(model_files)} models, {sum(len(a) for a in model_files.values())} animation clips")
    for (f, name), n in sorted(MISSING_ANIMS.items()):
        print(f"animation {name} not in {f} or its child models, animation 0 instead: {n}")
    for (f, socket), n in sorted(resolver.missing_sockets.items()):
        print(f"attachment dropped, no socket {socket} on {f}: {n}")
    for name, users in sorted(fx_missing.items()):
        print(f"effect group {name} not found, named in {', '.join(users)}")
    for rel in sorted(styles.missing):
        print(f"render style {rel} not found, default style instead")
    for cls, n in sorted(resolver.undrawn_attachments.items()):
        print(f"{n} {cls} attachments not drawn (not a model object)")
    if resolver.hidden_weapons:
        print(f"{resolver.hidden_weapons} weapon attachments not drawn (no hand-held model)")
    exported, missing = sounds.export_sounds(root, level_objects, out_root, level_sounds)
    print(f"{len(exported)} sound files")
    for rel, users in missing.items():
        print(f"sound file {rel} not found, named in {', '.join(users)}")
    strings, glyphs, hud_sounds = hudtext.export_hud(root, out_root)
    print(f"HUD: {len(strings)} strings, {len(glyphs)} glyphs, {len(hud_sounds)} sound files")
    if not only:
        with open(os.path.join(out_root, "levels.json"), "w") as f:
            json.dump({"levels": index}, f, indent=1)


if __name__ == "__main__":
    main()
