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
the levels' instances play are exported (animation.clip: engine rules applied, channels parent-relative).
"""
import json
import os
import struct

import numpy as np

import animation
import butes
import ltb
import renderstyle

FORMAT_VERSION = 3

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
        self.attachables = {s["name"].lower(): s for s in butes.load(os.path.join(a, "attachments.txt")).values()
                            if "name" in s}
        self.weapons = {s["name"].lower() for s in butes.load(os.path.join(a, "weapons.txt")).values()
                        if "name" in s}
        self.skipped_weapons = 0   # weapon attachments (weapons.txt hand-held models) are not drawn yet
        self.missing_sockets = {}  # (character model, position) -> attachments dropped for want of a socket
        self.undrawn_attachments = {}   # object attachment class without a model -> count

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

        if not b("Visible") or b("StartHidden", False):
            return None
        cls = obj["cls"]
        if cls in ("ArchiveBin", "SecRezzer", "CAIHuman"):
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

    def occupants(self, obj):
        """What a character's attachment positions hold, as (position, name, attachable or None for a
        weapon). The object's own position properties are created first (CAttachments::ReadProp/Init),
        then the template's DefaultAttachmentN = "Position, Name" unless UseDefaultAttachments is off
        (CAIHuman InitialUpdate); a default for an occupied position is dropped (CAttachments::Attach)."""
        p = {q["k"].lower(): q for q in obj["props"]}
        t = self.templates.get(p["modeltemplate"]["s"].lower()) if "modeltemplate" in p else None
        if not t:
            return []
        wanted = []
        for pos in ATTACHMENT_POSITIONS:
            q = p.get(pos.lower())
            if q and q["t"] == "s" and q["s"].strip():
                wanted.append((pos, q["s"].strip()))
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
        return out

    def weapon_at(self, obj, position):
        """The weapon a character holds at `position` (e.g. RightHand, its primary weapon), or None."""
        return next((name for pos, name, a in self.occupants(obj)
                     if a is None and pos.lower() == position.lower()), None)

    def attachments(self, obj):
        """A character's drawn attachments as (socket, model file, skins, render styles); the position
        name is the parent model's socket. Weapons occupy their position but aren't drawn."""
        out = []
        for pos, _name, a in self.occupants(obj):
            if a is None:
                self.skipped_weapons += 1
                continue
            # Type 0 is a Prop; type 1 creates its Class, which only draws the model if it's a Prop.
            if a.get("type") == 1 and a.get("class") not in MODEL_ATTACHMENT_CLASSES:
                self.undrawn_attachments[a.get("class")] = self.undrawn_attachments.get(a.get("class"), 0) + 1
                continue
            if "model" in a:
                out.append((pos, norm(a["model"]), [norm(x) for x in butes.indexed(a, "skin")],
                            [norm(x) for x in butes.indexed(a, "renderstyle")]))
        return out


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


# Character styles whose second pass needs a real second draw over the framebuffer (ticket #11). Until
# then they draw pass 0 only; every other style the model shader can't draw still stops the export.
PASS0_ONLY = {"chars/rs/thorn_body.ltb", "chars/rs/rector_cloak.ltb", "chars/rs/thorn_corruption.ltb",
              "rs/alpha_transparent.ltb",
              # Seeker (loads since #6): opaque alpha-tested pass, then an additive pass on the complement.
              "chars/rs/seeker.ltb"}
# Two-pass alpha-blended glow style (Thorn's cloak, ticket #11): the glow buffer gets GlowDefaultRS instead.
GLOW_DEFAULT_INSTEAD = {"chars/rs/glow_thorncloak_rs.ltb"}


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
        self.pass0_only = {}     # PASS0_ONLY style -> {model file: pieces drawn with pass 0 only}
        self.glow_fallbacks = set()   # (style, GLOW_DEFAULT_INSTEAD glow style it maps to)

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
            name = rel if s else "<default>"
            if s and rel in PASS0_ONLY:
                s.passes = s.passes[:1]
                self.pass0_only.setdefault(rel, {})
            c = renderstyle.compile_style(s or renderstyle.default_style(), name)
            glow = self.glow_map.get(rel, self.glow_default) if s else self.glow_default
            if glow in GLOW_DEFAULT_INSTEAD:
                self.glow_fallbacks.add((rel, glow))
                glow = self.glow_default
            g = self._load(glow)
            if g is None:
                raise ValueError(f"{name}: glow style {glow} not found")
            # Mapped to itself: the glow buffer gets the style's own first pass, blend included.
            c["glow"] = dict(c["passes"][0], blendOver=0) if glow == rel else renderstyle.compile_glow(g, glow)
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
            if name in self.pass0_only:
                self.pass0_only[name][rel] = self.pass0_only[name].get(rel, 0) + 1
            if c["name"] not in index:
                index[c["name"]] = len(table)
                table.append(c)
            out.append({"style": index[c["name"]],
                        "tex": [skins[t] if 0 <= t < len(skins) else "" for t in textures]})
        return out


BONE_WEIGHT = np.dtype([("weight", "<f4"), ("bone", "<i4")])   # Unity BoneWeight1


def skin_weights(mesh, nv):
    """Per vertex influence count (1..4) and the influences (Unity BoneWeight1, heaviest first).
    Bone indices are model node indices. Skeletal render-direct meshes: each bone set loads
    bones[0..n-1] and blends with the vertex's first n-1 stored weights plus 1 - their sum
    (CD3DSkelMesh::Render, D3DVBF_{n-1}WEIGHTS). Rigid and vertex-animated meshes follow one node."""
    if mesh.kind != ltb.SKEL:
        return np.ones(nv, np.uint8), np.array([(1.0, mesh.bone)] * nv, BONE_WEIGHT)
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
    posCount, rotOffset, rotCount (offsets in floats; a count is 1 for a constant channel or keys)."""
    floats, meta, n = [], [], 0

    def put(a):
        nonlocal n
        a = np.ascontiguousarray(a, np.float32).reshape(-1)
        floats.append(a)
        n += len(a)
        return n - len(a)

    for c in clips:
        entry = {"name": c.name, "length": c.length / 1000.0, "keys": len(c.times),
                 "times": put(c.times / 1000.0), "channels": []}
        for p, q in zip(c.pos, c.rot):
            entry["channels"] += [put(p), len(p), put(q), len(q)]
        meta.append(entry)
    return (np.concatenate(floats) if floats else np.zeros(0, np.float32)), meta


def export_model(extracted, rel, out_root, anims=(), load=None):
    """Writes the model and the clips of `anims` (animation names in the model or its child models).
    load(rel): a model loader (default ltb.load), for child models."""
    m = ltb.load(os.path.join(extracted, rel))
    children = animation.load_children(extracted, rel, m, load) if anims else []
    anim_floats, anim_meta = clip_block([animation.clip(m, children, a) for a in anims])
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
        out["rgba"] = (128, 128, 128, 255)  # unused: Tron/Model lights from the material (D3D lighting)
        tris = mesh.indices.astype(np.uint32).reshape(-1)
        pieces.append({"name": p.name, "textures": textures, "style": style, "kind": mesh.kind,
                       "bone": mesh.bone, "vtxOffset": nv, "vtxCount": int(len(out)), "idxOffset": ni,
                       "idxCount": int(len(tris)), "min": pos.min(0).tolist(), "max": pos.max(0).tolist()})
        verts.append(out)
        idx.append(tris)
        c, w = skin_weights(mesh, len(out))
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
