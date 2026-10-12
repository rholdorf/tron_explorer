"""Keyframers: KeyFramers that start active and move their target objects along a path of keys.

Format (ltjs keyframer.cpp CreateKeyList, keydata.cpp KeyData::Copy; research note
docs/research/keyframer-paths.md): a KeyFramer's KeyDataIndex (truncated) indexes a blind object data
chunk (dat85 KEYFRAMER_BLINDOBJECTID) holding u32 numKeys (used as u16), then per key:
u16 control (bit0 prev tangent, bit1 next tangent), u8 soundLen, u8 commandLen, f32 pos[3],
f32 pitchYawRoll[3] (radians), f32 timeStamp (s since the previous key), f32 soundRadius,
sound[soundLen], command[commandLen] (not NUL-terminated), then the tangents present (relative to pos).
"""
import struct


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
