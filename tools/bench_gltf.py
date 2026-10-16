"""Bench glTF: one level's drawn world geometry as a .glb, for the sibling project mus-y-sinak, which tries its
world-space shaders on it. Positions and flat normals only, in metres: no UVs, no textures, no lightmaps.

One primitive per surface family x texture x animated x overlay, so every number in its `extras` is exact:
- texture: the section's texture name (the name only), blend: the owner's BlendMode (None / Translucent /
  Additive), animated: the section draws a .spr sprite or has a texture effect (docs/research on branch
  research/texture-animation), effect: that effect's name or null
- overlay: the triangles lie just in front of another texture's surface, facing the same way (a decal)
- glow: the share of a fullbright texture that lights itself (mean alpha, 0-1; 0 when not fullbright),
  glowCoverage: the share of its texels with alpha >= 0.5, glowSpread: the standard deviation of its alpha
  (0-0.5; low = a sheet of light, high = a lit pattern on a dark plate), both 0 when not fullbright,
  glowColor: its mean rgb * alpha, color: its mean rgb (linear RGB, sprites averaged over their frames)
- lightmap: area-weighted mean luminance of the lightmap as the engine applies it (x2, 0-2, 1 = the texture as
  drawn), over the primitive's lightmapped triangles; null when none is. vertexLight: the same for the
  vertex colours (the light of triangles without a lightmap), null when every triangle has a lightmap
Triangles the level doesn't draw at start (world models not Visible, or StartHidden) are left out.

Axes: LithTech is left-handed (x right, y up, z forward) like Unity; glTF is right-handed. x is negated
on the way out, which is the inverse of what Unity's glTF importers do, so the bench gets the viewer's
coordinates (LithTech units * METRES) back on import. Triangles are wound counter-clockwise seen from the
side their vertex normals face.

The output is the game's geometry: write it under export/, never into a repository.

Usage: python tools/bench_gltf.py <extracted dir> <level> [out.glb]   (level e.g. retailsingleplayer/m01-01)"""
import collections
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

import dat85  # noqa: E402
import dtx  # noqa: E402
import surfaces  # noqa: E402
from baseline import METRES  # noqa: E402
from export_level import LIGHTMAP_SHADER, LIGHTMAPPED_SHADERS, apply_vertex_light_groups, section_lightmap  # noqa: E402

FLIP = np.array([-1.0, 1.0, 1.0])
COLOURS = {   # display colours only, so the file reads in any viewer; the bench replaces the materials
    "floor-interior": (0.20, 0.45, 0.80), "floor-exterior": (0.20, 0.70, 0.40), "wall": (0.60, 0.60, 0.65),
    "ceiling": (0.80, 0.60, 0.20), "glass": (0.50, 0.85, 0.95), "emissive": (1.00, 1.00, 1.00),
    "unclassified": (0.90, 0.10, 0.60),
}
LUMA = np.array([0.2126, 0.7152, 0.0722])
OVERLAY_GAP = (0.01, 2.0)   # LithTech units in front of the surface below: decals sit a fraction of a unit up


def _start_rotation(rot):
    """glTF quaternion (x, y, z, w) of a LithTech Rotation (Euler pitch, yaw, roll in radians, applied as
    Unity's Quaternion.Euler does: z, then x, then y)."""
    def axis(i, a):
        q = [0.0, 0.0, 0.0, math.cos(a / 2)]
        q[i] = math.sin(a / 2)
        return q

    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]
    x, y, z, w = mul(mul(axis(1, rot[1]), axis(0, rot[0])), axis(2, rot[2]))
    return [x, -y, -z, w]   # the x mirror


def _linear(c):
    """sRGB 0-1 to linear."""
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def frame_stats(rgba, fullbright):
    """(color, glow, glowColor, glowCoverage, glowSpread) of one RGBA uint8 frame."""
    px = rgba.reshape(-1, 4).astype(np.float64) / 255
    rgb, a = _linear(px[:, :3]), px[:, 3] if fullbright else np.zeros(len(px))
    return rgb.mean(0), a.mean(), (rgb * a[:, None]).mean(0), (a >= 0.5).mean() if fullbright else 0.0, a.std()


def texture_stats(root, name):
    """frame_stats of a texture, averaged over a sprite's frames; None when it can't be read."""
    out = [frame_stats(rgba, fullbright) for rgba, fullbright in dtx.frames(root, name)]
    if not out:
        return None
    return tuple(np.mean([o[k] for o in out], axis=0) for k in range(5))


