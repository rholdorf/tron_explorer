"""PROTOTYPE (#99): builds the comparison page from the run.sh captures. python -I build_page.py <ssao dir> <out.html>"""
import base64, io, json, re, sys
from pathlib import Path
import numpy as np
from PIL import Image

G, OUT = Path(sys.argv[1]), Path(sys.argv[2])
HERE = Path(__file__).parent
VIS = [("off", "sem SSAO"), ("subtle", "sutil"), ("subtlehalfmed", "sutil, ½ res, amostras médias"),
       ("subtlecheap", "sutil, ½ res, poucas amostras"), ("subtlehalfgauss", "sutil, ½ res, gaussiano"),
       ("cheap", "médio, ½ res"), ("cheapstrong", "forte, ½ res"), ("medium", "médio"), ("strong", "forte"), ("after", "depois do opaco")]
BENCH_NAMES = {"off": "sem SSAO", "subtle": "sutil (0,5 · 0,3 m)", "medium": "médio (1 · 0,5 m)", "strong": "forte (2 · 1 m)",
               "after": "depois do opaco", "cheap": "médio, ½ res", "cheapstrong": "forte, ½ res",
               "bench-off": "sem SSAO", "bench-medium": "médio", "bench-medium-cheap": "médio, ½ res",
               "bench-strong-cheap": "forte, ½ res", "subtlecheap": "sutil, ½ res, poucas amostras",
               "subtlehalfmed": "sutil, ½ res, amostras médias", "subtlehalfgauss": "sutil, ½ res, gaussiano",
               "bench-subtle": "sutil", "bench-subtle-cheap": "sutil, ½ res, poucas amostras",
               "bench-subtle-halfmed": "sutil, ½ res, amostras médias", "bench-subtle-halfgauss": "sutil, ½ res, gaussiano"}
STACK = {"off": "bench-off", "subtle": "bench-subtle", "subtlehalfmed": "bench-subtle-halfmed", "subtlecheap": "bench-subtle-cheap",
         "subtlehalfgauss": "bench-subtle-halfgauss", "cheap": "bench-medium-cheap", "cheapstrong": "bench-strong-cheap",
         "medium": "bench-medium"}   # tile ms: the whole remaster with that SSAO
STILLS = ["intro/40.0", "intro/20.0", "m01-01/3.0", "m02-04/3.0", "m05-01/3.0", "m10-04/3.0"]
CW, CH = 480, 300

def b64(im, fmt="WEBP", **kw):
    buf = io.BytesIO(); im.save(buf, fmt, **kw)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()

def lum(im): return np.asarray(im.convert("RGB")).astype(float).sum(2)

def ratio(a, b): return Image.fromarray((np.clip((lum(b) + 3) / (lum(a) + 3), 0, 1) * 255).astype(np.uint8)).convert("RGB")

def best_box(a, b):
    d = np.maximum(lum(a) - lum(b), 0)[:1700]          # skip the subtitle band
    ii = d.cumsum(0).cumsum(1)
    best, at = -1, (0, 0)
    for y in range(0, d.shape[0] - CH, 20):
        for x in range(0, d.shape[1] - CW, 20):
            s = ii[y + CH - 1, x + CW - 1] - ii[y, x + CW - 1] - ii[y + CH - 1, x] + ii[y, x]
            if s > best: best, at = s, (x, y)
    return (*at, at[0] + CW, at[1] + CH)

bench = {}
for line in (G / "bench.txt").read_text().splitlines():
    tag = line.split()[0]
    m = re.search(r"avg=([\d.]+)ms.*p95=([\d.]+)ms", line)
    bench.setdefault(tag, []).append((float(m[1]), float(m[2])))
avg = {t: (sum(a for a, _ in v) / len(v), sum(p for _, p in v) / len(v)) for t, v in bench.items()}

data = {"rows": [{"k": k, "label": l, "avg": round(avg[STACK[k]][0], 2) if k in STACK else None} for k, l in VIS],
        "bench": [{"group": "fiel + SSAO", "label": BENCH_NAMES[t], "avg": round(avg[t][0], 2), "p95": round(avg[t][1], 2)}
                  for t in ["off", "cheap", "cheapstrong", "subtle", "medium", "strong", "after"] if t in avg]
               + [{"group": "remaster (MSAA 4x + glow 512²)", "label": BENCH_NAMES[t], "avg": round(avg[t][0], 2), "p95": round(avg[t][1], 2)}
                  for t in ["bench-off", "bench-subtle-halfmed", "bench-subtle-cheap", "bench-subtle-halfgauss", "bench-subtle",
                            "bench-medium-cheap", "bench-strong-cheap", "bench-medium"]],
        "views": [], "still": {}, "ratio_still": {}, "anims": {}, "ratio_anims": {}}

# motion: intro 21 s, the crop where the strong variant darkens most on the first frame
a0, s0 = Image.open(G / "off/seq-intro/f000.png"), Image.open(G / "strong/seq-intro/f000.png")
box = best_box(a0, s0)
data["views"].append(["move", "intro 21 s"])
for k, _ in VIS:
    fr = [Image.open(G / f"{k}/seq-intro/f{i:03}.png").convert("RGB").crop(box) for i in range(24)]
    fa = [Image.open(G / f"off/seq-intro/f{i:03}.png").convert("RGB").crop(box) for i in range(24)]
    data["anims"][f"0:{k}"] = b64(fr[0], save_all=True, append_images=fr[1:], duration=83, loop=0, quality=92)
    rr = [ratio(x, y) for x, y in zip(fa, fr)]
    data["ratio_anims"][f"0:{k}"] = b64(rr[0], save_all=True, append_images=rr[1:], duration=83, loop=0, quality=92)

for i, s in enumerate(STILLS):
    a, st = Image.open(G / f"off/{s}.png"), Image.open(G / f"strong/{s}.png")
    box = best_box(a, st)
    data["views"].append(["still", s.replace("/", " ").replace(".0", " s")])
    for k, _ in VIS:
        im = Image.open(G / f"{k}/{s}.png").convert("RGB")
        data["still"][f"{i}:{k}"] = b64(im.crop(box), "PNG")
        data["ratio_still"][f"{i}:{k}"] = b64(ratio(a.convert("RGB"), im).crop(box), "WEBP", quality=90)
    print(s, box, {k: round(lum(Image.open(G / f"{k}/{s}.png")).mean() / 3, 1) for k, _ in VIS})

notes = (HERE / "notes.html").read_text() if (HERE / "notes.html").exists() else ""
OUT.write_text((HERE / "template.html").read_text().replace("__NOTES__", notes).replace("__DATA__", json.dumps(data)))
print(OUT, OUT.stat().st_size // 1024, "KB")
