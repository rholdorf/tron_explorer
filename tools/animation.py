"""Model animations for the viewer: child models, clips with the engine's per-node rules, a reference
sampler (the viewer's ModelAnimator mirrors it) and the idle animation a character starts in.

A clip holds each node's parent-relative channels with the engine's evaluation rules already applied
(TransformMaker::Recurse in ltjs): MNODE_ROTATIONONLY nodes take their bind offset from the parent
instead of the keyed position, and the root adds the animation's binding translation. Every channel
has 1 key (constant) or one per key time.
"""
import os

import numpy as np

import butes
import ltb


def norm(path):
    return path.replace("\\", "/").strip().lower()


def load_children(extracted, rel, m, load=None):
    """The model's child models (ServerLoadChildModelCB): each name is joined to the parent's directory.
    Children never have children of their own. `load(rel)` loads a model (default ltb.load)."""
    load = load or (lambda r: ltb.load(os.path.join(extracted, r)))
    base = os.path.dirname(norm(rel))
    return [load(f"{base}/{norm(c)}" if base else norm(c)) for c in m.child_models]


def find_anim(m, children, name):
    """(owner model, animation) for `name` (Model::FindAnim: the model's own animations, then each
    child's in order; case-insensitive, first match), or (None, None)."""
    for owner in [m] + list(children):
        a = ltb.find_anim(owner.anims, name)
        if a is not None:
            return owner, a
    return None, None


class Clip:
    def __init__(self, name, times, pos, rot):
        self.name = name
        self.times = np.asarray(times, np.float64)   # ms, from 0, never decreasing (duplicates kept)
        self.pos = pos   # per node: (1 or n, 3)
        self.rot = rot   # per node: (1 or n, 4) quaternion x y z w

    @property
    def length(self):
        """Loop length in ms: the last key's time (AnimTracker wraps with t %= lastKeyTime)."""
        return float(self.times[-1])


def clip(m, children, name):
    """The clip of animation `name` played on model m. A child's animation drives m's node i with the
    child's channel i (TransformMaker: GetAnimNode(iNode)); nodes are never matched by name."""
    owner, anim = find_anim(m, children, name)
    if anim is None:
        raise KeyError(f"{name}: no such animation in {m.path} or its children")
    if len(owner.nodes) != len(m.nodes):
        raise ValueError(f"{name}: {owner.path} has {len(owner.nodes)} nodes, {m.path} {len(m.nodes)}")
    pos, rot = [], []
    for n, (p, q) in zip(m.nodes, ltb.decode_anim(owner, anim)):
        if n.flags & ltb.MNODE_ROTATIONONLY:
            p = np.array([ltb.parent_offset(m, n)])
        elif not len(p):
            p = np.zeros((1, 3))
        if n.parent < 0:
            p = p + np.asarray(anim.translation, np.float64)
        if not len(q):
            q = np.array([[0.0, 0.0, 0.0, 1.0]])
        pos.append(_collapse(p))
        rot.append(_collapse(q))
    return Clip(anim.name, anim.times, pos, rot)


def _collapse(keys):
    """A channel whose keys are all equal is stored as one constant key."""
    return keys[:1] if len(keys) > 1 and (keys == keys[0]).all() else keys


def key_at(times, t):
    """(k, frac): t lies between key k and k + 1. k is the last key with time <= t, so a zero-length
    interval between two keys with the same time is never used (the later key wins)."""
    k = int(np.searchsorted(times, t, side="right")) - 1
    k = max(0, min(k, len(times) - 1))
    if k + 1 >= len(times):
        return k, 0.0
    return k, float((t - times[k]) / (times[k + 1] - times[k]))


def slerp(a, b, t):
    """quat_Slerp (ltquatbase.cpp): shortest path, linear when the two are nearly equal."""
    cos = float(np.dot(a, b))
    if cos < 0:
        cos, b = -cos, -b
    if 1.0 - cos > 0.0001:
        omega = np.arccos(cos)
        s0, s1 = np.sin((1 - t) * omega) / np.sin(omega), np.sin(t * omega) / np.sin(omega)
    else:
        s0, s1 = 1 - t, t
    return s0 * a + s1 * b


def sample(c, t):
    """Each node's (position, quaternion) at time t (ms), looping: positions lerp, rotations slerp
    (AnimTracker / TransformMaker)."""
    if c.length > 0:
        t = t % c.length
    k, f = key_at(c.times, t)
    out = []
    for p, q in zip(c.pos, c.rot):
        pp = p[0] if len(p) == 1 else p[k] + (p[min(k + 1, len(p) - 1)] - p[k]) * f
        qq = q[0] if len(q) == 1 else slerp(q[k], q[min(k + 1, len(q) - 1)], f)
        out.append((tuple(pp.tolist()), tuple(np.asarray(qq).tolist())))
    return out


