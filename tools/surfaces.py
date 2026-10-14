"""Surface families: what kind of surface a world triangle is (floor-interior, floor-exterior, wall, ceiling,
glass, emissive), for the style baseline and the bench glTF that the sibling project mus-y-sinak reads.

Orientation gives floor / wall / ceiling (|normal.y| >= 0.7, the walkable slope); a floor is interior when
the first thing straight above it is geometry, not sky. The material wins over orientation: a world model
drawn Translucent is glass, one drawn Additive is emissive. Render triangles carry no surface flags of their
own (their poly ids don't map onto the physics BSP's polygons), so the material comes from the owning world
model's BlendMode. A fullbright texture is no sign of a light: most of Tron 2.0's base textures are
fullbright (150 of m01-01's 207), their light baked into the vertex colours."""
import numpy as np

from floor import FloorCaster

FAMILIES = ("floor-interior", "floor-exterior", "wall", "ceiling", "glass", "emissive", "unclassified")
WALKABLE = 0.7


def family(normal, *, covered, blend="None"):
    if blend == "Translucent":
        return "glass"
    if blend == "Additive":
        return "emissive"
    n = np.asarray(normal, np.float64)
    length = np.linalg.norm(n)
    if length < 1e-9:
        return "unclassified"
    y = n[1] / length
    if y >= WALKABLE:
        return "floor-interior" if covered else "floor-exterior"
    if y <= -WALKABLE:
        return "ceiling"
    return "wall"


class CoverCaster:
    """Straight-up casts: a point is covered when the first triangle above it is geometry, not sky."""

    def __init__(self, ceilings, sky):
        flip = np.array([1, -1, 1], np.float64)
        self.ceilings = FloorCaster(np.asarray(ceilings, np.float64).reshape(-1, 3, 3) * flip)
        self.sky = FloorCaster(np.asarray(sky, np.float64).reshape(-1, 3, 3) * flip)

    def covered(self, pos):
        p = np.asarray(pos, np.float64) * np.array([1, -1, 1])
        ceiling = self.ceilings.floor_below(p) if len(self.ceilings.tris) else None
        if ceiling is None:
            return False
        sky = self.sky.floor_below(p) if len(self.sky.tris) else None
        return sky is None or ceiling > sky   # mirrored: the higher value is the lower hit


RENDERED_SHADERS = {1, 4, 8, 9}   # gouraud, lightmap_texture, dualtexture, lightmap_dualtexture (not skypan)


def world_triangles(w):
    """Every drawn world triangle: (verts (n, 3, 3), summed vertex normals (n, 3), texture names (n,),
    owner BlendMode (n,)). The main
    world's render blocks, then each world model's under its object's BlendMode; sky objects are left out."""
    blend = {}
    for o in w.objects:
        name = o["props"].get("Name", "")
        if name and "BlendMode" in o["props"]:
            blend[name.lower()] = o["props"]["BlendMode"]
    sky = {str(o["props"].get("SkyObjectName", "")).lower() for o in w.objects if o["class"] == "SkyPointer"}
    verts, vnormals, texs, modes = [], [], [], []

    def add(blocks, mode):
        for b in blocks:
            i = 0
            for s in b.sections:
                tris = b.tris[i:i + s.tri_count]
                i += s.tri_count
                if s.shader not in RENDERED_SHADERS or not len(tris):
                    continue
                verts.append(b.verts["pos"][tris])
                vnormals.append(b.verts["normal"][tris].sum(1))
                texs.extend([s.textures[0]] * len(tris))
                modes.extend([mode] * len(tris))

    add(w.render.blocks, "None")
    for rw in w.render.world_models:
        if rw.name.lower() not in sky:
            add(rw.blocks, blend.get(rw.name.lower(), "None"))
    if not verts:
        return np.zeros((0, 3, 3)), np.zeros((0, 3)), np.array([], object), np.array([], object)
    return (np.concatenate(verts).astype(np.float64), np.concatenate(vnormals).astype(np.float64),
            np.array(texs, object), np.array(modes, object))


def sky_triangles(w):
    import dat85
    phys = next(b for b in w.bsps if b.flags & dat85.WIF_PHYSICSBSP)
    tris = []
    for surf, _plane, vs in phys.polys:
        if int(phys.surfaces[surf]["flags"]) & dat85.SURF_SKY:
            tris.extend(dat85.fan(phys.points[list(vs)]))
    return np.array(tris, np.float64).reshape(-1, 3, 3)


def classify(w):
    """Family and area (LithTech units²) of every drawn world triangle, in world_triangles order."""
    v, vn, texs, modes = world_triangles(w)
    cross = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    # The winding's handedness isn't the face's side: the vertex normals say which way it faces.
    cross *= np.where((cross * vn).sum(1) < 0, -1.0, 1.0)[:, None]
    area = 0.5 * np.linalg.norm(cross, axis=1)
    normal = cross / np.maximum(2 * area, 1e-12)[:, None]
    ceilings = v[normal[:, 1] <= -WALKABLE]
    caster = CoverCaster(ceilings, sky_triangles(w))
    centroid = v.mean(1)
    fams = []
    for k in range(len(v)):
        up = normal[k, 1] >= WALKABLE and modes[k] not in ("Translucent", "Additive")
        covered = caster.covered(centroid[k] + (0, 1, 0)) if up else True
        fams.append(family(normal[k], covered=covered, blend=modes[k]))
    return np.array(fams, object), area
