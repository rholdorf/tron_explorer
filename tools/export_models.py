"""Model instances for the viewer: resolve which .ltb + skins each level object shows, and export
those models to the runtime format.

export/models/<model path>.json  pieces, nodes, sockets, anims
export/models/<model path>.bin   'TRMD', u32 version, u32 nVerts, u32 nIdx, u32 nInfluences, u32 nAnimFloats,
                                 verts (nVerts * 44 bytes, same layout as level.bin),
                                 idx (u32, relative to the piece's first vertex),
                                 influences per vertex (u8 x nVerts, 1..4),
                                 influences (nInfluences * Unity BoneWeight1: f32 weight, i32 node),
                                 animation clips (nAnimFloats * f32, indexed by the json's anims)
Only LOD 0 is exported, at the bind pose (vertices are stored in model space). Only the animations
the levels' instances play are exported (animation.clip: engine rules applied, channels parent-relative),
with their animation keys and the uniform scale of vertex-animated pieces (binarybit's Yes / No).
"""
import json
import os
import struct

import numpy as np

import animation
import butes
from butes import norm
import ltb
import renderstyle

FORMAT_VERSION = 5

OUT_VERTEX = np.dtype([("pos", "<f4", 3), ("normal", "<f4", 3), ("rgba", "u1", 4), ("uv", "<f4", 2),
                       ("uv2", "<f4", 2)])


def props(obj):
    """A level object's properties by lowercase key."""
    return {q["k"].lower(): q for q in obj["props"]}


def string(p, key):
    """The value of string property `key` (lowercase) in props(obj) `p`, or ""."""
    q = p.get(key)
    return q["s"] if q and q["t"] == "s" else ""


def model_entry(section, model_key, prefix=""):
    """(model file, skins, render styles) of an attribute-file entry: its `model_key` and its
    <prefix>SkinN / <prefix>RenderStyleN slots, kept in position (empty slots too)."""
    return norm(section[model_key]), [norm(x) for x in butes.indexed(section, prefix + "skin")], \
        [norm(x) for x in butes.indexed(section, prefix + "renderstyle")]


BINARY_BIT = ("props/models/binarybit.ltb",
              ("props/rs/binarybit_idle.ltb", "props/rs/binarybit_yes.ltb", "props/rs/binarybit_no.ltb"))


