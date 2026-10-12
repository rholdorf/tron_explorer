# Render styles: file format and the combinations Tron 2.0 uses

Research for #2 (map #1). Answers: what is in a type-5 `.ltb`, what each field means in D3D terms,
which combinations Tron 2.0's 175 type-5 files use, and how a model piece picks its render style.

Sources:

- **ltjs** (`bibendovsky/ltjs`), the open LithTech Jupiter engine:
  `engine/runtime/render_a/src/sys/d3d/d3d_renderstyle.cpp` (`Load_LTBData`, `SetDefaults`),
  `d3d_renderstatemgr.cpp` (`SetRenderStyleStates`, `SetRenderStyleTextures`),
  `renderstylelookuptables.cpp` (enum → D3D mapping), `rendermodelpiecelist.cpp` (`QueuePiece`, pass loop),
  `engine/sdk/inc/ltrenderstyle.h` (structs, enums), `engine/runtime/model/src/ltb.h` (`LTB_Header`),
  `engine/runtime/shared/src/objectmgr.cpp` (`ModelInstance::GetRenderStyle`),
  `engine/runtime/client/src/setupobject.cpp` (`ModelSetRenderStyle`),
  `engine/runtime/server/src/server_extradata.cpp` (`se_ChangeModelRenderStyle`),
  `engine/sdk/inc/ltbasedefs.h` (`MAX_MODEL_RENDERSTYLES 8`),
  `game/objectdll/objectshared/prop.cpp`, `proptypemgr.cpp`.
- **The render style packer** (the tool that writes these files). Its LTA loader and writer are in
  `jsj2008/lithtech` `tools/RenderStyle_Packer/RenderStyle_LTA_Loader.cpp` and `renderstylepacker.cpp`.
  Its tool-side enums are in `madeinserver/lithtech` `libs/lttool/engine/renderstyle.h`.
- **The game's own files** in `extracted/`: 175 type-5 `.ltb` files, one leftover source file
  `chars/rs/glow_teambossweapons.lta.bak` (used to check the binary layout field by field), and
  `attributes/*.txt`.
- **Survey**: a throwaway script over `extracted/` and `export/levels/**/level.json`. It used `tools/ltb.py`
  and `tools/butes.py`, and isn't committed.

## 1. File format

All little-endian. These are raw MSVC x86 structs: 4-byte enums, and every `bool` padded to 4 bytes
inside a struct. The packer `fwrite`s whole structs (`renderstylepacker.cpp`).

```
LTB_Header (20 bytes)  u8 fileType = 5, pad, u16 version = 3, u8 reserved1, pad, u32 reserved2..4
u32 totalSize          bytes after the next field
u32 styleCount         always 1 in Tron (engine: take the first style the device supports)
per style:
  u32 size             bytes of this style after this field
  LightingMaterial     68 bytes: float4 Ambient, Diffuse, Emissive, Specular (RGBA), float SpecularPower
  u32 passCount        1 or 2 in Tron (engine asserts <= 4)
  per pass:
    RenderPassOp       532 bytes (below)
    u8 hasD3DPass      0 in every Tron file except rs/wireframea.ltb
    [D3D pass block]   only if hasD3DPass (vertex/pixel shader data, see "Outliers")
```

`RenderPassOp` (532 bytes):

```
TextureStageOps[4]     4 x 120 bytes:
    u32 TextureParam   0 none, 1..4 = the piece's texture slot 0..3
    u32 ColorOp, ColorArg1, ColorArg2, AlphaOp, AlphaArg1, AlphaArg2
    u32 UVSource, UAddress, VAddress, TexFilter
    bool UVTransform_Enable (+3 pad), float UVTransform_Matrix[16]
    bool ProjectTexCoord   (+3 pad), u32 TexCoordCount
u32 BlendMode, ZBufferMode, CullMode
u32 TextureFactor      D3DRS_TEXTUREFACTOR, ARGB
u32 AlphaRef           D3DRS_ALPHAREF
bool DynamicLight (+3) D3DRS_LIGHTING
u32 ZBufferTestMode    D3DRS_ZFUNC (uses the alpha test enum)
u32 AlphaTestMode, FillMode
bool bUseBumpEnvMap (+3), u32 BumpEnvMapStage, float BumpEnvMap scale, offset   (bump is never used)
```

