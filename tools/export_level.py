"""Export a DAT v85 world to the viewer's runtime format.

<out>/level.json  metadata (materials, meshes, colliders, world models, objects)
<out>/level.bin   binary payload:
    char[4] 'TRLV', u32 version,
    u32 nVerts, u32 nIdx, u32 nColVerts, u32 nColIdx, u32 lmWidth, u32 lmHeight,
    render verts  (nVerts * 44 bytes: pos f32x3, normal f32x3, rgba u8x4, uv f32x2, lightmap uv f32x2)
    render idx    (u32, relative to the owning mesh's first vertex)
    collider verts (f32x3)
    collider idx  (u32, relative to the owning collider's first vertex)
    lightmap atlas (lmWidth * lmHeight * 4 bytes RGBA32, first row = v 0)
    light grid    (lightGrid.dims x*y*z RGB u8, x fastest then y then z; light groups added)

Lightmapping (d3d_renderblock.cpp): a lightmapped polygon is stored twice in its render block, once
in a "lightmap" section (shader 2: uv0 = lightmap coords, one RLE RGB lightmap per section) and once
in a "lightmap_texture" section (shader 4: the texture pass). The game draws the lightmap and then
multiplies the texture over it; here the lightmap texels are packed into one atlas per level and
the texture-pass triangles get the matching lightmap uv (matched by vertex position), so the
viewer draws both in one pass. Light groups (switchable lights) are added with their initial color.
All positions are raw LithTech units/space (left-handed, Y up — same handedness as Unity).
"""
import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import animation  # noqa: E402
import dat85  # noqa: E402
import export_models  # noqa: E402
import floor  # noqa: E402
import ltb  # noqa: E402
import modellight  # noqa: E402

FORMAT_VERSION = 10
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
        self.light_grid = None
        self.unmatched_lm_tris = 0

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
            subs = [lg.section_lms[si] if si < len(lg.section_lms) else [] for lg in b.light_groups]
            lmid = len(self.lightmaps)
            self.lightmaps.append(section_lightmap(s, subs, b.light_groups))
            for t in tris:
                pts = [b.verts["pos"][i].tobytes() for i in t]
                by_tri[tuple(sorted(pts))] = {p: (lmid, *b.verts["uv0"][i]) for p, i in zip(pts, t)}
        return by_tri

    def add_mesh(self, name, blocks):
        """Merge render blocks into one mesh with one submesh per material."""
        parts, lmids, by_mat = [], [], {}
        base = 0
        for b in blocks:
            if len(b.verts) == 0:
                continue
            v = np.zeros(len(b.verts), OUT_VERTEX)
            v["pos"] = b.verts["pos"]
            v["normal"] = b.verts["normal"]
            v["uv"] = np.nan_to_num(b.verts["uv0"], nan=0.0, posinf=0.0, neginf=0.0)
            c = apply_vertex_light_groups(b.verts["color"], b.light_groups)  # D3DCOLOR 0xAARRGGBB
            v["rgba"][:, 0] = (c >> 16) & 0xFF
            v["rgba"][:, 1] = (c >> 8) & 0xFF
            v["rgba"][:, 2] = c & 0xFF
            v["rgba"][:, 3] = (c >> 24) & 0xFF
            block_parts, block_lmids = [v], [np.full(len(v), NO_LIGHTMAP, np.int32)]
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
                    tris = np.arange(nv, nv + len(flat), dtype=np.uint32).reshape(-1, 3)
                    nv += len(flat)
                by_mat.setdefault(self.material(s), []).append(tris.astype(np.uint32) + base)
            parts += block_parts
            lmids += block_lmids
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
    p = {q["k"].lower(): q for q in o["props"]}
    if o["cls"] in ("CAIHuman", "Prop", "Alarm"):
        q = p.get("movetofloor")
        return bool(q["v"][0]) if q and q["t"] == "b" and q["v"] else True
    if o["cls"] in ("PropType", "Finder"):
        t = resolver.proptypes.get(p["type"]["s"].lower()) if "type" in p else None
        return bool(t.get("movetofloor", 1)) if t else False
    return False


