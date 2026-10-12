"""How the LithTech D3D renderer lights a model (ModelDraw::SetupModelLight, setupmodel.cpp): an
ambient term from the light grid plus up to MaxModelLights lights, the rest folded into ambient.
The viewer does the same per instance (LevelBuilder / ModelLighting.cs); this is the reference.
See docs/research/light-grid.md.
"""
import math

import numpy as np


def is_black(color):
    """SLightGroup::IsBlack: any channel below 1/255 counts as off."""
    return any(c < 1.0 / 255.0 for c in color)


def with_light_groups(grid, groups):
    """A copy of the grid with the lit groups' samples added at their current color
    (CLightTable::AddLightGroupSamples does it per lookup on the 8 corners; baking it into the nodes
    is the same except that sums clamp at 255 per node instead of after interpolation)."""
    acc = grid.data.astype(np.float32)
    dz, dy, dx = acc.shape[:3]
    for lg in groups:
        if is_black(lg.color):
            continue
        x0, y0, z0 = lg.min
        s = lg.samples.astype(np.float32)[..., None] * np.array(lg.color, np.float32)
        # Clip the group box to the grid.
        sz, sy, sx = (slice(max(0, -m), max(0, min(n, d - m))) for m, n, d in
                      ((z0, s.shape[0], dz), (y0, s.shape[1], dy), (x0, s.shape[2], dx)))
        s = s[sz, sy, sx]
        z, y, x = max(0, z0), max(0, y0), max(0, x0)
        acc[z:z + s.shape[0], y:y + s.shape[1], x:x + s.shape[2]] += s
    out = type(grid)()
    out.base, out.cell, out.dims = grid.base, grid.cell, grid.dims
    out.data = np.minimum(acc, 255).astype(np.uint8)
    return out


def euler_forward(rot):
    """gr_GetEulerVectors forward axis of (pitch, yaw, roll) radians (gr_SetupMatrixEuler column 2)."""
    p, y = rot[0], rot[1]
    return [math.cos(p) * math.sin(y), -math.sin(p), math.cos(p) * math.cos(y)]


def light_group_colors(w):
    """Initial color (0-1) of each light group by name, from the render blocks and the grid."""
    colors = {}

    def walk(rw):
        for b in rw.blocks:
            for lg in b.light_groups:
                colors.setdefault(lg.name, tuple(lg.color))
        for sub in rw.world_models:
            walk(sub)
    walk(w.render)
    for lg in w.grid_light_groups:
        colors.setdefault(lg.name, tuple(lg.color))
    return colors


STATIC_LIGHT_CLASSES = ("Light", "DirLight", "ObjectLight")


def static_lights(objects, group_colors):
    """CWorldSharedBSP::AddStaticLights: the light objects that light models directly, in file order.
    Only LightObjects lights with FastLightObjects off qualify; a light without a FastLightObjects
    property inherits the last value seen (starting at on), as the engine's loop does."""
    out = []
    fast = True
    for o in objects:
        if o["class"] not in STATIC_LIGHT_CLASSES:
            continue
        p = o["props"]
        if "FastLightObjects" in p:
            fast = bool(p["FastLightObjects"])
        if not p.get("LightObjects", True) or fast:
            continue
        color = p.get("LightColor", p.get("InnerColor", [0.0, 0.0, 0.0]))
        scale = p.get("BrightScale", 1.0) * p.get("ObjectBrightScale", 1.0)
        group = p.get("LightGroup", "")
        gc = group_colors.get(group, (1.0, 1.0, 1.0)) if group else (1.0, 1.0, 1.0)
        radius = p.get("LightRadius", 0.0)
        coefs = p.get("AttCoefs", [1.0, 0.0, 19.0])
        exps = p.get("AttExps", [0.0, -1.0, -2.0])
        out.append({
            "name": p.get("Name", ""),
            "cls": o["class"],
            "pos": list(p.get("Pos", [0.0, 0.0, 0.0])),
            "dir": euler_forward(p["Rotation"]) if p.get("Rotation") else [0.0, 0.0, 0.0],
            "color": [c * scale * g for c, g in zip(color, gc)],
            "radius": radius,
            "cosFov": math.cos(p["FOV"] * math.pi / 360.0) if "FOV" in p else -1.0,
            "att": p.get("Attenuation", "D3D"),
            "attCoefs": [c * radius ** e if radius else (c if e == 0 else 0.0) for c, e in zip(coefs, exps)],
            "toAmbient": p.get("ConvertToAmbient", 0.0),
        })
    return out


