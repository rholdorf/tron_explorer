# Why ArchiveBin looks like alpha_chrome: it is two models

Research for #12 (map #1, follow-up to #7). Question: in the game, an archive bin has a dark opaque
frame over translucent glass. The bin's slot-0 style `props/rs/archivecube.ltb`, read as the file
says, can't draw that. Why? Does the game code switch styles, or does the engine reject ColorOp 19
and fall back? And should the exporter's `STYLE_OVERRIDES` stay?

## Answer

Neither. **The `ArchiveBin` object spawns a second model, `ArchiveBin_Frame`, and attaches it to
the bin's `Frame` socket.** The dark frame in the reference frames is that model, drawn with its
own slot-1 style `rs/alpha_chrome.ltb`. The glass is the bin's own model, `archivebin.ltb`, whose two
pieces are named `CubeGlass` and `CubeGlass1`. It draws with `archivecube`, as the file says.
Nothing in the game swaps render styles. The engine doesn't reject the style. ColorOp 19 makes no
difference here: either way it reads, stage 1 outputs the texture.

**Recommendation: replace the override.** Delete `STYLE_OVERRIDES`. For every `ArchiveBin` object,
also emit the `ArchiveBin_Frame` template's model at the bin's own transform. Draw both models with
their styles as resolved, with no special cases.

## Evidence

### 1. The game code attaches a frame model (object.lto)

No Tron 2.0 game source is public. GitHub code search finds no `ArchiveBin_Frame` and no
`class ArchiveBin` from Tron. Repo search for Tron 2.0 / LithTech / Killer App finds only a DAT
converter (`lokea2/DAT2LTA85`) and this repo. ltjs is NOLF2's game code and has no ArchiveBin. So the
primary source is the game's own server DLL, `extracted/object.lto`: a PE32 i386 DLL, image base
`0x10000000`. I disassembled it with `objdump -d --x86-asm-syntax=intel`.

- The string table has `.?AVArchiveBin@@` (the RTTI name for class `ArchiveBin`), `ArchiveBin_Frame`
  (VA `0x1028449c`), `Frame` (`0x102c478c`) and `BaseClass` (`0x102c4780`).
- `ArchiveBin_Frame` is referenced only in the function at `0x1000f360`. That function sits in the
  same code block as the ArchiveBin messages `"%s : Archive bin is empty on initial update."` (xref
  `0x1000e308`) and `ArchiveBinInvalidPSet` (xref `0x1000e752`). It does the following, in order:
  1. `0x1000f4ce`: it calls the model interface's GetSocket with `"Frame"` on its own object. If that
     fails, it bails out (`jne 0x1000f6b3`). Then it gets the socket transform.
  2. `0x1000f509`: `strncpy(ocs.m_Name, "ArchiveBin_Frame", 127)`.
  3. `0x1000f526`: `g_pModelButeMgr->GetModelId("ArchiveBin_Frame")`. Then come the bounds check
     against the model count and the calls `GetModelFilename(id)` → `ocs.m_Filename`,
     `CopySkinFilenames(id, 0, ocs.m_SkinNames, 128)` and `CopyRenderStyleFilenames(id, &ocs)`
     (`0x1000f53c`, `0x1000f56d` and `0x1000f57e`). The argument shapes match those methods in ltjs
     `game/.../modelbutemgr.cpp` (`CModelButeMgr::GetModelId`, `GetModelFilename`, `CopySkinFilenames`,
     `CopyRenderStyleFilenames`). This is the NOLF2-lineage ModelButeMgr that Tron's `modelbutes.txt`
     feeds.
  4. `0x1000f5ea`: `g_pLTServer->CreateObject(GetClass("BaseClass"), &ocs)`. The handle is stored in a
     member object reference, and any previous frame is removed first (`0x1000f611`–`0x1000f643`).
  5. `0x1000f6aa`: `CreateAttachment(hBin, hFrame, "Frame", &(0,0,0), &(0,0,0,1), &hAttachment)`.
     The offset is zero and the rotation is the identity.