Checks: 1 pass gives 68 + 4 + 533 = 605 (`size` of the 637-byte files), and 2 passes give 1138
(the 1170-byte files). Every one of the 164 version-3 files parses to exactly its `size`. The
`.lta.bak` source matches `chars/rs/glow_teambossweapons.ltb` field by field.

**Differences from ltjs's loader**:

- ltjs reads an 8-byte `RSD3DOptions` (`bUseEffectShader`, `EffectShaderID`) after each style.
  Tron's files don't have it: `size` ends right after the last pass. A Tron reader must not expect it.
- ltjs reads the optional D3D pass as 1+4+1+4 bytes. The one Tron file that has one
  (`rs/wireframea.ltb`) uses the larger, older `RSD3DRenderPass` from the tool header (vertex shader
  filename, constant registers, stream declarations, and embedded shader code).

### Enum values (file value → D3D)

From `ltrenderstyle.h` and `renderstylelookuptables.cpp`:

| Field | Values |
|---|---|
| BlendMode | 0 NOBLEND (ONE,ZERO) · 1 ADD (ONE,ONE) · 2 SATURATE (INVDESTCOLOR,ONE) · 3 MOD_SRCALPHA (SRCALPHA,INVSRCALPHA) · 4 MOD_SRCCOLOR (SRCCOLOR,INVSRCCOLOR) · 5 MOD_DSTCOLOR (DESTCOLOR,INVDESTCOLOR) · 6 MUL_SRCCOL_DSTCOL (SRCCOLOR,DESTCOLOR) · 7 MUL_SRCCOL_ONE (SRCCOLOR,ONE) · 8 MUL_SRCALPHA_ZERO (SRCALPHA,ZERO) · 9 MUL_SRCALPHA_ONE (SRCALPHA,ONE) · 10 MUL_DSTCOL_ZERO (DESTCOLOR,ZERO) |
| ZBufferMode | 0 ZRW (test+write) · 1 ZRO (test, no write) · 2 NOZ |
| CullMode | 0 NONE · 1 CCW (D3D default) · 2 CW |
| AlphaTest / ZTest | 0 none/ALWAYS · 1 LESS · 2 LESSEQUAL · 3 GREATER · 4 GREATEREQUAL · 5 EQUAL · 6 NOTEQUAL |
| FillMode | 0 WIRE · 1 FILL |
| ColorArg / AlphaArg | 0 CURRENT · 1 DIFFUSE · 2 TEXTURE · 3 TFACTOR |
| ColorOp | 0 DISABLE · 1 SELECTARG1 · 2 SELECTARG2 · 3 MODULATE · 4 MODULATE2X · 5 MODULATEALPHA (= D3DTOP_BLENDCURRENTALPHA) · 6 MODULATETFACTOR (= BLENDFACTORALPHA) · 7 ADD · 8 DOTPRODUCT3 · … · **19 MODULATETEXALPHA (= BLENDTEXTUREALPHA)**, see below |
| AlphaOp | 0 DISABLE · 1 SELECTARG1 · 2 SELECTARG2 · 3 MODULATE · 4 MODULATEALPHA (BLENDCURRENTALPHA) · 5 MODULATETFACTOR (BLENDFACTORALPHA) · 6 ADD · 7 ADDSIGNED · 8 ADDSIGNED2X · 9 SUBTRACT · 10 MODULATETEXALPHA (BLENDTEXTUREALPHA) |
| UVSource | 0..3 model UV set 1..4 · 4 CAMERASPACENORMAL · 5 CAMERASPACEPOSITION · 6 CAMERASPACEREFLECTIONVECTOR · 7..9 world-space normal/position/reflection |
| UAddress/VAddress | 0 WRAP · 1 CLAMP · 2 MIRROR · 3 MIRRORONCE |
| TexFilter | 0 POINT · 1 BILINEAR · 2 TRILINEAR · 3 ANISOTROPIC · 4 POINT_PTMIP |

