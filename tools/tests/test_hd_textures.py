"""Remaster's HD textures (tools/hd_textures.py, #105): 2x the DTX, RGB through the upscaler, alpha bicubic per
channel, wrap-padded, written as an HD DTX the viewer's DtxLoader reads through its raw path. The core runs with a
stand-in for waifu2x (a bicubic 4x per channel); the real upscaler's tests skip without $WAIFU2X."""
import io
import os
import struct

import numpy as np
import pytest
from PIL import Image

import dtx
import hd_textures as hd

WAIFU2X = os.environ.get("WAIFU2X", "")
TILING = "tex/prototype/m07/crista/secm07b/floors/m07b_f03.dtx"   # the trial's seam case (#100)


def bicubic_net(src, dst):
    """Stand-in for waifu2x: every PNG 4x, bicubic per channel."""
    for f in os.listdir(src):
        a = np.asarray(Image.open(os.path.join(src, f)).convert("RGB"))
        Image.fromarray(hd.resize(a, (a.shape[1] * 4, a.shape[0] * 4), Image.BICUBIC)).save(os.path.join(dst, f))


def invert_net(src, dst):
    """A net that changes RGB beyond recognition: alpha must not follow it."""
    bicubic_net(src, dst)
    for f in os.listdir(dst):
        p = os.path.join(dst, f)
        Image.fromarray(255 - np.asarray(Image.open(p))).save(p)