def section_light(w):
    """Per world_triangles triangle: (effect name, lightmap luminance x2 or nan, vertex-light luminance x2).
    A lightmapped texture-pass triangle finds its lightmap triangle by its sorted vertex positions, as the
    exporter does; its luminance is the mean of the lightmap at its corners and centroid."""
    effects, lms, vls = [], [], []
    lm_cache, vc_cache = {}, {}
    for _name, _mode, _drawn, b, _si, s, tris in surfaces.world_sections(w):
        key = id(b)
        if key not in vc_cache:
            c = apply_vertex_light_groups(b.verts["color"], b.light_groups)
            rgb = np.stack([(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF], 1).astype(np.float64)
            vc_cache[key] = rgb @ LUMA / 255 * 2
        vls.append(vc_cache[key][tris].mean(1))
        effects.extend([s.effect.lower() or None] * len(tris))
        lm = np.full(len(tris), np.nan)
        if s.shader in LIGHTMAPPED_SHADERS:
            if key not in lm_cache:
                lm_cache[key] = _block_lightmaps(b)
            by_tri = lm_cache[key]
            for k, t in enumerate(tris):
                pts = [b.verts["pos"][i].tobytes() for i in t]
                m = by_tri.get(tuple(sorted(pts)))
                if m is None:
                    continue
                img, uv = m[0], np.array([m[1][p] for p in pts])
                uv = np.vstack([uv, uv.mean(0)])
                h, wd = img.shape[:2]
                x = np.clip((uv[:, 0] * wd).astype(int), 0, wd - 1)
                y = np.clip((uv[:, 1] * h).astype(int), 0, h - 1)
                lm[k] = (img[y, x].astype(np.float64) @ LUMA).mean() / 255 * 2
        lms.append(lm)
    if not lms:
        return np.array([], object), np.zeros(0), np.zeros(0)
    return np.array(effects, object), np.concatenate(lms), np.concatenate(vls)


def _block_lightmaps(b):
    """{sorted vertex positions of a lightmap triangle: (its section's lightmap image, {position: uv})}."""
    by_tri, start = {}, 0
    for si, s in enumerate(b.sections):
        tris = b.tris[start:start + s.tri_count]
        start += s.tri_count
        if s.shader != LIGHTMAP_SHADER or not s.lm_data:
            continue
        subs = [lg.section_lms[si] if si < len(lg.section_lms) else [] for lg in b.light_groups]
        img = section_lightmap(s, subs, b.light_groups)
        for t in tris:
            pts = [b.verts["pos"][i].tobytes() for i in t]
            by_tri[tuple(sorted(pts))] = (img, {p: tuple(b.verts["uv0"][i]) for p, i in zip(pts, t)})
    return by_tri


def overlays(v, normal, texs):
    """Whether each triangle is an overlay: its centroid lies OVERLAY_GAP in front of a same-facing triangle
    of another texture at least half its size, inside that triangle's outline."""
    area = 0.5 * np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1)
    centroid = v.mean(1)
    buckets = collections.defaultdict(list)
    for i, k in enumerate(map(tuple, np.round(normal * 8).astype(int))):
        buckets[k].append(i)
    out = np.zeros(len(v), bool)
    for idx in buckets.values():
        if len(idx) < 2:
            continue
        idx = np.array(idx)
        p0, n, c, t, ar = v[idx, 0], normal[idx], centroid[idx], texs[idx], area[idx]
        e0, e1 = v[idx, 1] - p0, v[idx, 2] - p0
        d00, d01, d11 = (e0 * e0).sum(1), (e0 * e1).sum(1), (e1 * e1).sum(1)
        den = d00 * d11 - d01 * d01
        for a in range(len(idx)):
            gap = ((c[a] - p0) * n).sum(1)
            cand = (gap > OVERLAY_GAP[0]) & (gap < OVERLAY_GAP[1]) & (t != t[a]) & (ar >= ar[a] * 0.5) & (den > 0)
            if not cand.any():
                continue
            q = c[a] - n[cand] * gap[cand, None] - p0[cand]
            d20, d21 = (q * e0[cand]).sum(1), (q * e1[cand]).sum(1)
            y = (d11[cand] * d20 - d01[cand] * d21) / den[cand]
            z = (d00[cand] * d21 - d01[cand] * d20) / den[cand]
            out[idx[a]] = bool(((y >= 0) & (z >= 0) & (y + z <= 1)).any())
    return out


