# How MSAA fits the viewer's camera pipeline

Research for #93 (map #91, remaster mode). Question: with MSAA 4x on the main camera (`PC_RPAsset` or
per camera), what breaks or changes in the viewer's pipeline? That covers the `glowCam` with its fixed
glow RT and composite, `TronGlowComposite`, the capture paths (`-shots`, `-frames`), HUD and subtitle
text, alpha-tested surfaces (alpha-to-coverage?), and Metal's MSAA cost on Apple silicon at 3600×2260.

Sources: the repo at 82c696b, and the **installed URP 17.3.0 source**
(`TronViewer/Library/PackageCache/com.unity.render-pipelines.universal@746735fb06f2`, `package.json`
`"version": "17.3.0"`; public mirror: branch `6000.3/staging` of Unity-Technologies/Graphics). Also the
Unity 6000.3 manual and Apple's Metal documentation and WWDC sessions. Line numbers refer to those files.
Nothing was run. The cost section is arithmetic plus documented behaviour, and must still be measured.

## Answer

Nothing breaks. With MSAA on, only the sky + main camera stack (and the IO camera) render multisampled.
The glow camera, the composite, the HUD and the captures all stay single-sample, so they work and look as
they do today. Alpha-tested texels don't get smoothed unless the shaders opt into alpha-to-coverage.
The real cost on this pipeline is bandwidth: the stack's MSAA target can't stay in tile memory, and
`PC_RPAsset` asks for depth and opaque copies that the viewer never samples. On a macOS player those
copies turn into a shader resolve of the MSAA depth.

## How URP picks a camera's sample count

- `UniversalRenderPipeline.cs:1409-1411`, evaluated every frame for each base camera:
  `if (camera.allowMSAA && asset.msaaSampleCount > 1 && rendererSupportsMSAA) msaaSamples =
  (camera.targetTexture != null) ? camera.targetTexture.antiAliasing : asset.msaaSampleCount;`
  - An **RT-target camera takes the RT's `antiAliasing`**, not the asset's count.
  - Forward and Forward+ support MSAA. Deferred and Deferred+ turn it off (`UniversalRenderer.cs:485-489`).
    `PC_Renderer` is `m_RenderingMode: 2` (Forward+).
- **Overlay cameras have no MSAA of their own.** The camera inspector's Output section, which holds
  *MSAA* ("Enable Multisample Anti-aliasing for this camera"), exists only on Base cameras
  ([camera component reference](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/camera-component-reference.html)).
  An overlay renders into the base camera's target
  ([camera stacking](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/cameras/camera-stacking-concepts.html):
  "A camera stack overrides the output of the Base Camera with the combined output of all the cameras in
  the camera stack").
- `asset.msaaSampleCount` has a plain setter (`Data/UniversalRenderPipelineAsset.cs:1110-1114`). Line 1410
  reads it every frame, so **changing it at runtime takes effect on the next frame** for every camera that
  allows MSAA. In the Editor this writes the asset itself, which then persists, the same trap as the
  `runInBackground` leak.
- The **back buffer's** sample count is set once, when the pipeline is built:
  `QualitySettings.antiAliasing = asset.msaaSampleCount` (`UniversalRenderPipeline.cs:257-265`). Turning the
  asset up later at runtime leaves the back buffer at whatever it was then.
- [Anti-aliasing in URP](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/anti-aliasing.html):
  MSAA is set under *Quality > Anti Aliasing (MSAA)* on the URP asset. It "does not fix shader aliasing issues
  such as specular or texture aliasing", and it can't be combined with TAA.

## The viewer's cameras today

| Camera | Type | Target | Sample count with asset MSAA 4x |
|---|---|---|---|
| `skyCam` (`TronExplorer.cs:318-329`) | Base; `cameraStack = [mainCam]` | screen | **4** (`allowMSAA` defaults to true) |
| `mainCam` (`TronExplorer.cs:296-308`) | **Overlay** on `skyCam` | skyCam's intermediate | **4**, from skyCam; `mainCam.allowMSAA` has no effect |
| `glowCam` (`TronExplorer.cs:346-356`) | Base, `depth = -10` | `glowRT` 256², `new RenderTexture(..., 24, ARGB32, Linear)` | **1**: the RT's `antiAliasing` is 1 by default |
| IO camera (`IOCamView.cs:58-70`) | Base, `depth = 10`, partial `pixelRect` | screen | **4** |

`PC_RPAsset.asset`: `m_MSAA: 1` (off), `m_RenderScale: 1`, `m_RequireDepthTexture: 1`,
`m_RequireOpaqueTexture: 1`, `m_StoreActionsOptimization: 0` (Auto). `PC_Renderer.asset`:
`m_UseNativeRenderPass: 1`, `m_IntermediateTextureMode: 0`. QualitySettings "PC" (the Standalone default)
uses `PC_RPAsset`, `antiAliasing: 0`. The project is in Gamma colour space (`m_ActiveColorSpace: 0`).

So **the switch for the world is the asset's count, or `skyCam.allowMSAA`** (plus the IO camera's), not
`mainCam`.