**ColorOp 19.** The engine enum in ltjs stops at 16 (`MODULATETEXALPHA`). The packer's own header
puts `DECAL`, `HIGHLIGHT` and `HIGHLIGHT2` at 11–13, so its `MODULATETEXALPHA` is **19**. The Tron
files only use values 0–8 and 19, so the two enums never disagree on anything else. 19 shows up in 3
files (`props/rs/archivecube.ltb`, `chars/rs/inner_glow.ltb`, `rs/fullbrighton_alpha_specular.ltb`).
The likely reading is the tool's: 19 = `BLENDTEXTUREALPHA`. But that's an inference: Tron's own renderer
isn't available to check. ltjs would index past the end of its lookup table here.

**Garbage TextureParam.** `chars/rs/glow_teambossweapons.ltb` stores `TextureParam = 0x77C2C1B0`
on stage 0 of both passes. Its source asks for `RENDERSTYLE_USE_TEXTURE5`, which the packer doesn't
know, so it wrote an uninitialised value. The engine's `switch` has no `default`, so that stage keeps
whatever texture was bound before. It's a character glow style, not used by props.

### Semantics in D3D terms (`SetRenderStyleStates`)

- **DynamicLight = 1 (lit)**: `D3DRS_LIGHTING` on, with the style's `LightingMaterial` as the D3D
  material. Specular is enabled only when the specular color isn't black. The diffuse that stage 0
  receives is the D3D fixed-function lighting result:
  `Emissive + Ambient·AmbientLight + Σ Diffuse·light`. How the engine feeds the light grid and
  dynamic lights into that is research #3 / task #8. Material ambient is 0 in many styles (for example
  `archivecube`, `jet_rs`). That matters if the light grid arrives as D3D ambient light.
- **DynamicLight = 0 (unlit)**: lighting off. Tron's model vertices have no color stream, so diffuse
  is white: the piece is **fullbright**.
- A later pass with DynamicLight = 0 when pass 0 is lit is forced lit with a plain material, but only
  when the `MultiPassLightMatch` console variable is set (`forceAdditionalPassLighting`).
- **Texture stages** are standard D3D9 fixed-function stages. They cascade until the first stage whose
  ColorOp is DISABLE. CURRENT in stage 0 means diffuse. TFACTOR is `TextureFactor` (ARGB).
  `MODULATETFACTOR` uses TFACTOR's *alpha* as the blend weight: `Arg1·a + Arg2·(1−a)`.
- **TextureParam k** binds the piece's texture list entry k−1. That list is built in `QueuePiece`:
  entry n = `instance.skins[piece.iTextures[n]]` for n < `piece.nTextures`, and NULL after that.
  `tools/ltb.py` currently discards `nTextures`.
- **UVSource 4–9** are `D3DTSS_TCI_*` texture-coordinate generation. The world-space sources (7–9)
  only differ from the camera-space ones when `UVTransform_Enable` is set. Only then does the engine
  multiply the inverse view into the texture matrix. **Without a transform, WORLD_REFL behaves exactly
  like CAM_REFL.** Without a transform, D3D uses the reflection vector's x, y directly as u, v (range
  −1..1, WRAP).
- **Fog**: the model pass loop (`rendermodelpiecelist.cpp`, `drawmodel.cpp`) never touches the fog
  states. Every pass is fogged independently, with the world fog color, *before* blending (D3D9
  fixed-function fog). There is no lightmap-style fog-color trick for models. See section 5.
- **Alpha override**: when the object's alpha is below 0.99, the material's ambient, diffuse and
  specular alpha are multiplied by it for that draw (`rendermodelpiecelist.cpp`).

## 2. Resolving a piece's render style

1. Each **LOD** of a model piece stores `i32 renderStyle`, an index (`ModelPiece::m_iRenderStyle`).
   The exporter uses LOD 0.
2. Each model instance has `m_pRenderStyles[8]` (`MAX_MODEL_RENDERSTYLES`). Slot i is loaded from
   `ObjectCreateStruct::m_RenderStyleNames[i]`. The game fills those from `RenderStyle0..N` of the
   model template (`modelbutes.txt`), the prop type (`proptypes.txt`) or the attachment
   (`attachments.txt`). A `Prop` with its own `Filename` sets no render styles (`prop.cpp`).
