"""Remaster's HD textures (#105, decided in #102): every DTX the exported levels draw, at twice its size, as an
HD DTX the viewer's DtxLoader reads through its raw path. Optional, after export_level.py:

    .venv/bin/python -I tools/hd_textures.py extracted export [level filter ...] [--waifu2x <binary>]

The upscaler is the user's waifu2x-ncnn-vulkan (20250915, MIT; `xattr -dr com.apple.quarantine` after download),
given by --waifu2x or $WAIFU2X, with its models-cunet folder beside the binary; without it the step says so and
writes nothing. Level filters match level paths as export_level.py's do. Writes <export>/textures_hd/<dtx path>
(the path as DtxLoader.Normalize gives it) and skips textures whose HD file is newer than the DTX.

Which textures: every DTX path in the exported levels' level.json (world materials, model skins, attachments,
effect models' skins, objects' texture properties), the EnvMap / DetailTex their command strings name, and the
IO camera's frame (interface/hud/ionode_hud.dtx, ionode_static.dtx). Not effect textures (an fx/ folder: no gain
in the trial, #100) and not sprites (.spr frames: sprites keep the DTX's size).

Pixels: the DTX's first mip, wrap-padded (16 texels, or the whole tile when the side is <= 64) so tiling edges
match. RGB only goes through waifu2x (cunet, noise 3, 4x, folder mode); alpha is bicubic as its own channel. The
4x result is cropped and halved to 2x with Lanczos, per channel: Pillow's RGBA resize premultiplies and blackens
RGB wherever alpha is 0, which on fullbright textures is the glow mask.

File: the source's 164-byte header and command string (flags, user flags, texture group, UI mip offset, detail
scale/angle, AlphaRef, EnvMap, ...) with doubled width and height, a full mip chain down to 1x1 (box filtered per
channel), no sections, and BPP ident 4 (DXT1, where the source is DXT1) or 6 (DXT5: DXT3 and BGRA32 sources too),
encoded with Pillow's DDS writer. Rows stay in the DTX's own order: row 0 of the raw data is row 0 here, as
LoadRawTextureData uploads it. Mip m is max(1, w >> m) x max(1, h >> m), in 4x4 blocks of 8 (DXT1) or 16 bytes.

Pillow's BC encoder is fast (milliseconds a texture) but plain: on 20 of m10-04's textures its RGB is 29 to 44 dB
PSNR against the uncompressed 2x image, 1 to 5 dB below a PCA + least-squares BC1 fit. Its DXT5 alpha was about
9 dB below block min/max endpoints, so the alpha blocks are this module's own (alpha_blocks) (#105).
"""
import glob
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import dtx  # noqa: E402

SCALE = 2           # the HD texture's size over the DTX's
NET_SCALE = 4       # waifu2x's
PAD = 16
HUD = ["interface/hud/ionode_hud.dtx", "interface/hud/ionode_static.dtx"]
DXT1, DXT5 = 4, 6   # BPP idents
BATCH_PIXELS = 8 << 20   # source texels (padded) per waifu2x run


def norm(path):
    return path.replace("\\", "/").strip().lower()


def excluded(path):
    return path.endswith(".spr") or path.startswith("fx/") or "/fx/" in path


def command(data):
    return data[36:164].split(b"\0")[0].decode("ascii", "replace")


def command_textures(cmd):
    """The textures a DTX command string links (EnvMap, EnvMapAlpha, DetailTex), as DtxLoader.ParseCommand."""
    out = []
    for part in cmd.split(";"):
        tok = part.split()
        if len(tok) >= 2 and tok[0].lower() in ("envmap", "envmapalpha", "detailtex"):
            out.append(norm(tok[1]))
    return out