## Per item

### glowCam, glow RT, blur and `TronGlowComposite`: unchanged

- `glowRT` is created without `antiAliasing`, so line 1411 gives `glowCam` 1 sample whatever the asset
  says. The glow buffer stays at 256² single-sample, as the game's screenglowmgr has it, and stays faithful.
  The blur (`Graphics.Blit` ×2, `TronExplorer.cs:399-401`) works on single-sample RTs as before.
- To antialias the glow buffer, set `glowRT.antiAliasing`. Unity resolves an MSAA RT on its own when the
  target changes: "To the rest of the system only this 'resolved' surface is visible"
  ([RenderTexture.antiAliasing](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/RenderTexture-antiAliasing.html)).
  It would change the glow's look, though, and the 24-tap blur hides edge aliasing at 256² anyway.
- The composite is drawn in `OnGUI` (`TronExplorer.cs:672-673`, `Graphics.DrawTexture(... blurB,
  compositeMat)`, `Blend One One`, `ZTest Always`). That runs after URP has resolved the stack and blitted
  it to the back buffer, so it adds onto the resolved image. Nothing in it depends on the sample count.

### Intermediate target and resolve

- A base camera with a stack always renders into an intermediate texture
  (`UniversalRenderer.cs:2008-2011`: `renderType == Base && !resolveFinalTarget`). So does a camera that
  needs the opaque texture or has a non-default viewport (line 2042; the IO camera).
  `m_RequiresIntermediateAttachments` is true for the stack whether MSAA is on or off.
- On Metal, the resolve happens inside the render pass (store action Resolve on the last camera of the
  stack, `UniversalRenderer.cs:1490`). There's no separate resolve blit:
  `PlatformRequiresExplicitMsaaResolve()` returns false for Metal players (`UniversalRenderer.cs:1985-1997`).
  In the **Editor** it always returns true, because the Game view's RT has 1 sample, so Editor timings
  include an extra resolve. That's one more reason to measure only in the player build.

### Back buffer, HUD and subtitles

- Everything in `OnGUI` is drawn into the back buffer after URP: the glow composite, the letterbox, the
  IONode frame, the fade, the HUD text (`HudFont.cs:73-83`, `GL.QUADS` in pixel coordinates,
  `Hidden/Tron/HudText`), subtitles, menu and info bar.
- The back buffer's sample count is `Screen.msaaSamples`. URP drops it to 1 only when **one** camera renders
  that frame (`canOptimizeScreenMSAASamples = cameraCount == 1`, `UniversalRenderPipeline.cs:2617-2622`;
  `ScriptableRenderer.cs:2368-2376`). In a level, the viewer always has at least `skyCam` + `glowCam`
  (+ IO camera), so the optimisation never applies.
  - If the asset already holds 4x at startup, `QualitySettings.antiAliasing = 4` gives a **4x back
    buffer** on a macOS player (if `SystemInfo.supportsMultisampledBackBuffer`;
    `ScriptableRenderer.cs:2362`). The OnGUI draws then go into a multisampled back buffer that gets
    resolved on present. Full-screen rects and pixel-aligned text quads cover every sample of a pixel, so
    they don't change, but the buffer costs bandwidth and memory for nothing.
  - If the asset starts at 1 (faithful) and the toggle raises it at runtime, the back buffer stays at 1
    sample (above). That's the cheaper shape for a runtime toggle.
  - `Screen.SetMSAASamples(1)` is the public call URP itself uses to force it down.
