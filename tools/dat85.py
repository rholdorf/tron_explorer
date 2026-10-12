"""LithTech Jupiter world (.dat, version 85) parser — Tron 2.0 / NOLF2.

Sections (offsets from header):
  world info + extents + world tree + world models (BSPs: physics, vis, doors...)
  objects        (class name + typed properties)
  blind objects  (chunks of opaque object data: keyframer paths, see keyframer.py)
  light grid     (RGB samples for model lighting)
  blockers       (SURF_PHYSICSBLOCKER polys: invisible player blockers)
  particle blockers
  render data    (render blocks: vertices w/ uv0/uv1/normal, triangles, sections
                  with texture names + lightmaps; plus one render world per world model),
                 then the light grid's light groups, to EOF
Reference: ltjs (bibendovsky/ltjs) world_shared_bsp.cpp, de_mainworld.cpp, d3d_renderblock.cpp,
light_table.cpp
"""
import struct

import numpy as np

# World info flags
WIF_MOVEABLE = 1 << 1
WIF_MAINWORLD = 1 << 2
WIF_PHYSICSBSP = 1 << 4
WIF_VISBSP = 1 << 5

# Surface flags
SURF_SOLID = 1 << 0
SURF_NONEXISTENT = 1 << 1
SURF_INVISIBLE = 1 << 2
SURF_TRANSPARENT = 1 << 3
SURF_SKY = 1 << 4
SURF_PHYSICSBLOCKER = 1 << 17
SURF_ADDITIVE = 1 << 19

SHADER_NAMES = {0: "none", 1: "gouraud", 2: "lightmap", 4: "lightmap_texture", 5: "skypan",
                6: "skyportal", 7: "occluder", 8: "dualtexture", 9: "lightmap_dualtexture"}

PROP_TYPES = {0: "string", 1: "vector", 2: "color", 3: "real", 4: "flags", 5: "bool", 6: "longint", 7: "rotation"}

VERTEX_DTYPE = np.dtype([("pos", "<f4", 3), ("uv0", "<f4", 2), ("uv1", "<f4", 2), ("color", "<u4"),
                         ("normal", "<f4", 3)])
assert VERTEX_DTYPE.itemsize == 44  # retail files carry no tangent/binormal