def referenced(root, export_root, only=()):
    """Sorted DTX paths (normalised) the exported levels draw, as the module docstring says, that exist in root
    (and aren't empty)."""
    found = set(HUD)

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.strip().lower().endswith(".dtx"):
            found.add(norm(o))

    levels = os.path.join(export_root, "levels")
    for f in sorted(glob.glob(os.path.join(levels, "**", "level.json"), recursive=True)):
        rel = os.path.relpath(os.path.dirname(f), levels)
        if only and not any(s in rel for s in only):
            continue
        with open(f) as fp:
            walk(json.load(fp))
    out, todo = set(), sorted(p for p in found if not excluded(p))
    while todo:
        p = todo.pop()
        full = os.path.join(root, p)
        if p in out or excluded(p) or not os.path.isfile(full) or os.path.getsize(full) < dtx.HEADER:
            continue
        out.add(p)
        with open(full, "rb") as fp:
            todo += command_textures(command(fp.read(dtx.HEADER)))
    return sorted(out)


# --- pixels ---------------------------------------------------------------------------------------------------

def pad_of(n):
    return n if n <= 64 else PAD


def wrap_pad(a):
    """(padded array, px, py): a wrapped by pad_of texels on each side."""
    py, px = pad_of(a.shape[0]), pad_of(a.shape[1])
    return np.pad(a, ((py, py), (px, px), (0, 0)), mode="wrap"), px, py


def resize(a, size, f):
    """Each channel of a (h, w, c) uint8 array resized to size (w, h) on its own (never Pillow's RGBA resize)."""
    return np.dstack([np.asarray(Image.fromarray(np.ascontiguousarray(a[..., c])).resize(size, f))
                      for c in range(a.shape[2])])


def finish(rgb4, padded, px, py, w, h):
    """The 2x RGBA texture from the net's 4x RGB of the padded tile: alpha bicubic 4x per channel, both cropped,
    then halved with Lanczos per channel."""
    a = np.asarray(Image.fromarray(np.ascontiguousarray(padded[..., 3]))
                   .resize((padded.shape[1] * NET_SCALE, padded.shape[0] * NET_SCALE), Image.BICUBIC))
    full = np.dstack([rgb4[..., :3], a])[py * NET_SCALE:(py + h) * NET_SCALE, px * NET_SCALE:(px + w) * NET_SCALE]
    return resize(full, (w * SCALE, h * SCALE), Image.LANCZOS)


def upscale(images, net, work):
    """The 2x RGBA of each (h, w, 4) uint8 image; net(in_dir, out_dir) upscales every PNG in in_dir 4x (RGB) to
    the same name in out_dir. work: a scratch directory."""
    src, dst = os.path.join(work, "in"), os.path.join(work, "out")
    for d in (src, dst):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    pads = []
    for i, a in enumerate(images):
        p, px, py = wrap_pad(a)
        Image.fromarray(np.ascontiguousarray(p[..., :3])).save(os.path.join(src, f"{i}.png"), compress_level=1)
        pads.append((p, px, py))
    net(src, dst)

    def one(i):
        p, px, py = pads[i]
        rgb = np.asarray(Image.open(os.path.join(dst, f"{i}.png")).convert("RGB"))
        if rgb.shape[:2] != (p.shape[0] * NET_SCALE, p.shape[1] * NET_SCALE):
            raise ValueError(f"upscaler gave {rgb.shape[1]}x{rgb.shape[0]} for {p.shape[1]}x{p.shape[0]}")
        return finish(rgb, p, px, py, images[i].shape[1], images[i].shape[0])
    with ThreadPoolExecutor() as ex:
        out = list(ex.map(one, range(len(images))))
    shutil.rmtree(src)
    shutil.rmtree(dst)
    return out


