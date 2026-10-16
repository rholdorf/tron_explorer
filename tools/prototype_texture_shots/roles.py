import sys, os, struct, collections, json
import numpy as np
sys.path.insert(0, 'tools')
import dat85, surfaces
root = 'extracted'
w = dat85.load(f'{root}/worlds/retailsingleplayer/m01-01.dat')
v, vn, texs, modes = surfaces.world_triangles(w)
names = np.array([t.lower() for t in texs], object)
fn = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]); ar = np.linalg.norm(fn, axis=1) / 2
fn[(fn * vn).sum(1) < 0] *= -1; fn /= np.maximum(np.linalg.norm(fn, axis=1), 1e-12)[:, None]
c = v.mean(1)

def dtx(name):
    p = os.path.join(root, name.replace('\\', '/'))
    if name.endswith('.spr') or not os.path.exists(p): return None
    d = open(p, 'rb').read()
    cmd = d[36:164].split(b'\0')[0].decode('latin1')
    return {'fullbright': bool(struct.unpack_from('<i', d, 16)[0] & 1), 'bpp': d[26], 'cmd': cmd}

# Decal: centroid lies within 2 units in front of a coplanar-ish, same-facing triangle of another texture.
key = np.round(fn * 8).astype(int)
buckets = collections.defaultdict(list)
for i, k in enumerate(map(tuple, key)): buckets[k].append(i)
decal = np.zeros(len(v), bool)
for k, idx in buckets.items():
    idx = np.array(idx)
    if len(idx) < 2: continue
    P = v[idx]; N = fn[idx]; C = c[idx]
    for a in range(len(idx)):
        dist = ((C[a] - P[:, 0]) * N).sum(1)          # height of a's centroid over each plane
        cand = (dist > 0.01) & (dist < 2.0) & (names[idx] != names[idx[a]]) & (ar[idx] > ar[idx[a]] * 0.5)
        if not cand.any(): continue
        for b in np.flatnonzero(cand):
            q = C[a] - N[b] * dist[b]; t = P[b]
            v0, v1, v2 = t[1] - t[0], t[2] - t[0], q - t[0]
            d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
            den = d00 * d11 - d01 * d01
            if den == 0: continue
            y = (d11 * d20 - d01 * d21) / den; z = (d00 * d21 - d01 * d20) / den
            if y >= 0 and z >= 0 and y + z <= 1: decal[idx[a]] = True; break
rows = []
for n in collections.Counter(names):
    sel = names == n; d = dtx(n) if n else None
    rows.append({'name': n, 'tris': int(sel.sum()), 'decal': round(float(decal[sel].mean()), 2),
                 'blend': collections.Counter(modes[sel]).most_common(1)[0][0],
                 'fullbright': d and d['fullbright'], 'alpha': d and d['bpp'] in (0, 3, 5, 6) and ('AlphaRef' in d['cmd'] or d['bpp'] != 4),
                 'alpharef': d and 'alpharef' in d['cmd'].lower(), 'cmd': d and d['cmd']})
json.dump(rows, open(sys.argv[1], 'w'))
print('textures', len(rows))
print('fullbright', sum(1 for r in rows if r['fullbright']))
print('alpharef (cutout)', sum(1 for r in rows if r['alpharef']))
print('blend', collections.Counter(r['blend'] for r in rows))
print('decal >=50% of tris', sum(1 for r in rows if r['decal'] >= .5), ' >0', sum(1 for r in rows if r['decal'] > 0))
print('cmds', collections.Counter((r['cmd'] or '').split(' ')[0] for r in rows))