class Resolver:
    """Maps a level object to (model file, skins, render styles), following the game's sources:
    the object's own Filename/Skin, a PropType entry (proptypes.txt) or a ModelTemplate
    (modelbutes.txt)."""

    def __init__(self, extracted):
        a = os.path.join(extracted, "attributes")
        self.modelbutes = butes.load(os.path.join(a, "modelbutes.txt"))
        self.templates = {s["name"].lower(): s for s in self.modelbutes.values() if "name" in s}
        self.proptypes = {s["type"].lower(): s for s in butes.load(os.path.join(a, "proptypes.txt")).values()
                          if "type" in s}
        self.attachables = {s["name"].lower(): s for s in butes.load(os.path.join(a, "attachments.txt")).values()
                            if "name" in s}
        self.weapons = {s["name"].lower(): s for s in butes.load(os.path.join(a, "weapons.txt")).values()
                        if "name" in s}
        self.hidden_weapons = 0    # weapon attachments without a hand-held model (HHModel empty)
        self.missing_sockets = {}  # (parent model, socket) -> attachments dropped for want of the socket
        self.undrawn_attachments = {}   # object attachment class without a model -> count

    def template(self, name):
        """(model file, skins, render styles) of a modelbutes.txt template, as the game's
        CModelButeMgr::GetModelFilename / CopySkinFilenames / CopyRenderStyleFilenames give them."""
        return model_entry(self.templates[name.lower()], "modelfile")

    @staticmethod
    def bin_items(obj):
        """The berries an ArchiveBin shows as (socket, template), one per item (Type1..Type6 that names an
        item type, in order), item k at Socket{k}. ArchiveBin (object.lto 0x1000f800) picks the template
        by the item type's index in the list Subroutine, Procedural, Primitive, Permission Set, Email,
        Custom, HelpFile (0x10284410): 0 is SubroutineBerry, 3 PSetBerry, any other DocumentBerry."""
        p = props(obj)
        out = []
        for k in range(1, 7):
            t = string(p, f"type{k}").strip().lower()
            if t in BIN_ITEM_TYPES:
                out.append((f"Socket{len(out) + 1}", BERRY_TEMPLATES.get(BIN_ITEM_TYPES.index(t), "DocumentBerry")))
        return out

    @staticmethod
    def turret_mount(obj, parents):
        """Where a TronTurret sits, as (parent, socket), or None ("could not find a parent"). TronTurret
        (object.lto 0x1006c960, 0x1006d590) finds the object named by its Parent property and, every
        update, puts itself at that object's ParentSocket: a socket attachment for a static frame. Aiming
        at its Target turns it from there (behavior). parents: object name (lowercase) -> (parent, its
        model's socket names, lowercase)."""
        p = props(obj)
        parent, sockets = parents.get(string(p, "parent").strip().lower(), (None, set()))
        socket = string(p, "parentsocket")
        return (parent, socket) if socket.lower() in sockets else None

    @staticmethod
    def _skins(value):
        return [norm(s) for s in value.split(";") if s.strip()] if value else []

    def resolve(self, obj, spawned=False):
        """spawned: the object is a template a Spawner copies (CObjectTemplateMgr::AddTemplate stores it
        with Template FALSE), so the copy is created like a placed object."""
        p = {q["k"]: q for q in obj["props"]}

        def s(key):
            q = p.get(key)
            return q["s"] if q and q["t"] == "s" else ""

        def b(key, default=True):
            q = p.get(key)
            return bool(q["v"][0]) if q and q["t"] == "b" and q["v"] else default

        # GameBase::ReadProp: a Template object is saved as a spawner template and never created;
        # in single player an object with SinglePlayer off isn't created either.
        if (b("Template", False) and not spawned) or not b("SinglePlayer"):
            return None
        if not b("Visible") or b("StartHidden", False):
            return None
        cls = obj["cls"]
        if cls in ("ArchiveBin", "SecRezzer", "CAIHuman"):
            t = self.templates.get(s("ModelTemplate").lower())
            if not t or "modelfile" not in t:
                return None
            return model_entry(t, "modelfile")
        if cls == "IONode":
            # IONode::ReadProp (object.lto 0x10022650) takes the hard-coded template "IONode"; its first
            # update (state 0, 0x10023090) sets the "off" skins: Skin4 in slot 0, then Skin1..3.
            file, skins, rs = self.template("IONode")
            return file, skins[4:5] + skins[1:4], rs
        if cls == "Optimizer":
            # Optimizer::ReadProp (0x100301ec): the hard-coded template "Optimizer", its first three skins
            # (the "on" set; death switches to Skin3..5, 0x10031128).
            file, skins, rs = self.template("Optimizer")
            return file, skins[:3], rs
        if cls == "BinaryBit":
            # BinaryBit::ReadProp (object.lto 0x10012c30): the hard-coded model, no skins, render styles
            # Idle / Yes / No (docs/research/secrezzer-binarybit.md).
            return BINARY_BIT[0], [], list(BINARY_BIT[1])
        if cls in ("PropType", "Finder", "TronTurret"):
            # TronTurret::ReadProp (object.lto 0x1006b818) reads its type from "PropType".
            t = self.proptypes.get(s("PropType" if cls == "TronTurret" else "Type").lower())
            if not t or "filename" not in t:
                return None
            return model_entry(t, "filename")
        if cls in ("Prop", "Alarm") and s("Filename"):
            return norm(s("Filename")), self._skins(s("Skin")), []
        return None

    def occupants(self, obj):
        """What a character's attachment positions hold, as (position, name, attachable or None for a
        weapon). The object's own position properties are created first (CAttachments::ReadProp/Init),
        then the template's DefaultAttachmentN = "Position, Name" unless UseDefaultAttachments is off
        (CAIHuman InitialUpdate); a default for an occupied position is dropped (CAttachments::Attach)."""
        p = props(obj)
        t = self.templates.get(string(p, "modeltemplate").lower())
        if not t:
            return []
        wanted = []
        for pos in ATTACHMENT_POSITIONS:
            if string(p, pos.lower()).strip():
                wanted.append((pos, string(p, pos.lower()).strip()))
        use_defaults = p.get("usedefaultattachments")
        if not use_defaults or use_defaults["t"] != "b" or use_defaults["v"][0]:
            for d in butes.indexed(t, "defaultattachment"):
                pos, name = (x.strip() for x in d.split(",", 1))
                wanted.append((pos, name))
        out, occupied = [], set()
        for pos, name in wanted:
            if pos.lower() not in POSITION_SET or pos.lower() in occupied or name.lower() == "<none>":
                continue
            weapon = name.split(",")[0].strip()   # WeaponMgr::ReadWeapon "weapon,ammo"
            if weapon.lower() in self.weapons:
                occupied.add(pos.lower())
                out.append((pos, weapon, None))
                continue
            a = self.attachables.get(name.lower())
            if not a:
                continue   # "Unmatched attable name": nothing is created
            occupied.add(pos.lower())
            out.append((pos, name, a))
        if self.holsters(p):
            out = [o for o in out if o[0].lower() not in ("righthand", "lefthand")]
        return out

    @staticmethod
    def holsters(p):
        """CAIHuman::ReadProp/InitialUpdate: HolsterWeapons with a RightHand or LeftHand set on the object
        (the holster string) detaches both hands after the defaults are attached. Tron's weapons have no
        HolsterAttachment, so nothing takes their place. p: props(obj)."""
        h = p.get("holsterweapons")
        if not (h and h["t"] == "b" and h["v"] and h["v"][0]):
            return False
        return any(string(p, k).strip().lower() not in ("", "<none>") for k in ("righthand", "lefthand"))

    def weapon_at(self, obj, position):
        """The weapon a character holds at `position` (e.g. RightHand, its primary weapon), or None."""
        return next((name for pos, name, a in self.occupants(obj)
                     if a is None and pos.lower() == position.lower()), None)

    def look_at_nodes(self, obj):
        """The nodes a character turns to look at something (CTrackedNodeContext::_Init for kTrack_LookAt): its
        model template's Skeleton, that [SkeletonN]'s LookAtTrackingNodes, that [TrackingNodesN]'s Node0..
        in order, each {name, clone ("" for none), axis and up (None: SetNodeConstraints' defaults), discomfort
        [x, y], max [x, y] (degrees), maxVel (degrees/s)}. [] without a group."""
        t = self.templates.get(string(props(obj), "modeltemplate").lower())
        if not t or "skeleton" not in t:
            return []
        skeleton = self.modelbutes.get(f"Skeleton{int(t['skeleton'])}", {})
        if "lookattrackingnodes" not in skeleton:
            return []
        g = self.modelbutes.get(f"TrackingNodes{int(skeleton['lookattrackingnodes'])}", {})

        def vec(key):
            v = g.get(key)
            return [float(x) for x in str(v).split(",")] if v not in (None, "") else None

        out = []
        while f"node{len(out)}name" in g:
            k = f"node{len(out)}"
            out.append({"name": g[k + "name"], "clone": g.get(k + "clonename", ""),
                        "axis": vec(k + "forwardvector"), "up": vec(k + "upvector"),
                        "discomfort": [float(g.get(k + "discomfortx", 0)), float(g.get(k + "discomforty", 0))],
                        "max": [float(g.get(k + "maxx", 0)), float(g.get(k + "maxy", 0))],
                        "maxVel": float(g.get(k + "maxvel", 0))})
        return out

    def attachable(self, name):
        """(model file, skins, render styles) that CAttachments::Attach(position, name) draws, or None: a
        weapon's hand-held model (none without an HHModel), else an attachments.txt entry's Model when it is a
        Prop (type 0, or a type 1 class that is one)."""
        weapon = name.split(",")[0].strip()
        if weapon.lower() in self.weapons:
            w = self.weapons[weapon.lower()]
            return model_entry(w, "hhmodel", "hh") if w.get("hhmodel") else None
        a = self.attachables.get(name.lower())
        if not a or "model" not in a or (a.get("type") == 1 and a.get("class") not in MODEL_ATTACHMENT_CLASSES):
            return None
        return model_entry(a, "model")

    def attachments(self, obj):
        """A character's drawn attachments as (socket, model file, skins, render styles); the position
        name is the parent model's socket. A weapon draws its hand-held model (CreateWeaponAttachment:
        HHModel, HHSkinN, HHRenderStyleN, no offset; HHModelScale is for powerups only); without one
        CHHWeaponModel::Setup hides it."""
        out = []
        for pos, name, a in self.occupants(obj):
            if a is None:
                w = self.weapons[name.lower()]
                if not w.get("hhmodel"):
                    self.hidden_weapons += 1
                    continue
                out.append((pos, *model_entry(w, "hhmodel", "hh")))
                continue
            # Type 0 is a Prop; type 1 creates its Class, which only draws the model if it's a Prop.
            if a.get("type") == 1 and a.get("class") not in MODEL_ATTACHMENT_CLASSES:
                self.undrawn_attachments[a.get("class")] = self.undrawn_attachments.get(a.get("class"), 0) + 1
                continue
            if "model" in a:
                out.append((pos, *model_entry(a, "model")))
        return out