- The only caller is `0x1000d23e`, inside the bin's setup routine. It runs unconditionally right after
  the loop that fills the bin's 6 item slots.

### 2. The attributes and models agree (extracted/)

- `attributes/modelbutes.txt` `[Model35]` `ArchiveBin_1` (and `_2`…, identical): `ModelFile =
  props\models\ArchiveBin.ltb`, `Skin0 = archive_Cube.dtx`, `Skin1 = Tex\chrome.dtx`,
  `RenderStyle0 = props\RS\ArchiveCube.ltb`, `RenderStyle1 = RS\ALPHA_CHROME.LTB`, `Type = 3`.
- `[Model111]` `ArchiveBin_Frame`: the same skins and the same two render styles, with `ModelFile =
  props\models\ArchiveBin_Frame.ltb`.
- The model pieces, from `tools/ltb.py`, LOD 0:

  | File | Piece | `iTextures` | render style index → file |
  |---|---|---|---|
  | `archivebin.ltb` | `CubeGlass` | [0, 1] | 0 → `archivecube` |
  | `archivebin.ltb` | `CubeGlass1` | [0, 1] | 0 → `archivecube` |
  | `archivebin_frame.ltb` | `CubeFrame` | [0, 1] | **1 → `alpha_chrome`** |

  So `RenderStyle1` isn't dead (`render-styles.md` §2 says it is). The frame model uses it, and the
  bin template lists it only because the two templates are copies of each other.
- `archivebin.ltb` has a socket `Frame` on node 0 (`joint1`) with position (0,0,0), rotation
  (0,0,0,1) and scale 1. It also has `Socket1`…`Socket9`, for the items. In both models `joint1`'s
  bind transform is the identity. **So the frame sits exactly at the bin's transform.**
- No `.lta`/`.lta.bak` source exists for these models or for `archivecube`.

### 3. ColorOp 19 is not the cause (ltjs engine)

From `engine/runtime/render_a/src/sys/d3d/` in `bibendovsky/ltjs` (master `46aca18`):

- **No rejection.** `CD3DRenderStyle::Load_LTBData` (`d3d_renderstyle.cpp`) loops over the styles in
  the file. It calls `Compile()`, which is just `return true`, and then `IsSupportedOnDevice()`. It
  takes the first style that passes. If none passes, it returns false, the instance's slot stays empty,
  and the piece gets the backup style (`SetDefaults`). `IsSupportedOnDevice` only checks
  `MaxTextureBlendStages` and the `TextureOpCaps` bits for the ColorOp and AlphaOp values it knows.
  Its `switch` has **no `default`**, so ColorOp 19 is accepted without any check. There is no
  `ValidateDevice` call anywhere in the render style path.
- **What 19 becomes in ltjs.** `SetRenderStyleStates` (`d3d_renderstatemgr.cpp`) does
  `SetTextureStageState(D3DTSS_COLOROP, kTables.m_nColorOp[ColorOp])` with no bounds check.
  `m_nColorOp` has `RENDERSTYLE_COLOROP_TYPE_COUNT` = 17 entries, and `m_nAlphaOp` (11 entries) follows
  it in `CRenderStyleLookupTables` (`renderstylelookuptables.h`). So index 19 reads `m_nAlphaOp[2]` =
  `D3DTOP_SELECTARG2`.
- **What 19 means to the packer.** The packer that wrote Tron's files kept the PS2 ops `DECAL`,
  `HIGHLIGHT` and `HIGHLIGHT2` at 11–13. That shifts `MODULATETEXALPHA` (= `D3DTOP_BLENDTEXTUREALPHA`)
  to 19 (`madeinserver/lithtech` `libs/lttool/engine/renderstyle.h`). In the later packer at
  `jsj2008/lithtech` `tools/RenderStyle_Packer/renderstyle.h`, those three lines are commented out as
  `//OLD PS2`, which gives 16, the engine's value. Tron's engine binary isn't available, so whether
  *its* enum had 17 or 20 entries can't be checked.
