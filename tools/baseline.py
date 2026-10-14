"""Style baseline: what Tron 2.0's single-player levels look like as numbers (room sizes, room graph,
surface family mix, object density, light), for the sibling project mus-y-sinak. See
docs/research/style-baseline.md.

Rooms aren't marked in the levels (AIVolumes are floor tiles, AIRegions are AI territories), so they are
derived from the reachable floor: a grid of floor cells, flooded from the start points, cut at doors.
segment() splits it into rooms (the parts wide enough to hold a core) and corridors (the rest)."""
from collections import deque

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
    into a single room, which are alcoves of it. Edges join nodes whose cells touch, or that touch the same door."""
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
        if len(comp) < core * core and len(touching) == 1:   # an alcove of the room it opens into
            r = touching.pop()
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

import numpy as np

import dat85

CELL = 16.0          # grid cell, LithTech units (~27 cm)
STEP = 18            # PlayerController.stepHeight
HEADROOM = 60        # crouched player height: lower ceilings block
WALL_BAND = (20, 90)  # a wall crossing this band above the floor blocks the cell
MAX_CELLS = 400_000  # flood cap: past this a level is an open space, not interiors
DOOR_CLASSES = {"SlidingDoor", "RotatingDoor", "Door"}
DOOR_MIN_HEIGHT = 96
DOOR_MAX_THICKNESS = 64


def _raster_plane(P, n, sink):
    """Cell centres inside convex polygon P (xz projection), with the polygon's height there."""
    lo = np.floor(P[:, [0, 2]].min(0) / CELL).astype(int)
    hi = np.floor(P[:, [0, 2]].max(0) / CELL).astype(int)
    gx, gz = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1), indexing="ij")
    gx, gz = gx.ravel(), gz.ravel()
    cx, cz = (gx + .5) * CELL, (gz + .5) * CELL
    q = P[:, [0, 2]]
    k = len(q)
    area2 = sum(q[i][0] * q[(i + 1) % k][1] - q[(i + 1) % k][0] * q[i][1] for i in range(k))
    s = 1 if area2 > 0 else -1
    inside = np.ones(len(cx), bool)
    for i in range(k):
        a, b = q[i], q[(i + 1) % k]
        inside &= s * ((b[0] - a[0]) * (cz - a[1]) - (b[1] - a[1]) * (cx - a[0])) >= 0
    d = -(n @ P[0])
    ys = -(n[0] * cx + n[2] * cz + d) / n[1]
    for x, z, y in zip(gx[inside].tolist(), gz[inside].tolist(), ys[inside].tolist()):
        sink.setdefault((x, z), []).append(y)


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
        floors, walls, ceils, skies = {}, [], {}, {}
        for surf, plane, vs in phys.polys:
            flags = int(phys.surfaces[surf]["flags"])
            if not flags & dat85.SURF_SOLID or flags & dat85.SURF_NONEXISTENT:
                continue
            n = phys.planes[plane][:3].astype(np.float64)
            P = phys.points[list(vs)].astype(np.float64)
            if flags & dat85.SURF_SKY:
                if abs(n[1]) > 1e-3:
                    _raster_plane(P, n, skies)
            elif n[1] >= 0.7:
                _raster_plane(P, n, floors)
            elif n[1] <= -0.7:
                _raster_plane(P, n, ceils)
            else:
                walls.append(P)
        self.walls = WallIndex(walls)
        self.ceils = {k: np.array(v) for k, v in ceils.items()}
        self._cache = {}
        self.skies = {k: np.array(v) for k, v in skies.items()}
        layers = {k: sorted({round(y) for y in ys}) for k, ys in floors.items()}
        # Seeds: the start and teleport points, and every AI volume's floor (the designers' own mark of
        # walkable floor), which reaches the parts joined only by elevators or teleports.
        self.starts = [o["props"]["Pos"] for o in w.objects if o["class"] in ("GameStartPoint", "TeleportPoint")]
        for o in w.objects:
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
                    for y in layers.get(kk, []):
                        if s[1] - 200 <= y <= s[1] + 10 and (*kk, y) not in self.floor and self._ok(kk, y):
                            self.floor[(*kk, y)] = y
                            q.append((*kk, y))
        while q:
            c = q.popleft()
            n = []
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                kk = (c[0] + dx, c[1] + dz)
                for y in layers.get(kk, []):
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
            above = self.ceils.get(c[:2])
            ceil = above[above > y + 1].min() if above is not None and (above > y + 1).any() else None
            sky = self.skies.get(c[:2])
            sky = sky[sky > y + 1].min() if sky is not None and (sky > y + 1).any() else None
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
        c = self.ceils.get(k)
        return c is None or not ((c > y + 1) & (c < y + HEADROOM)).any()

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
            for c, y in self.floor.items():
                x, z = (c[0] + .5) * CELL, (c[1] + .5) * CELL
                if lo[0] <= x <= hi[0] and lo[2] <= z <= hi[2] and lo[1] - 40 <= y <= lo[1] + 40:
                    out.add(c)
        return out