def _trunc(v):
    return int(v)  # ltfptosi: toward zero


def sample_grid(grid, pos, ltjs_order=False):
    """CLightTable::GetLightVal: trilinear sample (0-255 RGB ints) of the grid at a world position.
    ltjs_order=True lerps Y from the y+1 node to the y node, as ltjs's code reads; the default is the
    textbook order, which fits the baked vertex colors better."""
    data = grid.data
    f = [(pos[i] - grid.base[i]) / grid.cell[i] for i in range(3)]
    c = [max(-1, min(_trunc(f[i]), grid.dims[i] - 1)) for i in range(3)]
    o = [0 if c[i] in (-1, grid.dims[i] - 1) else 1 for i in range(3)]
    x, y, z = (max(0, v) for v in c)
    t = [v - math.floor(v) for v in f]

    def s(dx, dy, dz):
        return data[z + dz * o[2], y + dy * o[1], x + dx * o[0]].astype(np.float32)

    def lerp(a, b, u):
        return a + (b - a) * np.float32(u)

    def ylerp(lo, hi):
        return lerp(hi, lo, t[1]) if ltjs_order else lerp(lo, hi, t[1])

    near = lerp(ylerp(s(0, 0, 0), s(0, 1, 0)), ylerp(s(1, 0, 0), s(1, 1, 0)), t[0])
    far = lerp(ylerp(s(0, 0, 1), s(0, 1, 1)), ylerp(s(1, 0, 1), s(1, 1, 1)), t[0])
    v = np.clip(lerp(near, far, t[2]), 0, 255)
    return tuple(int(c) for c in v)


MODEL_SUN_VARIANCE = 0.05  # ModelSunVariance console variable default


class SkyCaster:
    """Segment casts against the world's polygons for ModelDraw::GetDirLightAmount: a point sees the
    sun if the first polygon toward it is a sky polygon (CastRayAtSky). tris: (n, 3, 3), sky: (n,)."""

    def __init__(self, tris, sky):
        self.v0 = tris[:, 0].astype(np.float64)
        self.e1 = tris[:, 1] - self.v0
        self.e2 = tris[:, 2] - self.v0
        self.sky = np.asarray(sky, bool)
        lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
        self.longest = float(np.linalg.norm(hi - lo)) if len(tris) else 0.0

    @classmethod
    def from_bsp(cls, bsp):
        """The solid polygons of a world BSP (the physics BSP holds the sky polygons)."""
        import dat85
        tris, sky = [], []
        for surf, _plane, vs in bsp.polys:
            flags = int(bsp.surfaces[surf]["flags"])
            if not flags & dat85.SURF_SOLID or flags & dat85.SURF_NONEXISTENT:
                continue
            for k in range(1, len(vs) - 1):
                tris.append((vs[0], vs[k], vs[k + 1]))
                sky.append(bool(flags & dat85.SURF_SKY))
        idx = np.array(tris, np.int64).reshape(-1, 3)
        return cls(np.asarray(bsp.points, np.float64)[idx], np.array(sky, bool))

    def hits_sky(self, start, direction):
        """CastRayAtSky: the segment start .. start + direction (Moller-Trumbore, both faces)."""
        o, d = np.asarray(start, np.float64), np.asarray(direction, np.float64)
        p = np.cross(d, self.e2)
        det = np.einsum("ij,ij->i", self.e1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = o - self.v0
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, self.e1)
        v = (q @ d) * inv
        t = np.einsum("ij,ij->i", self.e2, q) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0) & (t <= 1)
        if not hit.any():
            return False
        i = np.flatnonzero(hit)[np.argmin(t[hit])]
        return bool(self.sky[i])

    def sun_amount(self, pos, sun_dir, right, radius, variance=MODEL_SUN_VARIANCE):
        """ModelDraw::GetDirLightAmount: 0-1, how much of the model sees the sky toward the sun, by
        bisecting between rays from pos +- (sun_dir x right) * radius."""
        pos, sun_dir = np.asarray(pos, np.float64), np.asarray(sun_dir, np.float64)
        ray = sun_dir * -self.longest
        up = np.cross(sun_dir, np.asarray(right, np.float64)) * radius
        top, bottom = self.hits_sky(pos + up, ray), self.hits_sky(pos - up, ray)
        if top == bottom:
            return 1.0 if top else 0.0
        var, f_top, f_bottom, light = 1.0, 1.0, -1.0, 1.0
        while var > variance and top != bottom:
            mid = (f_top + f_bottom) * 0.5
            lit = self.hits_sky(pos + up * mid, ray)
            var *= 0.5
            if not lit:
                light -= var
            if lit == top:
                f_top, top = mid, lit
            else:
                f_bottom, bottom = mid, lit
        return light


