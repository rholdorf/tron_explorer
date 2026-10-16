"""PROTOTYPE, throwaway (map #41, ticket #43): a contact sheet of one level's world textures, for the user to
assign texture classes. One row per texture: the image, a top-down plan with its triangles highlighted,
counts, surface families, BlendMode, height above the level's lowest floor, and a proposed class from the
folder name. The page lets the user change each class and copy the resulting table as JSON.

Output is the game's textures: written under export/, never committed, never published.

Usage: python -I tools/prototype_texture_sheet.py extracted retailsingleplayer/m01-01"""
import base64
import collections
import html
import io
import json
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
import dat85  # noqa: E402
import surfaces  # noqa: E402
from baseline import METRES  # noqa: E402

CLASSES = ["structure", "trim", "light", "glass", "energy", "screen", "panel", "console", "furniture", "tool"]
RULES = [   # folder or name fragment -> proposed class, first match wins
    ("occluder", "tool"), ("blocker", "tool"), ("tex\\prefab.dtx", "tool"),
    ("\\lights\\", "light"), ("lightstrip", "light"), ("[light", "light"), ("blinker", "light"),
    ("\\glass\\", "glass"), ("window", "glass"),
    ("\\energy\\", "energy"), ("forcefield", "energy"), ("\\forcefields\\", "energy"),
    ("\\displays\\", "screen"), ("sign_", "screen"), ("static", "screen"), ("fx\\spr\\", "screen"),
    ("\\details\\", "panel"), ("\\detail\\", "panel"), ("digital_wall", "panel"), ("datablocks", "panel"),
    ("socket", "console"), ("transporter", "console"),
    ("\\trim\\", "trim"),
]


def propose(name):
    for frag, cls in RULES:
        if frag in name:
            return cls
    return "structure"


