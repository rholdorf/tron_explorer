import sys, json, os, numpy as np
from PIL import Image, ImageDraw
S = sys.argv[1]; work = f'{S}/trial'; d = json.load(open(f'{work}/stats.json'))
COLS = ['nearest', 'bicubic', 'esr-anime', 'esr-av3', 'w2x-cunet', 'w2x-n3', 'bicubic-alpha', 'esr-anime_alpha-net', 'w2x-cunet_alpha-net']
C = 256; LAB = 18
def corner(img):  # tile 2x2, crop CxC centred on the wrap corner
    t = np.concatenate([np.concatenate([img, img], 1)] * 2, 0)
    H, W = img.shape[:2]; cy, cx = H, W
    h, w = min(C, 2 * H), min(C, 2 * W)
    return t[cy - h // 2: cy + h // 2, cx - w // 2: cx + w // 2]
cats = {}
for k, m in d['meta'].items(): cats.setdefault(m['cat'], []).append(k)
os.makedirs(f'{S}/sheets', exist_ok=True)
for cat, keys in cats.items():
    sheet = Image.new('RGB', (len(COLS) * (C + 4), LAB + len(keys) * (C + LAB + 4)), (40, 40, 40))
    dr = ImageDraw.Draw(sheet)
    for j, c in enumerate(COLS): dr.text((j * (C + 4) + 4, 3), c, fill=(255, 255, 255))
    for i, k in enumerate(keys):
        y = LAB + i * (C + LAB + 4); m = d['meta'][k]
        dr.text((4, y + 2), f"{m['name']}  {m['w']}x{m['h']}  fullbright={m['fb']}", fill=(255, 220, 120))
        for j, c in enumerate(COLS):
            a = np.asarray(Image.open(f'{work}/out/{k}/{c}.png'))
            if a.ndim == 3: a = a[..., :3]
            tile = Image.fromarray(corner(a)).convert('RGB')
            sheet.paste(tile, (j * (C + 4), y + LAB))
    sheet.save(f'{S}/sheets/{cat}.png'); print(cat, sheet.size)