def euler_right(rot):
    """gr_SetupMatrixEuler column 0 (the right axis) of (pitch, yaw, roll) radians."""
    p, y, r = rot[0], rot[1], rot[2]
    return [math.cos(r) * math.cos(y) + math.sin(r) * math.sin(p) * math.sin(y), math.sin(r) * math.cos(p),
            -math.cos(r) * math.sin(y) + math.sin(r) * math.sin(p) * math.cos(y)]


def sun_light(objects):
    """The level's StaticSunLight as the client gets it (sm_TellClientAboutGlobalLight): direction
    = forward of its rotation, color = InnerColor * BrightScale * ObjectBrightScale. None if absent
    or black (SetupModelLight skips a black sun)."""
    for o in objects:
        if o["class"] != "StaticSunLight":
            continue
        p = o["props"]
        scale = p.get("BrightScale", 1.0) * p.get("ObjectBrightScale", 1.0)
        color = [c * scale for c in p.get("InnerColor", [0.0, 0.0, 0.0])]
        if not any(color):
            return None
        return {"dir": euler_forward(p.get("Rotation") or [0.0, 0.0, 0.0]), "color": color,
                "toAmbient": p.get("ConvertToAmbient", 0.0)}
    return None


DIRECTIONAL_COS_FOV = 0.98  # retail StaticLightCB [0x58d9e4]: spots with cos(FOV/2) above it are directional
MAX_MODEL_LIGHTS = 4  # MaxModelLights console variable default; Tron's autoexec.cfg doesn't set it


def light_sample(lt, pos):
    """CRenderLight::GetLightSample of a static light (point or spot) at a position (0-255 RGB)."""
    v = [pos[i] - lt["pos"][i] for i in range(3)]
    d2 = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
    r = lt["radius"]
    if d2 >= r * r:
        return [0.0, 0.0, 0.0]
    d = math.sqrt(d2)
    att = lt["att"].lower()
    if att == "quartic":
        k = (1.0 - d2 / (r * r)) ** 2
    elif att == "linear":
        k = 1.0 - d / r
    else:
        a = lt["attCoefs"]
        k = 1.0 / (a[0] + a[1] * d + a[2] * d2)
    if lt["cosFov"] > -0.99:  # spot (StaticLightCB)
        if d == 0:
            return [0.0, 0.0, 0.0]
        dot = (v[0] * lt["dir"][0] + v[1] * lt["dir"][1] + v[2] * lt["dir"][2]) / d
        if dot <= lt["cosFov"]:
            return [0.0, 0.0, 0.0]
        k *= (dot - lt["cosFov"]) / (1.0 - lt["cosFov"])
    return [c * k for c in lt["color"]]


