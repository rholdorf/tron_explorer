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
              keys (u32 time, str cmd), then per node (tree order) its channel data:
                ANCMPRS_NONE   u8 isVertexAnim; nKeys x f32 pos[3], then nKeys x f32 quat[4]
                ANCMPRS_REL    u32 nPos, f32 pos[3] each; u32 nRot, f32 quat[4] each
                ANCMPRS_REL_16 u32 nPos, i16 pos[3] (/16) each; u32 nRot, i16 quat[4] (/32767) each
                ANCMPRS_REL_16_ROT_ONLY  f32 positions, i16 quaternions
              (a count is 0 = null channel, 1 = constant or nKeys)
  sockets     u32 n; each: u32 node, str name, quat rot, vec3 pos, vec3 scale
  anim bindings per child model (self first): u32 n; each str name, f32 dims[3], f32 translation[3]
Render object vertex streams follow GetVertexFlags_and_Size (d3d_utils.h): position+normal
(+ blend weights / packed bone indices for skeletal), then uv sets, then basis vectors.
"""
import struct

import numpy as np

RIGID, SKEL, VA, NULL = 4, 5, 6, 7

VERT_POSITION, VERT_NORMAL, VERT_DIFFUSE = 0x1, 0x2, 0x4
VERT_UV = (0x10, 0x20, 0x40, 0x80)
VERT_BASIS = 0x100


class Unsupported(ValueError):
    """A file the engine itself refuses to load as a model, so the game never draws it."""


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
            if not 1 <= max_tri <= 4:  # CD3DSkelMesh::Load_RD fails, and with it Model::Load
                raise Unsupported(f"skeletal mesh with {max_tri} bones per triangle")
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
    m.path = path
    m.version = r.u32()
    if m.version < 23:  # MIN_MODEL_FILE_VERSION (model.h)
        raise Unsupported(f"model version {m.version} (the engine loads 23+)")
    m.allocs = r.fmt("<15I")
    m.command = r.str()
    m.vis_radius = r.f32()
    n_obb = r.u32()
    # Oriented bounding boxes (hit detection): pos, size, basis[3], u32 node. Built without MODEL_OBB the
    # engine skips sizeof(ModelOBB) (64 bytes) per box whatever the version (Model::Load); seeker,
    # m0204_jet and pv_energyclaw are v23 files laid out that way.
    r.p += n_obb * 64
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
    m.anims_offset = r.p   # animation block (read_anims)
    m.data = data
    m.anims = read_anims(r, len(m.nodes))
    m.sockets = []
    for _ in range(r.u32()):   # LoadSockets
        s = Socket()
        s.node = r.u32()
        s.name = r.str()
        s.rot = r.fmt("<4f")   # quaternion x, y, z, w, relative to the node
        s.pos = r.fmt("<3f")
        s.scale = r.fmt("<3f")
        m.sockets.append(s)
    for c in range(n_child):   # LoadAnimBindings: self, then each child model (always empty in Tron)
        for _ in range(r.u32()):
            name = r.str()
            dims, t = r.fmt("<3f"), r.fmt("<3f")
            a = find_anim(m.anims, name) if c == 0 else None
            if a is not None:
                a.dims = dims
                a.translation = t   # added to the root node's position (TransformMaker::InitTransform)
    m.end = r.p
    m.first_pose = first_pose(m, m.anims[0]) if m.anims else None
    return m


def find_anim(anims, name):
    """Model::FindAnim: linear, case-insensitive, first match."""
    name = name.lower()
    return next((a for a in anims if a.name.lower() == name), None)


def first_pose(m, anim):
    """Each node's parent-relative (position, quaternion) at frame 0 of `anim` (animation 0 is the pose
    a model spawns in; TransformMaker::Recurse). MNODE_ROTATIONONLY nodes keep their bind offset from
    the parent (Model::SetNodeParentOffsets); the root adds the animation's translation."""
    out = []
    for n, (pos, rot) in zip(m.nodes, decode_anim(m, anim)):
        p = tuple(pos[0].tolist()) if len(pos) else (0.0, 0.0, 0.0)
        q = tuple(rot[0].tolist()) if len(rot) else (0.0, 0.0, 0.0, 1.0)
        if n.flags & MNODE_ROTATIONONLY:
            p = parent_offset(m, n)
        if n.parent < 0:
            p = tuple(a + b for a, b in zip(p, anim.translation))
        out.append((p, q))
    return out


