# Light grid format and how the engine lights models

Research for issue #3 (map #1). Question: what is the layout of the DAT v85 light grid section,
and how does the LithTech renderer turn it, plus anything else, into model lighting? Does it add
dynamic level lights to models?

Primary source: `bibendovsky/ltjs` at commit
[`46aca18`](https://github.com/bibendovsky/ltjs/tree/46aca1800c8b8d6761bc9314dcd8330f82c77998).
Its engine and the Tron 2.0 game code (`game/*/tron`) are LithTech Jupiter source.
Links below are abbreviated as `ltjs:<path>#L<n>`, which means
`https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/<path>#L<n>`.
Every layout claim was checked against all 63 retail `.dat` files in `extracted/worlds/` with
throwaway scripts (see [Verification](#verification)).

## 1. Binary layout

### 1.1 Light grid (`lgrid_pos`, the 3rd header offset)

Reader: `CLightTable::Load` (`ltjs:engine/runtime/world/src/light_table.cpp#L82`), called from
`CWorldSharedBSP::LoadLightGrid` after `SeekTo(lightgrid_pos)`
(`ltjs:engine/runtime/world/src/world_shared_bsp.cpp#L320`).

| Offset | Type | Field |
|---|---|---|
| +0 | `float[3]` | `base`: world position of grid node (0,0,0) |
| +12 | `float[3]` | `cell`: node spacing per axis (the engine stores `1/cell`) |
| +24 | `int32[3]` | `dims`: node count in x, y, z |
| +36 | `uint32` | compressed byte count (the engine reads it but doesn't use it) |
| +40 | bytes | RLE stream that decompresses to `dims.x*dims.y*dims.z*3` bytes |

- **RLE** (`Load_RLE_DeCompress`, `light_table.cpp#L43`): this is the same TGA-style scheme as the
  lightmaps (`dat85.decompress_lightmap` can be reused). Each tag byte has a count
  `n = (tag & 0x7F) + 1`. If the high bit is set, one RGB triple follows and is repeated `n` times.
  Otherwise `n` raw RGB triples follow.
- **Memory order:** `index = ((z*dims.y + y)*dims.x + x)*3`, so x varies fastest, then y, then z.
  The bytes are **R,G,B** (`LTRGB_TO_VECTOR`, `light_table.cpp#L5`). Values run 0–255 in the same
  scale as a D3D color byte.
- **In the retail data:** `base == ext_min` from the world header in every file. `cell` is uniform
  per level: 250, 512, 1024, 2048, 4096 or 8192 units (m01-01 uses 1024).
  `dims = floor((ext_max-ext_min)/cell) + 1`. For m01-01 that gives `13×17×14`, so the grid covers
  the world box. The RLE stream ends exactly at `coll_pos` in all 63 files, and the compressed
  size field matches in all 63. The world offset (`w.offset`) plays no part: the engine reads it
  only for texture scripts (`GetSourceWorldOffset`).
- Most nodes are black because they lie in solid space or outside the playable volume.
  m01-01 averages about (4, 4, 5), with a maximum of 255.

### 1.2 World light groups (after the render section)

`CWorldClientBSP::LoadRenderData` (`ltjs:engine/runtime/client/src/world_client_bsp.cpp#L363`)
reads the render world first (what `dat85.read_render_world` parses). It then reads the light-grid
"fix-ups" of the switchable light groups (`LoadLightGroup`, `light_table.cpp#L235`):

```
uint32 count
repeat count:
    uint16 len; char name[len]   # ID = fold(id*31 + byte) over the name (CClientLightGroup::Load, #L62)
    float  color[3]              # current color, 0–1 per channel (same name/color as the render-block groups)
    int32  min[3]                # first grid node covered, in light-grid coordinates
    int32  ext[3]                # node count per axis
    uint8  samples[ext.x*ext.y*ext.z]   # intensity, x fastest then y then z
```

The section ends exactly at EOF in all 63 files (`render_end` → EOF). Only 5 levels have any:
intro (3), m05-01 (2), m05-04 (1), m07-01cin (3), m08-01 (1). Each sample counts as
`color * sample` (0–255 scale) and is added to the base grid (see §2.1). When a script changes a
group's color, `SetLightGroupColor` (`light_table.cpp#L273`) updates it in the grid.

## 2. How a model is lit (D3D renderer)

Entry point: `ModelDraw::SetupModelLight`
(`ltjs:engine/runtime/render_a/src/sys/d3d/setupmodel.cpp#L267`). It runs once per **root**
model instance per frame. Attachments copy their parent's device light list (`setupmodel.cpp`,
`QueueAllModelInfo`).

### 2.1 Sample point and interpolation

- **Sample point:** the instance position (`pInstance->GetPos()`), so one sample per model, not
  per vertex. The console variable `ModelLightingSkipRootNode` (default 0; Tron's `autoexec.cfg`
  doesn't set it) would use the root's first child node instead.
- **Lookup:** `CLightTable::GetLightVal` (`light_table.cpp#L107`):
  1. `f = (pos - base) / cell`. The grid coordinate is `trunc(f)` clamped to `[-1, dims-1]`.
     On the last node, or below 0, the +1 neighbour on that axis collapses onto the same node.
     Negative coordinates are then raised to 0. The fraction is `f - floor(f)`.
  2. It fetches the 8 corner nodes.
  3. It adds every active light group's samples to those corners (`AddLightGroupSamples`,
     `#L175`). A group counts as "black" and is skipped if **any** channel of its color is below
     1/255 (`IsBlack`, `light_table.h#L103`). That's an OR, so a pure-red group also counts as
     off. It's a quirk, but it's what the code does.
  4. It interpolates **trilinearly**, clamps to 0–255 and returns RGB. If there is no grid, it
     returns 128 grey.
- **Y-axis quirk.** As written, the Y lerp goes from the `y+1` node to the `y` node by `fy`
  (`VEC_LERP(ySamples[0], samples[0], samples[2], fSamplePt.y)`, `#L162`; `samples[0]` is
  `(x,y+1,z)`). That mirrors the interpolation inside each cell vertically. X and Z use the
  normal order. Tested against the data (correlation between the grid sample 32 units off a world
  vertex and that vertex's baked color, over 4000 vertices per level), the **textbook order fits
  better in all 5 levels tested**:

  | level | engine order | textbook order |
  |---|---|---|
  | m01-01 | -0.04 | 0.27 |
  | m02-03 | 0.27 | 0.34 |
  | m03-01 | 0.29 | 0.55 |
  | m04-02 | 0.02 | 0.39 |
  | m09-03 | 0.14 | 0.20 |

  The difference at prop positions is large: the mean over a level's props is 10–40 out of 255,
  and the maximum is up to 228. This evidence can't tell whether the retail `Lithtech.exe` has
  the same code as ltjs. **Recommendation:** implement the textbook trilinear order and keep a
  one-line switch to the ltjs order. Settle the choice against the reference screenshots.

### 2.2 What is summed for a model

`SetupModelLight` builds a `CRelevantLightList` holding an **ambient** term and at most
`MaxModelLights` real lights. That console variable defaults to 4
(`rendererconsolevars.h#L185`), and Tron's `autoexec.cfg` doesn't set it. Contributions are added
in this order:

1. **Sun** (`#L335`): this applies only if the level has a `StaticSunLight` and the console
   variable `ModelApplySun` is set (default 1). The color is `InnerColor * BrightScale *
   ObjectBrightScale` (`sm_TellClientAboutGlobalLight`,
   `ltjs:engine/runtime/server/src/s_client.cpp#L1574`) and the direction is the object's
   forward vector. The amount is 0–1, from rays toward the sky (`GetDirLightAmount`: it hits a
   `SURF_SKY` poly or it doesn't, subdivided across the model's height). It becomes a D3D
   directional light. 8 levels have one: dm-03, discarena03, m02-04, m06-03, m06-04, m09-01,
   m09-03, m10-01.
2. **Light grid** (`#L375`): the `GetLightVal` RGB goes into the ambient term as is (0–255).
   This is the floor that ticket #8 builds on.
3. **Dynamic lights** (`#L393`): **every** visible `OT_LIGHT` object (`g_ObjectDynamicLights`,
   filled by `d3d_ProcessLight`, `drawlight.cpp#L13`, when `DynamicLight` is 1, the default and
   Tron's setting) is skipped only if it has `FLAG_ONLYLIGHTWORLD`. It becomes a point light
   with D3D attenuation `(1, 0, 19/r²)` and range `r`. `DynamicLightWorld` defaults to 0, so by
   default these light **models only**, not the world.
4. **Static object lights** (`#L414`, `StaticLightCB` `#L114`): these are `Light`, `DirLight` and
   `ObjectLight` objects from the DAT object list. They're found in the world tree inside the box
   `pos ± model VisRadius`. The engine builds them at load time in `AddStaticLights`
   (`ltjs:engine/runtime/world/src/world_shared_bsp.cpp#L439`), but **only when
   `LightObjects` is true and `FastLightObjects` is false** (`#L652`). Lights with
   `FastLightObjects=1` (the class default) reach models only through the light grid.
   - Color is `LightColor` (or `InnerColor`) × `BrightScale` × `ObjectBrightScale`, multiplied by
     the light group's color if the light has a `LightGroup`.
   - Attenuation coefficients are `AttCoefs * radius^AttExps`. The `Attenuation` string selects
     the model: `D3D`, `Linear` or `Quartic`.
   - `FOV` > -0.99 makes it a spot: `cos(FOV/2)`, with direction = forward of `Rotation`
     (Euler).

All lights go through `CRelevantLightList::InsertLight`
(`ltjs:engine/runtime/render_a/src/sys/d3d/relevantlightlist.cpp#L21`):

- A light's score is the max channel of its intensity at the instance position, times
  `(1 - ConvertToAmbient)`.
- The top `MaxModelLights` become D3D lights scaled by `(1 - ConvertToAmbient)`. The engine adds
  `ConvertToAmbient × sample` to the ambient term.
- Lights that don't make the cut are **added to the ambient term** at their sampled intensity.

The intensity at a point comes from `CRenderLight::GetLightSample` (`renderlight.cpp#L259`):

- Zero beyond the radius.
- Quartic: `(1 - d²/r²)²`. Linear: `1 - d/r`. D3D: `1/(a + b·d + c·d²)`.
- Spots are also multiplied by `(dot - cosFOV)/(1 - cosFOV)` inside the cone and are zero
  outside it.

### 2.3 How the device applies it

- **Point lights.** D3D-attenuation point lights stay real D3D point lights. Quartic and linear
  point lights become a directional light from the light toward the object, colored by the sample
  at the object position (`CreateSampledDirLight`, `#L209`).
- **Spots.** Spots become a directional light colored by the brightest sample among the center
  and the 8 corners of the model's dims box (`CreateMultiSampledDirLight`, `#L219`).
- **Final color.** The device draws with fixed-function `D3DRS_LIGHTING = TRUE`
  (`rendermodelpiecelist.cpp#L376`), lit per vertex (Gouraud) with the vertex normals:
  `emissive + matAmbient·ambient/255 + Σ matDiffuse·light/255·max(0, N·L)`.
  The material is the render style's `LightingMaterial` (render-style ticket #2). The default
  style uses ambient 1 and diffuse 0.8.
- **Ambient clamp and per-instance color.** At queue time the engine clamps the ambient term to
  255 per channel (`devicelightlist.cpp#L67`). Then `AddAmbientAndScale(LightAdd, ObjectColor/255)`
  (`setupmodel.cpp#L633`) adds the hook's `LightAdd` to the ambient term and scales the ambient
  term and every light by the instance color.
  - `LightAdd` defaults to the `ModelAdd` console command. Tron's `autoexec.cfg` ends with
    `ModelAdd 0 0 0`; the earlier `"ModelAdd" "50 50 50"` line is a dead variable, because
    `con_ModelAdd` is a command.
  - Tron's `DefaultModelHook` (`ltjs:game/clientshelldll/clientshellshared/gameclientshell.cpp`)
    overrides `LightAdd` for objects flagged `USRFLG_GLOW` (a pulsing 50–255 glow) or
    `USRFLG_MODELADD` (color in the top 3 bytes of the user flags). Both flags are gameplay
    state, not level data.
  - `Saturate 1` multiplies `ObjectColor` by `ModelSaturation`, which defaults to 1.
- **Switches.** Lighting is off (ambient 255, no lights) if the console variable `LightModels` is
  0 or the object has `FLAG_NOLIGHT`.

## 3. What the retail levels contain

The survey covers all 63 `.dat` files.

- **Static object lights** (LightObjects=1, FastLightObjects=0): 232 in total: 205 `DirLight`,
  20 `Light` and 7 `ObjectLight`, all `Attenuation "Quartic"`, 18 of them inside a light group.
  The other ~10,000 light objects are grid-only: 4,019 `Light` and 98 `DirLight` with
  FastLightObjects=1, and the rest with LightObjects=0.
  - Nearly every level has three `DirLight`s named **`GlobalLightHigh/Medium/Low`**: about 80,000
    units out, radius 200,000, `FOV 5`, InnerColor around 110–180 grey. That's a 2.5° half-angle
    cone. In m01-01, m03-01, m04-02 and m06-01 they reach almost no prop: 0–8 props fall inside
    a cone, and the mean contribution is 0–8 out of 255. Per the ltjs code they're therefore
    nearly inert for models. Check this against the screenshots before dropping them.
  - Real local object lights are rare. One example is m06-01's 7 `StreetLamp*.Light02` spots
    (radius 600) and 2 point `Light`s.
- **Dynamic light sources placed in levels:** none of the `ClientLightFX` family
  (`FlickerLight`, `GlowingLight`, `*WaveLightFX`) and no `SearchLight`. There is exactly one
  `Lightning` object (m05-04). Everything else that makes `OT_LIGHT` at runtime is gameplay:
  muzzle flash (`MuzzleLight 1`), projectiles, ClientFX `DynaLight`, flashlight.
- **`LightGroup` game objects** (16, in m01-02, intro, m07-01cin, m05-01, m05-04, m08-01) switch
  the groups at runtime. That is behavior; at load time use the initial color stored in the file.

## 4. Answer for the map

- The **light grid** is a per-instance ambient term: one trilinear sample at the model's
  position, with the light-group deltas added. It fully defines a model's lighting in most
  levels.
- **Dynamic lights do add to models.** By default every runtime `OT_LIGHT` lights models and not
  the world. But the levels place almost none: one `Lightning`. The rest come from gameplay, so
  they belong to the behavior effort.
- What **level** lights add on top of the grid is the **static object lights**:
  `Light`/`DirLight`/`ObjectLight` with `LightObjects=1, FastLightObjects=0`, plus
  `StaticSunLight` (8 levels, with a sky-visibility test). They're few: about 3 far "GlobalLight"
  spots per level, which by the ltjs code light almost nothing, plus a handful of local lamps.
  Including them is cheap: up to 4 directional/point lights per instance, the rest folded into
  ambient. Leaving them out changes little except where local lamps exist (for example m06-01).

## Verification

Throwaway scripts (in the session scratchpad, not committed) used `tools/dat85.py`:

- Parsed the grid of all 63 levels: the compressed size field matched, the stream ended at
  `coll_pos`, and `base == ext_min` with full coverage.
- Parsed the world light groups after `render_end`: the section ended at EOF.
- Ported `GetLightVal` (both Y orders) and sampled it at every prop/character position. Nearly every
  prop was inside the grid. The exceptions were m07-03 (7 of 39), `intro` and some `*cin` levels.
- Correlated the samples with baked vertex colors (the table in §2.1).
- Surveyed the light classes and their `LightObjects`/`FastLightObjects` flags.

Reference sampler (engine semantics, textbook Y order):

```python
def light_val(g, base, cell, dims, pos):  # g: uint8[z][y][x][3]
    f = [(pos[i] - base[i]) / cell[i] for i in range(3)]
    c = [max(-1, min(int(f[i]), dims[i] - 1)) for i in range(3)]
    o = [0 if c[i] in (-1, dims[i] - 1) else 1 for i in range(3)]
    x, y, z = (max(0, v) for v in c)
    t = [v - math.floor(v) for v in f]
    s = lambda dx, dy, dz: g[z + dz*o[2], y + dy*o[1], x + dx*o[0]].astype(float)
    L = lambda a, b, u: a + (b - a) * u
    lo = L(L(s(0,0,0), s(1,0,0), t[0]), L(s(0,1,0), s(1,1,0), t[0]), t[1])
    hi = L(L(s(0,0,1), s(1,0,1), t[0]), L(s(0,1,1), s(1,1,1), t[0]), t[1])
    return np.clip(L(lo, hi, t[2]), 0, 255)
```

## Open questions

- Retail `Lithtech.exe` versus the ltjs Y-lerp order (§2.1). Settle it with a screenshot of a
  prop that sits between two grid nodes with different light, or by disassembling
  `GetLightVal`.
- Whether the retail engine really makes the `GlobalLight*` spots this narrow (FOV 5 → 2.5°
  half-angle).
