"""Model instances for the viewer: resolve which .ltb + skins each level object shows, and export
those models to the runtime format.

export/models/<model path>.json  pieces, nodes
export/models/<model path>.bin   'TRMD', u32 version, u32 nVerts, u32 nIdx, u32 nInfluences,
                                 verts (nVerts * 44 bytes, same layout as level.bin),
                                 idx (u32, relative to the piece's first vertex),
                                 influences per vertex (u8 x nVerts, 1..4),
                                 influences (nInfluences * Unity BoneWeight1: f32 weight, i32 node)
Only LOD 0 is exported, at the bind pose (vertices are stored in model space).
"""
import json
import os
import struct

import numpy as np

import butes
import ltb
import renderstyle

FORMAT_VERSION = 2

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

    def attachments(self, obj):
        """A character's attachments as (socket, model file, skins, render styles). The object's own
        position properties are created first (CAttachments::ReadProp/Init), then the template's
        DefaultAttachmentN = "Position, Name" unless UseDefaultAttachments is off (CAIHuman
        InitialUpdate); a default for an occupied position is dropped (CAttachments::Attach). The
        position name is the parent model's socket. Weapons occupy their position but aren't drawn."""
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
            if name.split(",")[0].strip().lower() in self.weapons:   # WeaponMgr::ReadWeapon "weapon,ammo"
                occupied.add(pos.lower())
                self.skipped_weapons += 1
                continue
            a = self.attachables.get(name.lower())
            if not a:
                continue   # "Unmatched attable name": nothing is created
            occupied.add(pos.lower())
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
                g = renderstyle.compile_glow(g, glow)
                if len(draws) == 1 and len(g["passes"]) == 1:
                    draws[0]["glow"] = g["passes"]   # over the model's own state
                else:
                    # A draw of a multi-draw style that writes opaque with Z carries a one-pass glow;
                    # otherwise the glow is a draw of its own with the glow style's state.
                    d = next((d for d in draws if len(g["passes"]) == 1 and tuple(d["blend"]) == (1, 0)
                              and d["zwrite"]), None)
                    if d is None:
                        d = {k: g[k] for k in ("blend", "zwrite", "ztest", "cull")}
                        d["passes"] = []
                        draws.append(d)
                    d["glow"] = g["passes"]
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
    """The model's dims (half-extents): its first animation's, which a prop takes as its object dims
    (ModelInstance::GetDims); the bind-pose box when it has no animation."""
    n = struct.unpack_from("<I", m.data, m.anims_offset)[0]
    if n:
        return list(struct.unpack_from("<3f", m.data, m.anims_offset + 4))
    pts = [p.lods[0][3].field("pos") for p in m.pieces if p.lods[0][3].field("pos") is not None]
    if not pts:
        return [0.0, 0.0, 0.0]
    pts = np.concatenate(pts)
    return ((pts.max(0) - pts.min(0)) / 2).tolist()


def export_model(extracted, rel, out_root):
    m = ltb.load(os.path.join(extracted, rel))
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
                         "scale": list(s.scale)} for s in m.sockets]}
    base = os.path.join(out_root, "models", rel)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    with open(base + ".bin", "wb") as f:
        f.write(b"TRMD")
        f.write(struct.pack("<4I", FORMAT_VERSION, nv, ni, sum(len(w) for w in weights)))
        for a in verts + idx + counts + weights:
            f.write(np.ascontiguousarray(a).tobytes())
    with open(base + ".json", "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    return meta