def mip_sizes(w, h, n, block):
    return [max(1, (max(1, w >> m) + 3) // 4) * max(1, (max(1, h >> m) + 3) // 4) * block for m in range(n)]


def first(extracted, bpp, alpha=None):
    """A DTX of that BPP ident (and with / without alpha < 255), 16 to 256 px a side, not an effect texture."""
    for d, _, files in sorted(os.walk(extracted)):
        if hd.excluded(os.path.relpath(d, extracted).lower() + "/"):
            continue
        for f in sorted(files):
            if not f.endswith(".dtx"):
                continue
            p = os.path.join(d, f)
            data = open(p, "rb").read(dtx.HEADER)
            if len(data) < dtx.HEADER:
                continue
            w, h = struct.unpack_from("<HH", data, 8)
            if data[26] != bpp or max(w, h) > 256 or min(w, h) < 16:
                continue
            rel = os.path.relpath(p, extracted)
            if alpha is not None and bool((dtx.load(extracted, rel)[0][..., 3] < 255).any()) != alpha:
                continue
            return rel
    pytest.skip(f"no DTX with BPP ident {bpp}")


@pytest.mark.parametrize("bpp", [hd.DXT1, 5, hd.DXT5, 3])
def test_round_trip(extracted, tmp_path, bpp):
    """An HD DTX reads back through tools/dtx.py at twice the size, with the source's flags, extra bytes and
    command string, the HD BPP ident, a full mip chain sized as DtxLoader measures it, and pixels close to the
    2x image it encodes."""
    rel = first(extracted, bpp)
    src = open(os.path.join(extracted, rel), "rb").read()
    a, fullbright = dtx.load(extracted, rel)
    img = hd.upscale([a], bicubic_net, str(tmp_path / "work"))[0]
    data = hd.write_hd(src[:dtx.HEADER], img, bool((a[..., 3] < 255).any()))
    out = tmp_path / "hd" / rel
    out.parent.mkdir(parents=True)
    out.write_bytes(data)

    b, fb = dtx.load(str(tmp_path / "hd"), rel)
    w, h = struct.unpack_from("<HH", src, 8)
    assert b.shape == (h * 2, w * 2, 4) and fb == fullbright
    hw, hh, n, sections = struct.unpack_from("<HHHH", data, 8)
    assert (hw, hh, n, sections) == (w * 2, h * 2, max(w * 2, h * 2).bit_length(), 0)
    assert data[:8] == src[:8] and data[16:24] == src[16:24]                        # type, version, flags
    assert data[24:26] + data[27:36] == src[24:26] + src[27:36]                     # extra but the BPP ident
    assert data[26] == (hd.DXT1 if bpp == hd.DXT1 else hd.DXT5)
    assert hd.command(data) == hd.command(src) and data[36:164] == src[36:164]
    assert len(data) - dtx.HEADER == sum(mip_sizes(hw, hh, n, 8 if data[26] == hd.DXT1 else 16))
    mse = ((b[..., :3].astype(float) - img[..., :3]) ** 2).mean()
    assert 10 * np.log10(255 ** 2 / max(mse, 1e-9)) > 26   # Pillow's BC: 29 to 44 dB on the trial's samples


def test_mips_decode(extracted, tmp_path):
    """Each mip level decodes to the box-filtered level it was made from."""
    rel = first(extracted, hd.DXT5)
    a, _ = dtx.load(extracted, rel)
    img = hd.upscale([a], bicubic_net, str(tmp_path))[0]
    data = hd.write_hd(open(os.path.join(extracted, rel), "rb").read(dtx.HEADER), img, True)
    hw, hh, n = struct.unpack_from("<HHH", data, 8)
    off = dtx.HEADER
    for m, (level, size) in enumerate(zip(hd.mips(img), mip_sizes(hw, hh, n, 16))):
        lw, lh = max(1, hw >> m), max(1, hh >> m)
        assert level.shape[:2] == (lh, lw)
        bw, bh = (lw + 3) // 4 * 4, (lh + 3) // 4 * 4
        dec = np.asarray(Image.frombuffer("RGBA", (bw, bh), data[off:off + size], "bcn", 3))[:lh, :lw]
        assert np.abs(dec.astype(int) - level).mean() < 6, m
        off += size
    assert off == len(data)


def test_dxt1_cutout_keeps_holes(extracted, tmp_path):
    """DXT1 stays opaque unless the source has cut-out texels (none of the game's 667 DXT1 files does), which then
    stay holes (1-bit alpha)."""
    header = open(os.path.join(extracted, first(extracted, hd.DXT1)), "rb").read(dtx.HEADER)
    img = np.full((32, 32, 4), 200, np.uint8)
    img[..., 3] = 255
    img[:8, :8, 3] = 0
    for alpha in (True, False):
        (tmp_path / "x.dtx").write_bytes(hd.write_hd(header, img, alpha))
        b, _ = dtx.load(str(tmp_path), "x.dtx")
        assert (b[:8, :8, 3] == 0).all() == alpha and (b[8:, 8:, 3] == 255).all()


def test_alpha_is_per_channel_bicubic(tmp_path):
    """Alpha never goes through the net: with a net that inverts RGB it still matches bicubic 4x of the padded
    alpha, cropped and halved with Lanczos (within 1/255), and RGB where alpha is 0 keeps its colour (Pillow's
    RGBA resize would premultiply it to black)."""
    rng = np.random.default_rng(1)
    h, w = 64, 128
    y, x = np.mgrid[0:h, 0:w]
    a = np.zeros((h, w, 4), np.uint8)
    a[..., :3] = rng.integers(64, 255, (h, w, 3))
    a[..., 3] = np.where(x < w // 2, 0, (127 + 127 * np.sin(y * 2 * np.pi / h))).astype(np.uint8)
    out = hd.upscale([a], invert_net, str(tmp_path))[0]
    p, px, py = hd.wrap_pad(a)
    ref = np.asarray(Image.fromarray(np.ascontiguousarray(p[..., 3])).resize((p.shape[1] * 4, p.shape[0] * 4),
                                                                              Image.BICUBIC))
    ref = ref[py * 4:(py + h) * 4, px * 4:(px + w) * 4]
    ref = np.asarray(Image.fromarray(np.ascontiguousarray(ref)).resize((w * 2, h * 2), Image.LANCZOS))
    assert np.abs(out[..., 3].astype(int) - ref).max() <= 1
    clear = out[8:-8, 8:w - 8, 3] == 0
    assert clear.all() and out[8:-8, 8:w - 8, :3][clear].mean() > 60   # inverted 64..255: 0..191, not black


def psnr(a, b):
    mse = ((a.astype(float) - b) ** 2).mean()
    return 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def test_dxt5_alpha_beats_pillow():
    """The DXT5 alpha blocks (min/max endpoints, 8 levels, nearest index) beat Pillow's on gradients and edges by a
    clear margin, keep flat blocks and hard 0/255 edges exact, and leave Pillow's colour blocks as they were."""
    y, x = np.mgrid[0:64, 0:64]
    img = np.zeros((64, 64, 4), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = x * 4, y * 4, 128
    a = np.where(x < 32, x * 255 / 31, 0)                       # ramp, then a hard edge to 0
    a = np.where(y < 16, a, np.where(y < 32, (x + y) % 16 * 17, a))   # sharp sawtooth
    a[48:, :16] = 200                                            # flat blocks
    a[48:, 16:32] = np.where((x[48:, 16:32] + y[48:, 16:32]) % 2, 255, 0)   # 0/255 checker
    img[..., 3] = a.astype(np.uint8)
    ours = np.asarray(Image.frombuffer("RGBA", (64, 64), hd.encode(img, hd.DXT5, True), "bcn", 3))
    b = io.BytesIO()
    Image.fromarray(img).save(b, "DDS", pixel_format="DXT5")
    pil = np.asarray(Image.frombuffer("RGBA", (64, 64), b.getvalue()[128:], "bcn", 3))
    assert psnr(ours[..., 3], img[..., 3]) > psnr(pil[..., 3], img[..., 3]) + 6
    assert (ours[48:, :32, 3] == img[48:, :32, 3]).all()
    assert (ours[..., :3] == pil[..., :3]).all()
    for size in [(1, 1), (2, 2), (8, 2)]:     # small mips: one block per started 4x4
        assert len(hd.alpha_blocks(np.zeros(size[::-1], np.uint8))) == ((size[0] + 3) // 4) * ((size[1] + 3) // 4)


def edge_step(img):
    """The wrap edge's mean step (last column to first, last row to first) over the interior's mean step between
    the same pair of texels' halves (odd to even: at 2x the steps alternate within and between source texels)."""
    f = img[..., :3].astype(float)
    inner = (np.abs(np.diff(f, axis=1)[:, 1::2]).mean() + np.abs(np.diff(f, axis=0)[1::2]).mean()) / 2
    edge = (np.abs(f[:, -1] - f[:, 0]).mean() + np.abs(f[-1] - f[0]).mean()) / 2
    return edge / inner


def test_wrap_edge_without_seam(tmp_path):
    """A tiling texture's HD copy still tiles: the step across the wrap edge is an interior step. Unpadded, the
    upscaler's edge handling (here bicubic's clamp) leaves one."""
    rng = np.random.default_rng(2)
    a = np.zeros((32, 32, 4), np.uint8)
    a[..., :3] = rng.integers(0, 255, (32, 32, 3))
    a[..., 3] = 255
    out = hd.upscale([a], bicubic_net, str(tmp_path))[0]
    assert edge_step(out) < 1.3
    clamped = hd.resize(a, (64, 64), Image.BICUBIC)
    assert edge_step(clamped) > 1.6


@pytest.fixture(scope="module")
def net():
    if not os.access(WAIFU2X, os.X_OK):
        pytest.skip(f"waifu2x-ncnn-vulkan not found at {WAIFU2X} (set WAIFU2X)")
    return hd.waifu2x(WAIFU2X)


def test_waifu2x_tiling_texture(extracted, tmp_path, net):
    """The trial's tiling floor (#100) through waifu2x: twice the size, no seam at the wrap edge."""
    a, _ = dtx.load(extracted, TILING)
    out = hd.upscale([a], net, str(tmp_path))[0]
    assert out.shape == (a.shape[0] * 2, a.shape[1] * 2, 4)
    assert edge_step(out) < 1.5 * max(1.0, edge_step(a))


def test_step_skips_without_binary(capsys, tmp_path):
    """Without the binary the step writes nothing and says so."""
    assert hd.main([str(tmp_path), str(tmp_path), "--waifu2x", str(tmp_path / "none")]) == 0
    assert "skipped" in capsys.readouterr().out
    assert not (tmp_path / "textures_hd").exists()


def test_referenced_and_incremental(extracted, tmp_path):
    """The step takes the DTX paths in level.json (not fx/, not .spr), the EnvMaps their command strings name and
    the IO camera's frame, and skips textures whose HD file is newer than the DTX."""
    tex, env = None, None
    for d, _, files in sorted(os.walk(os.path.join(extracted, "tex"))):
        for f in sorted(files):
            p = os.path.join(d, f)
            links = hd.command_textures(hd.command(open(p, "rb").read(dtx.HEADER))) if f.endswith(".dtx") else []
            if links and os.path.isfile(os.path.join(extracted, links[0])) and os.path.getsize(p) < 100_000:
                tex, env = os.path.relpath(p, extracted), links[0]
                break
        if tex:
            break
    assert tex, "no texture with an EnvMap"
    level = tmp_path / "export" / "levels" / "x"
    level.mkdir(parents=True)
    (level / "level.json").write_text(
        '{"materials":[{"tex":"FX\\\\a.dtx"},{"tex":"Tex\\\\b.spr"},{"tex":"%s"}]}'
        % tex.upper().replace("/", "\\\\"))
    names = hd.referenced(extracted, str(tmp_path / "export"))
    assert {tex, env, *hd.HUD} == set(names)
    calls = []

    def counting(src, dst):
        calls.append(len(os.listdir(src)))
        bicubic_net(src, dst)
    s = hd.run(extracted, str(tmp_path / "export"), counting, log=lambda *_: None)
    assert s["written"] == len(names) and calls == [len(names)]
    assert os.path.isfile(tmp_path / "export" / "textures_hd" / tex)
    s = hd.run(extracted, str(tmp_path / "export"), counting, log=lambda *_: None)
    assert s["written"] == 0 and s["skipped"] == len(names) and len(calls) == 1
