"""MoveToFloor (MoveObjectToFloor, serverutilities.cpp in ltjs): an object casts a segment 10000 units
straight down from its position; if the floor it hits is farther away than its dims.y (its half-height,
the model origin being mid-body), it drops to hit.y + dims.y + 0.1. It never moves up.

The cast (IntersectSegment, IGNORE_NONSOLID | INTERSECT_HPOLY) hits the physics BSP and solid world
models. Polygons are hit from their front side only, so a downward cast sees floors (planes facing up)."""
import numpy as np

import dat85

DROP = 10000.0
# World model classes that collide like solid brushes, and brush volumes (never drawn, never solid).
# Kept in step with LevelBuilder.SolidClasses / HiddenClasses in the viewer.
SOLID_CLASSES = {c.lower() for c in (
    "WorldModel", "SlidingDoor", "RotatingDoor", "Door", "SlidingWorldModel", "RotatingWorldModel",
    "SpinningWorldModel", "SlidingSwitch", "RotatingSwitch", "Breakable", "DemoSkyWorldModel")}
HIDDEN_CLASSES = {c.lower() for c in (
    "DynamicOccluderVolume", "VolumeBrush", "EndlessFall", "SafteyNet", "Wind", "Electricity", "EnergyZone",
    "LightCycleSlowZone", "LightCycleSpeedZone", "HealthZone")}


def world_model_owners(w):
    """Lower-cased world model name -> the object it belongs to: the first object of that name, or the first
    brush (solid or volume) object of that name when there is one, as LevelBuilder picks it."""
    owners = {}
    for o in w.objects:
        name, c = o["props"].get("Name", ""), o["class"].lower()
        if not name:
            continue
        brush = c in SOLID_CLASSES or c in HIDDEN_CLASSES
        prev = owners.get(name.lower())
        if prev is None or (brush and not (prev["class"].lower() in SOLID_CLASSES or prev["class"].lower() in HIDDEN_CLASSES)):
            owners[name.lower()] = o
    return owners


def place_world_models(w):
    """Moves each brush object to its world model's centre, as the engine does when it binds the two
    (server_extradata.cpp: "Move the OBJECT to the center of the world model geometry", SetPos to the BSP's
    m_WorldTranslation): DEdit's Pos of a world model object is not where it is in the game. Keyframers with
    IgnoreOffsets put that point on their keys, and the object turns about it."""
    owners = world_model_owners(w)
    for b in w.bsps:
        if b.flags & dat85.WIF_PHYSICSBSP:
            continue
        o = owners.get(b.name.lower())
        if o is not None and (o["class"].lower() in SOLID_CLASSES or o["class"].lower() in HIDDEN_CLASSES):
            o["props"]["Pos"] = [float(v) for v in b.translation]


class FloorCaster:
    """Vertical casts against up-facing triangles: tris (n, 3, 3)."""

    def __init__(self, tris):
        tris = np.asarray(tris, np.float64).reshape(-1, 3, 3)
        self.tris = tris
        self.lo = tris[:, :, [0, 2]].min(1)
        self.hi = tris[:, :, [0, 2]].max(1)

    @classmethod
    def from_bsps(cls, bsps):
        """Up-facing solid polygons (fan-triangulated) of the given world BSPs."""
        tris = []
        for b in bsps:
            for surf, plane, vs in b.polys:
                flags = int(b.surfaces[surf]["flags"])
                if not flags & dat85.SURF_SOLID or flags & dat85.SURF_NONEXISTENT or b.planes[plane][1] <= 0:
                    continue
                tris.extend(dat85.fan(b.points[list(vs)]))
        return cls(np.array(tris, np.float64).reshape(-1, 3, 3))

    @classmethod
    def from_world(cls, w):
        """The physics BSP and the world models of solid brush objects (not sky objects)."""
        owners = {k: (o["class"].lower(), o["props"]) for k, o in world_model_owners(w).items()}
        sky = {str(o["props"].get("SkyObjectName", "")).lower() for o in w.objects if o["class"] == "SkyPointer"}
        bsps = []
        for b in w.bsps:
            if b.flags & dat85.WIF_PHYSICSBSP:
                bsps.append(b)
                continue
            c, props = owners.get(b.name.lower(), ("", {}))
            if c in SOLID_CLASSES and props.get("Solid", True) and b.name.lower() not in sky:
                bsps.append(b)
        return cls.from_bsps(bsps)

    def floor_below(self, pos, dist=DROP):
        """Height of the first floor the segment pos .. pos - (0, dist, 0) hits, or None."""
        x, y, z = (float(v) for v in pos)
        near = np.nonzero((self.lo[:, 0] <= x) & (self.hi[:, 0] >= x) &
                          (self.lo[:, 1] <= z) & (self.hi[:, 1] >= z))[0]
        if not len(near):
            return None
        t = self.tris[near]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        # Barycentric coordinates of (x, z) in the triangles' XZ projections.
        v0x, v0z = b[:, 0] - a[:, 0], b[:, 2] - a[:, 2]
        v1x, v1z = c[:, 0] - a[:, 0], c[:, 2] - a[:, 2]
        px, pz = x - a[:, 0], z - a[:, 2]
        den = v0x * v1z - v1x * v0z
        ok = np.abs(den) > 1e-12
        den = np.where(ok, den, 1.0)
        u = (px * v1z - v1x * pz) / den
        v = (v0x * pz - px * v0z) / den
        eps = 1e-9
        inside = ok & (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps)
        h = a[:, 1] + u * (b[:, 1] - a[:, 1]) + v * (c[:, 1] - a[:, 1])
        hit = inside & (h <= y) & (h >= y - dist)
        return float(h[hit].max()) if hit.any() else None


def move_to_floor(pos, dims_y, caster):
    """The object's position after MoveObjectToFloor."""
    floor = caster.floor_below(pos) if caster else None
    if floor is None or pos[1] - floor <= dims_y:
        return list(pos)
    return [pos[0], floor + dims_y + 0.1, pos[2]]
