"""ClientFX effect groups (docs/research/clientfx-groups.md, clientfx-types.md): the .fxf readers, the
game's group lookup, and the form the viewer plays them from.

The game loads every ClientFX/*.fxf (CClientFXDB::LoadFxGroups): text when the file starts with
`Groups:`, binary otherwise. A group is a loop of Phase ms holding fx keys; each key is an effect type
(`Type;label`) with props. Names match case-insensitively and the first group loaded wins.

Export (export_group): the keys the game creates at FX detail High, start/end clamped to the phase as
the loader does, the base props parsed (UpdatePos, Offset, ...), Ck/Sk keys sorted, and the type's
own props by name: combos as their index, paths normalized ("" when unset), the rest as read.
"""
import os
import struct

import butes

TEXT, INTEGER, FLOAT, COMBO, VECTOR, VECTOR4, CLRKEY, PATH = range(8)
TYPE_TAGS = ["STRING", "INTEGER", "FLOAT", "COMBO", "VECTOR", "VECTOR4", "CLRKEY", "PATH"]
PAYLOAD = {TEXT: 128, INTEGER: 4, FLOAT: 4, COMBO: 128, VECTOR: 12, VECTOR4: 16, CLRKEY: 8, PATH: 128}

# Tron's clientfx.fxd effect types
TYPES = {"ParticleSystem", "Sprite", "LTBModel", "PlaySound", "PlayRandomSound", "LightningFX", "FlareSpriteFX",
         "PolyTrail", "LTBBouncyChunk", "BouncyChunk", "CreateFX", "DynaLight", "CamJitter", "FallingStuff",
         "WonkyFX", "SpriteSystem", "Null"}

# DetailLevel combo -> plays at the manager's default level, High (IsDetailLevelEnabled's table):
# All, High, Medium+High and Low+High do; Medium, Low and Low+Medium are never created.
PLAYS_AT_HIGH = {0: True, 1: True, 2: False, 3: False, 4: True, 5: False, 6: True}

# CBaseFXProps: the props every key has, parsed by the base class
BASE_PROPS = {"updatepos", "attachname", "offset", "rotateadd", "disableatdist", "menulayer", "maxstartoffset",
              "randomizestartoffset", "startoffsetinterval", "smoothshutdown", "detaillevel", "isgore", "ck", "sk"}

# Props that name another group: CreateFX starts one, a particle splat creates one
GROUP_PROPS = {("CreateFX", "fxname"), ("ParticleSystem", "splateffect")}


def _cstr(b):
    return b.split(b"\0", 1)[0].decode("latin-1")


def _key(fx_name, fx_id, linked, link_id, link_node, start, end, repeat, props):
    return {"name": fx_name, "type": fx_name.split(";", 1)[0], "id": fx_id, "linked": bool(linked),
            "linkId": link_id, "linkNode": link_node, "start": start, "end": end, "repeat": repeat,
            "props": props}


def read_binary(data):
    """Groups of a binary .fxf (ReadFXGroups): little-endian, no alignment between records."""
    p = 0

    def take(fmt):
        nonlocal p
        v = struct.unpack_from(fmt, data, p)
        p += struct.calcsize(fmt)
        return v

    def chars(n):
        nonlocal p
        p += n
        return _cstr(data[p - n:p])

    groups = []
    for _ in range(take("<I")[0]):
        n_fx = take("<I")[0]                      # the count comes before the name here
        name = chars(128)
        phase = take("<I")[0]
        keys = []
        for _ in range(n_fx):
            fx_name = chars(128)
            fx_id, linked, link_id = take("<IB3xI")   # LINK_STATUS {bool; uint32; char[32]}
            link_node = chars(32)
            start, end, repeat = take("<ffI")
            take("<Iff")                          # TrackID, MinScale, MaxScale: editor only
            props = []
            for _ in range(take("<I")[0]):
                n = data[p]
                pname = data[p + 1:p + 1 + n].decode("latin-1")
                p += 1 + n
                ptype = take("<I")[0]
                raw = data[p:p + PAYLOAD[ptype]]
                p += PAYLOAD[ptype]
                if ptype in (TEXT, COMBO, PATH):
                    v = _cstr(raw)
                elif ptype == INTEGER:
                    v = struct.unpack("<i", raw)[0]
                elif ptype == FLOAT:
                    v = struct.unpack("<f", raw)[0]
                elif ptype == CLRKEY:
                    t, c = struct.unpack("<fI", raw)
                    v = (t, c & 255, (c >> 8) & 255, (c >> 16) & 255, c >> 24)
                else:
                    v = struct.unpack("<3f" if ptype == VECTOR else "<4f", raw)
                props.append((pname, ptype, v))
            keys.append(_key(fx_name, fx_id, linked, link_id, link_node, start, end, repeat, props))
        groups.append({"name": name, "phase": phase, "keys": keys})
    if p != len(data):
        raise ValueError(f"binary .fxf: {len(data) - p} bytes left after {len(groups)} groups")
    return groups


