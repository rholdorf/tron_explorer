"""Style baseline: what Tron 2.0's single-player levels look like as numbers (room sizes, room graph,
surface family mix, object density, light), for the sibling project mus-y-sinak. See
docs/research/style-baseline.md.

Rooms aren't marked in the levels (AIVolumes are floor tiles, AIRegions are AI territories), so they are
derived from the reachable floor: a grid of floor cells, flooded from the start points, cut at doors.
segment() splits it into rooms (the parts wide enough to hold a core) and corridors (the rest).

Usage: python tools/baseline.py <extracted dir> <out.json>"""
import colorsys
import glob
import json
import os
import subprocess
import sys
from collections import deque

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

import dat85  # noqa: E402
import surfaces  # noqa: E402

DIAGONALS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


class Segmentation:
    def __init__(self, adj, rooms, corridors, edges, dist):
        self.adj = adj
        self.rooms = rooms
        self.corridors = corridors
        self.edges = edges
        self.dist = dist

    def run(self, cell, axis):
        """Length of the straight run of floor cells through `cell` along x (axis 0) or z (axis 1)."""
        n = 1
        for step in (1, -1):
            c = cell
            while True:
                nxt = next((a for a in self.adj.get(c, ()) if a[axis] == c[axis] + step
                            and a[1 - axis] == c[1 - axis]), None)
                if nxt is None:
                    break
                n, c = n + 1, nxt
        return n

    def width(self, cells):
        """Median cross-section of a set of cells: per cell, the shorter of its x and z runs."""
        w = sorted(min(self.run(c, 0), self.run(c, 1)) for c in cells)
        return w[len(w) // 2]

    def corridor_width(self, i):
        return self.width(self.corridors[i])


def _ring(adj, c):
    """8-neighbourhood: the 4-neighbours and the diagonal cells reachable through one of them."""
    out = list(adj[c])
    for a in adj[c]:
        for b in adj[a]:
            if b[0] != c[0] and b[1] != c[1] and b not in out:
                out.append(b)
    return out


def _components(cells, adj, ring=False):
    seen, out = set(), []
    for start in sorted(cells):
        if start in seen:
            continue
        comp, q = {start}, deque([start])
        seen.add(start)
        while q:
            c = q.popleft()
            for a in (_ring(adj, c) if ring else adj[c]):
                if a in cells and a not in seen:
                    seen.add(a)
                    comp.add(a)
                    q.append(a)
        out.append(comp)
    return out


def _small_holes(xz, limit):
    """A function telling whether an xz position off the floor lies in an enclosed gap of at most
    `limit` cells (a pillar, a console), as opposed to the open void past a wall or a big pit."""
    memo = {}

    def small(p):
        if p not in memo:
            seen, q = {p}, deque([p])
            while q and len(seen) <= limit:
                c = q.popleft()
                for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    a = (c[0] + d[0], c[1] + d[1])
                    if a not in xz and a not in seen:
                        seen.add(a)
                        q.append(a)
            result = len(seen) <= limit
            memo.update(dict.fromkeys(seen, result))
        return memo[p]
    return small


def segment(adj, core, doors=(), hole=64):
    """Rooms and corridors of a floor grid. `adj` maps each cell to its walkable 4-neighbours; door cells
    are cut out. The edge is where the floor stops, except at small enclosed gaps (up to `hole` cells: pillars,
consoles), which a room flows around. A cell at least `core` cells (Chebyshev) from the edge is a room core; a room is a
    connected core grown back by core - 1 cells (a morphological opening), so a corridor narrower than
    2 * core - 1 never holds one. What's left is corridors, except scraps smaller than core² opening
    into a single room (alcoves) or smaller than core between rooms (openings), which join the room they
    touch most. Edges join nodes whose cells touch, or that touch the same door."""
    doors = set(doors) & set(adj)
    full = adj
    adj = {c: [a for a in n if a not in doors] for c, n in adj.items() if c not in doors}
    xz = {c[:2] for c in full}
    small = _small_holes(xz, hole)
    present = {c: {a[:2] for a in n} for c, n in adj.items()}
    dist, q = {}, deque()
    for c in adj:
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = (c[0] + dx, c[1] + dz)
            if p not in present[c] and (p in xz or not small(p)):
                dist[c] = 1
                q.append(c)
                break
    while q:
        c = q.popleft()
        for a in _ring(adj, c):
            if a not in dist:
                dist[a] = dist[c] + 1
                q.append(a)
    cores = {c for c, d in dist.items() if d >= core}
    rooms = _components(cores, adj, ring=True)
    owner = {c: i for i, r in enumerate(rooms) for c in r}
    q = deque((c, 0) for c in sorted(owner))
    while q:
        c, steps = q.popleft()
        if steps == core - 1:
            continue
        for a in _ring(adj, c):
            if a not in owner:
                owner[a] = owner[c]
                rooms[owner[c]].add(a)
                q.append((a, steps + 1))
    corridors = []
    for comp in _components(set(adj) - set(owner), adj):
        touching = {owner[a] for c in comp for a in adj[c] if a in owner}
        if len(comp) < core * core and len(touching) == 1 or len(comp) < core and touching:
            # An alcove of the room it opens into, or a scrap between rooms: part of the room it touches most.
            contact = {}
            for c in comp:
                for a in adj[c]:
                    if a in owner:
                        contact[owner[a]] = contact.get(owner[a], 0) + 1
            r = max(sorted(contact), key=contact.get)
            rooms[r] |= comp
            owner.update(dict.fromkeys(comp, r))
        else:
            corridors.append(comp)
    node = {c: f"r{i}" for c, i in owner.items()}
    node.update({c: f"c{i}" for i, comp in enumerate(corridors) for c in comp})
    edges = set()
    for c, n in adj.items():
        for a in n:
            if node[a] != node[c]:
                edges.add(tuple(sorted((node[c], node[a]))))
    for door in _components(doors, full):
        touching = sorted({node[a] for d in door for a in full[d] if a in node})
        edges |= {(x, y) for i, x in enumerate(touching) for y in touching[i + 1:]}
    return Segmentation(adj, rooms, corridors, edges, dist)



# ---------------------------------------------------------------- floor grid of a level


CELL = 16.0          # grid cell, LithTech units (~27 cm)
STEP = 18            # PlayerController.stepHeight
HEADROOM = 60        # crouched player height: lower ceilings block
WALL_BAND = (20, 90)  # a wall crossing this band above the floor blocks the cell
MAX_CELLS = 400_000  # flood cap: past this a level is an open space, not interiors
DOOR_CLASSES = {"SlidingDoor", "RotatingDoor", "Door"}
DOOR_MIN_HEIGHT = 96
DOOR_MAX_THICKNESS = 64


class PlaneIndex:
    """Non-vertical polygons bucketed by their xz bounds: the heights at which they cross a cell's centre
    column, computed when first asked (a level's floors can be hundreds of thousands of m², mostly
    unreachable, so rasterizing them all up front doesn't fit in memory)."""
    BUCKET = 256.0

    def __init__(self, polys):
        self.polys = []
        self.buckets = {}
        self.memo = {}
        for P, n in polys:
            q = P[:, [0, 2]]
            k = len(q)
            area2 = sum(q[i][0] * q[(i + 1) % k][1] - q[(i + 1) % k][0] * q[i][1] for i in range(k))
            i = len(self.polys)
            self.polys.append((q, 1 if area2 > 0 else -1, n, -(n @ P[0])))
            lo, hi = q.min(0), q.max(0)
            for bx in range(int(lo[0] // self.BUCKET), int(hi[0] // self.BUCKET) + 1):
                for bz in range(int(lo[1] // self.BUCKET), int(hi[1] // self.BUCKET) + 1):
                    self.buckets.setdefault((bx, bz), []).append(i)

    def heights(self, k):
        if k not in self.memo:
            x, z = (k[0] + .5) * CELL, (k[1] + .5) * CELL
            out = []
            for i in self.buckets.get((int(x // self.BUCKET), int(z // self.BUCKET)), ()):
                q, sign, n, d = self.polys[i]
                inside = True
                for j in range(len(q)):
                    a, b = q[j], q[(j + 1) % len(q)]
                    if sign * ((b[0] - a[0]) * (z - a[1]) - (b[1] - a[1]) * (x - a[0])) < 0:
                        inside = False
                        break
                if inside:
                    out.append(-(n[0] * x + n[2] * z + d) / n[1])
            self.memo[k] = np.array(out)
        return self.memo[k]


def _clip(P, axis, value, keep_above):
    """Sutherland-Hodgman: the part of convex polygon P on one side of the plane P[:, axis] = value."""
    out = []
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        ina = (a[axis] >= value) == keep_above
        inb = (b[axis] >= value) == keep_above
        if ina:
            out.append(a)
        if ina != inb:
            t = (value - a[axis]) / (b[axis] - a[axis])
            out.append(a + t * (b - a))
    return np.array(out).reshape(-1, 3)


def _overlaps_square(q, x0, z0, x1, z1):
    """Whether convex xz polygon q (possibly flat: a segment) overlaps the square, by separating axes."""
    sq = np.array([[x0, z0], [x1, z0], [x1, z1], [x0, z1]])
    if q[:, 0].max() < x0 or q[:, 0].min() > x1 or q[:, 1].max() < z0 or q[:, 1].min() > z1:
        return False
    for i in range(len(q)):
        e = q[(i + 1) % len(q)] - q[i]
        if abs(e[0]) + abs(e[1]) < 1e-6:
            continue
        n = np.array([-e[1], e[0]])
        pq, ps = q @ n, sq @ n
        if pq.max() < ps.min() or ps.max() < pq.min():
            return False
    return True


class WallIndex:
    """Wall polygons bucketed by their xz bounds, to ask whether a wall crosses a cell's column between
    two heights."""
    BUCKET = 256.0

    def __init__(self, polys):
        self.polys = polys
        self.lo = [P.min(0) for P in polys]
        self.hi = [P.max(0) for P in polys]
        self.buckets = {}
        for i, (lo, hi) in enumerate(zip(self.lo, self.hi)):
            for bx in range(int(lo[0] // self.BUCKET), int(hi[0] // self.BUCKET) + 1):
                for bz in range(int(lo[2] // self.BUCKET), int(hi[2] // self.BUCKET) + 1):
                    self.buckets.setdefault((bx, bz), []).append(i)

    def crosses(self, x0, z0, x1, z1, y0, y1):
        cands = set()
        for bx in range(int(x0 // self.BUCKET), int(x1 // self.BUCKET) + 1):
            for bz in range(int(z0 // self.BUCKET), int(z1 // self.BUCKET) + 1):
                cands.update(self.buckets.get((bx, bz), ()))
        for i in cands:
            lo, hi = self.lo[i], self.hi[i]
            if hi[1] < y0 or lo[1] > y1 or hi[0] < x0 or lo[0] > x1 or hi[2] < z0 or lo[2] > z1:
                continue
            P = _clip(_clip(self.polys[i], 1, y0, True), 1, y1, False)
            if len(P) and _overlaps_square(P[:, [0, 2]], x0, z0, x1, z1):
                return True
        return False


class FloorGrid:
    """The reachable floor of a level: cells (ix, iz, floor y rounded) flooded from the start points.
    floor[cell] is the floor height, ceiling[cell] the lowest solid surface above (None: none), sky[cell]
    whether the sky is what's straight above, adj[cell] the walkable 4-neighbours."""

    def __init__(self, w):
        phys = next(b for b in w.bsps if b.flags & dat85.WIF_PHYSICSBSP)
        floors, walls, ceils, skies = [], [], [], []
        for surf, plane, vs in phys.polys:
            flags = int(phys.surfaces[surf]["flags"])
            if not flags & dat85.SURF_SOLID or flags & dat85.SURF_NONEXISTENT:
                continue
            n = phys.planes[plane][:3].astype(np.float64)
            P = phys.points[list(vs)].astype(np.float64)
            if flags & dat85.SURF_SKY:
                if abs(n[1]) > 1e-3:
                    skies.append((P, n))
            elif n[1] >= 0.7:
                floors.append((P, n))
            elif n[1] <= -0.7:
                ceils.append((P, n))
            else:
                walls.append(P)
        self.walls = WallIndex(walls)
        self.ceils = PlaneIndex(ceils)
        self.skies = PlaneIndex(skies)
        self._cache = {}
        floor_index = PlaneIndex(floors)
        layer_memo = {}

        def layers(k):
            if k not in layer_memo:
                layer_memo[k] = sorted({round(float(y)) for y in floor_index.heights(k)})
            return layer_memo[k]
        # Seeds: the start and teleport points, the exit triggers, and every AI volume's floor (the designers'
        # own mark of walkable floor), which reaches the parts joined only by elevators or teleports.
        self.starts = [o["props"]["Pos"] for o in w.objects if o["class"] in ("GameStartPoint", "TeleportPoint")]
        for o in w.objects:
            if o["class"] == "ExitTrigger" and "Pos" in o["props"]:
                p, d = o["props"]["Pos"], o["props"].get("Dims", [0, 0, 0])
                self.starts.append([p[0], p[1] - d[1] + 100, p[2]])
            if o["class"].startswith("AIVolume") and o["class"] != "AIVolumePlayerInfo" and "Dims" in o["props"]:
                p, d = o["props"]["Pos"], o["props"]["Dims"]
                self.starts.append([p[0], p[1] - d[1] + 100, p[2]])
        self.floor, self.adj, self.open = {}, {}, False
        q = deque()
        for s in self.starts:
            k = (int(s[0] // CELL), int(s[2] // CELL))
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    kk = (k[0] + dx, k[1] + dz)
                    for y in layers(kk):
                        if s[1] - 200 <= y <= s[1] + 10 and (*kk, y) not in self.floor and self._ok(kk, y):
                            self.floor[(*kk, y)] = y
                            q.append((*kk, y))
        while q:
            c = q.popleft()
            n = []
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                kk = (c[0] + dx, c[1] + dz)
                for y in layers(kk):
                    if abs(y - c[2]) <= STEP and self._ok(kk, y):
                        a = (*kk, y)
                        n.append(a)
                        if a not in self.floor:
                            self.floor[a] = y
                            q.append(a)
            self.adj[c] = n
            if len(self.floor) > MAX_CELLS:
                self.open = True
                break
        for c in list(self.adj):
            self.adj[c] = [a for a in self.adj[c] if a in self.floor]
        for c in self.floor:
            self.adj.setdefault(c, [])
        self.ceiling, self.sky = {}, {}
        for c, y in self.floor.items():
            above = self.ceils.heights(c[:2])
            ceil = float(above[above > y + 1].min()) if (above > y + 1).any() else None
            sky = self.skies.heights(c[:2])
            sky = float(sky[sky > y + 1].min()) if (sky > y + 1).any() else None
            self.ceiling[c] = ceil
            self.sky[c] = ceil is None or (sky is not None and sky < ceil)

    def _ok(self, k, y):
        key = (*k, y)
        if key not in self._cache:
            self._cache[key] = self._walkable(k, y)
        return self._cache[key]

    def _walkable(self, k, y):
        x0, z0 = k[0] * CELL, k[1] * CELL
        if self.walls.crosses(x0, z0, x0 + CELL, z0 + CELL, y + WALL_BAND[0], y + WALL_BAND[1]):
            return False
        c = self.ceils.heights(k)
        return not ((c > y + 1) & (c < y + HEADROOM)).any()

    def door_cells(self, w):
        """Floor cells under a door: inside its world model's xz bounds, near its bottom. Only upright thin
        panels count; SlidingDoor also makes elevators (flat) and InfoString displays (off the floor)."""
        bsps = {b.name.lower(): b for b in w.bsps}
        out = set()
        for o in w.objects:
            if o["class"] not in DOOR_CLASSES:
                continue
            b = bsps.get(str(o["props"].get("Name", "")).lower())
            if b is None or b.points is None or not len(b.points):
                continue
            lo, hi = b.points.min(0), b.points.max(0)
            ext = hi - lo
            if ext[1] < DOOR_MIN_HEIGHT or min(ext[0], ext[2]) > DOOR_MAX_THICKNESS:
                continue
            # Doors are thinner than a cell (12 units is common): take every cell the panel overlaps.
            for c, y in self.floor.items():
                x, z = c[0] * CELL, c[1] * CELL
                if x < hi[0] and x + CELL > lo[0] and z < hi[2] and z + CELL > lo[2] and lo[1] - 40 <= y <= lo[1] + 40:
                    out.add(c)
        return out


# ---------------------------------------------------------------- measuring a level


METRES = 0.017       # LT.Scale: player dims 106 units ~ 1.8 m; the commonest door (128) ~ 2.18 m
CORE = 10            # room core, cells: a room is at least 2 * CORE - 1 cells (~5.2 m) wide somewhere
EDGE = 3             # cells (~0.8 m): an object this close to the room's edge stands at the wall
INTERIOR = 0.7       # a level is interior when this share of its reachable floor has a ceiling
MIN_AREA = 500       # m²: smaller levels (the ending, the last boss's arena) are minor, left out
CATEGORIES = {
    "light": {"Light", "DirLight", "ObjectLight", "StaticSunLight"},
    "prop": {"Prop", "PropType", "ArchiveBin", "Breakable"},
    "panel": {"SlidingSwitch", "RotatingSwitch", "InfoString", "DisplayTimer", "DisplayMeter", "BinaryBit",
              "IONode"},
    "character": {"CAIHuman"},
}


def _m(cells):
    return cells * CELL * METRES


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


class LevelMeasure:
    def __init__(self, w, name):
        self.name = name
        self.w = w
        self.grid = g = FloorGrid(w)
        if g.open:
            return   # past the flood cap: an open space, recorded but not split into rooms
        self.doors = g.door_cells(w)
        self.seg = s = segment(g.adj, core=CORE, doors=self.doors)
        self.columns = {}
        for c, y in g.floor.items():
            self.columns.setdefault(c[:2], []).append(c)
        self.node = {c: f"r{i}" for i, r in enumerate(s.rooms) for c in r}
        self.node.update({c: f"c{i}" for i, comp in enumerate(s.corridors) for c in comp})

    def cell_at(self, pos, reach=1024):
        """The floor cell an object at pos stands over: the highest floor at most 16 below it, within
        `reach` (or under its ceiling)."""
        k = (int(pos[0] // CELL), int(pos[2] // CELL))
        best = None
        for c in self.columns.get(k, ()):
            y = self.grid.floor[c]
            top = self.grid.ceiling[c] if self.grid.ceiling[c] is not None else y + reach
            if y - 16 <= pos[1] <= top + 16 and (best is None or y > self.grid.floor[best]):
                best = c
        return best

    def _side(self, c, axis, step):
        n, cur = 0, c
        while n <= EDGE:
            nxt = next((a for a in self.seg.adj.get(cur, ()) if a[axis] == cur[axis] + step
                        and a[1 - axis] == cur[1 - axis]), None)
            if nxt is None:
                break
            n, cur = n + 1, nxt
        return n

    def placement(self, c):
        near_x = min(self._side(c, 0, 1), self._side(c, 0, -1)) < EDGE
        near_z = min(self._side(c, 1, 1), self._side(c, 1, -1)) < EDGE
        return "corner" if near_x and near_z else "wall" if near_x or near_z else "center"

    def space(self, cells):
        g = self.grid
        heights = [g.ceiling[c] - g.floor[c] for c in cells if not g.sky[c]]
        xs = [c[0] for c in cells]
        zs = [c[1] for c in cells]
        extent = sorted([max(xs) - min(xs) + 1, max(zs) - min(zs) + 1])
        return {
            "area": round(len(cells) * (CELL * METRES) ** 2, 2),
            "width": round(_m(self.seg.width(cells)), 2),
            "extentShort": round(_m(extent[0]), 2),
            "extentLong": round(_m(extent[1]), 2),
            "ceilingHeight": round(_median(heights) * METRES, 2) if heights else None,
            "skyShare": round(sum(g.sky[c] for c in cells) / len(cells), 3),
            "floorY": round(_median([g.floor[c] for c in cells]) * METRES, 2),
        }

    def graph(self):
        nodes = [f"r{i}" for i in range(len(self.seg.rooms))] + [f"c{i}" for i in range(len(self.seg.corridors))]
        degree = dict.fromkeys(nodes, 0)
        for a, b in self.seg.edges:
            degree[a] += 1
            degree[b] += 1
        adj = {n: [] for n in nodes}
        for a, b in self.seg.edges:
            adj[a].append(b)
            adj[b].append(a)
        comps = _components(set(nodes), adj)
        # Elevators, platforms and teleports aren't in the physics BSP, so a level's graph comes apart into
        # components; the start and the exit are seldom in the same one. Measure the largest instead.
        largest = max(comps, key=len) if comps else set()
        diameter = 0
        for n in sorted(largest):
            far = {n: 0}
            q = deque([n])
            while q:
                x = q.popleft()
                for a in adj[x]:
                    if a not in far:
                        far[a] = far[x] + 1
                        q.append(a)
            diameter = max(diameter, max(far.values()))
        return {
            "rooms": len(self.seg.rooms),
            "corridors": len(self.seg.corridors),
            "edges": len(self.seg.edges),
            "components": len(comps),
            "cycles": len(self.seg.edges) - len(nodes) + len(comps),
            "roomDegree": [degree[f"r{i}"] for i in range(len(self.seg.rooms))],
            "corridorDegree": [degree[f"c{i}"] for i in range(len(self.seg.corridors))],
            "deadEnds": sum(1 for d in degree.values() if d == 1),
            "largestComponentShare": round(len(largest) / max(len(nodes), 1), 3),
            "largestComponentDiameter": diameter,
        }

    def objects(self):
        per = {f"r{i}": {k: 0 for k in CATEGORIES} | {"door": 0} for i in range(len(self.seg.rooms))}
        placements = {k: {"wall": 0, "center": 0, "corner": 0} for k in CATEGORIES}
        lights = []
        for o in self.w.objects:
            cat = next((k for k, v in CATEGORIES.items() if o["class"] in v), None)
            if cat is None or "Pos" not in o["props"]:
                continue
            if cat == "light":
                col = o["props"].get("LightColor") or o["props"].get("InnerColor")
                if col:
                    lights.append([round(float(v)) for v in col[:3]])
            c = self.cell_at(o["props"]["Pos"])
            if c is None or not self.node.get(c, "").startswith("r"):
                continue
            per[self.node[c]][cat] += 1
            placements[cat][self.placement(c)] += 1
        for d in _components(self.doors, self.grid.adj):
            touching = {self.node[a] for c in d for a in self.grid.adj[c] if a in self.node}
            for n in touching:
                if n.startswith("r"):
                    per[n]["door"] += 1
        return per, placements, lights

    def surface_mix(self):
        fams, area = surfaces.classify(self.w)
        v, *_ = surfaces.world_triangles(self.w)
        centroid = v.mean(1)
        out = dict.fromkeys(surfaces.FAMILIES, 0.0)
        for k in range(len(fams)):
            p = centroid[k]
            kx, kz = int(p[0] // CELL), int(p[2] // CELL)
            near = False
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for c in self.columns.get((kx + dx, kz + dz), ()):
                        y, top = self.grid.floor[c], self.grid.ceiling[c]
                        if y - 8 <= p[1] <= (top + 8 if top is not None else y + 512):
                            near = True
                            break
                    if near:
                        break
                if near:
                    break
            if near:
                out[fams[k]] += float(area[k]) * METRES ** 2
        return {k: round(v, 1) for k, v in out.items()}

    def result(self):
        g = self.grid
        if g.open:
            return {"level": self.name, "kind": "open", "reachableArea": None, "note":
                    f"flood stopped at {MAX_CELLS} cells ({round(MAX_CELLS * (CELL * METRES) ** 2)} m2)"}
        rooms = [self.space(r) for r in self.seg.rooms]
        corridors = [self.space(c) | {"length": round(len(c) * (CELL * METRES) ** 2 / max(_m(self.seg.width(c)), 1e-6), 2)}
                     for c in self.seg.corridors]
        per, placements, lights = self.objects()
        for room, counts in zip(rooms, per.values()):
            room["objects"] = counts
        interior = 1 - sum(g.sky.values()) / max(len(g.sky), 1)
        ai = [o for o in self.w.objects if o["class"].startswith("AIVolume") and o["class"] != "AIVolumePlayerInfo"]
        return {
            "level": self.name,
            "kind": "open" if interior < INTERIOR else "minor" if len(g.floor) * (CELL * METRES) ** 2 < MIN_AREA
                    else "interior",
            "reachableArea": round(len(g.floor) * (CELL * METRES) ** 2, 1),
            "interiorShare": round(interior, 3),
            "aiVolumeShare": round(self._ai_share(ai), 3),
            "rooms": rooms,
            "corridors": corridors,
            "graph": self.graph(),
            "placements": placements,
            "lightColors": lights,
            "surfaceArea": self.surface_mix(),
        }

    def _ai_share(self, vols):
        boxes = []
        for o in vols:
            p, d = np.array(o["props"]["Pos"]), np.array(o["props"].get("Dims", [0, 0, 0]), float)
            if round((o["props"].get("Rotation") or [0, 0, 0, 0])[1] / (np.pi / 2)) % 2:
                d = d[[2, 1, 0]]
            boxes.append((p - d, p + d))
        if not boxes or not self.grid.floor:
            return 0.0
        lo = np.array([b[0] for b in boxes])
        hi = np.array([b[1] for b in boxes])
        hit = 0
        for c, y in self.grid.floor.items():
            x, z = (c[0] + .5) * CELL, (c[1] + .5) * CELL
            if ((lo[:, 0] <= x) & (x <= hi[:, 0]) & (lo[:, 2] <= z) & (z <= hi[:, 2]) &
                    (lo[:, 1] - 40 <= y) & (y <= hi[:, 1] + 24)).any():
                hit += 1
        return hit / len(self.grid.floor)


# ---------------------------------------------------------------- the baseline file


SCHEMA_VERSION = 1
PERCENTILES = (5, 25, 50, 75, 95)


def _pct(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {f"p{p}": round(float(np.percentile(xs, p)), 3) for p in PERCENTILES} | {"n": len(xs)}


def _hue(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return "grey" if s < 0.15 else ["red", "orange", "yellow", "lime", "green", "teal", "cyan", "azure", "blue",
                                     "violet", "magenta", "pink"][int(h * 12 + 0.5) % 12]


def summarize(levels):
    """Percentiles over the interior levels' raw samples."""
    inner = [l for l in levels if l["kind"] == "interior"]
    rooms = [r for l in inner for r in l["rooms"]]
    corridors = [c for l in inner for c in l["corridors"]]
    out = {
        "levels": [l["level"] for l in inner],
        "room": {k: _pct([r[k] for r in rooms]) for k in ("area", "width", "extentShort", "extentLong",
                                                          "ceilingHeight")},
        "corridor": {k: _pct([c[k] for c in corridors]) for k in ("width", "length", "area", "ceilingHeight")},
        "perLevel": {
            "rooms": _pct([l["graph"]["rooms"] for l in inner]),
            "corridors": _pct([l["graph"]["corridors"] for l in inner]),
            "cycles": _pct([l["graph"]["cycles"] for l in inner]),
            "deadEndShare": _pct([l["graph"]["deadEnds"] / max(l["graph"]["rooms"] + l["graph"]["corridors"], 1)
                                  for l in inner]),
            "reachableArea": _pct([l["reachableArea"] for l in inner]),
            "components": _pct([l["graph"]["components"] for l in inner]),
            "largestComponentShare": _pct([l["graph"]["largestComponentShare"] for l in inner]),
            "largestComponentDiameter": _pct([l["graph"]["largestComponentDiameter"] for l in inner]),
        },
        "degree": {
            "room": _pct([d for l in inner for d in l["graph"]["roomDegree"]]),
            "corridor": _pct([d for l in inner for d in l["graph"]["corridorDegree"]]),
        },
        "objectsPer100m2": {k: _pct([r["objects"][k] / r["area"] * 100 for r in rooms if r["area"] > 0])
                            for k in (*CATEGORIES, "door")},
    }
    place = {}
    for l in inner:
        for cat, counts in l["placements"].items():
            for where, n in counts.items():
                place.setdefault(cat, {}).setdefault(where, 0)
                place[cat][where] += n
    out["placementShare"] = {cat: {k: round(v / max(sum(c.values()), 1), 3) for k, v in c.items()}
                             for cat, c in place.items()}
    hues = {}
    for l in inner:
        for rgb in l["lightColors"]:
            hues[_hue(rgb)] = hues.get(_hue(rgb), 0) + 1
    out["lightHueShare"] = {k: round(v / max(sum(hues.values()), 1), 3) for k, v in sorted(hues.items())}
    surf = dict.fromkeys(surfaces.FAMILIES, 0.0)
    for l in inner:
        for k, v in l["surfaceArea"].items():
            surf[k] += v
    out["surfaceShare"] = {k: round(v / max(sum(surf.values()), 1e-9), 3) for k, v in surf.items()}
    return out


def main():
    extracted, out = sys.argv[1], sys.argv[2]
    paths = sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat")))
    levels = []
    for p in paths:
        name = os.path.basename(p)[:-4]
        if name.endswith("cin"):
            continue
        r = LevelMeasure(dat85.load(p), name).result()
        if "graph" in r:
            print(f"{name:8s} {r['kind']:8s} {r['reachableArea']:9.0f} m2  rooms {r['graph']['rooms']:3d}  "
                  f"corridors {r['graph']['corridors']:3d}  ai {r['aiVolumeShare']:.2f}", flush=True)
        else:
            print(f"{name:8s} {r['kind']:8s} {r['note']}", flush=True)
        levels.append(r)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": {"repo": "rholdorf/tron_explorer", "commit": commit, "tool": "tools/baseline.py",
                       "source": "Tron 2.0 retail single-player levels (cinematics left out)"},
        "units": {"length": "m", "area": "m2", "metresPerUnit": METRES},
        "method": {"cellUnits": CELL, "coreCells": CORE, "edgeCells": EDGE, "interiorThreshold": INTERIOR, "minAreaM2": MIN_AREA,
                   "stepUnits": STEP, "headroomUnits": HEADROOM, "maxCells": MAX_CELLS},
        "baseline": summarize(levels),
        "levels": levels,
    }
    with open(out, "w") as f:
        json.dump(doc, f, indent=1, default=float)
        f.write("\n")


if __name__ == "__main__":
    main()