BIN_ITEM_TYPES = ["subroutine", "procedural", "primitive", "permission set", "email", "custom", "helpfile"]
# Bin item type (index in BIN_ITEM_TYPES) -> the berry's modelbutes.txt template; any other is DocumentBerry.
BERRY_TEMPLATES = {0: "SubroutineBerry", 3: "PSetBerry"}


# CHumanAttachments' positions (attachments.cpp), plus Tron's rod positions (CAIHuman level properties).
ATTACHMENT_POSITIONS = [
    "RightHand", "LeftHand", "Head", "Eyes", "Nose", "Chin", "Back", "RightFoot", "LeftFoot", "Snowmobile",
    "Light", "LeftLowerArm", "LeftUpperArm", "RightLowerArm", "RightUpperArm", "LeftLowerLeg", "LeftUpperLeg",
    "RightLowerLeg", "RightUpperLeg", "UpperTorso", "Torso", "LeftShoulder", "RightShoulder", "RightHand2",
    "LeftHand2", "LeftLowerArm2", "LeftLowerLeg2", "LeftUpperArm2", "LeftUpperLeg2", "RightUpperArm2",
    "RightUpperLeg2", "RightLowerArm2", "RightLowerLeg2", "UpperTorso2", "LeftRod", "RightRod"]
