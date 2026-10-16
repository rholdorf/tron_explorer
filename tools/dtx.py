"""DTX v-5 textures (LithTech Jupiter) and .spr sprites as RGBA pixels, for measuring them, not drawing them:
the first mip only, decoded with Pillow's BCn decoder. Layout as the viewer's DtxLoader.cs: a 164-byte header
(dtxmgr.h), flags at 16 (bit 0 = fullbright), the BPP ident at 26, the command string at 36. A sprite is
u32 frames, u32 frame rate, 12 bytes, then frames x (u16 length, DTX path)."""
import os
import struct

import numpy as np
from PIL import Image

HEADER = 164
BCN = {4: 1, 5: 2, 6: 3}   # BPP ident -> Pillow bcn mode: DXT1, DXT3, DXT5


def _path(root, name):
    return os.path.join(root, name.replace("\\", "/").strip().lower())


def load(root, name):
    """(RGBA uint8 array (h, w, 4), fullbright) of a DTX's first mip, or None when the file is missing."""
    path = _path(root, name)
    if not os.path.exists(path):
        return None
    data = open(path, "rb").read()
    w, h = struct.unpack_from("<HH", data, 8)
    fullbright = bool(struct.unpack_from("<i", data, 16)[0] & 1)
    bpp = data[26]
    body = data[HEADER:]
    if bpp in (0, 3):
        img = Image.frombuffer("RGBA", (w, h), body[:w * h * 4], "raw", "BGRA", 0, 1)
    else:
        n = BCN[bpp]
        img = Image.frombuffer("RGBA", (w, h), body[:(w // 4) * (h // 4) * (8 if n == 1 else 16)], "bcn", n)
    return np.asarray(img), fullbright


def frames(root, name):
    """Every frame of a texture as [(RGBA, fullbright)]: one for a DTX, each frame for a sprite."""
    if not name.lower().endswith(".spr"):
        t = load(root, name)
        return [t] if t else []
    path = _path(root, name)
    if not os.path.exists(path):
        return []
    data = open(path, "rb").read()
    n, p, out = struct.unpack_from("<I", data, 0)[0], 20, []
    for _ in range(n):
        ln = struct.unpack_from("<H", data, p)[0]
        t = load(root, data[p + 2:p + 2 + ln].decode("ascii"))
        p += 2 + ln
        if t:
            out.append(t)
    return out