def _device_light(lt, pos, dims):
    """CRenderLight::CreateDeviceLight -> (direction the light travels, color 0-255). Every static
    light becomes a directional light: quartic/linear points sampled at the model
    (CreateSampledDirLight), spots at the brightest of the center and the 8 dims-box corners
    (CreateMultiSampledDirLight). The engine keeps D3D-attenuation points as D3D point lights; no
    retail static light uses that model, so they're sampled like the others here."""
    if lt.get("directional"):
        return lt["dir"], lt["color"]
    color = light_sample(lt, pos)
    if lt["cosFov"] > -0.99:
        best = sum(c * c for c in color)
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    c = light_sample(lt, (pos[0] + dims[0] * sx, pos[1] + dims[1] * sy, pos[2] + dims[2] * sz))
                    m = sum(x * x for x in c)
                    if m > best:
                        best, color = m, c
    d = [pos[i] - lt["pos"][i] for i in range(3)]
    n = math.sqrt(sum(x * x for x in d)) or 1.0
    return [x / n for x in d], color


def model_lighting(grid, pos, dims, vis_radius, lights, sun=None, sun_amount=0.0, ltjs_order=False,
                   max_lights=MAX_MODEL_LIGHTS):
    """ModelDraw::SetupModelLight for a model instance at `pos` (half-extents `dims`, model
    VisRadius `vis_radius`): {"ambient": 0-255 RGB ints (the D3D ambient light), "lights": up to
    max_lights {"dir": unit direction the light travels, "color": 0-255 RGB}}.
    sun = {"dir", "color", "toAmbient"} (StaticSunLight), lit by `sun_amount` (GetDirLightAmount)."""
    ambient = [0.0, 0.0, 0.0]
    slots = []  # CRelevantLightList: [(score, light)], strongest first

    def insert(lt, to_ambient):
        # CRelevantLightList::InsertLight
        sample = list(lt["color"]) if lt.get("directional") else light_sample(lt, pos)
        score = max(sample) * (1.0 - to_ambient)
        i = next((k for k, (s, _) in enumerate(slots) if score > s), len(slots))
        if i >= max_lights:
            for c in range(3):
                ambient[c] += sample[c]
            return
        if len(slots) >= max_lights:
            _, out = slots.pop()
            for c, x in enumerate(light_sample(out, pos) if not out.get("directional") else out["color"]):
                ambient[c] += x
        kept = dict(lt, color=[c * (1.0 - to_ambient) for c in lt["color"]])
        slots.insert(i, (score, kept))
        for c in range(3):
            ambient[c] += to_ambient * sample[c]

    if sun is not None and any(sun["color"]):
        insert({"directional": True, "dir": list(sun["dir"]), "color": [c * sun_amount for c in sun["color"]]},
               sun["toAmbient"])
    for c, x in enumerate(sample_grid(grid, pos, ltjs_order)):
        ambient[c] += x
    for lt in lights:
        r = lt["radius"]
        # FindObjectsInBox2: the light's box (pos +- radius) touches the model's (pos +- VisRadius).
        if any(abs(lt["pos"][i] - pos[i]) > r + vis_radius for i in range(3)):
            continue
        if all(c < 1.0 for c in lt["color"]):  # StaticLightCB early out
            continue
        if lt["cosFov"] > DIRECTIONAL_COS_FOV:
            # Retail Lithtech.exe StaticLightCB (0x54f2cb), not in ltjs: a spot narrower than this is
            # set up as a directional light along its direction, at full color wherever the model is.
            insert({"directional": True, "dir": list(lt["dir"]), "color": list(lt["color"])}, lt["toAmbient"])
        else:
            insert(lt, lt["toAmbient"])
    out = []
    for _, lt in slots:
        d, color = _device_light(lt, pos, dims)
        if any(c > 0 for c in color):
            out.append({"dir": d, "color": color})
    # CDeviceLightList::SetAmbientColor: clamp to 255 and truncate.
    return {"ambient": tuple(int(min(255.0, c)) for c in ambient), "lights": out}