POSITION_SET = {x.lower() for x in ATTACHMENT_POSITIONS}
# Object attachment classes that are Props (powerarmor.cpp). AttachedExplosion is an Explosion (GameBase,
# OT_NORMAL): its Model line is never drawn.
MODEL_ATTACHMENT_CLASSES = {"PowerArmor", "ShellArmor"}


class Styles:
    """Compiles the render styles a level's model pieces draw with (renderstyle.compile_style) into
    the level's style table. A style the model shader can't draw stops the export."""

    def __init__(self, extracted):
        self.extracted = extracted
        glow = butes.load(os.path.join(extracted, "attributes", "clientbutes.txt"))["GlowRSMap"]
        self.glow_default = norm(glow["glowdefaultrs"])
        self.glow_map = {norm(glow[f"glowmaprs{i}"]): norm(glow[f"glowmaprsto{i}"])
                         for i in range(len(butes.indexed(glow, "glowmaprs")))}
        self.compiled = {}
        self.models = {}
        self.missing = set()   # style paths set on a piece whose file doesn't exist (default style used)

    def model(self, rel):
        if rel not in self.models:
            self.models[rel] = ltb.load(os.path.join(self.extracted, rel))
        return self.models[rel]

    def _load(self, rel):
        path = os.path.join(self.extracted, rel)
        return renderstyle.load(path) if rel and os.path.isfile(path) else None

    def compile(self, rel):
        """rel = '' or a missing file: the engine's backup style (CD3DRenderStyle::SetDefaults)."""
        if rel not in self.compiled:
            s = self._load(rel)
            if rel and s is None:
                self.missing.add(rel)
            name = rel if s else "<default>"
            c = renderstyle.compile_style(s or renderstyle.default_style(), name)
            glow = self.glow_map.get(rel, self.glow_default) if s else self.glow_default
            draws = c["draws"]
            for d in draws:
                d["glow"] = []
            if glow == rel:
                # Mapped to itself: the glow buffer gets the style's own first pass, blend included.
                draws[0]["glow"] = [dict(draws[0]["passes"][0], blendOver=0)]
            else:
                g = self._load(glow)
                if g is None:
                    raise ValueError(f"{name}: glow style {glow} not found")
                place_glow(draws, renderstyle.compile_glow(g, glow))
            c["name"] = name
            self.compiled[rel] = c
        return self.compiled[rel]

    def instance_pieces(self, rel, skins, styles, table, index):
        """Per exported piece of the model: its style (index into `table`) and its texture list
        (ModelPiece::m_iTextures -> instance skins; QueuePiece)."""
        out = []
        for p in self.model(rel).pieces:
            textures, style, _prio, mesh, _used = p.lods[0]
            if mesh.indices is None or not mesh.streams or mesh.field("pos") is None:
                continue
            name = styles[style] if 0 <= style < len(styles) else ""
            c = self.compile(name)
            if c["name"] not in index:
                index[c["name"]] = len(table)
                table.append(c)
            out.append({"style": index[c["name"]],
                        "tex": [skins[t] if 0 <= t < len(skins) else "" for t in textures]})
        return out


