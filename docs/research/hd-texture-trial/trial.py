"""Trial 4x upscale of representative DTX textures (#100). Run from the repo root with .venv/bin/python -I."""
import os, sys, time, subprocess, json, shutil
sys.path.insert(0, 'tools'); import dtx
import numpy as np
from PIL import Image, ImageDraw

S = sys.argv[1]
ESR = f'{S}/bin/esr2/realesrgan-ncnn-vulkan'
W2X = [p for p in __import__('glob').glob(f'{S}/bin/w2x/*/waifu2x-ncnn-vulkan')][0]
SET = {
 'world': ['tex/prototype/m07/crista/secm07b/floors/m07b_f03.dtx', 'tex/prototype/m01/geoff/data2m01_l/walls/labwall04.dtx',
           'tex/prototype/prefab/m06/m06grid09.dtx'],
 'glow':  ['tex/prototype/m09/geoff/firewall09k/walls/firewallm09_w20.dtx', 'tex/prototype/global/dblockbaseorange.dtx',
           'tex/prototype/m10/geoff/shipq/lights/m10q_l19.dtx', 'tex/prototype/m04/courtney/routerm04x/trim/m04x_t07.dtx'],
 'models':['chars/skins/jet_head_orange.dtx', 'chars/skins/tronhead_green.dtx', 'chars/skins/lightcyclist_torso_cyan.dtx',
           'props/skins/socket_face_1p.dtx'],
 'effects':['fx/tex/white_ring_add_1.dtx', 'fx/tex/byte_spark.dtx', 'fx/tex/digicubes_14.dtx'],
 'hud':   ['interface/hud/tronnumber_0.dtx', 'interface/hud/helpimages/helpimg_hogs.dtx',
           'interface/hud/reticle_psets_full_5.dtx', 'interface/hud/pset_icon_2.dtx'],
}
METHODS = {
 'esr-anime': lambda i, o: [ESR, '-i', i, '-o', o, '-n', 'realesrgan-x4plus-anime', '-s', '4', '-f', 'png', '-m', f'{S}/bin/esr2/models'],
 'esr-av3':   lambda i, o: [ESR, '-i', i, '-o', o, '-n', 'realesr-animevideov3', '-s', '4', '-f', 'png', '-m', f'{S}/bin/esr2/models'],
 'w2x-n3': lambda i, o: [W2X, '-i', i, '-o', o, '-n', '3', '-s', '4', '-f', 'png',
                            '-m', os.path.join(os.path.dirname(W2X), 'models-cunet')],
 'w2x-cunet': lambda i, o: [W2X, '-i', i, '-o', o, '-n', '1', '-s', '4', '-f', 'png',
                            '-m', os.path.join(os.path.dirname(W2X), 'models-cunet')],
}
X = 4

def pad_of(n):  # wrap pad per axis: whole tile when tiny, else 16 texels
    return n if n <= 64 else 16

work = f'{S}/trial'; shutil.rmtree(work, ignore_errors=True)
for d in ('in_rgba', 'in_alpha', 'src'): os.makedirs(f'{work}/{d}')
meta = {}
for cat, names in SET.items():
    for n in names:
        a, fb = dtx.load('extracted', n)
        h, w = a.shape[:2]; py, px = pad_of(h), pad_of(w)
        key = f'{cat}__{os.path.basename(n)[:-4]}'
        meta[key] = dict(name=n, w=w, h=h, fb=fb, py=py, px=px, cat=cat)
        Image.fromarray(a).save(f'{work}/src/{key}.png')
        p = np.pad(a, ((py, py), (px, px), (0, 0)), mode='wrap')
        Image.fromarray(p).save(f'{work}/in_rgba/{key}.png')
        al = np.repeat(p[..., 3:4], 3, axis=2)  # alpha as grey RGB, through the net
        Image.fromarray(al).save(f'{work}/in_alpha/{key}.png')

timing = {}
for m, cmd in METHODS.items():
    for src in ('in_rgba', 'in_alpha'):
        out = f'{work}/{m}_{src}'; os.makedirs(out)
        t = time.time(); r = subprocess.run(cmd(f'{work}/{src}', out), capture_output=True, text=True)
        timing[f'{m}/{src}'] = round(time.time() - t, 2)
        if r.returncode: print(m, src, r.stderr[-800:])