def dtx_image(root, name):
    """First mip of a DTX (or a sprite's first frame) as an RGBA PIL image, plus the fullbright flag."""
    path = os.path.join(root, name.replace("\\", "/").lower())
    if not os.path.exists(path):
        return None, False
    data = open(path, "rb").read()
    if path.endswith(".spr"):
        n = struct.unpack_from("<I", data, 0)[0]
        if not n:
            return None, False
        ln = struct.unpack_from("<H", data, 20)[0]
        return dtx_image(root, data[22:22 + ln].decode("ascii"))
    w, h = struct.unpack_from("<HH", data, 8)
    flags = struct.unpack_from("<i", data, 16)[0]
    bpp = data[26]
    body = data[164:]
    if bpp in (0, 3):
        img = Image.frombuffer("RGBA", (w, h), body[:w * h * 4], "raw", "BGRA", 0, 1)
    else:
        n = {4: 1, 5: 2, 6: 3}[bpp]
        size = (w // 4) * (h // 4) * (8 if n == 1 else 16)
        img = Image.frombuffer("RGBA", (w, h), body[:size], "bcn", n)
    return img.copy(), bool(flags & 1)


def pose(idx, area, fn, cent, level_c, i, fov=60.0):
    """A camera pose (viewer/Unity coordinates: metres, Y up) looking at the texture's biggest patch: the
    triangles of it within 4 m of its largest triangle that face roughly the same way."""
    seed = idx[np.argmax(area[idx])]
    patch = idx[(np.linalg.norm(cent[idx] - cent[seed], axis=1) < 4.0) & ((fn[idx] @ fn[seed]) > 0.7)]
    wgt = area[patch] + 1e-9
    target = (cent[patch] * wgt[:, None]).sum(0) / wgt.sum()
    n = (fn[patch] * wgt[:, None]).sum(0)
    n = n / max(np.linalg.norm(n), 1e-9) if np.linalg.norm(n) > 1e-6 else fn[seed]
    radius = max(np.linalg.norm(cent[patch] - target, axis=1).max(), 0.3)
    d = float(np.clip(1.4 * radius / np.tan(np.radians(fov / 2)), 4.0, 9.0))
    up = np.array([0.0, 1.0, 0.0])
    if abs(n[1]) < 0.7:
        dir_ = n + 0.25 * up
    else:   # floor or ceiling: look at it obliquely, from the side of the level's centre
        h = level_c - target
        h[1] = 0
        h = h / np.linalg.norm(h) if np.linalg.norm(h) > 1e-6 else np.array([1.0, 0, 0])
        dir_ = 0.75 * np.sign(n[1]) * up + 0.66 * h
    dir_ /= np.linalg.norm(dir_)
    eye = target + dir_ * d
    return {"i": i, "target": [round(float(x), 3) for x in target], "eye": [round(float(x), 3) for x in eye],
            "normal": [round(float(x), 3) for x in n], "fov": fov}


def png_uri(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    root, level = sys.argv[1], sys.argv[2]
    w = dat85.load(os.path.join(root, "worlds", level + ".dat"))
    v, vn, texs, modes = surfaces.world_triangles(w)
    fams, _ = surfaces.classify(w)
    v = v * METRES
    area = 0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1)
    names = np.array([t.lower() for t in texs], object)
    fn = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    fn[(fn * vn).sum(1) < 0] *= -1
    fn /= np.maximum(np.linalg.norm(fn, axis=1), 1e-12)[:, None]
    cent = v.mean(1)
    level_c = cent.mean(0)
    poses = []
    is_floor = np.isin(fams, ["floor-interior", "floor-exterior"])
    floor_y = np.percentile(v[is_floor][:, :, 1], 1)

    S = 300
    lo, hi = v[:, :, [0, 2]].reshape(-1, 2).min(0), v[:, :, [0, 2]].reshape(-1, 2).max(0)
    scale = (S - 8) / (hi - lo).max()

    def plan_xy(tri):
        p = (tri[:, [0, 2]] - lo) * scale + 4
        return [(float(x), float(S - y)) for x, y in p]

    base = Image.new("RGB", (S, S), (24, 26, 32))
    d = ImageDraw.Draw(base)
    for tri in v[fams != "wall"]:
        d.polygon(plan_xy(tri), fill=(52, 56, 66))

    rows = []
    for name, n in collections.Counter(names).most_common():
        sel = names == name
        img, fullbright = dtx_image(root, name) if name else (None, False)
        thumb = None
        if img is not None:
            img.thumbnail((256, 256))
            thumb = png_uri(img)
            mean = np.asarray(img.convert("RGB"), np.float32).reshape(-1, 3).mean(0) / 255
        plan = base.copy()
        dp = ImageDraw.Draw(plan)
        for tri in v[sel]:
            dp.polygon(plan_xy(tri), fill=(255, 140, 30), outline=(255, 140, 30))
        # Zoomed plan: the texture's own extent (at least 12 m), the rest of the level faint around it.
        xz = v[sel][:, :, [0, 2]].reshape(-1, 2)
        c, half = (xz.min(0) + xz.max(0)) / 2, max(6.0, (xz.max(0) - xz.min(0)).max() / 2 * 1.15)
        zs = (S - 8) / (2 * half)
        near = np.all(np.abs(v[:, :, [0, 2]] - c).max(2) < half * 1.5, axis=1)
        zoom = Image.new("RGB", (S, S), (24, 26, 32))
        dz = ImageDraw.Draw(zoom)

        def zxy(tri):
            p = (tri[:, [0, 2]] - c) * zs + S / 2
            return [(float(x), float(S - y)) for x, y in p]
        for tri, fam in zip(v[near & ~sel], fams[near & ~sel]):
            dz.polygon(zxy(tri), fill=None if fam == "wall" else (52, 56, 66),
                       outline=(90, 96, 110) if fam == "wall" else None)
        for tri in v[sel]:
            dz.polygon(zxy(tri), fill=(255, 140, 30), outline=(255, 180, 80))
        # Height above the local floor: the highest nearby floor at or below the texture's lowest point.
        ymin = v[sel][:, :, 1].min()
        fy = v[near & is_floor & ~sel][:, :, 1].max(1)
        fy = fy[fy <= ymin + 0.05]
        y = v[sel][:, :, 1] - (fy.max() if len(fy) else floor_y)
        poses.append(pose(np.flatnonzero(sel), area, fn, cent, level_c, len(rows)) | {"texture": name})
        rows.append({
            "name": name or "(no texture)", "tris": int(n), "area": round(float(area[sel].sum()), 1),
            "families": dict(collections.Counter(fams[sel]).most_common()),
            "blend": dict(collections.Counter(modes[sel]).most_common()),
            "height": [round(float(y.min()), 1), round(float(y.max()), 1)],
            "fullbright": fullbright, "thumb": thumb, "plan": png_uri(plan), "zoom": png_uri(zoom), "span": round(2 * half),
            "mean": [round(float(c), 2) for c in mean] if img is not None else None,
            "proposed": propose(name),
        })

    out = os.path.join("export", "prototype", os.path.basename(level) + "-texture-classes.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(PAGE.replace("__LEVEL__", html.escape(level)).replace("__CLASSES__", json.dumps(CLASSES))
                .replace("__ROWS__", json.dumps(rows)).replace("__SHOTS__", os.path.basename(level) + "-shots"))
    with open(os.path.join("export", "prototype", os.path.basename(level) + "-texture-poses.json"), "w") as f:
        json.dump(poses, f)
    print(out, len(rows), "textures", collections.Counter(r["proposed"] for r in rows))


PAGE = r"""<!doctype html><meta charset=utf-8><title>Texture classes __LEVEL__ (prototype)</title>
<style>
body{font:13px system-ui;background:#111318;color:#d8dbe2;margin:0;padding:16px}
h1{font-size:16px;margin:0 0 4px} .note{color:#8a90a0;margin-bottom:12px}
.bar{position:sticky;top:0;background:#111318;padding:8px 0;z-index:2;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.bar button,.bar select{background:#232733;color:#d8dbe2;border:1px solid #3a4050;border-radius:4px;padding:4px 8px}
.counts span{margin-right:10px;color:#9fb4ff}
.row{display:flex;flex-wrap:wrap;gap:12px;padding:10px 0;border-bottom:1px solid #262a35;align-items:start}
.row.changed{background:#1b2230}
.thumb{width:256px;height:256px;object-fit:contain;background:repeating-conic-gradient(#333 0 25%,#222 0 50%) 0 0/16px 16px;image-rendering:pixelated}
.shot{height:300px;width:auto;max-width:100%;background:#000}
.info{min-width:280px;flex:1}
.name{font-family:ui-monospace,monospace;font-size:12px;word-break:break-all;color:#fff}
.meta{color:#9aa0ae;margin:4px 0} .sw{display:inline-block;width:12px;height:12px;vertical-align:middle;border:1px solid #555}
select.cls{font-size:14px;padding:4px;margin-top:6px;background:#232733;color:#fff;border:1px solid #4a5268;border-radius:4px}
textarea{width:100%;height:200px;background:#0b0c10;color:#cde;font-family:ui-monospace,monospace;font-size:11px}
</style>
<h1>Texture classes: __LEVEL__ <small style="color:#f80">PROTOTYPE</small></h1>
<div class=note>Orange = where the texture is, top-down: whole level, then zoomed to the texture (span in the hover title; walls as grey lines). Height = metres above the nearby floor under the texture's lowest point. Classes are pre-filled from folder names; change any, then "Copy table" and paste it back.</div>
<div class=bar><button id=copy>Copy table</button>
<label>show <select id=filter><option value="">all</option></select></label>
<span class=counts id=counts></span></div>
<div id=rows></div>
<h2>Table</h2><textarea id=out readonly></textarea>
<script>
const CLASSES=__CLASSES__, ROWS=__ROWS__;
const rowsEl=document.getElementById('rows'), out=document.getElementById('out'), filter=document.getElementById('filter');
CLASSES.forEach(c=>filter.add(new Option(c,c)));
const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
ROWS.forEach((r,i)=>{r.cls=r.proposed;
 const fam=Object.entries(r.families).map(([k,n])=>`${k} ${n}`).join(', ');
 const bl=Object.entries(r.blend).map(([k,n])=>`${k} ${n}`).join(', ');
 const sw=r.mean?`<span class=sw style="background:rgb(${r.mean.map(x=>x*255|0)})"></span>`:'';
 const d=document.createElement('div');d.className='row';d.id='r'+i;
 d.innerHTML=`${r.thumb?`<img class=thumb src="${r.thumb}">`:'<div class=thumb></div>'}<img class=shot src="__SHOTS__/${String(i).padStart(3,'0')}.jpg" onerror="this.remove()"><img src="${r.plan}" width=300 height=300><img src="${r.zoom}" width=300 height=300 title="zoom: ${r.span} m across">
 <div class=info><div class=name>${esc(r.name)}</div>
 <div class=meta>${r.tris} tris · ${r.area} m² · height ${r.height[0]}–${r.height[1]} m ${sw}${r.fullbright?' · <b>fullbright</b>':''}</div>
 <div class=meta>families: ${fam}</div><div class=meta>blend: ${bl}</div>
 <select class=cls>${CLASSES.map(c=>`<option${c===r.cls?' selected':''}>${c}</option>`).join('')}</select>
 <span class=meta> proposed: ${r.proposed}</span></div>`;
 d.querySelector('select').onchange=e=>{r.cls=e.target.value;d.classList.toggle('changed',r.cls!==r.proposed);update()};
 rowsEl.appendChild(d)});
function update(){
 const t={};ROWS.forEach(r=>{if(r.cls!=='structure')t[r.name]=r.cls});
 out.value=JSON.stringify(t,null,1);
 const c={};ROWS.forEach(r=>c[r.cls]=(c[r.cls]||0)+1);
 document.getElementById('counts').innerHTML=CLASSES.filter(k=>c[k]).map(k=>`<span>${k} ${c[k]}</span>`).join('');
 ROWS.forEach((r,i)=>document.getElementById('r'+i).hidden=filter.value&&r.cls!==filter.value);
}
filter.onchange=update;
document.getElementById('copy').onclick=()=>{navigator.clipboard.writeText(out.value).catch(()=>{out.select()})};
update();
</script>"""


if __name__ == "__main__":
    main()