def quat_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def globals_(m, pose):
    """Model-space node matrices of a pose: global[n] = global[parent] x TR(q, p) (column vectors,
    translation in column 3, like ltb.Node.transform)."""
    out = []
    for n, (p, q) in zip(m.nodes, pose):
        local = np.eye(4)
        local[:3, :3] = quat_matrix(q)
        local[:3, 3] = p
        out.append(local if n.parent < 0 else out[n.parent] @ local)
    return out


# ------------------------------------------------------------------ idle animation

class AnimTable:
    """An animation table (attributes/Animations*.txt, Animation= in modelbutes.txt): prop groups
    ([properties]: Group { Prop ... }) and animation rows ([animations]: Name Movement { props }).
    Each row's props are one value per group: None, a prop, or ANY (AnyGroup)."""

    ANY = "*"

    def __init__(self, path):
        with open(path, "rb") as f:
            lines = butes._strip_comments(f.read().decode("latin-1"))
        text, section = {}, None
        for line in lines:
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                section = s[1:-1].lower()
                continue
            text.setdefault(section, []).append(line)
        tokens = " ".join(text.get("properties", [])).replace("{", " { ").replace("}", " } ").split()
        self.groups, self.group_of = [], {}
        i = 0
        while i < len(tokens):
            group = tokens[i].lower()
            j = tokens.index("}", i)
            self.groups.append(group)
            for p in tokens[i + 2:j]:
                self.group_of.setdefault(p.lower(), group)
            i = j + 1
        self.rows = []   # (name, {group: value})
        for line in text.get("animations", []):
            s = line.strip()
            if "{" not in s:
                continue
            head, body = s.split("{", 1)
            name = head.split()[0]
            self.rows.append((name, self.props(body.split("}")[0].split())))

    def props(self, names):
        out = {}
        for p in names:
            p = p.lower()
            if p.startswith("any") and p[3:] in self.groups:
                out[p[3:]] = self.ANY
            elif p in self.group_of:
                out[self.group_of[p]] = p
        return out

    def _matches(self, row, request):
        """CAnimationProp ==: same value, or ANY on either side (None matches only None)."""
        for g in self.groups:
            a, b = row.get(g), request.get(g)
            if a != b and a != self.ANY and b != self.ANY:
                return False
        return True

    def find(self, request, seed=0):
        """CAnimationMgr::FindAnimation: rows whose props equal the request exactly; else the first row
        (file order) that matches with wildcards, together with every row with exactly its props; one
        of several is picked at random (here: by `seed`). No match: the 'Base None {}' row."""
        def key(props):
            return tuple(props.get(g) for g in self.groups)
        want = key(request)
        rows = [n for n, p in self.rows if key(p) == want]
        if not rows:
            first = next((p for _n, p in self.rows if self._matches(p, request)), None)
            if first is not None:
                rows = [n for n, p in self.rows if key(p) == key(first)]
        if not rows:
            rows = [n for n, p in self.rows if not p][:1]
        return rows[seed % len(rows)] if rows else None


class IdleSelector:
    """The animation a placed CAIHuman starts in: state HumanIdle asks the template's animation table
    for {Posture=Stand, WeaponPosition=Down, Weapon=W} (CAIHumanStateIdle::UpdateAnimation), with
    Movement=Hover for hovering AIs (CAIHuman::UpdateAnimation). W comes from the RightHand weapon's
    AIWeaponType in weapons.txt: 1 (Ranged) Weapon1, 2 (Melee) Weapon2, else or none Weapon3
    (CAI::GetWeaponProp)."""

    WEAPON_PROP = {1: "weapon1", 2: "weapon2"}

    def __init__(self, extracted, resolver):
        self.extracted = extracted
        self.resolver = resolver
        a = os.path.join(extracted, "attributes")
        self.weapon_type = {s["name"].lower(): s.get("aiweapontype", 0)
                            for s in butes.load(os.path.join(a, "weapons.txt")).values() if "name" in s}
        self.human_type = {s["name"].lower(): s.get("humantype", "") for s in
                           butes.load(os.path.join(a, "aibutes.txt")).values() if "name" in s}
        self.tables = {}

    def table(self, rel):
        if rel not in self.tables:
            path = os.path.join(self.extracted, rel)
            self.tables[rel] = AnimTable(path) if os.path.isfile(path) else None
        return self.tables[rel]

    def idle(self, obj, seed=0):
        """The idle animation's name for a CAIHuman level object, or None (no table)."""
        p = {q["k"].lower(): q for q in obj["props"]}
        t = self.resolver.templates.get(p["modeltemplate"]["s"].lower()) if "modeltemplate" in p else None
        table = self.table(norm(t["animation"])) if t and "animation" in t else None
        if table is None:
            return None
        weapon = self.resolver.weapon_at(obj, "RightHand")
        w = self.WEAPON_PROP.get(self.weapon_type.get(weapon.lower(), 0) if weapon else 0, "weapon3")
        request = table.props(["Stand", "Down", w])
        if self.human_type.get(str(t.get("ainame", "")).lower()) == "Hovering":   # CAIHuman::SetAIType
            request.update(table.props(["Hover"]))
        return table.find(request, seed)