def parent_offset(m, n):
    """m_vOffsetFromParent: the node's bind position in its parent's space (SetNodeParentOffsets)."""
    if n.parent < 0:
        return (0.0, 0.0, 0.0)
    rel = np.linalg.inv(m.nodes[n.parent].transform.astype(np.float64)) @ n.transform.astype(np.float64)
    return tuple(rel[:3, 3].tolist())


class Socket:
    pass


MNODE_ROTATIONONLY = 0x2

# Position / rotation key formats for each ANCMPRS_* compression (AnimNode::Load; model.h decoding:
# i16 positions are 1.11.4 fixed point (/16), i16 quaternions /32767).
_KEYS = {1: (("<f4", 1.0), ("<f4", 1.0)), 2: (("<i2", 16.0), ("<i2", 32767.0)),
         3: (("<f4", 1.0), ("<i2", 32767.0))}


class Anim:
    """One animation (ModelAnim + AnimInfo). times: key times in ms (they start at 0 and never
    decrease, but consecutive keys can share a time). Node channels stay undecoded until decode_anim."""

    def __init__(self):
        self.name = ""
        self.dims = (0.0, 0.0, 0.0)          # user dims (half-extents); the bindings have the final value
        self.translation = (0.0, 0.0, 0.0)   # root translation, from the bindings
        self.compression = 0
        self.interp_ms = 0
        self.times = None
        self.node_offset = 0                 # byte offset of the node channels in the model file


def _channels(r, compression, n_keys, n_nodes, decode):
    """Walks one animation's node channels (AnimNode::Load; nodes in tree order = index order). Returns
    per node (positions (k, 3), quaternions x y z w (k, 4)) with k = 0 (null channel: zero position,
    identity rotation), 1 (constant) or n_keys; None when not decoding."""
    out = [] if decode else None
    for _ in range(n_nodes):
        pos, rot = np.zeros((0, 3)), np.zeros((0, 4))
        if compression == 0:
            if r.u8():             # vertex animation (never used by Tron)
                for _ in range(n_keys):
                    r.p += 12 * r.u32()
            elif decode:
                pos = r.array("<f4", n_keys * 3).reshape(-1, 3).astype(np.float64)
                rot = r.array("<f4", n_keys * 4).reshape(-1, 4).astype(np.float64)
            else:
                r.p += 28 * n_keys
        elif compression in _KEYS:
            chans = []
            for width, (f, scale) in zip((3, 4), _KEYS[compression]):
                n = r.u32()
                if decode:
                    chans.append(r.array(f, n * width).reshape(-1, width).astype(np.float64) / scale)
                else:
                    r.p += n * width * np.dtype(f).itemsize
            if decode:
                pos, rot = chans
        else:
            raise ValueError(f"animation compression {compression} not supported")
        if decode:
            out.append((pos, rot))
    return out


def read_anims(r, n_nodes):
    """The animation block (Model::Load; ModelAnim::Load, AnimNode::Load in ltjs). Key times are read;
    node channels are only stepped over, decode_anim reads them on demand."""
    anims = []
    for _ in range(r.u32()):
        a = Anim()
        a.dims = r.fmt("<3f")
        a.name = r.str()
        a.compression, a.interp_ms, n_keys = r.fmt("<3I")
        times = []
        for _ in range(n_keys):
            times.append(r.u32())
            r.str()                    # command string (FOOTSTEP_KEY, FIRE, ...)
        a.times = np.array(times, np.float64)
        a.node_offset = r.p
        _channels(r, a.compression, n_keys, n_nodes, False)
        anims.append(a)
    return anims


def decode_anim(m, anim):
    """Node channels of one of m's own animations: per node (positions (k, 3), quaternions (k, 4)),
    parent-relative, k in {0, 1, len(anim.times)}."""
    return _channels(Reader(m.data, anim.node_offset), anim.compression, len(anim.times), len(m.nodes), True)


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
