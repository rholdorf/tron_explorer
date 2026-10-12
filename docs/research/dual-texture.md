# Dual-texture sections with an empty second texture

Ticket #18. Question: where does the second texture of `dualtexture` (8) and
`lightmap_dualtexture` (9) world sections come from when `tex2` is empty?

## Answer

Nowhere. The engine refuses the dual-texture shader for these sections and draws them with the plain
texture shader. That shader ignores the base texture's `EnvMap` and `DetailTex`, but keeps its
fullbright flag, alpha test and texture effect.

## Data

All dual-texture sections in the retail worlds are in `intro` and `m01-01`, all with shader 8, and
none has a second texture (`tools/tests/test_dual_texture.py` pins this). There are 52 distinct
(texture, effect) materials, all 52 in m01-01 and 22 of them in intro, so 74 counted per level. There are
17,461 triangles in m01-01; the rest of m01-01 is gouraud (shader 1, no lightmaps). Every texture
except `m01l_w12`, `m01p_w24`, `m01x_b01`, `m01x_g01` and `occluder` also appears as shader 1 in
the same level. That includes 6 sprites (`fx/spr/1anim0N.spr`).

Base-texture features (DTX header and command string):
- Most are fullbright (`flags & 1`).
- One has an environment map: `labcolorbaselight.dtx` (`Envmap Tex\Env\Env003.dtx`).
- None has `DetailTex`.

## Engine path

From ltjs `engine/runtime/render_a/src/sys/d3d/`:

1. `d3d_renderblock.cpp` `Load`: `TranslatePCShaderCode` maps 8 → `eShader_Gouraud_DualTexture` and
   9 → `eShader_Lightmap_DualTexture`. A missing `m_pTexture[1]` only prints
   `Renderer: Error loading texture` to the console.
2. `d3d_renderworld.cpp` `AllocShader`: dual-texture shaders are taken as is. No detail, envmap or
   fullbright variant is chosen from the base texture, unlike shaders 1 and 4.
3. `CRenderShader_Gouraud_DualTexture::ValidateShader` (and the lightmap one) returns false when
   `m_pTexture[1]` is null.
4. The fallback switch in `AllocShader` then picks:
   - `eShader_Gouraud_DualTexture` → `eShader_Gouraud_Texture`
   - `eShader_Lightmap_DualTexture` → `eShader_Lightmap_Texture`
5. `CRenderShader_Gouraud_Texture` draws the texture modulated by the vertex color (2x with
   Saturate) and adds a second blended pass by texture alpha when the texture is fullbright
   (`PostFlushBlock`). It glows when fullbright, alpha-tests by `AlphaRef`, and installs the
   section's texture effect on the base channel. This is the same thing the viewer draws for a
   plain shader-1 texture.

## Retail check (`Lithtech.exe`, disassembled)

The retail binary does the same:
- Its shader enum is shorter (no DOT3 or Effect shaders): Gouraud 0, Gouraud_Texture 1,
  DualTexture 10, Lightmap 11, Lightmap_Texture 12, Lightmap_DualTexture 17.
- The section loader (`0x528614`) translates 8 → 10 and 9 → 17, and prints the error for a missing
  second texture.
- The `AllocShader` fallback table (`0x4d591a`, byte index `0x4d6000`) sends 10 → 1 and 17 → 12.
- The DualTexture vtable is `0x58ce88`. Its `ValidateShader` (`0x53c700`) returns false when
  `m_pTexture[1]` is null.

## What changed in the viewer

Before this ticket, the viewer drew shader 8 like shader 1, but also applied the DTX `EnvMap` and
`DetailTex`. In the data, that only affects `labcolorbaselight.dtx` in m01-01 and intro, which
showed an environment map the game does not draw. Now:
- `LevelBuilder.BuildMaterials` skips EnvMap and DetailTex for shaders 8 and 9.
- `export_level.Writer.material` fails on a dual-texture section that does have a second texture
  (none exist; the real dual-texture blend is not implemented).

No format change.
