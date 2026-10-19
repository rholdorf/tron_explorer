"""The HUD text the viewer draws (docs/research/mission-text.md, branch research/mission-text): the game's
string table, its font and the HUD's sounds, written to <export>/hud/.

- strings.json: every string in cres.dll's RT_STRING table, {"ids": [...], "texts": [...]}; MISSIONTEXT and
  TRANSMISSION messages name them by id.
- font.png / font.json: font 0 (Tw Cen MT, interface/fonts/twcenmt_.ttf) rasterized with FreeType into one
  atlas, white with the coverage in alpha, and each glyph's box and advance. The game renders the TTF at
  PointSize 20 into its own pages (twencen_20.ffa) and scales them to the asked char height; the viewer does
  the same from a larger render (HudFont.cs has the scale, measured on the reference video). Metrics are in
  atlas pixels: "size" is the em, "ascent" the win ascent (glyph "oy" is from there down).
- subtitles.json: the dialogue subtitles' layout (layout.txt [Subtitle]; docs/research/dialogue.md, branch
  research/dialogue). They use font 0 as above and show the string whose id is the voice's.
- the sounds the HUD plays (MissionText TypeSound / ScrollSound, the msgfadeout soundbute), to
  <export>/sounds/ like the levels' sounds.
"""

import json
import os
import struct

from PIL import Image, ImageDraw, ImageFont

import butes
import sounds

FONT = "interface/fonts/twcenmt_.ttf"
RENDER_SIZE = 64          # em size of the atlas render, in pixels
ATLAS_WIDTH = 1024
PAD = 2
HUD_SOUNDS = ("interface/snd/type.wav", "interface/snd/enter.wav")
HUD_SOUNDBUTES = ("msgfadeout",)
RT_STRING = 6


def _pe_resources(data):
    """{(type, name, lang): bytes} of a PE file's resource section (one level per type / name / language)."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    ddir = opt + (96 if magic == 0x10B else 112)
    rva = struct.unpack_from("<I", data, ddir + 2 * 8)[0]   # IMAGE_DIRECTORY_ENTRY_RESOURCE
    sec = opt + struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(nsec):
        vsize, vaddr, _, raw = struct.unpack_from("<IIII", data, sec + i * 40 + 8)
        if vaddr <= rva < vaddr + vsize:
            base = raw + rva - vaddr
            delta = vaddr - raw
            break
    else:
        return {}

    def entries(off):
        named, ids = struct.unpack_from("<HH", data, base + off + 12)
        for k in range(named + ids):
            name, target = struct.unpack_from("<II", data, base + off + 16 + k * 8)
            yield name, target

    out = {}
    for t, t_off in entries(0):
        for n, n_off in entries(t_off & 0x7FFFFFFF):
            for lang, leaf in entries(n_off & 0x7FFFFFFF):
                drva, size = struct.unpack_from("<II", data, base + leaf)
                out[(t, n, lang)] = data[drva - delta:drva - delta + size]
    return out


def read_strings(path):
    """{id: text} of a PE file's string table: block n holds ids 16(n-1)..16n-1, each a u16 length and that
    many UTF-16LE units; empty entries aren't strings (LoadString fails on them)."""
    with open(path, "rb") as f:
        data = f.read()
    out = {}
    for (t, block, _), raw in sorted(_pe_resources(data).items()):
        if t != RT_STRING:
            continue
        p = 0
        for k in range(16):
            n = struct.unpack_from("<H", raw, p)[0]
            p += 2
            if n:
                out[(block - 1) * 16 + k] = raw[p:p + 2 * n].decode("utf-16-le")
            p += 2 * n
    return out


def _win_cell(ttf):
    """usWinAscent + usWinDescent and unitsPerEm of a TrueType file."""
    with open(ttf, "rb") as f:
        data = f.read()
    ntables = struct.unpack_from(">H", data, 4)[0]
    tables = {}
    for i in range(ntables):
        tag, _, off, _ = struct.unpack_from(">4sIII", data, 12 + i * 16)
        tables[tag] = off
    upem = struct.unpack_from(">H", data, tables[b"head"] + 18)[0]
    asc, desc = struct.unpack_from(">HH", data, tables[b"OS/2"] + 74)
    return asc, desc, upem