def mips(img):
    """The full mip chain of an RGBA image, down to 1x1: each level the 2x2 box average of the one before."""
    out = [img]
    a = img.astype(np.float32)
    while a.shape[0] > 1 or a.shape[1] > 1:
        if a.shape[0] > 1:   # an odd side drops its last row, as max(1, h >> m) does
            a = (a[0:a.shape[0] // 2 * 2:2] + a[1::2]) * 0.5
        if a.shape[1] > 1:
            a = (a[:, 0:a.shape[1] // 2 * 2:2] + a[:, 1::2]) * 0.5
        out.append(np.clip(np.rint(a), 0, 255).astype(np.uint8))
    return out


# --- file -----------------------------------------------------------------------------------------------------

def alpha_blocks(a):
    """DXT5 alpha blocks (8 bytes each, blocks row by row) of a (h, w) uint8 alpha: endpoints a0 = the block's max,
    a1 = its min (a0 > a1: the 8-level palette a0, a1, (6 a0 + a1) / 7 ... (a0 + 6 a1) / 7), each texel the nearest
    level, 3-bit indices little-endian in texel order. A flat block is a0 = a1 with every index 0. A side that
    isn't a multiple of 4 is edge-padded (the padding is never sampled)."""
    h, w = a.shape
    a = np.pad(a, ((0, -h % 4), (0, -w % 4)), mode="edge")
    bh, bw = a.shape[0] // 4, a.shape[1] // 4
    b = a.reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(-1, 16).astype(np.int32)
    a0, a1 = b.max(1), b.min(1)
    i = np.arange(1, 7)
    levels = np.concatenate([a0[:, None], a1[:, None], ((7 - i) * a0[:, None] + i * a1[:, None]) / 7], 1)
    idx = np.abs(b[:, :, None] - levels[:, None, :]).argmin(2).astype(np.uint64)
    idx[a0 == a1] = 0
    bits = (idx << (np.arange(16, dtype=np.uint64) * 3)).sum(1, dtype=np.uint64)
    out = np.zeros((len(b), 8), np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for k in range(6):
        out[:, 2 + k] = (bits >> np.uint64(8 * k)) & np.uint64(0xFF)
    return out


def encode(level, bpp, alpha):
    """BC blocks of an RGBA level (DXT1 or DXT5 ident): colour from Pillow's DDS writer (the data after its 128-byte
    header), DXT5 alpha from alpha_blocks (Pillow's is ~9 dB worse). A DXT1 level keeps alpha only when the source
    had cut-out texels (alpha thresholded at 128)."""
    if bpp == DXT1:
        im = Image.fromarray(np.ascontiguousarray(level[..., :3]))
        if alpha:
            a = np.where(level[..., 3] >= 128, 255, 0).astype(np.uint8)
            im = Image.fromarray(np.dstack([level[..., :3], a]))
    else:
        im = Image.fromarray(np.ascontiguousarray(level))
    b = io.BytesIO()
    im.save(b, "DDS", pixel_format="DXT1" if bpp == DXT1 else "DXT5")
    data = b.getvalue()[128:]
    blocks = ((level.shape[1] + 3) // 4) * ((level.shape[0] + 3) // 4)
    assert len(data) == blocks * (8 if bpp == DXT1 else 16), "unexpected DDS data size"
    if bpp == DXT1:
        return data
    out = np.frombuffer(data, np.uint8).reshape(-1, 16).copy()
    out[:, :8] = alpha_blocks(level[..., 3])
    return out.tobytes()


def hd_bpp(src_bpp):
    return DXT1 if src_bpp == DXT1 else DXT5


def write_hd(src_header, img, alpha):
    """HD DTX bytes: src_header (the source's first 164 bytes) with img's size, its full mip chain, no sections and
    the HD BPP ident; then each level's blocks. alpha: the source has texels with alpha < 255 (DXT1 cut-outs)."""
    h, w = img.shape[:2]
    if w % 4 or h % 4:
        raise ValueError(f"HD size {w}x{h} not a multiple of 4")
    bpp = hd_bpp(src_header[26])
    levels = mips(img)
    head = bytearray(src_header[:dtx.HEADER])
    struct.pack_into("<HHHH", head, 8, w, h, len(levels), 0)
    head[26] = bpp
    return bytes(head) + b"".join(encode(m, bpp, alpha) for m in levels)


# --- the step -------------------------------------------------------------------------------------------------

def waifu2x(binary):
    """net() for upscale(): waifu2x-ncnn-vulkan cunet, noise 3, 4x, on a folder."""
    models = os.path.join(os.path.dirname(binary), "models-cunet")

    def net(src, dst):
        r = subprocess.run([binary, "-i", src, "-o", dst, "-n", "3", "-s", str(NET_SCALE), "-f", "png", "-m", models],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"waifu2x failed ({r.returncode}): {r.stderr[-2000:]}")
    return net


def stale(src, dst):
    return not os.path.exists(dst) or os.path.getmtime(dst) <= os.path.getmtime(src)


def run(root, export_root, net, only=(), log=lambda m: print(m, flush=True)):
    """Writes the HD textures the module docstring describes; returns {"textures", "written", "skipped" (up to
    date), "failed" (not written), "bytes" (all of them on disk), "seconds", "net_seconds"}."""
    t0 = time.time()
    out_root = os.path.join(export_root, "textures_hd")
    names = referenced(root, export_root, only)
    todo = [n for n in names if stale(os.path.join(root, n), os.path.join(out_root, n))]
    stats = {"textures": len(names), "written": 0, "skipped": len(names) - len(todo), "failed": 0, "bytes": 0,
             "net_seconds": 0.0}
    batches, cur, size = [], [], 0
    for n in todo:
        with open(os.path.join(root, n), "rb") as fp:
            w, h = struct.unpack_from("<HH", fp.read(12), 8)
        cur.append(n)
        size += (w + 2 * pad_of(w)) * (h + 2 * pad_of(h))
        if size >= BATCH_PIXELS:
            batches.append(cur)
            cur, size = [], 0
    if cur:
        batches.append(cur)

    def timed(src, dst):
        t = time.time()
        net(src, dst)
        stats["net_seconds"] += time.time() - t
    with tempfile.TemporaryDirectory(prefix="hd_textures_") as work:
        for bi, batch in enumerate(batches):
            srcs, images = [], []
            for n in batch:
                with open(os.path.join(root, n), "rb") as fp:
                    srcs.append(fp.read(dtx.HEADER))
                images.append(dtx.load(root, n)[0])
            hd = upscale(images, timed, work)

            def save(i):
                dst = os.path.join(out_root, batch[i])
                try:
                    data = write_hd(srcs[i], hd[i], bool((images[i][..., 3] < 255).any()))
                except ValueError as e:
                    log(f"{batch[i]}: {e}, not written")
                    return 0
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst + ".tmp", "wb") as fp:
                    fp.write(data)
                os.replace(dst + ".tmp", dst)
                return len(data)
            with ThreadPoolExecutor() as ex:
                sizes = list(ex.map(save, range(len(batch))))
            stats["written"] += sum(1 for s in sizes if s)
            stats["failed"] += sum(1 for s in sizes if not s)
            log(f"batch {bi + 1}/{len(batches)}: {len(batch)} textures, {time.time() - t0:.0f}s")
    for n in names:
        p = os.path.join(out_root, n)
        if os.path.exists(p):
            stats["bytes"] += os.path.getsize(p)
    stats["seconds"] = time.time() - t0
    return stats


def main(argv):
    args, binary = [], os.environ.get("WAIFU2X", "")
    i = 0
    while i < len(argv):
        if argv[i] == "--waifu2x":
            binary = argv[i + 1]
            i += 2
        else:
            args.append(argv[i])
            i += 1
    if len(args) < 2:
        print(__doc__)
        return 2
    root, export_root, only = args[0], args[1], args[2:]
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        print(f"HD textures skipped: no waifu2x-ncnn-vulkan binary ({binary or 'set --waifu2x or $WAIFU2X'})")
        return 0
    if not os.path.isdir(os.path.join(os.path.dirname(binary), "models-cunet")):
        print(f"HD textures skipped: no models-cunet beside {binary}")
        return 0
    s = run(root, export_root, waifu2x(binary), only)
    print(f"HD textures: {s['textures']} referenced, {s['written']} written, {s['skipped']} up to date, "
          f"{s['failed']} not written, {s['bytes'] / 1e6:.0f} MB in textures_hd, {s['seconds']:.0f}s "
          f"(waifu2x {s['net_seconds']:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
