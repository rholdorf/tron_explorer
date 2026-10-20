# Depth-normals and motion vectors for the Tron shaders

Ticket #94 (map #91, remaster mode). Question: what does it take for `Tron/World`, `Tron/Model` and
`Tron/Effect` to write DepthOnly / DepthNormals and MotionVectors so URP's SSAO and STP work? Which
passes and LightMode tags URP 17.3 expects, how each kind of moving thing gets correct motion vectors,
what STP does with surfaces that write none, and what STP needs on Metal / Apple silicon.

Sources: the URP 17.3.0 and core packages the project resolves
(`TronViewer/Library/PackageCache/com.unity.render-pipelines.universal@746735fb06f2`, `...core@9e589b64c45d`,
Unity 6000.3.26f1), the Unity 6000.3 manual, and the viewer's own code. Package paths below are relative
to the package root. Nothing was run; this is all from reading.

## Answer in short

- **The shader passes are cheap. The camera setup is what blocks STP.** The main camera is an
  **Overlay** camera stacked on the sky's Base camera (`TronExplorer.cs:305-327`). URP turns TAA off,
  and STP with it, for any camera that is an overlay or has a stack (`UniversalCameraData.cs:506`). The
  sky has to stop being a camera stack before STP can run at all.
- **SSAO is already on today and does nothing.** `PC_Renderer.asset:71-78` has an active
  `ScreenSpaceAmbientOcclusion` feature with Source = DepthNormals. That forces a DepthNormals prepass
  that none of the Tron shaders draw into, and no Tron shader samples the AO texture. Faithful mode pays
  for it and gets nothing back. Turning it off doesn't change a pixel.
- **What each shader needs:**
  - `Tron/World`: DepthOnly + DepthNormals + MotionVectors, about ½ to 1 day.
  - `Tron/Model`: the same three, about 1 day, because its alpha test runs the whole fixed-function
    stage evaluator.
  - `Tron/Effect`: none. URP never draws transparents in any of those passes.
  - `Tron/Glow`, `Tron/GlowComposite` and `Tron/HudText`: none.
- **SSAO done right means the Tron shaders sample the AO themselves.** Only then can fullbright and
  glowing texels skip it. That needs the AO texture before opaques, so it needs a prepass, so it needs
  the DepthNormals (or DepthOnly) passes. "After Opaque" mode needs no new pass, but it darkens
  everything, glowing lines included.
- **STP alone needs no new pass to get static geometry right.** Camera motion vectors come from the
  depth texture, which URP can copy after opaques. MotionVectors passes only matter for things that
  move: keyframed world models, doors, characters and props.
- **Effects will ghost or smear under STP and URP has no switch for it.** Transparents get no object
  motion vectors, and URP passes STP no "responsive" stencil (a `TODO` in `StpUtils.cs`).
- **STP runs on Metal**: compute shaders, `only_renderers ... metal`; it's excluded only on GLES. It
  needs the Render Graph path, which Unity 6000.3 already uses.

## 1. Which passes URP 17.3 looks for

| URP pass | LightMode tag(s) it draws | Queue range | Source |
|---|---|---|---|
| Depth prepass | `DepthOnly` | opaque (≤ 2500) | `Runtime/Passes/DepthOnlyPass.cs:26`, `Runtime/UniversalRenderer.cs:363` |
| Depth-normals prepass | `DepthNormals`, `DepthNormalsOnly` | opaque | `Runtime/Passes/DepthNormalOnlyPass.cs:19`, `Runtime/UniversalRenderer.cs:364` |
| Object motion vectors | `MotionVectors` | opaque | `Runtime/Passes/MotionVectorRenderPass.cs:14-15, 35` |
| Forward opaques/transparents | `UniversalForwardOnly`, `SRPDefaultUnlit` (no tag), `LightweightForward`, … | | `Runtime/UniversalRenderer.cs:393-397` |

The Tron shaders have one untagged pass each, which counts as `SRPDefaultUnlit`. So today they draw only
in the forward passes. In every prepass and in the object motion vector pass they are simply missing.