def build_font(ttf, chars):
    """(atlas image, metrics dict) for the characters, rendered at RENDER_SIZE."""
    font = ImageFont.truetype(ttf, RENDER_SIZE)
    asc, _, upem = _win_cell(ttf)
    scale = RENDER_SIZE / upem
    glyphs, x, y, row = [], PAD, PAD, 0
    boxes = []
    for ch in sorted(set(chars)):
        if ch in "\r\n":
            continue
        # Boxes are relative to the cell top (the win ascent above the baseline).
        l, t, r, b = font.getbbox(ch, anchor="ls")
        w, h = max(r - l, 0), max(b - t, 0)
        if x + w + PAD > ATLAS_WIDTH:
            x, y, row = PAD, y + row + PAD, 0
        boxes.append((ch, x, y, w, h, l, t))
        x += w + PAD
        row = max(row, h)
    height = 1
    while height < y + row + PAD:
        height *= 2
    alpha = Image.new("L", (ATLAS_WIDTH, height), 0)
    draw = ImageDraw.Draw(alpha)
    for ch, gx, gy, w, h, l, t in boxes:
        if w and h:
            draw.text((gx - l, gy - t), ch, font=font, fill=255, anchor="ls")
        glyphs.append({"c": ord(ch), "x": gx, "y": gy, "w": w, "h": h, "ox": l,
                       "oy": round(asc * scale) + t, "adv": font.getlength(ch)})
    img = Image.merge("RGBA", (*(Image.new("L", alpha.size, 255),) * 3, alpha))
    meta = {"size": RENDER_SIZE, "ascent": asc * scale,
            "width": ATLAS_WIDTH, "height": height, "glyphs": glyphs}
    return img, meta


def _point(value):
    """A layout point as layout.txt writes it, "(x,y)"."""
    return [int(v) for v in str(value).strip("() ").split(",")]


def subtitle_layout(extracted):
    """The dialogue subtitles' look and place (layout.txt [Subtitle], read by CHUDSubtitles): the font
    number (0, the HUD font), size in pixels, colour, the box's lines, and its top-left corner and width
    in 640x480 layout units, in play (FullScreenPos/FullScreenWidth) and while a scene camera is on
    (Pos/Width). LineScrollTime is there too but subtitles don't read it."""
    s = butes.load(os.path.join(extracted, "attributes", "layout.txt"))["Subtitle"]
    return {"font": s["font"], "fontSize": s["fontsize"], "numLines": s["numlines"], "color": s["textcolor"],
            "playPos": _point(s["fullscreenpos"]), "playWidth": s["fullscreenwidth"],
            "cinematicPos": _point(s["pos"]), "cinematicWidth": s["width"]}


def iocam_layout(extracted):
    """The IO camera's inset (layout.txt [Miscellaneous] IOCameraRect, IOCameraFOVX/Y, read by cshell.dll at
    0x100a7200) and its HUD frame ([IONodeCam], CHUDIOCamera), in 640x480 layout units, as the viewer's IOCamLayout
    names them. Piece2MaxFlicker is spelt so in the file."""
    layout = butes.load(os.path.join(extracted, "attributes", "layout.txt"))
    m, c = layout["Miscellaneous"], layout["IONodeCam"]
    return {"rect": _point(m["iocamerarect"]), "fovX": float(m["iocamerafovx"]), "fovY": float(m["iocamerafovy"]),
            "center": _point(c["center"]),
            "piece1Tex": butes.norm(c["piece1tex"]), "piece1MinAlpha": c["piece1minalpha"],
            "piece1MaxAlpha": c["piece1maxalpha"], "piece1Period": c["piece1period"], "piece1Radius": c["piece1radius"],
            "piece2Tex": butes.norm(c["piece2tex"]), "piece2MinInterval": c["piece2mininterval"],
            "piece2MaxInterval": c["piece2maxinterval"], "piece2MinRadius": c["piece2minradius"],
            "piece2MaxRadius": c["piece2maxradius"], "piece2MinFlickers": c["piece2minflickers"],
            "piece2MaxFlickers": c["piece2maxflicker"], "piece2FlickerTime": c["piece2flickertime"]}


def export_hud(extracted, out_root):
    """Writes <out_root>/hud/{strings.json, font.png, font.json, subtitles.json, iocam.json} and the HUD's sound
    files.
    Returns (strings, glyphs, sound files exported)."""
    out = os.path.join(out_root, "hud")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "subtitles.json"), "w") as f:
        json.dump(subtitle_layout(extracted), f, separators=(",", ":"))
    with open(os.path.join(out, "iocam.json"), "w") as f:
        json.dump(iocam_layout(extracted), f, separators=(",", ":"))
    strings = read_strings(os.path.join(extracted, "cres.dll"))
    ids = sorted(strings)
    with open(os.path.join(out, "strings.json"), "w", encoding="utf-8") as f:
        json.dump({"ids": ids, "texts": [strings[i] for i in ids]}, f, ensure_ascii=False, separators=(",", ":"))
    chars = {chr(c) for c in range(32, 127)} | {chr(c) for c in range(160, 256)}
    for s in strings.values():
        chars.update(s)
    img, meta = build_font(os.path.join(extracted, FONT), chars)
    img.save(os.path.join(out, "font.png"))
    with open(os.path.join(out, "font.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    bute = sounds.soundbutes(extracted)
    files = list(HUD_SOUNDS) + [p for name in HUD_SOUNDBUTES for p in bute.files(name)]
    exported = [rel for rel in (butes.norm(p) for p in files) if sounds.export_file(extracted, rel, out_root)]
    return strings, meta["glyphs"], exported
