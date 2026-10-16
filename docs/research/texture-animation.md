# How Tron 2.0 animates and scrolls world textures

Ticket #42 (map #41). Question: which world textures on a level change their image or scroll over time,
and how can a tool tell from the extracted files alone? Moving world models (keyframers, spinners) don't
count.

## Answer

A world texture is animated through exactly two mechanisms, and both are set **per render section** in
the `.dat`:

1. **Sprite texture.** The section's texture name ends in `.spr`. The engine loads it as a sprite and
   switches frames over time.
2. **Texture effect.** The section's `effect` string (read by `dat85.read_render_block` as `s.effect`)
   names a texture effect group, `textureeffectgroups/<effect>`. The group's scripts build a texture
   matrix from time every frame, which scrolls, rotates or warps the texture.

Nothing else animates a world texture in the retail data. DTX files have no frames, no world uses the
sky-pan shader or `PanSky`, and no level places a `TextureFX` object.

### The rule

```
animated(texture, section) =
      texture ends in ".spr" and the sprite has 2+ distinct frame files and a frame rate > 0
   or section.effect != "" and the group file exists and one of its evaluated stages
      - is on the base channel (1), or on the env-map channel (3) when the base texture's DTX command
        string has EnvMap and the section shader isn't 8 or 9, and
      - has a script with TSDIRTY_EVERYUPDATE whose matrix changes with time
```