DRAW_STATE = ("blend", "zwrite", "ztest", "cull", "wire")


def place_glow(draws, glows):
    """Puts a compiled glow style (renderstyle.compile_glow: its draws) on a style's draws. The glow pass
    swaps the whole style, states included (RemapRenderStyles), so a blended piece occludes the glow
    behind it. A first one-pass glow that writes opaque with Z rides on a draw that does too; otherwise
    each glow draw is a draw of its own with the glow style's state, after the style's."""
    def opaque_z(d):
        return tuple(d["blend"]) == (1, 0) and d["zwrite"] and not d.get("wire")
    for i, glow in enumerate(glows):
        d = None
        if i == 0 and len(glow["passes"]) == 1 and opaque_z(glow):
            d = next((d for d in draws if opaque_z(d)), None)
        if d is None:
            d = {k: glow.get(k, 0) for k in DRAW_STATE}
            d["passes"] = []
            draws.append(d)
        d["glow"] = glow["passes"]


BONE_WEIGHT = np.dtype([("weight", "<f4"), ("bone", "<i4")])   # Unity BoneWeight1


def skin_weights(mesh, nv, bone=None):
    """Per vertex influence count (1..4) and the influences (Unity BoneWeight1, heaviest first).
    Bone indices are model node indices. Skeletal render-direct meshes: each bone set loads
    bones[0..n-1] and blends with the vertex's first n-1 stored weights plus 1 - their sum
    (CD3DSkelMesh::Render, D3DVBF_{n-1}WEIGHTS). Rigid and vertex-animated meshes follow one node
    (`bone` when given, else the mesh's)."""
    if mesh.kind != ltb.SKEL:
        return np.ones(nv, np.uint8), np.array([(1.0, mesh.bone if bone is None else bone)] * nv, BONE_WEIGHT)
    if mesh.matrix_palettes:
        raise ValueError("matrix-palette skeletal mesh not supported")
    stored = mesh.field("weights")
    w = np.zeros((nv, 4), np.float32)
    b = np.zeros((nv, 4), np.int32)
    covered = np.zeros(nv, bool)
    for s in mesh.bone_sets:
        bones = [int(x) for x in s["bones"]]
        n = bones.index(0xFF) if 0xFF in bones else 4
        v = slice(s["first"], s["first"] + s["count"])
        if n > 1:
            w[v, :n - 1] = stored[v, :n - 1]
        w[v, n - 1] = 1 - w[v, :n - 1].sum(1)
        b[v, :n] = bones[:n]
        covered[v] = True
    if not covered.all():
        raise ValueError(f"{(~covered).sum()} vertices outside every bone set")
    w[w < 0] = 0
    order = np.argsort(-w, axis=1, kind="stable")
    w, b = np.take_along_axis(w, order, 1), np.take_along_axis(b, order, 1)
    w /= w.sum(1, keepdims=True)
    counts = np.maximum((w > 0).sum(1), 1).astype(np.uint8)
    keep = np.arange(4)[None, :] < counts[:, None]
    out = np.zeros(int(counts.sum()), BONE_WEIGHT)
    out["weight"], out["bone"] = w[keep], b[keep]
    return counts, out


def model_dims(m):
    """The model's dims (half-extents): its first animation's user dims (bindings applied), which a prop
    takes as its object dims (ModelInstance::GetDims); the bind-pose box when it has no animation."""
    if m.anims:
        return list(m.anims[0].dims)
    pts = [p.lods[0][3].field("pos") for p in m.pieces if p.lods[0][3].field("pos") is not None]
    if not pts:
        return [0.0, 0.0, 0.0]
    pts = np.concatenate(pts)
    return ((pts.max(0) - pts.min(0)) / 2).tolist()