URP's own `Shaders/Unlit.shader` is the template to copy:

- `DepthOnly` (`ZWrite On`, `ColorMask R`, lines 146-180).
- `DepthNormalsOnly` (lines 186-221). It writes world-space normals to `_CameraNormalsTexture`,
  octahedral-packed under `_GBUFFER_NORMALS_OCT`; see `Shaders/UnlitDepthNormalsPass.hlsl`.
- `MotionVectors` (`ColorMask RG`, lines 261-273). It includes
  `ShaderLibrary/ObjectMotionVectors.hlsl`.

The manual says the same: a custom shader needs a pass tagged `"LightMode" = "MotionVectors"` that
matches its other passes' alpha clipping and vertex deformation. For transform-only or skinned motion
with no alpha test, it can use
`UsePass "Hidden/Universal Render Pipeline/ObjectMotionVectorFallback/MOTIONVECTORS"`. URP stopped adding
that fallback by itself in 2023.2. ([Output a motion vector texture in a custom shader](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/features/motion-vectors-custom-shader.html))

Because `ObjectMotionVectors.hlsl` hard-codes `_BaseMap` and `_Cutoff` for its alpha test, the Tron
shaders would write their own vertex/fragment on top of `ShaderLibrary/MotionVectorsCommon.hlsl`. They
keep its maths:

- `positionCSNoJitter = _NonJitteredViewProjMatrix · M · pos`
- `prev = _PrevViewProjMatrix · UNITY_PREV_MATRIX_M · (unity_MotionVectorsParams.x == 1 ? TEXCOORD4 : pos)`
- output `CalcNdcMotionVectorFromCsPositions`

## 2. When a prepass happens, and what SSAO asks for

`GetRenderPassInputs` (`Runtime/UniversalRenderer.cs:1860-1915`) sums up what the enqueued passes need:

- A pass that needs **normals always forces a depth(-normals) prepass**: "URP's forward passes don't
  support rendering into the normals texture" (line 1878).
- A pass that needs **depth only** forces a prepass only if it runs **before** `AfterRenderingOpaques`.
  Otherwise URP copies the depth buffer after opaques.
- TAA (so STP too) sets `requiresMotionVectors`, and motion vectors imply a depth texture
  (lines 1891-1907).

SSAO (`Runtime/Passes/ScreenSpaceAmbientOcclusionPass.cs:160-184`) works like this in Forward/Forward+:

| Settings | Event | Input | Consequence for the Tron shaders |
|---|---|---|---|
| Source = DepthNormals, After Opaque off (**today's setting**) | `AfterRenderingPrePasses + 1` | Depth + Normal | DepthNormals prepass. Without a `DepthNormals(Only)` pass in the Tron shaders, both depth and normals are empty. |
| Source = Depth, After Opaque off | same | Depth | Depth prepass. Needs `DepthOnly` passes. Normals rebuilt from depth (1, 5 or 9 taps). |
| After Opaque on (any source) | `BeforeRenderingTransparents` | Depth (+Normal) | With Source = Depth: no prepass, the copied depth works, **no shader change**. But URP then multiplies the AO over the finished opaque colour, glowing texels included. |

The AO only reaches a surface in two ways:

- **After Opaque** mode, a full-screen multiply over the colour.
- A shader that samples `_ScreenSpaceOcclusionTexture` under the global keyword
  `_SCREEN_SPACE_OCCLUSION` (`ShaderLibrary/AmbientOcclusion.hlsl:8-30`), which the SSAO pass sets
  (`ScreenSpaceAmbientOcclusionPass.cs:457`).

URP Lit and Shader Graph do the second. The manual's "works with every shader that URP provides" says no
more than that. ([SSAO](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/post-processing-ssao.html))
So the map's question about fullbright texels is answered only by the second route. The Tron shaders add
`#pragma multi_compile_fragment _ _SCREEN_SPACE_OCCLUSION`, then scale only their *lit* term:

- `Tron/World`: `c * i.color * sat`, the lightmap product, not the fullbright lerp toward `tex.rgb`.
- `Tron/Model`: the `dif` input when `lit > 0`.

They return early in the glow pass. That route needs the prepass, so it needs the passes in §4.

### What's running today

`PC_RPAsset` is the PC quality level's pipeline (`QualitySettings.asset:104`, current quality 1) and
uses `PC_Renderer`.

- `PC_Renderer` has SSAO with `AfterOpaque: 0`, `Source: 1` (= DepthNormals)
  (`Assets/Settings/PC_Renderer.asset:71-78`).
- `PC_RPAsset` also has `m_RequireDepthTexture: 1` and `m_RequireOpaqueTexture: 1` (lines 22-23).

`ScreenSpaceAmbientOcclusion.AddRenderPasses` filters only offscreen-depth cameras
(`Runtime/RendererFeatures/ScreenSpaceAmbientOcclusion.cs:166-177`). So the feature is enqueued for the
sky, main, glow and IO cameras alike, and every one of them gets a DepthNormals prepass with nothing in
it, then SSAO and its blurs. Removing it (or the opaque-texture copy) is invisible in faithful mode and
probably wins back some milliseconds. Measure it in the player build. Any SSAO kept for remaster
should sit on a second renderer that only the main camera uses (`UniversalAdditionalCameraData.SetRenderer`),
so the 256² glow camera, the sky and the IO inset don't pay for it.

## 3. Motion vectors for each thing that moves

The URP motion vector pass draws two things:

1. **Camera motion vectors**: a full-screen pass from the depth texture and the current and previous
   view-projection. Every pixel with depth gets them, whatever its shader.
2. **Object motion vectors**: drawn over that for renderers whose material has a `MotionVectors` pass,
   only in the opaque queue range.

Sources: [manual: motion vectors render pass](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/features/motion-vectors-render-pass.html),
`MotionVectorRenderPass.cs:84-90, 115-130`. It runs after the depth copy
(`UniversalRendererRenderGraph.cs:984-989`).

Per-object vectors are drawn only when the shader has the pass, the renderer is a MeshRenderer,
SkinnedMeshRenderer or `Graphics.RenderMesh*`, and its mode isn't *Camera Motion Only*. "URP does not
support motion vectors for transparent materials." ([manual: motion vectors](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/features/motion-vectors.html))

| Thing | How the viewer draws and moves it | What it needs |
|---|---|---|
| Static world (BSP) | `Tron/World` MeshRenderers under `World` (`LevelBuilder.cs:106-110`) | Nothing: camera motion vectors from depth are exact. Depth has to be in the depth texture: a copy after opaques works with today's single pass, a prepass needs `DepthOnly`/`DepthNormals`. |
| Keyframed world models, doors, spinners | `Tron/World` MeshRenderers whose `transform` is moved (`ActiveWorldModelObject.cs:56-64`, `LevelBuilderDoors.cs:43-44`) | A `MotionVectors` pass in `Tron/World`. Unity supplies `UNITY_PREV_MATRIX_M` for a MeshRenderer whose transform changed. Without the pass they reproject as if static and ghost. |
| Characters | `SkinnedMeshRenderer` driven by bone Transforms (`LevelBuilder.cs:369-377`, `ModelAnimator`) | A `MotionVectors` pass in `Tron/Model` reading `TEXCOORD4` (previous skinned position, flagged by `unity_MotionVectorsParams.x == 1`). That's the default for skinned renderers (`skinnedMotionVectors` on). |
| Props and attachments | `Tron/Model` MeshRenderers parented to sockets and bones | The same pass: the previous matrix covers them. |
| Effect models | `ModelFXRenderer.cs:129-140`, SMR or MeshRenderer | The same pass where their material is opaque. Most are blended, so Transparent, and get none. |
| Sprites, particles, lightning, trails | `Tron/Effect`, rebuilt world-space quads via `Graphics.RenderMesh` (`SpriteDrawer.cs:148-158`, `ParticleRenderer.cs:157-167`, `DrawPrimRenderer.cs:160-170`) | Nothing can help: Transparent queue, no object motion vectors in URP, no depth write. They take the motion of whatever is behind them. See §5. |
| Camera on rails, screen shake, jitter | The same main camera moved by `SceneCameraView.cs:91-92`, `CameraJitter`, `ScreenShake` | Correct by itself: URP keeps the previous view-projection per camera. **Cuts** (scene camera switches, Space skip, free-flight toggle, level load, teleports) need `UniversalAdditionalCameraData.resetHistory = true` that frame (`UniversalAdditionalCameraData.cs:844-849`). Without it one frame reprojects across the cut. |
| Sky | Separate **Base** camera, with the main camera as an **Overlay** on its stack (`TronExplorer.cs:305-327`) | Has to change; see §5. Once the sky is drawn behind the main camera at far depth, camera motion vectors give the right rotation and only a small error from the `SkyDims` parallax. |
| Texture scripts (scrolling UVs), animated sprite frames, light-group colour changes | Shader/material changes, no motion | Not representable as motion. Left to STP's colour clamping. Usually fine, at worst a soft trail on fast scrolls. |

## 4. Effort for each shader

The common pattern: move the vertex transform, `TexFx`/UV and alpha-test code into an `HLSLINCLUDE`
block, so the new passes evaluate the same alpha as the forward pass. Each new pass keeps
`ZWrite [_ZWrite]`, `ZTest [_ZTest]`, `Cull [_Cull]`. URP filters those passes to the opaque range,
which already leaves out every blended material: those go to `RenderQueue.Transparent` in
`LevelBuilder.cs:618-622` and `:656`. Faithful mode stays pixel-identical: extra passes are drawn only
when a feature asks for them, and the forward pass doesn't change unless the
`_SCREEN_SPACE_OCCLUSION` variant is on.

- **`Tron/World`: about ½ to 1 day.**
  - Passes: `DepthOnly`, `DepthNormalsOnly` (mesh normals), `MotionVectors` (previous matrix only).
  - Alpha test: `_Cutoff` on `_MainTex` sampled at the `TexFx`-transformed UV, so `TexFx` goes into the
    include.
  - Sky materials (Background queue, `ZWrite 0`) are on the sky layer, which the main camera doesn't
    draw.
  - Optional AO sampling on the lit and lightmap terms, kept off fullbright texels.
- **`Tron/Model`: about 1 day.**
  - Passes: the same three.
  - Alpha test: the alpha test (`AlphaPass` over `EvalPass`) depends on the fixed-function stage
    evaluation, textures included, and on the vertex-lit alpha
    (`_MatDiffuse.a · (1 − _LTTransparency)`). The depth passes have to run the same `EvalPass`
    (alpha only).
  - Glow-only draws (`_P0.x < 0`) must `discard` in every new pass, or they write depth, normals and
    motion for geometry that only exists in the glow buffer.
  - Motion vectors read `TEXCOORD4` for skinned renderers.
  - Optional AO on `dif` for lit passes.
- **`Tron/Effect`: no passes.** It is always in the Transparent queue, so URP never draws it in a
  prepass or in the motion vector pass. The cost is in ghosting (§5), not in shader work.
- **`Tron/Glow`, `Tron/GlowComposite`, `Tron/HudText`: none.**
  - The glow is a separate base camera into a fixed 256² RT, composited in `OnGUI` after the frame
    (`TronExplorer.cs:338-356, 672`). It sits outside STP and isn't jittered, which is fine for a
    blurred buffer.
  - The HUD is drawn in `OnGUI` too.

**Plumbing outside the shaders**, which costs more than the shaders do:

- **Sky without camera stacking**, about 1 day. Options:
  - Render `skyCam` into an RT and draw it as the main camera's background, from a renderer feature at
    `BeforeRenderingOpaques` or a far quad.
  - Draw the sky layer in the main camera's renderer with its own view matrix.

  Either way the main camera becomes Base. Faithful mode may keep the current stack.
- `renderPostProcessing = true` on the main camera in remaster mode; it's `false` today
  (`TronExplorer.cs:307`). `IsTemporalAAEnabled` requires post-processing.
- `resetHistory` on every cut (see §3).
- A second renderer without SSAO for the sky, glow and IO cameras, or SSAO removed from `PC_Renderer`
  for faithful mode.
- The IO camera inset is a second Base camera with post-processing off (`IOCamView.cs:60-69`). It gets
  no STP, only plain upscaling. That's acceptable for a small inset.

## 5. STP: requirements, Metal, and surfaces with no motion vectors

- **When STP runs.** STP is TAA's prerequisite. URP forces AA to TAA whenever STP is selected, even at
  render scale 1 (`UniversalRenderPipeline.cs:1533-1543`; [manual: enable STP](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/stp/stp-enable.html):
  "STP remains active when Render Scale is set to 1.0").
- **Conditions.** `IsSTPEnabled = IsSTPRequested && IsTemporalAAEnabled` (`UniversalCameraData.cs:497-533`).
  `IsTemporalAAEnabled` requires:
  - post-processing on for the camera;
  - MSAA 1×;
  - **no camera stack and not an overlay**;
  - no `allowDynamicResolution`;
  - a renderer that supports motion vectors.

  Otherwise STP doesn't run, and URP says STP "should behave identically to TAA in cases where TAA
  support requirements aren't met". "STP is not compatible with Dynamic Resolution in URP, only with
  Render Scale" (manual).
- **Platform.** `STP.IsSupported()` is `SystemInfo.supportsComputeShaders && device != OpenGLES3`
  (`core: Runtime/STP/STP.cs:19-31`). The STP kernels carry
  `#pragma only_renderers d3d11 ... vulkan metal ...` (`StpSetup.compute:17`, `StpPreTaa.compute:10`,
  `StpTaa.compute:10`). URP falls back to Auto if STP isn't supported **or Render Graph is off**
  (`UniversalRenderPipeline.cs:2259`). Render Graph is the only path in 6000.3 unless
  `URP_COMPATIBILITY_MODE` is defined, and the project defines no scripting symbols
  (`ProjectSettings.asset:836`). The manual: "STP uses compute shaders, so target platforms must support
  Shader Model 5.0"; it is not supported on OpenGL ES.
  ([manual: STP](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/stp/stp-upscaler.html))
  Apple silicon on Metal meets all of that. There's an `ENABLE_LARGE_KERNEL` variant only for Qualcomm
  (`STP.cs:1103`), so Apple GPUs get the small kernel. The manual names no Metal caveat.
- **Surfaces that write no motion vectors.** They get the camera's motion vectors from the depth texture
  (§3). For a moving opaque without a `MotionVectors` pass, STP reprojects it as static. History
  rejection then has to catch it, which leaves trailing ghosts on fast movers: characters, doors,
  keyframed platforms.

  Transparent effects have no depth and no object motion vectors, so they take the vectors of the
  surface behind them. Additive sparks, lightning, trails and particles over a moving background or
  camera smear or ghost.

  STP has a "stencil responsive" feature for exactly this ("typically used for transparent objects
  like sparks"), but URP 17.3 never feeds it: `config.stencilMask = 0` with
  `// TODO: Support STP Stencil Responsive Feature in URP (JIRA: GFXRT-366)` (`Runtime/StpUtils.cs:45-52`).
  There's no URP-side switch to mitigate it. Options, all outside this ticket:
  - accept it and judge it on captures of m10-04's explosions;
  - write effect motion into the motion vector texture with a custom pass;
  - draw the effects after STP in a separate pass at output resolution (they'd no longer be anti-aliased).

## Open points for the tickets that consume this

- What it costs: measure SSAO plus prepass at 3600×2260 in the player build, and how much faithful mode
  gains by dropping today's unused SSAO, depth texture and opaque texture.
- Whether the effects' ghosting under STP is acceptable. That's a visual judgement on captures, not
  something to settle from reading.