def read_text(data):
    """Groups of a text .fxf: one `Tag: value` per line in a fixed order. As the game's sscanf("%s"), a
    value is its first token; a CLRKEY's channels are truncated to bytes (int(x * 255))."""
    lines = iter(s for s in (ln.strip() for ln in data.decode("latin-1").splitlines()) if s)

    def val(tag):
        t, _, v = next(lines).partition(":")
        if t != tag:
            raise ValueError(f"text .fxf: {tag} expected, found {t}")
        return v.strip()

    groups = []
    for _ in range(int(val("Groups"))):
        name = val("GroupName")
        n_fx = int(val("FxInGroup"))
        phase = int(val("Phase"))
        keys = []
        for _ in range(n_fx):
            fx_name = val("FxName")
            fx_id, linked, link_id = int(val("FxID")), int(val("Linked")), int(val("LinkID"))
            link_node = val("LinkNode")
            start, end, repeat = float(val("StartTime")), float(val("EndTime")), int(val("Repeat"))
            val("TrackID"), val("MinScale"), val("MaxScale")
            props = []
            for _ in range(int(val("Properties"))):
                pname = val("PropName")
                ptype = int(val("Type"))
                raw = val(TYPE_TAGS[ptype])
                if ptype in (TEXT, COMBO, PATH):
                    v = raw.split()[0] if raw else ""
                elif ptype == INTEGER:
                    v = int(raw)
                elif ptype == FLOAT:
                    v = float(raw)
                elif ptype == CLRKEY:
                    t, *c = map(float, raw.split())
                    v = (t, *(int(x * 255.0) for x in c))
                else:
                    v = tuple(map(float, raw.split()))
                props.append((pname, ptype, v))
            keys.append(_key(fx_name, fx_id, linked, link_id, link_node, start, end, repeat, props))
        groups.append({"name": name, "phase": phase, "keys": keys})
    return groups


def read_fxf(path):
    with open(path, "rb") as f:
        data = f.read()
    return read_text(data) if data[:7].lower() == b"groups:" else read_binary(data)


class Library:
    """Every group of the game's .fxf files, looked up as FindGroupFX does: case-insensitive, first loaded
    wins. Files load in name order (the engine's file list order is not known; the names that occur
    twice, DISC_impact, PRANK_impact and ZZZ_Empty, aren't reached by the levels)."""

    def __init__(self, extracted):
        self.groups = {}
        self.source = {}
        folder = os.path.join(extracted, "clientfx")
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith(".fxf"):
                for g in read_fxf(os.path.join(folder, fn)):
                    if g["name"].lower() not in self.groups:
                        self.groups[g["name"].lower()] = g
                        self.source[g["name"].lower()] = fn

    def find(self, name):
        return self.groups.get(name.strip().lower())

    def reached(self, names):
        """The groups these names reach, with the groups their CreateFX and splat props name, in order
        of discovery; and the names that find no group."""
        out, missing, todo = {}, [], [n for n in names if n.strip()]
        while todo:
            name = todo.pop(0)
            g = self.find(name)
            if g is None:
                if name.lower() not in (m.lower() for m in missing):
                    missing.append(name)
                continue
            if g["name"].lower() in out:
                continue
            out[g["name"].lower()] = g
            for k in g["keys"]:
                for pname, _, v in k["props"]:
                    if (k["type"], pname.lower()) in GROUP_PROPS and v.strip():
                        todo.append(v)
        return list(out.values()), missing


def combo(v):
    """A combo's value is the index before its first comma (GetComboVal: atoi(strtok(v, ",")))."""
    try:
        return int(v.split(",", 1)[0])
    except ValueError:
        return 0


def path(v):
    """A PATH prop `ext|path`; `ext|...` (or empty) is unset, ""."""
    p = v.split("|", 1)[1] if "|" in v else v
    return "" if p in ("", "...") else butes.norm(p)