def clip_block(clips):
    """The clips as one float block and their json entries: times (s), then per node its position keys
    (3 floats each) and rotation keys (4 floats, quaternion x y z w). channels: per node posOffset,
    posCount, rotOffset, rotCount (offsets in floats; a count is 1 for a constant channel or keys).
    scales: node, offset, count per scaled node (a vertex-animated piece's uniform scale, 1 float per key).
    cmds: the animation keys, {t (s), s}. interp: the blend (s) from the previous pose into the clip's
    first frame when it starts (trk_ScanToKeyFrame), 0 a cut. from (export_model): "" for a clip of the
    model or its .ltb children, else the ChildModel_N file it comes from."""
    floats, meta, n = [], [], 0

    def put(a):
        nonlocal n
        a = np.ascontiguousarray(a, np.float32).reshape(-1)
        floats.append(a)
        n += len(a)
        return n - len(a)

    for c in clips:
        entry = {"name": c.name, "length": c.length / 1000.0, "interp": c.interp_ms / 1000.0, "keys": len(c.times),
                 "times": put(c.times / 1000.0), "channels": []}
        for p, q in zip(c.pos, c.rot):
            entry["channels"] += [put(p), len(p), put(q), len(q)]
        entry["scales"] = []
        for node, f in sorted(c.scales.items()):
            entry["scales"] += [node, put(f), len(f)]
        entry["cmds"] = [{"t": t / 1000.0, "s": cmd} for t, cmd in c.commands]
        meta.append(entry)
    return (np.concatenate(floats) if floats else np.zeros(0, np.float32)), meta


def export_model(extracted, rel, out_root, anims=(), load=None):
    """Writes the model and the clips of `anims`: animation names in the model or its child models, or
    (name, file) for a ChildModel_N file's animation. load(rel): a model loader (default ltb.load), for
    child models."""
    m = ltb.load(os.path.join(extracted, rel))
    load = load or (lambda r: ltb.load(os.path.join(extracted, r)))
    children = animation.load_children(extracted, rel, m, load) if anims else []
    clips, sources = [], []
    for a in anims:
        name, source = (a, "") if isinstance(a, str) else a
        clips.append(animation.clip(m, children, name, load(source) if source else None))
        sources.append(source)
    anim_floats, anim_meta = clip_block(clips)
    for entry, source in zip(anim_meta, sources):
        entry["from"] = source
    # A vertex-animated piece the clips scale follows its own node (at the origin, unrotated, like
    # binarybit's d_Pyramid / d_NewSpike), so the node's scale scales it about the model origin.
    scaled = {m.nodes[n].name: n for c in clips for n in c.scales}
    verts, idx, pieces, counts, weights = [], [], [], [], []
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
        out["rgba"] = (128, 128, 128, 255)  # unused: Tron/Model lights from the style's lighting (D3D lighting)
        tris = mesh.indices.astype(np.uint32).reshape(-1)
        pieces.append({"name": p.name, "textures": textures, "style": style, "kind": mesh.kind,
                       "bone": mesh.bone, "vtxOffset": nv, "vtxCount": int(len(out)), "idxOffset": ni,
                       "idxCount": int(len(tris)), "min": pos.min(0).tolist(), "max": pos.max(0).tolist()})
        verts.append(out)
        idx.append(tris)
        c, w = skin_weights(mesh, len(out), scaled.get(p.name))
        counts.append(c)
        weights.append(w)
        nv += len(out)
        ni += len(tris)
    meta = {"version": FORMAT_VERSION, "file": rel, "pieces": pieces,
            "nodes": [{"name": n.name, "parent": n.parent, "transform": n.transform.reshape(-1).tolist(),
                       "pose": list(pose[0]) + list(pose[1])}
                      for n, pose in zip(m.nodes, m.first_pose)],
            "sockets": [{"name": s.name, "node": s.node, "pos": list(s.pos), "rot": list(s.rot),
                         "scale": list(s.scale)} for s in m.sockets],
            "anims": anim_meta}
    base = os.path.join(out_root, "models", rel)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    with open(base + ".bin", "wb") as f:
        f.write(b"TRMD")
        f.write(struct.pack("<5I", FORMAT_VERSION, nv, ni, sum(len(w) for w in weights), len(anim_floats)))
        for a in verts + idx + counts + weights + [anim_floats]:
            f.write(np.ascontiguousarray(a).tobytes())
    with open(base + ".json", "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    return meta