def model_instances(objects, resolver, styles, extracted, sun_amount=None, floor_caster=None, idle=None):
    """Objects that show an .ltb the exporter can find (see export_models.Resolver), and the render
    styles their pieces use. Characters are skinned (bones = the model's nodes) and are followed by
    their attachments: parent = the character's entry, socket = the parent model socket they sit at.

    pos: where the instance spawns, after MoveToFloor (floor.py) against floor_caster with its model's
    dims (animation 0's, times its scale). anim (characters): the animation it loops, the idle that
    idle (animation.IdleSelector) picks, else animation 0, the one a model spawns in.

    Every instance carries its lighting inputs (modellight.py): dims (its model's, times its scale),
    the model's visRadius and sunAmount = sun_amount(object, dims) (0 without one), at pos. Attachments
    and the ArchiveBin frame use their own model's dims at their object's (the character's, the bin's)
    position: the exporter doesn't pose sockets, so the parent object's position stands in for theirs."""
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
        if pos is None:
            pos = list(o["pos"])
            if floor_caster is not None and moves_to_floor(o, resolver):
                pos = floor.move_to_floor(pos, dims[1], floor_caster)
        models.append({"obj": i, "file": r[0], "skins": r[1], "styles": r[2], "scale": scale,
                       "pieces": pieces, "skinned": int(skinned), "parent": parent, "socket": socket,
                       "pos": [float(x) for x in pos], "anim": "",
                       "dims": dims, "visRadius": m.vis_radius,
                       "sunAmount": sun_amount(dict(o, pos=pos), dims) if sun_amount else 0.0})
        return True

    by_name, turrets = {}, []
    for i, o in enumerate(objects):
        r = resolver.resolve(o)
        if not r:
            continue
        scale = next((q["v"] for q in o["props"] if q["k"] == "Scale" and q["t"] == "v"), [1, 1, 1])
        if o["cls"] == "TronTurret":   # attached to another object's model: once all of them exist
            turrets.append((i, r, scale))
            continue
        character = o["cls"] == "CAIHuman"
        if not add(i, r, scale, character):
            continue
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
            # item socket. The game deals the items to Socket1..SocketN-1 in a random order (rand() shuffle,
            # 0x1000f730); the exporter keeps item order: item k at Socket{k}.
            for k, berry in enumerate(resolver.bin_items(o), 1):
                add(i, resolver.template(berry), [1, 1, 1], False, bin_index, f"Socket{k}", pos=placed)
        if not character:
            continue
        parent = len(models) - 1
        models[parent]["anim"] = character_anim(styles, extracted, r[0], idle.idle(o, i) if idle else None)
        sockets = {s.name.lower() for s in styles.model(r[0]).sockets}
        for socket, *att in resolver.attachments(o):
            if socket.lower() not in sockets:   # CreateAttachment fails: "unable to create socket"
                resolver.missing_sockets[(r[0], socket)] = resolver.missing_sockets.get((r[0], socket), 0) + 1
                continue
            add(i, att, [1, 1, 1], True, parent, socket, pos=placed)
    # TronTurret (object.lto 0x1006c960, 0x1006d590) finds the object named by its Parent property and,
    # every update, puts itself at that object's ParentSocket: a socket attachment for a static frame.
    # Aiming at its Target turns it from there (behavior).
    for i, r, scale in turrets:
        p = {q["k"].lower(): q["s"] for q in objects[i]["props"] if q["t"] == "s"}
        parent = by_name.get(p.get("parent", "").strip().lower())
        if parent is None or p.get("parentsocket", "").lower() not in \
                {s.name.lower() for s in styles.model(models[parent]["file"]).sockets}:
            add(i, r, scale, False)   # "could not find a parent": it stays where it was placed
            continue
        add(i, r, scale, False, parent, p["parentsocket"], pos=models[parent]["pos"])
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