- **It doesn't matter for archivecube.** Stage 1 is `op19(TEXTURE, TEXTURE)` on `TEX1@WORLD_REFL`.
  `BLENDTEXTUREALPHA(t, t) = t·a + t·(1−a) = t`, and `SELECTARG2 = t`. Both readings give the same
  result. Even the out-of-bounds read can't make the glass draw a dark frame.

Side note: the reading does matter for `rs/fullbrighton_alpha_specular.ltb`, whose stage 1 is
`op19(TEXTURE, CURRENT)`. It's a lerp under the packer's reading and a no-op under ltjs's
out-of-bounds read. That style is only a `[GlowRSMap]` source key (`GlowMapRS50`), and no placed prop
or character uses it. Our exporter keeps the packer's reading.

### 4. The reference frames

`reference/m01-02_bin-close.png` and `m01-01_bin-close.png` show a dark, thick, opaque cube frame
along the edges, with faint translucent glass panels in between that brighten what's behind them.
The frame is `CubeFrame` + `alpha_chrome`: alpha-blended, alpha test ≥ 1, and the texture's dark
border has alpha 255. The glass is `CubeGlass*` + `archivecube`: additive `SRCALPHA, ONE`, ZRO, and
only where (tex.a · diffuse.a)² < 0.5. That is exactly what #7 saw as a "grey haze with no frame".
It was the correct glass, with the frame model missing.

## Corrections to `docs/research/render-styles.md` (branch `research/render-styles`)

- §2 side note: "ArchiveBin's `RenderStyle1 = RS\ALPHA_CHROME.LTB` is never used". Wrong. It's
  used by the `ArchiveBin_Frame` model, which the game attaches.
- §4: "`archivecube` … aren't mapped [in `[GlowRSMap]`]". Wrong. `clientbutes.txt` has
  `GlowMapRS53 = GlowMapRSTo53 = Props\RS\ArchiveCube.ltb`, and `archiveberry` maps to itself too
  (`GlowMapRS78`). So the glass draws itself into the glow buffer. The frame (`alpha_chrome`, unmapped)
  draws black there. The exporter's `Styles.glow_map` already reads this correctly: it has 79 entries,
  `archivecube → archivecube` among them. Only the doc's prose was wrong.

## What the exporter should do

1. Remove `STYLE_OVERRIDES` and its lookup in `Styles.pieces`
   (`tools/export_models.py`). With it gone, the glass draws `archivecube` and the export is faithful.
2. In `Resolver` / the model export, an object with `cls == "ArchiveBin"` yields **two model
   instances**:
   - its `ModelTemplate` (as today);
   - the template named `ArchiveBin_Frame` (hard-coded, as in the game, whatever the bin's own
     template is), with the same `pos` / `rot` and scale 1. The `Frame` socket offset is the identity
     and `joint1` is the identity at bind.

   If the level format needs it, an `attachTo`/parent field would be more general. Today a second
   `models[]` entry with the same `obj` and transform is enough, because nothing animates. Both
   models have a `Spin` animation, but the attachment follows the socket, so when animation arrives
   the frame should follow the bin's `joint1`.
3. Expected style counts after the change: `archivecube` stays at 334 pieces (the `CubeGlass*`
   pieces), and `alpha_chrome` adds 167, one `CubeFrame` per bin. Check this at export time.
4. Don't generalise the override into a "style the engine would reject" rule. No style used by props
   or characters is rejected by the engine's load path, and ColorOp 19 is accepted.
5. Remaining risk: other game classes may also spawn hard-coded templates. Check `object.lto` for
   `GetModelId` call sites with literal names before trusting `modelbutes.txt` alone for other prop
   classes (for example `SecRezzer`'s active look, noted in #7).