# per-file timing on the biggest and smallest for the record
for m, cmd in METHODS.items():
    for key in ('glow__firewallm09_w20', 'glow__m04x_t07'):
        t = time.time(); subprocess.run(cmd(f'{work}/in_rgba/{key}.png', f'{work}/one.png'), capture_output=True)
        timing[f'{m}/one/{key}'] = round(time.time() - t, 2)

def crop(img, k):
    m = meta[k]; y, x = m['py'] * X, m['px'] * X
    return img[y:y + m['h'] * X, x:x + m['w'] * X]

def bicubic(a, k):
    m = meta[k]
    size = ((m['w'] + 2 * m['px']) * X, (m['h'] + 2 * m['py']) * X)  # per channel: Pillow premultiplies RGBA
    return np.dstack([np.asarray(Image.fromarray(np.ascontiguousarray(a[..., c])).resize(size, Image.BICUBIC)) for c in range(4)])

results = {}
for k, m in meta.items():
    padded = np.asarray(Image.open(f'{work}/in_rgba/{k}.png'))
    res = {'nearest': np.asarray(Image.open(f'{work}/src/{k}.png').resize((m['w'] * X, m['h'] * X), Image.NEAREST)),
           'bicubic': crop(bicubic(padded, k), k)}
    for meth in METHODS:
        rgba = np.asarray(Image.open(f'{work}/{meth}_in_rgba/{k}.png').convert('RGBA'))
        alnet = np.asarray(Image.open(f'{work}/{meth}_in_alpha/{k}.png').convert('L'))
        res[meth] = crop(rgba, k)
        res[meth + ':alpha-net'] = crop(alnet, k)
    res['bicubic-alpha'] = crop(bicubic(padded, k), k)[..., 3]
    results[k] = res
    os.makedirs(f'{work}/out/{k}', exist_ok=True)
    for mk, v in res.items(): Image.fromarray(v).save(f'{work}/out/{k}/{mk.replace(":", "_")}.png')

# seam metric: mean abs step across the wrap edge vs a typical interior step, per method
def seam(img):
    rgb = img[..., :3].astype(float)
    edge = (np.abs(rgb[:, 0] - rgb[:, -1]).mean() + np.abs(rgb[0] - rgb[-1]).mean()) / 2
    inner = (np.abs(np.diff(rgb, axis=1)).mean() + np.abs(np.diff(rgb, axis=0)).mean()) / 2
    return round(edge / max(inner, 1e-6), 2)

# alpha agreement: CLI's own (bicubic inside ncnn) vs Pillow bicubic vs alpha through the net
stats = {}
for k, res in results.items():
    s = {'seam': {mk: seam(res[mk]) for mk in ('bicubic', *METHODS)}}
    b = res['bicubic-alpha'].astype(float)
    for meth in METHODS:
        cli = res[meth][..., 3].astype(float); net = res[meth + ':alpha-net'].astype(float)
        s[meth] = dict(cli_vs_bicubic=round(np.abs(cli - b).mean(), 2), net_vs_bicubic=round(np.abs(net - b).mean(), 2),
                       net_vs_bicubic_max=int(np.abs(net - b).max()))
    stats[k] = s

# unpadded control: does skipping the wrap pad seam?
os.makedirs(f'{work}/nopad_in'); os.makedirs(f'{work}/nopad_out')
for k in ('world__m07b_f03', 'world__m06grid09', 'world__labwall04'):
    shutil.copy(f'{work}/src/{k}.png', f'{work}/nopad_in/')
subprocess.run(METHODS['esr-anime'](f'{work}/nopad_in', f'{work}/nopad_out'), capture_output=True)
for k in ('world__m07b_f03', 'world__m06grid09', 'world__labwall04'):
    stats[k]['seam']['esr-anime-nopad'] = seam(np.asarray(Image.open(f'{work}/nopad_out/{k}.png').convert('RGBA')))

json.dump(dict(meta=meta, timing=timing, stats=stats), open(f'{work}/stats.json', 'w'), indent=1, default=str)
print(json.dumps(timing, indent=1))
