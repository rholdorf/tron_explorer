"""LithTech Jupiter model (.ltb, D3D file type 1, LTB version 9, model version 23+) parser.

Layout (model_load.cpp, d3dmeshrendobj_*.cpp in ltjs):
  header      u8 fileType, pad, u16 version, u8 + pad, 3 x u32 reserved (20 bytes)
  u32 fileVersion, 15 x u32 allocation counts (modelallocations.cpp)
  str16 command string, f32 visRadius, u32 nOBB (+ OBBs)
  pieces      u32 n; each: str name, u32 nLODs, f32 lodDists[n], 2 x u32,
              per LOD: u32 nTextures, i32 textures[4], i32 renderStyle, u8 renderPriority,
                       u32 renderObjectType (4 rigid, 5 skeletal, 6 vertex-animated, 7 null),
                       render object, u8 usedNodeListSize + u8 usedNodes[]
  node tree   recursive: str name, u16 index, u8 flags, f32 globalTransform[4][4], u32 nChildren
  weight sets u32 n; each: str name, u32 n, f32 weights[n]
  child models u32 n (self included); names for 1..n-1
  animations  u32 n; each: f32x3 dims, str name, u32 compression, u32 interpMS, u32 nKeys,
              keys (u32 time, str cmd), then per node (tree order) its channel data
  sockets     u32 n; each: u32 node, str name, quat rot, vec3 pos, vec3 scale
  anim bindings per child model
Render object vertex streams follow GetVertexFlags_and_Size (d3d_utils.h): position+normal
(+ blend weights / packed bone indices for skeletal), then uv sets, then basis vectors.
"""
import struct

import numpy as np

RIGID, SKEL, VA, NULL = 4, 5, 6, 7

VERT_POSITION, VERT_NORMAL, VERT_DIFFUSE = 0x1, 0x2, 0x4
VERT_UV = (0x10, 0x20, 0x40, 0x80)
VERT_BASIS = 0x100