On the retail data, the checks after the first clause of each line remove only two cases (see "Whole
game"). So a tool that only needs a good-enough answer can use
**`texture.endswith(".spr") or section.effect != ""`**. On m01-01 the full rule and this shortcut give
the same result.

The key is (texture, effect), not the texture alone: the same texture can be static in one section and
scrolling in another. On m01-01 this happens with 6 textures, and with 62 (level, texture) pairs across
the game.

## Sources

### Sprites on world sections (ltjs)

- `engine/runtime/render_a/src/sys/d3d/d3d_renderblock.cpp`, `Load`: for each section texture name,
  `IsSpriteTexture` (a `.spr` extension) → `LoadSpriteData`, which loads the sprite and starts a
  `SpriteTracker` (`spr_InitTracker`: `SC_PLAY | SC_LOOP`).
- `d3d_rendershader_base.h` (~line 1190): each time the section is drawn,
  `spr_UpdateTracker(..., frameTime ms)` runs and the section's texture is set to the current frame.
- `engine/runtime/client/src/sprite.cpp` `spr_Create`: `.spr` = `u32 nFrames, u32 frameRate (fps),
  u32 transparent, u32 translucent, u32 colourKey`, then `nFrames × (u16 len, frame DTX path)`. One
  animation, loops. Frame = `(ms / (1000 / rate)) % nFrames`. A sprite with one frame never changes.
- Retail `Lithtech.exe` contains the same strings (`.spr`, `Couldn't find sprite file %s, using
  sprites/default.spr.`).

### Texture effects (ltjs)

- `d3d_renderblock.cpp` `Load` reads the section's effect string after its texture names and shader.
  If it isn't empty: `CTextureScriptMgr::GetInstance(effect)`.
- `texturescriptmgr.cpp` `GetInstance` opens `TextureEffectGroups\<name>` (the same string is in retail
  `Lithtech.exe`). Format: `u32 version (1), u32 stages (max 4)`, then for each stage: `u32 type` (0
  disabled, 1 overridden, 2 evaluated), `u32 channel`; overridden: `u32 source stage`; evaluated:
  `str16 script, u32 n, f32 defaults[n]` (the script's 6 user variables). **A missing file returns NULL,
  so the section has no effect.**
- `texturescriptinterpreter.cpp` `LoadScript` (`.tfs`): `u16 version, u32 skip + names, u32 input,
  u32 output, u32 dirty, u32 nConst, f32 consts, u32 codeLen, code` (4-byte ops over a register file
  that has `time` at 38 and `elapsed` at 39; `texturescriptdefs.h`).
- `texturescriptinstance.cpp` `Evaluate`: a stage is evaluated again only when its script has
  `TSDIRTY_EVERYUPDATE` (or a world-space input) and the frame changed, or when its variables changed.
  Otherwise it runs once, on the first update, and stays fixed.
- Channels (`texturescriptinstance.h`): 0 null, 1 base, 2 detail, 3 env map, 4 lightmap, 5 dual texture.
  World shaders install the base channel (`d3d_rendershader_gouraud.cpp`, `_lightmap.cpp`,
  `_gouraud_fullbright.cpp`: `Install(1, TSChannel_Base)`). They add the env-map channel only in
  their env-map variants, which are picked only when the DTX has `EnvMap`. The dual-texture fallback
  (shaders 8 and 9) ignores `EnvMap` (docs/research/dual-texture.md).
- User variables change only through `TextureFX` (`game/objectdll/objectshared/texturefx.cpp`,
  message `SETVAR <stage> <var> <value>`). Tron's `object.lto` has this class, but **no retail level
  places one** (all 63 worlds scanned), so the defaults in the `.tfg` are the values the game uses.

### Retail data (all scripts)

The 270 `.tfg` files use 8 scripts: `UVPan` (248 stages), `UVRotate` 11, `UVWarble` 8,
`WPos_XYPan` 5, `WPos_XZPan` 2, `WPos_YZPan` 2, `Warble` 1, `WSPosRotateAroundY` 1. Every evaluated
stage has dirty = 3 (every update + variable changed). When run for 20 s at 30 fps, every one of them
changes its matrix. Inputs are UV (most) or world-space position (env-map stages and one base stage).
Decompiled examples:

- `UVPan.tfs`: `m[2] = fmod(time·u0, 1); m[6] = fmod(time·u1, 1)`: scrolls U by `u0` and V by `u1`
  texture repeats per second (defaults are the first two floats in the `.tfg`).
- `UVWarble.tfs`: `m[1] = sin(2π·u0·t)·u2; m[4] = cos(2π·u1·t)·u3` (in the engine, `sin` returns cos and
  `cos` returns sin; see `TextureEffects.cs`): an oscillating shear.

### What was ruled out

- **DTX animation**: none. The v-5 header (`engine/runtime/shared/src/dtxmgr.h`) has no frame or
  animation fields, and its flags (`DTX_FULLBRITE` … `DTX_LUMBUMPMAP`) have no animation flag. No world
  DTX on any level has `m_nSections > 0`.
- **Sky panning**: shader 5 (`skypan`) appears in no retail world (the section shaders found are only 1,
  2, 4 and 8). `WorldProperties.PanSky` is `False` in every level.
- **Scrolling per world model or per object in the `.dat`**: there are no such properties. Scrolling
  is the section's `effect`, and world-model sections carry their own (for example `FF09`'s force-field
  sections). Moving world models are out of scope.
- **Objects that are not world geometry**: `PolyGrid` (9 in the game, none on m01-01) and `ScaleSprite`
  objects animate their own textures, but they aren't world sections.

## Whole game (63 worlds)

The full rule gives the same answer as the shortcut everywhere except here:

| Level | Texture | Effect | Why it's static |
|---|---|---|---|
| retailmultiplayer/discarena/discarena02 | `7glass03.dtx` | `prefab_{xy,xz,yz}_envmap_panfast.tfg` | env-map-only group; the DTX has no `EnvMap`, so the stage is never installed |
| m10-02, m10-04 | `m10q_d46.dtx` | `10hallpitpan.tfg` | group file not in the game data, so `GetInstance` returns NULL |

There are 77 world sprites, all with 2 or more distinct frames and a frame rate above 0.

## m01-01

47 of the 219 drawn texture names are animated in at least one section (58 (texture, effect) pairs,
6,016 of 63,616 triangles). 11 of them are only on the sky objects (`Sky01B01.*`, marked *sky*), which
`surfaces.world_triangles` leaves out of the bench glTF, so **36 are in the bench's scope**. "Mixed"
marks the 6 textures that also have static sections.

| Texture | Mechanism | Where |
|---|---|---|
| `fx/spr/1anim01.spr` … `1anim06.spr` (6) | sprite, 31 frames @ 15 fps | main world; `1anim03` also `start_area_lightfixtures` |
| `fx/spr/1sky01.spr` | sprite 13 @ 4 | *sky* `Sky01B01.Blocks` |
| `fx/spr/1sky02.spr` | sprite 14 @ 2 | *sky* |
| `fx/spr/1sky03.spr` | sprite 17 @ 1 | *sky* |
| `fx/spr/m0101switch.spr` | sprite 9 @ 10 | `M02-03Switch02/05.Inactive00` |
| `fx/spr/m01_01static.spr` | sprite 4 @ 15 | `outer_big_cyl` |
| `fx/spr/m01blinker.spr` | sprite 14 @ 3 | main world |
| `fx/spr/m01detail01.spr` | sprite 15 @ 3 | `M01DetailPanel*` |
| `fx/spr/m01detail02.spr` | sprite 2 @ 1 + `m01detail01.tfg` | `M01DetailPanel*` |
| `fx/spr/m01detail03.spr` | sprite 2 @ 1 | `M01DetailPanel*` |
| `fx/spr/m01detail04.spr` | sprite 17 @ 2 | `M01DetailPanel*` |
| `fx/spr/m01noisefloor.spr` | sprite 2 @ 4 + `m52floorgridpan.tfg` | `Noise02` |
| `fx/spr/worlds/m01/forcefieldm01_1.spr` | sprite 4 @ 12 + `forcefield_pan_up_slow_1.tfg` | `FF09/10/11/17/18` |
| `fx/spr/zipfade.spr` | sprite 12 @ 10 | main world |
| `fx/spr/zipfade2.spr` | sprite 24 @ 15 | main world |
| `m01/courtney/energy/m10c_e01.dtx` | `07pan_5.tfg` | `inner_big_cyl`, `outer_big_cyl` |
| `m01/courtney/labm01x/forcefields/m01_ff04.dtx` | `forcefield_color_pan_up_{uv_pan_crazy_1, env_pan_crazy_2..4}.tfg` (base + env map) | `FF*` |
| `m01/courtney/labm01x/forcefields/m01_ff08.dtx` | `forcefield_color_pan_up_fast_1.tfg` | `FF*` |
| `m01/curtis/digital_wall5.dtx` | `m01_01_slow_pan_up.tfg` | main world |
| `m01/dan/digital_wall2.dtx` | `m01_01_digital_pan`, `m01_01digital_pan2`, `m01_1_digiwall2`, `m01_1_digiwall3` | `IONodeActors00.WorldModel0`, `WorldModel07`, `WorldModel2` |
| `m01/dan/digital_wall3.dtx` | `m01_1digiwall_1.tfg` | `IONodeActors00.WorldModel0`, `WorldModel06` |
| `m01/dan/m01p_w17edit.dtx` (mixed) | `prefabenergy.tfg` | main world |
| `m01/geoff/data2m01_l/detail/m02n_d32.dtx` | `m01datapan01.tfg` | `WorldModel08` |
| `m01/geoff/data2m01_l/detail/m02n_d33.dtx` | `m01datapan02.tfg` | `WorldModel08` |
| `m01/geoff/labm01n/lights/m01n_l20.dtx` | `gridoverlay.tfg` | `M01_TutorialBridge.InterlacePan` |
| `m01/geoff/serverp/base/m01p_b04.dtx` (mixed) | `12infected.tfg` | main world (7 of 2,366 triangles) |
| `m01/geoff/serverp/glass/m01p_g03.dtx` (mixed) | `gridoverlay.tfg` | `M01_TutorialBridge.PanGrad` |
| `m02/curtis/reformating_wall_1.dtx` | `m07_02_panrightslow`, `m02_pan_x_neg` | main world, `KernelControlRoom00.WorldModel1/15` |
| `m02/curtis/reformating_wall_3.dtx` | `m07_03_center_pulse_up.tfg` | `KernelControlRoom00.WorldModel1/15` |
| `m02/curtis/transporter_2a.dtx` (mixed) | `m02_pan_x_neg`, `m02_pan_x_pos` | `KernelControlRoom00.tp_displayWM` |
| `m07/courtney/corruptm07y/base/m07y_b01.dtx` (mixed) | `12infected.tfg` (UVWarble) | main world (1,773 of 4,710 triangles) |
| `m09/courtney/firewallm09x/energy/m09x_e05.dtx` | `m02_panup.tfg` | `KernelControlRoom00.WorldModel2..5` |
| `prefab/m01/1sky04, 1sky06, 1sky07, 1sky08, clouds2_01.dtx` (5) | `sky01-01..04.tfg` | *sky* `Sky01B01.Streams` |
| `prefab/m01/1sky15, 1sky16, 1sky17.dtx` (3) | `sky01clouds02`, `sky01cloud01` | *sky* `Sky01B01.Clouds` |
| `prefab/m01/sign_tall.dtx` (mixed) | `prefab_sign_pan_right_2/3.tfg` | `sign_generic_tall0{0,1,2}.m1signTall` |
| `prefab/m01/sign_text.dtx` | `prefab_sign_pan_right_1/4.tfg` | same signs |

Texture paths under `tex/prototype/` are shortened.

## Method and confidence

- I parsed every render section of the 63 worlds with `tools/dat85.py`. For each section I read the
  `.spr` header, the DTX header and command string, the `.tfg`, and the `.tfs` header and bytecode. I
  ran each script in a Python copy of the interpreter (the same one as `TextureEffects.cs`) for 600
  frames and checked whether its matrix changed. The script was a throwaway in the session scratchpad;
  the viewer already draws both mechanisms (`TextureEffects`, `SpriteAnimator` in
  `TronViewer/Assets/Tron/Scripts/TextureEffects.cs`).
- **High confidence** on the mechanisms and the m01-01 list: ltjs source, the retail file formats, and a
  check of every stage.
- I did not disassemble the retail `Lithtech.exe`'s texture-script evaluator. Its strings
  (`TextureEffectGroups\`, `.spr`) and the earlier section-loader check (dual-texture.md) match ltjs.
  Every retail script has dirty = 3, so the dirty-flag logic can't change the answer.
- "Animated" here means the image changes in time. Effects with world-space inputs also move with the
  camera, but they all depend on time too. Sprite frames advance only while the section is drawn (each
  section has its own tracker), so phases differ between sections. That doesn't change the yes/no
  answer.