class Reader:
    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def vec3(self):
        v = struct.unpack_from("<3f", self.d, self.p)
        self.p += 12
        return v

    def fmt(self, f):
        v = struct.unpack_from(f, self.d, self.p)
        self.p += struct.calcsize(f)
        return v

    def skip(self, n):
        self.p += n

    def raw(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def str16(self):
        n = self.u16()
        return self.raw(n).decode("latin-1")

    def str32(self):
        n = self.u32()
        return self.raw(n).decode("latin-1")

    def cstr(self):
        e = self.d.index(b"\0", self.p)
        s = self.d[self.p:e].decode("latin-1")
        self.p = e + 1
        return s

    def array(self, dtype, count):
        dt = np.dtype(dtype)
        a = np.frombuffer(self.d, dtype=dt, count=count, offset=self.p)
        self.p += dt.itemsize * count
        return a


# ---------------------------------------------------------------- BSP world models

def fan(vs):
    """A convex polygon's triangles as a fan from its first vertex: (vs[0], vs[k], vs[k + 1])."""
    return [(vs[0], vs[k], vs[k + 1]) for k in range(1, len(vs) - 1)]


class WorldBsp:
    def __init__(self):
        self.flags = 0
        self.name = ""
        self.textures = []
        self.planes = None        # (n,4) normal+dist
        self.surfaces = None      # (n,) flags, tex, texflags
        self.polys = []           # list of (surface, plane, [vert indices])
        self.points = None        # (n,3)
        self.min = self.max = self.translation = None
        self.nodes = None
        self.root = -1

    def solid_triangles(self, exclude_flags=SURF_NONEXISTENT):
        """Fan-triangulate polys whose surface is solid. Returns (verts, tris)."""
        tris = []
        for surf_i, _plane, vs in self.polys:
            sflags = int(self.surfaces[surf_i]["flags"])
            if not (sflags & SURF_SOLID) or (sflags & exclude_flags):
                continue
            tris.extend(fan(vs))
        return self.points, np.array(tris, dtype=np.uint32).reshape(-1, 3)


def read_world_bsp(r):
    b = WorldBsp()
    b.flags = r.u32()
    b.name = r.str16()
    (n_points, n_planes, n_surfaces, n_user_portals, n_polies, n_leafs, n_verts,
     _vis_size, _n_leaf_lists, n_nodes) = r.fmt("<10I")
    b.min, b.max, b.translation = r.vec3(), r.vec3(), r.vec3()
    if n_user_portals:
        raise ValueError("user portals not supported")
    _names_len = r.u32()
    n_textures = r.u32()
    b.textures = [r.cstr() for _ in range(n_textures)]
    vert_counts = r.raw(n_polies)
    for _ in range(n_leafs):
        n_lists = r.u16()
        if n_lists == 0xFFFF:
            r.u16()
        else:
            for _ in range(n_lists):
                r.u16()
                r.skip(r.u16())
    b.planes = r.array("<f4", n_planes * 4).reshape(-1, 4)
    b.surfaces = r.array([("flags", "<u4"), ("tex", "<u2"), ("texflags", "<u2")], n_surfaces)
    for i in range(n_polies):
        nv = vert_counts[i]
        surf, plane = r.fmt("<2I")
        verts = r.fmt(f"<{nv}I")
        b.polys.append((surf, plane, verts))
    b.nodes = r.array([("poly", "<u4"), ("leaf", "<u2"), ("sides", "<i4", 2)], n_nodes)
    b.points = r.array("<f4", n_points * 3).reshape(-1, 3)
    b.root = r.i32()
    if r.u32() != 0:
        raise ValueError("terrain sections not supported")
    return b


# ---------------------------------------------------------------- render data

class RenderSection:
    __slots__ = ("textures", "shader", "tri_count", "effect", "lm_w", "lm_h", "lm_data")


class RenderBlock:
    __slots__ = ("center", "half", "sections", "verts", "tris", "poly_ids", "children", "light_groups")


class LightGroup:
    """Switchable light baked separately (d3d_renderblock.cpp SRBLightGroup): added on top of the
    vertex colors and lightmaps scaled by `color` (0-1 per channel)."""
    __slots__ = ("name", "color", "vertex_intensities", "section_lms")


class RenderWorld:
    def __init__(self, name=""):
        self.name = name
        self.blocks = []
        self.world_models = []  # list of RenderWorld


def read_render_block(r):
    rb = RenderBlock()
    rb.center, rb.half = r.vec3(), r.vec3()
    rb.sections = []
    for _ in range(r.u32()):
        s = RenderSection()
        s.textures = [r.str16(), r.str16()]
        s.shader = r.u8()
        s.tri_count = r.u32()
        s.effect = r.str16()
        s.lm_w, s.lm_h = r.u32(), r.u32()
        s.lm_data = r.raw(r.u32())
        rb.sections.append(s)
    rb.verts = r.array(VERTEX_DTYPE, r.u32())
    n_tris = r.u32()
    t = r.array("<u4", n_tris * 4).reshape(-1, 4)
    rb.tris, rb.poly_ids = t[:, :3], t[:, 3]
    for _ in range(r.u32()):  # sky portals
        nv = r.u8()
        r.p += nv * 12 + 16
    for _ in range(r.u32()):  # occluders
        nv = r.u8()
        r.p += nv * 12 + 16 + 4
    rb.light_groups = []
    for _ in range(r.u32()):
        lg = LightGroup()
        lg.name = r.str16()
        lg.color = r.vec3()
        lg.vertex_intensities = r.raw(r.u32())
        # per section: list of sub-lightmaps (left, top, width, height, RLE intensity data)
        lg.section_lms = []
        for _ in range(r.u32()):
            subs = []
            for _ in range(r.u32()):
                left, top, w, h = r.fmt("<4I")
                subs.append((left, top, w, h, r.raw(r.u32())))
            lg.section_lms.append(subs)
        rb.light_groups.append(lg)
    flags = r.u8()
    c = r.fmt("<2I")
    rb.children = [c[i] if flags & (1 << i) else -1 for i in range(2)]
    return rb


def read_render_world(r, name=""):
    rw = RenderWorld(name)
    rw.blocks = [read_render_block(r) for _ in range(r.u32())]
    for _ in range(r.u32()):
        wm_name = r.str16()
        rw.world_models.append(read_render_world(r, wm_name))
    return rw


def decompress_lightmap(data, w, h):
    """TGA-style RLE of 24-bit RGB (lightmap_compress.cpp)."""
    return decompress_rgb(data, w * h)[0]


def decompress_rgb(data, count, i=0):
    """TGA-style RLE of `count` RGB triples starting at data[i]. Returns (bytes, end offset)."""
    out = bytearray(count * 3)
    o = 0
    n = len(data)
    while i < n and o < len(out):
        tag = data[i]
        i += 1
        span = (tag & 0x7F) + 1
        if tag & 0x80:
            out[o:o + span * 3] = bytes(data[i:i + 3]) * span
            i += 3
        else:
            out[o:o + span * 3] = data[i:i + span * 3]
            i += span * 3
        o += span * 3
    return bytes(out), i


# ---------------------------------------------------------------- light grid

class GridLightGroup:
    """A switchable light group's share of the light grid (CLightTable::LoadLightGroup): `samples`
    [z, y, x] (0-255) over the `ext` nodes from grid node `min`, added to the grid as color * sample."""
    __slots__ = ("name", "color", "min", "ext", "samples")


def read_grid_light_groups(r):
    """The light grid fix-ups after the render data (CWorldClientBSP::LoadRenderData)."""
    groups = []
    for _ in range(r.u32()):
        lg = GridLightGroup()
        lg.name = r.str16()
        lg.color = r.vec3()
        lg.min, lg.ext = r.fmt("<3i"), r.fmt("<3i")
        ex, ey, ez = lg.ext
        lg.samples = r.array(np.uint8, ex * ey * ez).reshape(ez, ey, ex)
        groups.append(lg)
    return groups


class LightGrid:
    """CLightTable (light_table.cpp): RGB samples (0-255) on a regular grid over the world box.
    data[z, y, x] is node (x, y, z); node (0, 0, 0) sits at `base`, spaced `cell` apart."""
    __slots__ = ("base", "cell", "dims", "data")


def read_light_grid(r):
    """CLightTable::Load. Raises if the RLE stream doesn't match its stored compressed size."""
    g = LightGrid()
    g.base, g.cell = r.vec3(), r.vec3()
    g.dims = r.fmt("<3i")
    size = r.u32()
    start = r.p
    raw, r.p = decompress_rgb(r.d, g.dims[0] * g.dims[1] * g.dims[2], start)
    if r.p - start != size:
        raise ValueError(f"light grid: RLE stream is {r.p - start} bytes, header says {size}")
    g.data = np.frombuffer(raw, np.uint8).reshape(g.dims[2], g.dims[1], g.dims[0], 3)
    return g


# ---------------------------------------------------------------- objects

def read_objects(r):
    objs = []
    for _ in range(r.u32()):
        start = r.p
        size = r.u16()
        cls = r.str16()
        props = {}
        for _ in range(r.u32()):
            pname = r.str16()
            code = r.u8()
            _pflags = r.u32()
            plen = r.u16()
            pstart = r.p
            if code == 0:
                val = r.str16()
            elif code in (1, 2):
                val = list(r.vec3())
            elif code == 3:
                val = r.f32()
            elif code == 4:
                val = r.u32()
            elif code == 5:
                val = bool(r.u8())
            elif code == 6:  # PT_LONGINT is stored as a float on disk
                val = int(round(r.f32()))
            elif code == 7:
                val = list(r.fmt("<4f"))
            else:
                val = None
            r.p = pstart + plen
            props[pname] = val
        objs.append({"class": cls, "props": props})
        # size counts bytes after the u16 size field
        r.p = start + 2 + size if size else r.p
    return objs


def read_polys_section(r):
    polys = []
    for _ in range(r.u32()):
        plane = r.fmt("<4f")
        nv = r.u32()
        polys.append((plane, r.array("<f4", nv * 3).reshape(-1, 3)))
    return polys


# ---------------------------------------------------------------- blind object data

KEYFRAMER_BLINDOBJECTID = 0x6aaf0884


def read_blind_objects(r):
    """CWorldBlindObjectData::Load: [(id, bytes)] in file order; a KeyFramer's KeyDataIndex indexes it."""
    chunks = []
    for _ in range(r.u32()):
        size = r.u32()
        cid = r.u32()
        chunks.append((cid, r.raw(size)))
    return chunks


# ---------------------------------------------------------------- world

class World:
    pass


def load(path):
    with open(path, "rb") as f:
        data = f.read()
    r = Reader(data)
    w = World()
    if r.u32() != 85:
        raise ValueError("not a DAT v85 file")
    (obj_pos, blind_pos, lgrid_pos, coll_pos, pblock_pos, render_pos) = r.fmt("<6I")
    r.p += 32
    w.info = r.str32()
    w.ext_min, w.ext_max, w.offset = r.vec3(), r.vec3(), r.vec3()
    # world tree layout
    r.vec3(), r.vec3()
    n_nodes = r.u32()
    _terrain_depth = r.u32()
    r.p += (n_nodes + 7) // 8
    w.bsps = []
    for _ in range(r.u32()):
        r.u32()  # dummy
        w.bsps.append(read_world_bsp(r))
    w.objects = read_objects(Reader(data, obj_pos))
    br = Reader(data, blind_pos)
    w.blind = read_blind_objects(br)
    if br.p != lgrid_pos:
        raise ValueError(f"blind object data ends at {br.p}, light grid starts at {lgrid_pos}")
    w.light_grid = read_light_grid(Reader(data, lgrid_pos))
    w.blockers = read_polys_section(Reader(data, coll_pos))
    w.particle_blockers = read_polys_section(Reader(data, pblock_pos))
    rr = Reader(data, render_pos)
    w.render = read_render_world(rr)
    w.render_end = rr.p
    w.grid_light_groups = read_grid_light_groups(rr)
    if rr.p != len(data):
        raise ValueError(f"{len(data) - rr.p} bytes after the light grid's light groups")
    w.file_size = len(data)
    return w


if __name__ == "__main__":
    import sys
    from collections import Counter
    w = load(sys.argv[1])
    print("info:", w.info)
    print("extents:", w.ext_min, w.ext_max, "offset", w.offset)
    print("render end", w.render_end, "file size", w.file_size)
    print("bsps:", len(w.bsps))
    for b in w.bsps[:8]:
        print(f"  {b.name!r:30} flags={b.flags:#x} polys={len(b.polys)} pts={len(b.points)} tex={len(b.textures)}")
    print("objects:", len(w.objects), Counter(o["class"] for o in w.objects).most_common(25))
    print("blockers:", len(w.blockers), "particle blockers:", len(w.particle_blockers))
    rw = w.render
    nv = sum(len(b.verts) for b in rw.blocks)
    nt = sum(len(b.tris) for b in rw.blocks)
    print("render blocks:", len(rw.blocks), "verts", nv, "tris", nt, "world models", len(rw.world_models))
    sh = Counter(s.shader for b in rw.blocks for s in b.sections)
    print("shaders:", {SHADER_NAMES.get(k, k): v for k, v in sh.items()})
    tex = Counter(s.textures[0] for b in rw.blocks for s in b.sections)
    print("textures:", len(tex), list(tex)[:10])