class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def fmt(self, f):
        v = struct.unpack_from(f, self.d, self.p)
        self.p += struct.calcsize(f)
        return v

    def u8(self):
        return self.fmt("<B")[0]

    def u16(self):
        return self.fmt("<H")[0]

    def u32(self):
        return self.fmt("<I")[0]

    def i32(self):
        return self.fmt("<i")[0]

    def f32(self):
        return self.fmt("<f")[0]

    def str(self):
        n = self.u16()
        s = self.d[self.p:self.p + n].decode("latin-1")
        self.p += n
        return s

    def raw(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def array(self, dtype, count):
        a = np.frombuffer(self.d, dtype=dtype, count=count, offset=self.p)
        self.p += np.dtype(dtype).itemsize * count
        return a


def vertex_dtype(flags, blend_floats=0, indexed=False):
    """numpy dtype of one vertex stream (GetVertexFlags_and_Size)."""
    fields = []
    if flags & VERT_POSITION and flags & VERT_NORMAL:
        fields.append(("pos", "<f4", 3))
        if blend_floats:
            fields.append(("weights", "<f4", blend_floats))
        if indexed:
            fields.append(("bones", "u1", 4))
        fields.append(("normal", "<f4", 3))
    for k, bit in enumerate(VERT_UV):
        if flags & bit:
            fields.append(("uv", "<f4", (k + 1, 2)))
            break
    if flags & VERT_BASIS:
        fields.append(("basis", "<f4", 6))
    return np.dtype(fields)


class Mesh:
    """One LOD of a piece. Positions are in model space at the bind pose."""

    def __init__(self, kind):
        self.kind = kind
        self.streams = []      # structured arrays, one per present stream
        self.indices = None    # (n, 3) uint16
        self.bone = -1         # rigid / VA: the node the whole mesh follows
        self.bone_sets = None  # skeletal render-direct: (first, count, bones[4], indexStart)
        self.reindexed = None  # skeletal matrix-palette: palette index -> node
        self.min_bone = self.max_bone = 0
        self.max_bones_per_vert = 1
        self.matrix_palettes = False

    def field(self, name):
        for s in self.streams:
            if s.dtype.names and name in s.dtype.names:
                return s[name]
        return None


def read_mesh(r, kind):
    m = Mesh(kind)
    size = r.u32()
    end = r.p + size if size else None  # size counts the bytes after itself
    if kind == NULL:
        return m
    if kind == RIGID:
        nv, npoly, max_tri, max_vert = r.fmt("<4I")
        flags = r.fmt("<4I")
        m.bone = r.u32()
        for f in flags:
            if f:
                m.streams.append(r.array(vertex_dtype(f), nv))
    elif kind == SKEL:
        nv, npoly, max_tri, max_vert = r.fmt("<4I")
        m.max_bones_per_vert = max_vert
        reindexed = r.u8()
        flags = r.fmt("<4I")
        m.matrix_palettes = bool(r.u8())
        if m.matrix_palettes:
            m.min_bone, m.max_bone = r.fmt("<2I")
            if reindexed:
                m.reindexed = r.array("<u4", r.u32()).copy()
            blend = max_vert - 1
            for f in flags:
                if f:
                    m.streams.append(r.array(vertex_dtype(f, blend, indexed=True), nv))
        else:
            blend = max_tri - 1
            for f in flags:
                if f:
                    m.streams.append(r.array(vertex_dtype(f, blend), nv))
    elif kind == VA:
        nv, undup, npoly, max_tri, max_vert = r.fmt("<5I")
        flags = r.fmt("<4I")
        _anim_node = r.u32()
        m.bone = r.u32()
        for f in flags:
            if f:
                m.streams.append(r.array(vertex_dtype(f), nv))
    else:
        raise ValueError(f"unknown render object type {kind}")
    m.indices = r.array("<u2", npoly * 3).reshape(-1, 3)
    if kind == SKEL and not m.matrix_palettes:
        m.bone_sets = r.array(np.dtype([("first", "<u2"), ("count", "<u2"), ("bones", "u1", 4),
                                        ("index", "<u4")]), r.u32())
    elif kind == VA:
        r.p = end  # dup map (+4 bytes ltjs does not read): vertex animation is not supported here
    if end is not None and r.p != end:
        raise ValueError(f"render object size mismatch ({r.p - end:+d} bytes)")
    return m


class Piece:
    def __init__(self):
        self.name = ""
        self.lod_dists = []
        self.lods = []         # (textures[nTextures], renderStyle, renderPriority, Mesh, usedNodes)


class Node:
    def __init__(self):
        self.name = ""
        self.index = 0
        self.flags = 0
        self.transform = None  # 4x4 global (model space) bind transform, row-major m[row][col]
        self.children = []
        self.parent = -1


class Model:
    pass


def read_node(r, nodes, parent):
    n = Node()
    n.name = r.str()
    n.index = r.u16()
    n.flags = r.u8()
    n.transform = np.array(r.fmt("<16f"), np.float32).reshape(4, 4)
    n.parent = parent
    count = r.u32()
    nodes.append(n)
    for _ in range(count):
        n.children.append(read_node(r, nodes, n.index))
    return n.index


def load(path):
    with open(path, "rb") as f:
        data = f.read()
    r = Reader(data)
    file_type, ltb_version = r.fmt("<BxH")  # C struct with padding: 20 bytes in all
    r.p = 20
    if file_type != 1 or ltb_version != 9:
        raise ValueError(f"not a D3D LTB model (type {file_type}, version {ltb_version})")
    m = Model()
    m.version = r.u32()
    if m.version < 23:
        raise ValueError(f"model version {m.version} not supported")
    m.allocs = r.fmt("<15I")
    m.command = r.str()
    m.vis_radius = r.f32()
    n_obb = r.u32()
    r.p += n_obb * (64 if m.version >= 24 else 60)  # oriented bounding boxes (hit detection)
    m.pieces = []
    for _ in range(r.u32()):
        p = Piece()
        p.name = r.str()
        n_lods = r.u32()
        p.lod_dists = list(r.fmt(f"<{n_lods}f"))
        r.p += 8
        for _ in range(n_lods):
            n_tex = r.u32()
            textures = list(r.fmt("<4i"))[:n_tex]   # skin slots of the piece's texture list
            style = r.i32()
            priority = r.u8()
            kind = r.u32()
            mesh = read_mesh(r, kind)
            used = r.raw(r.u8())
            p.lods.append((textures, style, priority, mesh, used))
        m.pieces.append(p)
    m.nodes = []
    read_node(r, m.nodes, -1)
    m.nodes.sort(key=lambda n: n.index)
    m.weight_sets = []
    for _ in range(r.u32()):
        name = r.str()
        m.weight_sets.append((name, r.array("<f4", r.u32())))
    n_child = r.u32()
    m.child_models = [r.str() for _ in range(n_child - 1)]
    m.anims_offset = r.p   # animation data follows (parsed by load_anims)
    m.data = data
    return m


if __name__ == "__main__":
    import sys
    from collections import Counter
    for path in sys.argv[1:]:
        m = load(path)
        kinds = Counter(lod[3].kind for p in m.pieces for lod in p.lods)
        print(f"{path}: v{m.version} pieces={len(m.pieces)} nodes={len(m.nodes)} kinds={dict(kinds)} "
              f"children={m.child_models} cmd={m.command!r}")
        for p in m.pieces[:6]:
            t, style, prio, mesh, used = p.lods[0]
            nv = len(mesh.streams[0]) if mesh.streams else 0
            print(f"   {p.name:20} lods={len(p.lods)} tex={t} style={style} kind={mesh.kind} verts={nv} "
                  f"tris={0 if mesh.indices is None else len(mesh.indices)} bone={mesh.bone} "
                  f"mp={mesh.matrix_palettes} fields={[s.dtype.names for s in mesh.streams]}")