- HUD and subtitle text aren't affected by MSAA: they are textured quads aligned to the pixel grid, and
  MSAA only smooths polygon edges. Their sharpness at 3600×2260 depends on the render-scale and HUD
  decisions, not on this one.

### Captures

- `-frames` uses `ScreenCapture.CaptureScreenshot` (`TronExplorer.cs:111`). `-shots` uses
  `CaptureScreenshotAsTexture` (line 155), then for a resize a `Graphics.Blit` into
  `new RenderTexture(ShotWidth, ShotHeight, 0)` (line 145, single-sample) and `ReadPixels`. Both read the
  screen after rendering, so they get the resolved image with the HUD as shown. Neither path creates a
  multisampled texture of its own. (Unity's
  [ScreenCapture](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/ScreenCapture.html) docs
  don't say anything about MSAA. To verify once: a `-frames` capture with MSAA on should show smoothed
  edges.)
- `-shots` and `-frames` run with whatever MSAA the asset or toggle has at startup. A remaster capture
  needs `-remaster` applied before the first captured frame.

### Alpha-tested surfaces

- The viewer's alpha tests are `discard`s: `TronWorld.shader:149` (`_Cutoff`), `TronModel.shader:198-203`
  (`AlphaPass`, D3D's `ALPHAFUNC` on 8-bit alpha), `TronEffect.shader:82` (`_AlphaGreater`). None uses
  `AlphaToMask`.
- With MSAA, a `discard` drops every sample of the pixel, so **the cut-out edges inside a texture (grates,
  railings, foliage-like masks) stay as aliased as today**. Only triangle edges get smoothed.
- Alpha-to-coverage is the documented fix: `AlphaToMask On` "can reduce the excessive aliasing that
  occurs when you use MSAA with shaders that use alpha testing". The manual also warns it "is intended for
  use with MSAA. If you enable alpha-to-coverage mode when you are not using MSAA, the results can be
  unpredictable; different graphics APIs and GPUs handle this differently"
  ([Reduce aliasing with AlphaToMask mode](https://docs.unity3d.com/6000.3/Documentation/Manual/writing-shader-alpha-to-mask.html)).
  - **So faithful mode must keep it off**, and the switch has to be a material property, not a fixed state.
  - URP's own Lit does exactly that: `AlphaToMask[_AlphaToMask]` (`Shaders/Lit.shader:109`). It only
    exports a sharpened alpha when the camera is multisampled: `_AlphaToMaskAvailable = msaaSamples > 1 &&
    isOpaque` (`Runtime/Passes/DrawObjectsPass.cs:170`). The sharpening is `SharpenAlphaStrict(alpha,
    cutoff) = saturate((alpha - cutoff - 0.5*fwidth(alpha)) / max(fwidth(alpha), 1e-4) + 1)`
    (`ShaderLibrary/ShaderVariablesFunctions.hlsl:186-190`), so the cut-out doesn't grow or shrink.
  - The viewer's shaders use a hand-written `CGPROGRAM`/HLSL pass and don't include that library. Doing
    the same means writing the formula into the three `discard` sites, with `AlphaToMask [_A2C]` on the
    pass.
  - `TronModel`'s exact-compare alpha functions (`==`, `!=`) have no coverage equivalent, so only the
    `<`, `<=`, `>`, `>=` paths can be converted.
  - Effects are `Queue=Transparent` and alpha-blended. URP marks A2C as available only for opaque draws,
    and alpha-blended effects don't need it.

### Depth and opaque copies (cost the viewer doesn't use)

- `PC_RPAsset` has `m_RequireDepthTexture: 1` and `m_RequireOpaqueTexture: 1`. No camera overrides them
  (`UniversalRenderPipeline.cs:1615-1616` take the additional-camera-data values, which default to "use
  pipeline settings"). Overlay cameras drop only the opaque copy (lines 1645-1650).
  - No viewer shader samples `_CameraDepthTexture` or `_CameraOpaqueTexture`: a grep over
    `Assets/Tron` finds no match.
- With MSAA on, the **depth copy has to resolve the MSAA depth**. On a macOS player,
  `RenderingUtils.MultisampleDepthResolveSupported()` returns **false** (`RenderingUtils.cs:603-611`, "a
  driver bug on OSX when using some AMD graphics cards"). The depth attachment is then bound as an MSAA
  texture (`bindTextureMS`, `UniversalRendererRenderGraph.cs:1869-1873`), and CopyDepth resolves it in a
  shader that reads all four samples at full resolution.
- An attachment that a later pass samples or copies can't be memoryless. Render Graph only makes a texture
  memoryless when it is "only used in a single raster render pass, and not sampled"
  (`com.unity.render-pipelines.core/Runtime/RenderGraph/RenderGraphResourceTexture.cs:299`). The stack's
  colour target is shared by two cameras, and both copies read it, so its **4x samples get stored to
  memory**.
- Turning both requirements off for the viewer's cameras (on the asset or per camera) is a separate
  change, and faithful mode would get it too.
  - It isn't certain that today's image would be unchanged. The opaque copy is never sampled, so it can't
    change pixels, but that should be checked with a capture diff.

### Metal MSAA cost on Apple silicon at 3600×2260

- Apple GPUs hold the samples in on-chip tile memory and resolve them when the tile is stored. The
  recommended setup is a **memoryless** MSAA attachment with store action `.multisampleResolve`, so the
  samples never reach system memory ([WWDC20 10632, Optimize Metal Performance for Apple silicon
  Macs](https://developer.apple.com/videos/play/wwdc2020/10632/);
  [WWDC20 10602, Harness Apple GPUs with Metal](https://developer.apple.com/videos/play/wwdc2020/10602/);
  [WWDC19 606](https://developer.apple.com/videos/play/wwdc2019/606/)).
  - WWDC20 10632 names storing the MSAA attachment and reloading it just to resolve as an anti-pattern.
  - With 4x MSAA the maximum tile size in a render pass drops from 32×32 to 32×16
    ([Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf)), so a
    frame needs twice as many tiles.
- At 3600×2260 (8.14 Mpx) and RGBA8 colour (HDR is off on every camera), the arithmetic is:
  - one single-sample colour target: 32.5 MB.
  - a 4x MSAA colour target: **130 MB**, plus a 4x depth-stencil target of the same order.
  - When those samples are stored (see above), every frame writes them out and the depth copy reads them
    back.
- The viewer's pipeline today meets the documented conditions for the anti-pattern: a two-camera stack
  into one intermediate, plus depth and opaque copies.
  - The expected cost is therefore the stored-samples case, not the cheap on-tile case. How much of it
    lands in the 8.3 ms p95 budget has to be **measured in the player build**: m10-04 with every explosion
    fired, at native Retina, MSAA off/2x/4x, and with depth/opaque copies on vs off.
  - Xcode's Metal frame capture shows each attachment's store action and storage mode.
  - The Unity manual's general note: "when run on a tiled GPU with no post-processing anti-aliasing or
    custom render features in use, MSAA is a cheaper option than other anti-aliasing types"
    ([anti-aliasing](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/anti-aliasing.html)).

## What this means for the toggle (facts it rests on, not a decision)

- **Faithful stays pixel-identical** if the asset stays at `m_MSAA: 1` and remaster raises it at runtime:
  the back buffer is fixed at pipeline creation and stays single-sample, and glowCam is unaffected.
  - The setter mutates the asset, so in the Editor it would have to be restored on exit, or the viewer
    would have to switch to a runtime copy of the asset.
- An alternative is the asset at 4 with `skyCam.allowMSAA` and the IO camera's `allowMSAA` toggled per
  mode. It makes the back buffer 4x in faithful mode too, which costs bandwidth for nothing.
- Alpha-tested edges need an `AlphaToMask [_A2C]` property and a sharpened-alpha path in three shaders.
  Without that, MSAA leaves grates and cut-outs as they are.
- Measurements still to make:
  - MSAA 2x/4x on m10-04 with every explosion fired at 3600×2260 in the player build.
  - The same with depth and opaque copies off.