def plays(key):
    props = {n.lower(): v for n, t, v in key["props"]}
    return PLAYS_AT_HIGH.get(combo(props["detaillevel"]), True) if "detaillevel" in props else True


def encode_prop(k, v):
    """A type prop as the viewer reads object props (export_level.encode_prop): s string or path, n number
    or combo index, v vector."""
    if isinstance(v, str):
        return {"k": k, "t": "s", "s": v, "v": []}
    if isinstance(v, (list, tuple)):
        return {"k": k, "t": "v", "s": "", "v": [float(x) for x in v]}
    return {"k": k, "t": "n", "s": "", "v": [float(v)]}


def prop(key, name, default=None):
    """An exported key's type prop by name: its string, its number, or its vector."""
    p = next((q for q in key["props"] if q["k"] == name), None)
    if p is None:
        return default
    return p["s"] if p["t"] == "s" else p["v"][0] if p["t"] == "n" else p["v"]


def export_key(key, phase):
    """One fx key in the viewer's form. Ck: t, r, g, b, a per key, flat, in 0..1, a as stored (a
    transparency: drawn alpha = 1 - a); Sk: t, scale per key, flat (JsonUtility reads no nested arrays)."""
    start = min(max(key["start"], 0.0), phase)
    end = min(max(key["end"], 0.0), phase)
    base, props, ck, sk = {}, {}, [], []
    for name, ptype, v in key["props"]:
        low = name.lower()
        if low == "ck":
            ck.append([v[0]] + [c / 255.0 for c in v[1:]])
        elif low == "sk":
            sk.append([v[0], v[1]])
        elif low in BASE_PROPS:
            base[low] = v
        else:
            props[name] = combo(v) if ptype == COMBO else path(v) if ptype == PATH else \
                list(v) if isinstance(v, tuple) else v
    return {
        "type": key["type"], "label": key["name"], "id": key["id"],
        # a key linked to itself is unlinked; a link to a key not created leaves the instance parent
        "link": key["linkId"] if key["linked"] and key["linkId"] != key["id"] else -1,
        "start": start, "end": end, "continual": end - start >= phase - 0.01,
        "updatePos": combo(base.get("updatepos", "0")), "attach": base.get("attachname", ""),
        "offset": list(base.get("offset", (0.0, 0.0, 0.0))),
        "rotateAdd": list(base.get("rotateadd", (0.0, 0.0, 0.0))),
        "disableAtDist": combo(base.get("disableatdist", "0")) == 1,
        "maxStartOffset": base.get("maxstartoffset", 0.0),
        "randomizeStartOffset": combo(base.get("randomizestartoffset", "0")) == 1,
        "startOffsetInterval": base.get("startoffsetinterval", 0.0),
        "smoothShutDown": combo(base.get("smoothshutdown", "1")) == 1,
        "ck": [x for c in sorted(ck, key=lambda c: c[0]) for x in c],
        "sk": [x for k in sorted(sk, key=lambda k: k[0]) for x in k],
        "props": [encode_prop(k, v) for k, v in props.items()],
    }


def export_group(g):
    """A group in the viewer's form: phase in seconds, the keys created at detail High, ordered so a
    motion-linked key comes after the key it links to (the loader's bubble sort)."""
    phase = g["phase"] / 1000.0
    keys = [export_key(k, phase) for k in g["keys"] if plays(k)]
    for _ in range(len(keys)):
        moved = False
        for i in range(len(keys) - 1):
            if keys[i]["link"] == keys[i + 1]["id"] and keys[i]["link"] >= 0:
                keys[i], keys[i + 1] = keys[i + 1], keys[i]
                moved = True
        if not moved:
            break
    return {"name": g["name"], "phase": phase, "fx": keys}


def assets(groups):
    """What the exported groups need from the other exports: {model file: animations} for LTBModel and
    LTBBouncyChunk keys, and the sound names of PlaySound and chunk sounds (extracted paths)."""
    models, sounds = {}, []
    for g in groups:
        for k in g["fx"]:
            model = prop(k, "Model")
            if k["type"] in ("LTBModel", "LTBBouncyChunk") and model:
                anims = models.setdefault(model, set())
                if prop(k, "AniName"):
                    anims.add(prop(k, "AniName"))
            for s in (prop(k, "Sound"), prop(k, "ChunkSound")):
                if s and s not in sounds:
                    sounds.append(s)
    return models, sounds