3. When drawing: `instance.GetRenderStyle(piece.m_iRenderStyle)`. If the slot is empty (no name, or
   the load failed), it uses `g_RenderStateMgr.GetBackupRenderStyle()`.
4. **Default (backup) style** = `CD3DRenderStyle::SetDefaults()`. It has 1 pass: NOBLEND, ZRW,
   cull CCW, no alpha test, ZFUNC LESSEQUAL, FILL, TFACTOR 0x80808080, AlphaRef 128, lit. Stage 0 is
   TEXTURE1 with `MODULATE(TEXTURE, DIFFUSE)` for both color and alpha, UV set 1, WRAP, trilinear.
   Material: ambient 1, diffuse 0.8, emissive 0, specular 0, power 20. In other words, it's our current
   "texture × lit diffuse" shader.
5. If the server can't find a named file, it substitutes `RenderStyles\default.ltb`
   (`server_extradata.cpp`). That file doesn't exist in Tron, so the client ends up with the backup
   style too. `proptypemgr.cpp` fills `m_RenderStyleName` (singular) with `rs\default.ltb`, but that
   field isn't the model's style list.

In the 63 levels, every placed prop piece (277 instances) and every placed `CAIHuman` piece, default
attachments included, resolves to an existing file. No index is out of range, so **none of them uses
the backup style today**.

Side note: ArchiveBin's `RenderStyle1 = RS\ALPHA_CHROME.LTB` is never used, because both of its
pieces have index 0.

## 3. Survey of the 175 type-5 files

- **175** type-5 files.
- **10** are version 2: `renderstyles/rs_*.ltb`, the engine SDK samples. No attribute file references
  them, and the ltjs loader rejects any version other than 3.
- **165** are version 3. One of them, `rs/wireframea.ltb`, has a D3D vertex-shader pass; it's a
  wireframe debug style that nothing references.
- That leaves **164** files with the plain format: **134 with one pass and 30 with two**. No file has
  more than two passes.
- They use 119 distinct combinations (taking blend, Z, cull, alpha/Z test, lit, and per-stage
  texture/UV source/ops into account). Most belong to weapons, FX, light cycles and multiplayer
  content.
- Totals over all passes: blend ALPHA 89, OPAQUE 45, MUL_SRCALPHA_ONE 39, others under 6. Lit 152,
  unlit 42. UV sources: set 1 = 209, CAM_REFL = 52, WORLD_REFL = 11, WORLD_NORMAL = 6, others 1 each.
  Bump env map: never used. Wireframe fill: 8 passes.

### What the map's destination actually draws