def export(dat_path, out_dir, rel_name, resolver, styles, extracted, idle=None):
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

    # Model lighting (modellight.py): the light grid, the static object lights and the sun; the
    # viewer lights each instance from these. The sun's sky visibility needs the world polygons, so
    # it's computed here per instance.
    wr.light_grid = modellight.with_light_groups(w.light_grid, w.grid_light_groups)
    lights = modellight.static_lights(w.objects, modellight.light_group_colors(w))
    sun = modellight.sun_light(w.objects)
    sky = modellight.SkyCaster.from_bsp(physics) if sun else None

    def sun_amount(o, dims):
        if not sky:
            return 0.0
        return sky.sun_amount(o["pos"], sun["dir"], modellight.euler_right(o["rot"]), float(np.linalg.norm(dims)))

    # Characters and props that ask for it stand on the floor (floor.py); characters loop their idle.
    models, render_styles = model_instances(objects, resolver, styles, extracted, sun_amount,
                                            floor.FloorCaster.from_world(w),
                                            idle or animation.IdleSelector(extracted, resolver))

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
        "models": models,
        "renderStyles": render_styles,
        "lightGrid": {"origin": list(w.light_grid.base), "cell": list(w.light_grid.cell),
                      "dims": list(w.light_grid.dims)},
        "lights": lights,
        "sun": sun or {"dir": [0.0, -1.0, 0.0], "color": [0.0, 0.0, 0.0], "toAmbient": 0.0},
    }
    wr.finish_lightmaps()
    meta["lightmap"] = list(wr.lm_atlas.shape[1::-1]) if wr.lm_atlas is not None else [0, 0]
    meta["unmatchedLightmapTris"] = wr.unmatched_lm_tris
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
    resolver = export_models.Resolver(root)
    styles = export_models.Styles(root)
    idle = animation.IdleSelector(root, resolver)
    model_files = {}   # model file -> the animations its instances play
    worlds_dir = os.path.join(root, "worlds")
    for dat in sorted(glob.glob(os.path.join(worlds_dir, "**", "*.dat"), recursive=True)):
        rel = os.path.relpath(dat, worlds_dir)[:-4]
        if only and not any(s in rel for s in only):
            continue
        meta = export(dat, os.path.join(out_root, "levels", rel), rel, resolver, styles, root, idle)
        tris = sum(s["count"] for m in meta["meshes"] for s in m["subs"]) // 3
        print(f"{rel:45} meshes={len(meta['meshes']):4} tris={tris:7} colliders={len(meta['colliders']):4} "
              f"objects={len(meta['objects'])} models={len(meta['models'])}")
        index.append(rel)
        for m in meta["models"]:
            anims = model_files.setdefault(m["file"], set())
            if m["anim"]:
                anims.add(m["anim"])
    for rel, anims in sorted(model_files.items()):
        try:
            export_models.export_model(root, rel, out_root, sorted(anims), styles.model)
        except Exception as e:  # noqa: BLE001 - report and keep exporting the rest
            print(f"model {rel}: {e}")
    print(f"{len(model_files)} models, {sum(len(a) for a in model_files.values())} animation clips")
    for (f, name), n in sorted(MISSING_ANIMS.items()):
        print(f"idle animation {name} not in {f} or its child models, animation 0 instead: {n}")
    for (f, socket), n in sorted(resolver.missing_sockets.items()):
        print(f"attachment dropped, no socket {socket} on {f}: {n}")
    for rel in sorted(styles.missing):
        print(f"render style {rel} not found, default style instead")
    for cls, n in sorted(resolver.undrawn_attachments.items()):
        print(f"{n} {cls} attachments not drawn (not a model object)")
    if resolver.hidden_weapons:
        print(f"{resolver.hidden_weapons} weapon attachments not drawn (no hand-held model)")
    if not only:
        with open(os.path.join(out_root, "levels.json"), "w") as f:
            json.dump({"levels": index}, f, indent=1)


if __name__ == "__main__":
    main()
