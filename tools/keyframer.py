"""Keyframers: KeyFramers that start active and move their target objects along a path of keys.

Format (ltjs keyframer.cpp CreateKeyList, keydata.cpp KeyData::Copy; research note
docs/research/keyframer-paths.md): a KeyFramer's KeyDataIndex (truncated) indexes a blind object data
chunk (dat85 KEYFRAMER_BLINDOBJECTID) holding u32 numKeys (used as u16), then per key:
u16 control (bit0 prev tangent, bit1 next tangent), u8 soundLen, u8 commandLen, f32 pos[3],
f32 pitchYawRoll[3] (radians), f32 timeStamp (s since the previous key), f32 soundRadius,
sound[soundLen], command[commandLen] (not NUL-terminated), then the tangents present (relative to pos).
"""
import struct

# KeyFramer::OnTrigger verbs that run its own path (REVERSE is BACKWARD). MOVETO and the TARGET family
# aren't sent by any live keyframer to itself.
SELF_VERBS = {"ON": "ON", "OFF": "OFF", "PAUSE": "PAUSE", "RESUME": "RESUME", "FORWARD": "FORWARD",
              "BACKWARD": "BACKWARD", "REVERSE": "BACKWARD", "TOGGLEDIR": "TOGGLEDIR", "GOTO": "GOTO"}


def _split(text):
    """Command language tokens: words and parenthesized groups (kept as their inner text, nested ones
    whole); a top-level ';' ends a command. Returns a list of commands, each a list of tokens."""
    commands, tokens, word, depth = [], [], "", 0
    for ch in text:
        if depth:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if not depth:
                    tokens.append(("(", word))
                    word = ""
                    continue
            word += ch
        elif ch == "(":
            if word:
                tokens.append(word)
            word, depth = "", 1
        elif ch == ";" or ch.isspace():
            if word:
                tokens.append(word)
            word = ""
            if ch == ";" and tokens:
                commands.append(tokens)
                tokens = []
        else:
            word += ch
    if word:
        tokens.append(("(", word) if depth else word)
    if tokens:
        commands.append(tokens)
    return commands


def _words(tokens):
    """A message's words: a single parenthesized group stands for its inner words."""
    if len(tokens) == 1 and isinstance(tokens[0], tuple):
        return tokens[0][1].split()
    return [t[1] if isinstance(t, tuple) else t for t in tokens]


def find_key(name, base_key_name, n_keys):
    """KeyFramer::FindKey: the key index a key name stands for, or -1. The name is the keyframer's
    BaseKeyName (any case) followed by "0", "01".."09", "10".. (the key's index)."""
    if name[:len(base_key_name)].lower() != base_key_name.lower() or len(name) <= len(base_key_name):
        return -1
    ext = name[len(base_key_name):]
    for i in range(n_keys):
        if ext == (f"0{i}" if 0 < i < 10 else str(i)):
            return i
    return -1


def self_commands(command, name, base_key_name, n_keys, delay=0.0):
    """The messages a key command sends to its own keyframer `name`, in order: verb (SELF_VERBS'
    values), delay (s, from `delay <t> (<command>)`) and key (GOTO's key index, else -1)."""
    out = []
    for tokens in _split(command):
        head = tokens[0].lower() if isinstance(tokens[0], str) else ""
        if head == "delay" and len(tokens) >= 3:
            inner = tokens[2][1] if isinstance(tokens[2], tuple) else " ".join(_words(tokens[2:]))
            out += self_commands(inner, name, base_key_name, n_keys, delay + float(tokens[1]))
        elif head == "msg" and len(tokens) >= 3 and isinstance(tokens[1], str) \
                and tokens[1].lower() == name.lower():
            words = _words(tokens[2:])
            verb = SELF_VERBS.get(words[0].upper()) if words else None
            if verb is None:
                continue
            key = -1
            if verb == "GOTO":
                key = find_key(words[1], base_key_name, n_keys) if len(words) > 1 else -1
                if key < 0:
                    continue
            out.append({"verb": verb, "delay": delay, "key": key})
    return out


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