The table below covers every piece of the 277 placed props, the 836 placed `CAIHuman`s (58 model
templates), and their default attachments. They use **26 files with 25 distinct combinations**, and
**9 of those files are multi-pass**. One template, `seeker.ltb`, is among the files that fail to load
(#6). Notation: `TEXn@uv OP(arg1,arg2)` per stage, color op first then alpha op. `CUR`/`DIF`/`TEX`/`TF`
are the D3D argument names, and `||` separates passes.

**Props (task #7): 7 files, 7 combinations, 1 multi-pass**

| Render style | Pieces | Used by | Pass(es) |
|---|---|---|---|
| `chars/rs/jet_rs.ltb` | 387 | IC finder (PropType) | **2 passes**: OPAQUE ZRW CCW lit · `TEX1@UV1 MODULATE(TEX,DIF)` ; `TEX2@CAM_REFL MODULATETFACTOR(TEX,CUR)` with TF=0x20ffffff (env ≈ 12.5%) **‖** ALPHA ZRW CCW unlit · `TEX1@UV1 SELECTARG1(TEX)`, alpha = tex.a (fullbright where alpha) |
| `props/rs/archivecube.ltb` | 334 | ArchiveBin | MUL_SRCALPHA_ONE (additive) ZRO CCW, alpha test LESS 128, lit · `TEX1@UV1 MODULATE(TEX,DIF)` ; `TEX1@WORLD_REFL op19(TEX,TEX)`, alpha `MODULATE(CUR,CUR)` |
| `rs/fullbrighton_alpha.ltb` | 43 | SecRezzer | OPAQUE ZRW CCW lit · `TEX1 MODULATE(TEX,DIF)`, alpha `SELECTARG1(TEX)` ; `TEX1 MODULATEALPHA(TEX,CUR)` = lerp(lit, tex, tex.a) (alpha-masked fullbright) |
| `chars/rs/default.ltb` | 40 | Tank (Tracks/Triangle), SpeakerCamera | OPAQUE ZRW CCW lit · `TEX1 MODULATE2X(TEX,DIF)` |
| `props/rs/tank1.ltb` | 16 | Tank (Blue) | OPAQUE ZRW CCW lit · `TEX1 MODULATE(TEX,DIF)` ; `TEX2@WORLD_REFL MODULATETFACTOR(TEX,CUR)` with TF=0x08080808 (env ≈ 3%) |
| `rs/alpha_fullbright.ltb` | 16 | Tank (RedBody) | ALPHA ZRW CCW, alpha test ≥128, lit, emissive 1 · `TEX1 MODULATE(TEX,DIF)` |
| `props/rs/m0502forcefield.ltb` | 4 | m05_02 forcefield | ALPHA ZRW CCW, **ZFUNC LESS**, lit, emissive 1 · `TEX1 MODULATE(TEX,DIF)` |

Texture slots for these props: ArchiveBin TEX1 = `archive_cube`, TEX2 = `chrome`. The finder has
TEX1 = its skin and TEX2 = `tex\chrome.dtx`. Tank Blue has TEX1 = `Tank1` and TEX2 = `chrome`
(`iTextures = [0, 3]`).

**Characters and attachments (tasks #9 and #10): 19 more files**

| Render style | Pieces | Passes | Combination |
|---|---|---|---|
| `chars/rs/kernel_shell.ltb` | 4033 (attachments) | 1 | SATURATE ZRO cull NONE unlit · `TEX1 MODULATETFACTOR(TEX,TEX)` ; `TEX2@CAM_REFL MODULATETFACTOR(CUR,TEX)` |
| `chars/rs/jet_rs.ltb` | 936 | 2 | as for props |
| `chars/rs/ic_rs.ltb`, `kernel_rs.ltb` | 504 + 32 | 2 | OPAQUE ZRW cull NONE lit · `TEX1 MODULATE` ; `TEX2@WORLD_REFL MODULATETFACTOR` ‖ ALPHA ZRW NONE, alpha test ≥128, unlit · `TEX1 SELECTARG1` |
| `chars/rs/default.ltb` | 304 | 1 | as for props (MODULATE2X) |
| `chars/rs/default_tronworld.ltb` | 259 | 1 | OPAQUE ZRW CCW lit · `TEX1 MODULATE(TEX,DIF)` |
| `chars/rs/ma3a_face.ltb` | 105 | 1 | ALPHA ZRW NONE, ZFUNC LESS, unlit · `TEX1 SELECTARG1` |
| `chars/rs/byte_inner.ltb` | 48 | 1 | ADD ZRW CCW, ZFUNC LESS, lit · `TEX1 SELECTARG1` |
| `chars/rs/netrunner_shell.ltb` | 35 | 1 | ALPHA ZRW NONE lit · `TEX1 MODULATE` ; `TEX2@CAM_REFL MODULATETFACTOR` |
| `chars/rs/inner_glow.ltb` | 32 | 1 | MUL_SRCALPHA_ONE ZRW NONE lit · `TEX1 MODULATE` ; `TEX1 op19(TEX,TEX)` |
| `rs/alpha_transparent.ltb` | 26 | 2 | OPAQUE ZRW NONE, alpha test >250 ‖ ALPHA **ZRO** NONE, alpha test <251 (both lit `MODULATE2X`) |
| `chars/rs/rector_corruption.ltb` | 26 | 1 | MUL_SRCCOL_ONE ZRW CCW lit · `TEX1 MODULATETFACTOR(TEX,TEX)` |
| `chars/rs/rector_cloak.ltb`, `thorn_body.ltb` | 26 + 16 | 2 | **MUL_SRCCOL_DSTCOL** (src·src + dst·dst) ZRW · `TEX1 MODULATE(TF,TEX)` ; `MODULATEALPHA` ‖ OPAQUE ZRW, alpha test ≤128 · `TEX1 MODULATE` / `MODULATE2X` ; `TEX2@CAM_REFL MODULATETFACTOR` |
| `chars/rs/byte.ltb` | 24 | 2 | OPAQUE · `TEX1 MODULATE2X(TF,TEX)` ; `MODULATEALPHA` ‖ OPAQUE, alpha test ≤128 · `TEX1 MODULATE2X` ; `TEX2@CAM_REFL MODULATETFACTOR` |
| `chars/rs/icshield_rs.ltb` | 20 (attachments) | 1 | ALPHA ZRW NONE, alpha test >128, ZFUNC LESS, lit · `TEX1 MODULATE(CUR,TEX)` |
| `chars/rs/ma3acompiled_glow.ltb` | 15 | 1 | ALPHA ZRW NONE lit · `TEX1 MODULATE` ; `TEX1 MODULATETFACTOR(TEX,DIF)` |
| `chars/rs/teamboss_rs.ltb` | 5 | 2 | OPAQUE · `TEX1 MODULATE(TF,TEX)` ‖ OPAQUE, alpha test ≤128 · `TEX1 MODULATE` ; `TEX2@CAM_REFL MODULATETFACTOR` |
| `chars/rs/thorn_cloak.ltb` | 4 | 1 | OPAQUE lit · `TEX1 MODULATE2X` ; `TEX1 MODULATEALPHA(TEX,CUR)` |
| `chars/rs/thorn_corruption.ltb` | 2 | 2 | **MOD_SRCCOLOR** ZRW CCW · `TEX1 MODULATEALPHA` ; `TEX1 ADD` ‖ ALPHA **ZRO cull CW** · no texture, `SELECTARG2(DIF)` |
| `chars/rs/ma3a_enormous.ltb` | 2 | 1 | ALPHA ZRW CCW, ZFUNC LESS, unlit · `TEX1 MODULATE(TEX,TEX)` |

Building blocks this needs, beyond what the world shader already does:

- Blend modes: OPAQUE, ALPHA, MUL_SRCALPHA_ONE, ADD, SATURATE, MUL_SRCCOL_ONE, MUL_SRCCOL_DSTCOL and
  MOD_SRCCOLOR. All of these are blend factors that a Unity `Blend [_Src] [_Dst]` can express.
- Per-pass options: ZRO, cull NONE/CW, ZFUNC LESS, alpha test with LESS/LESSEQUAL/GREATER/GREATEREQUAL
  and per-style references (128, 250, 251).
- Stage ops: MODULATE2X, `MODULATETFACTOR` (lerp by TF alpha, plus TF color as an argument),
  `MODULATEALPHA`, SELECTARG1/2, ADD, op19.
- Second-stage env maps from `CAM_REFL` and `WORLD_REFL` (which behaves the same as CAM_REFL).
- The lit/unlit switch, and the material's ambient/diffuse/emissive (see #8).

## 4. Screen glow and render styles

`attributes/clientbutes.txt` `[GlowRSMap]`: when the engine draws models into the glow buffer, it
swaps each model's render style using `GlowMapRSn → GlowMapRSTon`. Any style that isn't mapped draws
with `GlowDefaultRS = RS\black.ltb`: opaque, ZRW, unlit, `SELECTARG1(TFACTOR=0)`. That's solid black,
so the model hides glow behind it.

For props: `jet_rs` → `chars\RS\GLow_Jet_RS.ltb`, which outputs `tex.rgb·tex.a` with blend (SRCALPHA,
ZERO), and `rs/alpha_fullbright` → the same glow style. `archivecube`, `fullbrighton_alpha`,
`default`, `tank1` and `m0502forcefield` aren't mapped, so they draw black into the glow buffer.

## 5. Implications

**For #7 "Render styles on props"**

- Only **7 render styles** need support for props. Six are single-pass. The only multi-pass one,
  `jet_rs` (pass 2: unlit SELECTARG1(TEX) with ALPHA blend, ZRW, same cull), **folds exactly into one
  shader pass**: `c = lerp(pass0, tex.rgb, tex.a)`. Fog folds too, because fog is a lerp and commutes
  with an alpha blend. So props need no extra renderers and no extra passes, and the SRP Batcher stays
  intact. Each style can be a keyword set and `Blend`/`ZWrite`/`ZTest`/`Cull`/cutoff properties on the
  existing shader.
- The exporter needs the piece's **`nTextures` and full `iTextures`** (today `ltb.py` drops
  `nTextures` and the viewer uses only `textures[0]`). It also needs the resolved style per piece.
  The rule is `styles[piece.style]` if present, otherwise the backup default. It should fail loudly on:
  an unknown combination, `hasD3DPass`, version ≠ 3, or a garbage `TextureParam`.
- Env maps on props sample the reflection vector's x, y with WRAP (CAM_REFL ≡ WORLD_REFL here). The
  viewer's D3D-accurate env mapping (commit e2521a5) should be reusable.
- Check op19 on ArchiveBin (`archivecube`, the most common prop style) against the reference
  screenshots (#5). Read as BLENDTEXTUREALPHA(TEX,TEX), stage 1 is just the archive-cube texture
  sampled by world reflection. It's additive with alpha², and only where alpha² < 0.5.
- Glow: props with unmapped styles must write black into the glow buffer (they occlude glow). They
  must not glow from the DTX fullbright flag the way world textures do.
- Lit styles depend on the material and the light-grid answer (#3, #8). Until that lands, keep the
  constant 128 vertex color as diffuse, but apply emissive and the unlit = white rule now.

**For the "Multi-pass render styles in URP" question and the multi-pass fog patch**

- The engine applies **no fog patch** to model passes. Each pass is fogged with the world fog color
  before it's blended. The world shader's trick (fog color on the lightmap pass, grey on the texture
  pass) is specific to the world renderer and must not be copied to models.
- Folding a second pass into the shader is exact (fog included) when that pass is OPAQUE or ALPHA with
  ZRW and the same cull. That covers `jet_rs`, `ic_rs`/`kernel_rs`, `byte` and `teamboss_rs`: alpha
  test on pass 2 → select.
- Passes that need the framebuffer can't be folded:
  - **pass 0 with MUL_SRCCOL_DSTCOL** (`rector_cloak`, `thorn_body`) and **MOD_SRCCOLOR**
    (`thorn_corruption`, whose pass 2 also uses ZRO and cull CW).
  - `alpha_transparent`'s ZRW-opaque / ZRO-blended split.

  These four character styles (70 pieces) need a real second draw. To replicate D3D, fog each
  draw's source color on its own.
- Single-pass additive styles (`archivecube`, `byte_inner`, `kernel_shell`, `rector_corruption`) also
  add the fogged color in D3D, so they pick up fog color. That's the faithful behavior; don't patch it.

**For other tickets**

- #8 / #3 (model lighting): lit styles use a D3D material, and many have ambient = 0, so how the light
  grid enters D3D (ambient vs. lights) decides whether those pieces get any light-grid color at all.
- #9 / #10 (characters): 19 more styles, including 8 more multi-pass ones (4 of which need a second draw),
  plus the glow remap table. `kernel_shell` alone covers 4033 attachment pieces.
- The `dualtexture` / empty `tex2` item in the map is unrelated to render styles: render styles only
  apply to models.

## Outliers and dead files

- `renderstyles/*.ltb` (10 files, version 2): SDK samples. Unreferenced.
- `rs/wireframea.ltb`: version 3 with a vertex-shader D3D pass (6912 bytes). Unreferenced.
- Referenced but missing from `extracted/`: `rs/alpha_fullbrightchrome.ltb` (proptypes.txt),
  `rs/default.ltb` (gadgettargets.txt), `rs/additive_noculling_alphaef32.ltb`,
  `chars/rs/m06_03ma3a*.ltb`, `weapons/mesh/rs/pv_claw_arm*.ltb`, `pv_prankster_base.ltb` (all in
  clientbutes.txt). None of them is used by a placed prop or character in the levels.
