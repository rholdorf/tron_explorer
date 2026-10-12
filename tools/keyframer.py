"""Keyframers: KeyFramers, which move their target objects along a path of keys while they are active.

Format (ltjs keyframer.cpp CreateKeyList, keydata.cpp KeyData::Copy; research note
docs/research/keyframer-paths.md): a KeyFramer's KeyDataIndex (truncated) indexes a blind object data
chunk (dat85 KEYFRAMER_BLINDOBJECTID) holding u32 numKeys (used as u16), then per key:
u16 control (bit0 prev tangent, bit1 next tangent), u8 soundLen, u8 commandLen, f32 pos[3],
f32 pitchYawRoll[3] (radians), f32 timeStamp (s since the previous key), f32 soundRadius,
sound[soundLen], command[commandLen] (not NUL-terminated), then the tangents present (relative to pos).

Every keyframer is exported, active at start or not (ticket #33): the viewer runs the messages it gets
(ON, PAUSE, RESUME, GOTO...) and its keys' commands, as text (ADR 0001), in KeyframerMotion.cs.
"""
import struct

import numpy as np

import waveform

CLASS = "KeyFramer"


def keyframers(objects, blind):
    """The level's keyframers, for the viewer: name, obj (its index in the level's objects, its
    command-manager id), startActive, startPaused, baseKeyName (key names are it + "0", "01".."09",
    "10"..), targets (the ObjectName list; each name can match several objects), looping, alignToPath,
    ignoreOffsets, totalPathTime (> 0: velocity mode), wave (index into waveform.NAMES), activeSound,
    soundRadius, and keys: pos, pyr, time, bezPrev, bezNext and command (the key's command string). One
    without keys, targets or a base key name is left out: it can never move anything."""
    out = []
    for i, o in enumerate(objects):
        p = o["props"]
        if o["class"] != CLASS:
            continue
        index = p.get("KeyDataIndex", -1.0)
        if index < 0 or int(index) >= len(blind):
            continue
        targets = [n.strip() for n in p.get("ObjectName", "").split(";") if n.strip()]
        name, base = p.get("Name", ""), p.get("BaseKeyName", "")
        keys = read_keys(blind[int(index)][1])
        if not targets or not keys or not base:
            continue
        # PushObjects is left out: it moves the targets with MoveObject (pushing what's in the way) rather
        # than SetObjectPos, which only matters to the player, and the viewer's keyframers don't push it.
        out.append({
            "name": name, "obj": i, "startActive": bool(p.get("StartActive", False)),
            "startPaused": bool(p.get("StartPaused", False)), "baseKeyName": base, "targets": targets,
            "looping": bool(p.get("Looping", False)), "alignToPath": bool(p.get("AlignToPath", False)),
            "ignoreOffsets": bool(p.get("IgnoreOffsets", False)),
            "totalPathTime": float(p.get("TotalPathTime", 0.0)),
            "wave": waveform.index(p.get("Wavetype", "Linear")),
            "activeSound": p.get("ActiveSound", "").strip(), "soundRadius": float(p.get("SoundRadius", 1000.0)),
            "keys": [export_key(k) for k in keys],
        })
    return out


def export_key(k):
    """A key for level.json: pos, pyr, time and, when present, bezPrev, bezNext and command. Numbers are
    written as the shortest decimal that reads back as the same float32 (what the viewer keeps)."""
    out = {"pos": _f32(k["pos"]), "pyr": _f32(k["pyr"]), "time": _f32([k["time"]])[0]}
    for name in ("bezPrev", "bezNext"):
        if k[name]:
            out[name] = _f32(k[name])
    if k["command"]:
        out["command"] = k["command"]
    return out


def _f32(values):
    return [float(np.format_float_positional(np.float32(v), unique=True, trim="0")) for v in values]


def read_keys(blob):
    """A keyframer chunk's keys: pos, pyr, time (running sum of the time stamps), sound, soundRadius,
    command, and Bezier controls bezPrev/bezNext (absolute; [] when absent)."""
    n, = struct.unpack_from("<I", blob, 0)
    p = 4
    keys, t = [], 0.0
    for _ in range(n & 0xffff):
        control, sound_len, command_len = struct.unpack_from("<HBB", blob, p)
        p += 4
        pos = struct.unpack_from("<3f", blob, p)
        pyr = struct.unpack_from("<3f", blob, p + 12)
        dt, radius = struct.unpack_from("<2f", blob, p + 24)
        p += 32
        sound = blob[p:p + sound_len].decode("latin-1").strip()
        p += sound_len
        command = blob[p:p + command_len].decode("latin-1")
        p += command_len
        controls = []
        for bit in (1, 2):
            if control & bit:
                d = struct.unpack_from("<3f", blob, p)
                p += 12
                controls.append([a + b for a, b in zip(pos, d)])
            else:
                controls.append([])
        t += dt
        keys.append({"pos": list(pos), "pyr": list(pyr), "time": t, "sound": sound, "soundRadius": radius,
                     "command": command, "bezPrev": controls[0], "bezNext": controls[1]})
    if p != len(blob):
        raise ValueError(f"keyframer chunk: {len(blob) - p} bytes left after {len(keys)} keys")
    return keys