def build(w, level, root):
    """(glTF JSON dict, binary buffer, triangles per family) for a loaded level; `root` is the extracted
    game directory the textures are read from."""
    v, vn, texs, modes = surfaces.world_triangles(w)
    fams, _area = surfaces.classify(w)
    effects, lms, vls = section_light(w)
    drawn = surfaces.world_drawn(w)
    v, vn, texs, modes, fams, effects, lms, vls = (a[drawn] for a in (v, vn, texs, modes, fams, effects, lms, vls))

    v, vn = v * FLIP, vn * FLIP   # mirrored, still in LithTech units (the overlay gap is in units)
    cross = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    back = (cross * vn).sum(1) < 0
    cross[back] *= -1
    area = 0.5 * np.linalg.norm(cross, axis=1)
    # A degenerate triangle (the unclassified ones) has no face normal: its vertex normals stand in.
    flat = np.linalg.norm(cross, axis=1) < 1e-9
    cross[flat] = vn[flat] + (np.linalg.norm(vn[flat], axis=1) < 1e-9)[:, None] * (0.0, 1.0, 0.0)
    normal = cross / np.linalg.norm(cross, axis=1)[:, None]
    lower = np.array([t.lower() for t in texs], object)
    over = overlays(v, normal, lower)
    animated = np.array([t.endswith(".spr") or e is not None for t, e in zip(lower, effects)])

    v = v * METRES
    v[back] = v[back][:, ::-1]

    stats = {t: texture_stats(root, t) if t else None for t in set(lower)}
    groups = collections.defaultdict(list)
    for k in range(len(v)):
        groups[(fams[k], lower[k], bool(animated[k]), bool(over[k]))].append(k)
    order = {f: i for i, f in enumerate(surfaces.FAMILIES)}

    blob, views, accessors, primitives = bytearray(), [], [], []
    counts = {f: int((fams == f).sum()) for f in surfaces.FAMILIES}
    for key in sorted(groups, key=lambda g: (order[g[0]], g[1], g[2], g[3])):
        fam, tex, anim, ov = key
        sel = np.array(groups[key])
        pos = v[sel].reshape(-1, 3).astype(np.float32)
        nrm = np.repeat(normal[sel], 3, axis=0).astype(np.float32)
        attrs = {}
        for name, data in (("POSITION", pos), ("NORMAL", nrm)):
            views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": data.nbytes, "target": 34962})
            blob += data.tobytes()
            acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": len(data), "type": "VEC3"}
            if name == "POSITION":
                acc["min"], acc["max"] = pos.min(0).tolist(), pos.max(0).tolist()
            accessors.append(acc)
            attrs[name] = len(accessors) - 1
        wt = area[sel] + 1e-12
        lit = ~np.isnan(lms[sel])
        st = stats[tex]
        effect = collections.Counter(e for e in effects[sel] if e).most_common(1)
        extras = {
            "texture": texs[sel[0]], "blend": modes[sel[0]], "animated": anim,
            "effect": effect[0][0] if effect else None, "overlay": ov,
            "glow": round(float(st[1]), 4) if st else 0.0,
            "glowCoverage": round(float(st[3]), 4) if st else 0.0,
            "glowSpread": round(float(st[4]), 4) if st else 0.0,
            "glowColor": [round(float(c), 4) for c in st[2]] if st else [0.0, 0.0, 0.0],
            "color": [round(float(c), 4) for c in st[0]] if st else None,
            "lightmap": round(float(np.average(lms[sel][lit], weights=wt[lit])), 4) if lit.any() else None,
            "vertexLight": round(float(np.average(vls[sel][~lit], weights=wt[~lit])), 4) if (~lit).any() else None,
            "triangles": int(len(sel)),
        }
        primitives.append({"attributes": attrs, "material": order[fam], "mode": 4, "extras": extras})

    start = next((o["props"] for o in w.objects if o["class"] == "GameStartPoint"), None)
    nodes = [{"name": "world", "mesh": 0}]
    if start is not None:
        rot = (start.get("Rotation") or [0, 0, 0])[:3]
        nodes.append({"name": "GameStartPoint", "translation": (np.array(start["Pos"]) * FLIP * METRES).tolist(),
                      "rotation": _start_rotation(rot)})
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    doc = {
        "asset": {"version": "2.0", "generator": "tron_explorer tools/bench_gltf.py",
                  "extras": {"repo": "rholdorf/tron_explorer", "commit": commit, "level": level,
                             "metresPerUnit": METRES, "trianglesPerFamily": counts,
                             "primitiveExtras": __doc__.split("\n\n")[1]}},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": [{"name": "world", "primitives": primitives}],
        "materials": [{"name": f, "pbrMetallicRoughness": {"baseColorFactor": [*COLOURS[f], 1.0],
                                                          "metallicFactor": 0.0, "roughnessFactor": 1.0}}
                      for f in surfaces.FAMILIES],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    return doc, bytes(blob), counts


def glb(doc, blob):
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def main():
    extracted, level = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join("export", "bench", os.path.basename(level) + ".glb")
    doc, blob, counts = build(dat85.load(os.path.join(extracted, "worlds", level + ".dat")), level, extracted)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(glb(doc, blob))
    print(out, len(doc["meshes"][0]["primitives"]), "primitives", " ".join(f"{k} {n}" for k, n in counts.items()))


if __name__ == "__main__":
    main()
