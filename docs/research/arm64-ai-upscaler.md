# AI upscalers that run offline on macOS arm64 without Rosetta

Research for #95 (map #91, remaster mode). Question: which image upscalers suited to flat-colour,
clean-line textures run natively on macOS 27 arm64 with no Rosetta, scriptable from `tools/`, under
which licences (code and weights), and how do they handle small inputs, alpha and tiling textures?

Read-only survey, 2026-10-20: nothing installed or downloaded. Sources are the projects' own repos,
release pages, CI workflows, licence files and PyPI metadata.

## Answer

Ranked for an HD-texture step in `tools/`:

| # | Tool | Native arm64? | Code licence | Weights licence | Alpha | Wrap seams |
|---|------|---------------|--------------|-----------------|-------|------------|
| 1 | **realesrgan-ncnn-vulkan** v0.2.0 CLI (models `realesrgan-x4plus-anime`, `realesr-animevideov3` x2/x3/x4) | Yes: universal binary (`lipo` of x86_64 + arm64), MoltenVK linked statically | MIT | BSD-3-Clause (Real-ESRGAN repo; no separate weights licence) | RGB through the net, **alpha bicubic** (separate) | Reflect-padded at the image edge: seams. Pre-pad with wrap in Python |
| 1b | **waifu2x-ncnn-vulkan** 20250915 / **realcugan-ncnn-vulkan** 20220728 CLIs | Yes: universal, same build recipe | MIT | MIT (waifu2x; Real-CUGAN `LICENSE` in bilibili/ailab) | Alpha bicubic | Same as above |
| 2 | **PyTorch 2.14.1 + spandrel 0.4.2** in the existing venv (MPS) | Yes: `torch-2.14.1-cp314-cp314-macosx_14_0_arm64.whl`; spandrel pure Python | BSD-style (torch), MIT (spandrel core) | Per model: Real-ESRGAN BSD-3, Real-CUGAN MIT; community models vary (often CC BY-NC-SA) | Whatever we write: alpha can be resized without AI | Whatever we write: `F.pad(mode="circular")` |
| 3 | **nunif / waifu2x** (swin_unet `art`, `art_scan`) | Yes via PyTorch MPS; docs ask for Python 3.12, so a second venv | MIT | MIT repo releases | Bleeds colour into transparent texels (`AlphaBorderPadding`), alpha upscaled by the 2x/4x model or bilinear | `replicate` padding: seams |
| 4 | **chaiNNer** 0.26.0 | Yes: `macos-universal.dmg`; MPS documented | GPL-3.0 | any model you load | Node graph | Node graph |
| 5 | **Upscayl** (app / `upscayl-bin`) | Yes: universal | AGPL-3.0 | bundled models mostly CC BY-NC-SA 4.0 (UltraSharp, Remacri) | as ncnn CLIs | as ncnn CLIs |

Recommendation: **(1) the ncnn-vulkan CLIs** for the pipeline. They are self-contained (no Python
packages, models in the zip), permissive in code and weights, already scale alpha without AI (what the
map's HD texture note asks for), and are driven by `subprocess` from `tools/`. Use **(2) torch + spandrel**
only if the CLIs misbehave under macOS 27 / MoltenVK, or if a model outside the ncnn set is wanted;
it is the most controllable but adds a large dependency to `.venv`. chaiNNer is useful by hand to pick
a model on sample textures, not for the pipeline. Avoid Upscayl's bundled models (non-commercial).

Seams on tiling textures are **our job in every option**: none of them wraps. Pad the decoded
texture with `numpy.pad(mode="wrap")` (or tile it 3x3 when it is ≤ 64 px), upscale, crop the centre
back to `scale × (w, h)`. This also gives tiny textures enough context.

**Not verified here** (needs one run, ~10 MB download, left to the implementation ticket): that the
2022 `realesrgan-ncnn-vulkan` binary, built against Vulkan SDK 1.2.162's MoltenVK, still finds the GPU
on macOS 27. The 2025 waifu2x-ncnn-vulkan build and the 2026 `ncnn` wheel use far newer SDKs, so they
are the fallback if it doesn't.

## The textures (what we would feed in)

The viewer reads DTX straight from `extracted/` at runtime (`DtxLoader.Root`; textures are not
exported to `export/` today). `tools/dtx.py` already decodes a DTX's first mip to RGBA with Pillow
(BGRA32 raw, or DXT1/3/5 via Pillow's `bcn` decoder) and reads the fullbright flag, so an HD step can
start there and write PNGs to `export/textures_hd/`. `DtxLoader` creates every texture with
`wrapMode = Repeat`, trilinear, aniso 4 (`DtxLoader.cs:139`).

Survey of every `.dtx` under `extracted/` (header fields as in `tools/dtx.py`):

- **8,500 DTX**, all power-of-two; 4,557 fullbright. 698 Mpx at the first mip.
- Format: 6,007 DXT5, 667 DXT1, 126 DXT3, 1,700 uncompressed BGRA32. Most carry an alpha channel,
  and all compressed ones carry DXT block artefacts.
- Largest side: ≤ 32 px 1,169; ≤ 64 px 1,113; ≤ 128 px 1,147; ≤ 256 px 2,820; ≤ 512 px 1,858;
  > 512 px 393. So ~40 % are 128 px or less: small inputs are the norm.
- By folder: `tex/prototype` 6,329 (world), `chars/skins` 397, `interface/hud` 356, `fx/tex` 317,
  `interface/subroutines` 242, `props/skins` 204, `interface/menu` 145, `weapons/*` ~200.

At 4x the first mips become ~11 Gpx (~45 GB as raw RGBA); at 2x ~2.8 Gpx. Only the textures the
levels reference need doing (not counted here), and the per-category exclusion list cuts it further.
The HUD/interface folders are the obvious exclusion candidates (#91: HUD at native resolution).

## Per tool

### ncnn-vulkan CLIs (Real-ESRGAN, waifu2x, Real-CUGAN)

- **Builds.** `xinntao/Real-ESRGAN-ncnn-vulkan` latest release v0.2.0 (2022-04-24) ships
  `realesrgan-ncnn-vulkan-v0.2.0-macos.zip`. Its `.github/workflows/release.yml` builds
  `CMAKE_OSX_ARCHITECTURES="x86_64"` and `"arm64"`, links MoltenVK statically
  (`-DUSE_STATIC_MOLTENVK=ON`, `MoltenVK.xcframework/macos-arm64_x86_64/libMoltenVK.a`) and joins the two
  with `lipo -create`: a universal binary that runs natively on arm64. `nihui/waifu2x-ncnn-vulkan`
  (release 20250915, newer Vulkan SDK) and `nihui/realcugan-ncnn-vulkan` (20220728) use the same recipe.
- **Licences.** Real-ESRGAN-ncnn-vulkan `LICENSE`: MIT (Xintao Wang), plus realsr-ncnn-vulkan's MIT
  (nihui). Weights are the `xinntao/Real-ESRGAN` release assets; that repo is BSD-3-Clause and states no
  separate licence for the `.pth` files. waifu2x and realcugan ncnn ports: MIT; waifu2x models come from
  `nagadomi/waifu2x` (MIT); Real-CUGAN from `bilibili/ailab/Real-CUGAN/LICENSE` (MIT, 2022 bilibili).
- **Models for flat colour.** Real-ESRGAN's `docs/model_zoo.md` lists `RealESRGAN_x4plus_anime_6B`
  ("optimized for anime images", smaller net) and `realesr-animevideov3` (x2/x3/x4, "XS size"); the ncnn
  CLI's `-n` takes `realesr-animevideov3 | realesrgan-x4plus | realesrgan-x4plus-anime | realesrnet-x4plus`
  (Real-ESRGAN `README.md`). Anime models flatten gradients and sharpen lines, which suits Tron's
  textures; GAN models can invent detail on 32 px inputs, so A/B before batch runs. waifu2x (2x, noise
  levels 0–3) is the conservative option and can remove DXT block noise.
- **Alpha.** `src/realesrgan.cpp`: with 4 channels the RGB goes through the net and the alpha tile
  through ncnn `Interp` bicubic 2x/3x/4x ("bicubic 2x/3x/4x for alpha channel"). waifu2x.cpp and
  realcugan.cpp do the same ("bicubic 2x for alpha channel"). Transparent texels keep whatever RGB they
  had; for alpha-tested textures bleed colour into them first (as nunif does) to avoid dark fringes.
- **Tiling / edges.** Internal tiles (`-t`) overlap by `prepadding` texels, so no seams between GPU
  tiles. At the image border `realesrgan_preproc.comp` mirrors coordinates (`x = abs(x)`,
  `(w-1) - abs(x - (w-1))`): reflect padding, so a wrapping texture's opposite edges are upscaled
  independently and will seam. Wrap-pad before, crop after.
- **Scriptable:** plain CLI (`-i -o -n -s -t -f png`), folder in / folder out. Unsigned download:
  needs `xattr -d com.apple.quarantine`.
- **Python bindings** `realesrgan-ncnn-py` / `realcugan-ncnn-py` / `waifu2x-ncnn-py` 2.0.0 (Final2x):
  universal2 wheels only for cp39–cp312, repos archived. **They do not install in our `.venv`
  (Python 3.14.8).** The `ncnn` wheel itself does (`ncnn-1.0.20261020-cp314-cp314-macosx_11_0_arm64.whl`,
  built with the Vulkan SDK 1.4.335.1 per `release-python.yml`), if we ever wanted to run the `.param/.bin`
  models from Python and do the tiling ourselves.

### PyTorch + spandrel (MPS)

- `torch` 2.14.1 (2026-09-30) has `cp314-cp314-macosx_14_0_arm64` wheels; MPS is PyTorch's Apple GPU
  backend. `spandrel` 0.4.2 (MIT, `requires_python >=3.10`, pure Python) auto-detects and loads `.pth` /
  `.safetensors` for ESRGAN/Real-ESRGAN (RRDBNet), Real-ESRGAN Compact (SRVGGNet), Real-CUGAN, SwinIR,
  HAT, DAT, SPAN and more (`README.md`). The core package holds only permissive architectures;
  non-commercial ones are in `spandrel_extra_arches`.
- Alpha, padding and tiling are ours to write: `F.pad(..., mode="circular")` solves wrap seams in one
  line; alpha can go through Pillow `LANCZOS`/bicubic or nearest for alpha-tested masks.
- Cost: torch is a large install into `.venv` (the venv today is numpy, Pillow, pytest).
- Don't use the `realesrgan` / `basicsr` packages themselves: last releases 2022, no wheels, and
  `basicsr` imports `torchvision.transforms.functional_tensor`, removed from torchvision
  (Real-ESRGAN issues #783, #859, #891). Their `RealESRGANer.enhance` is still the reference behaviour:
  `pre_pad=10` and `tile_pad=10` with `reflect` padding; alpha via the net (`alpha_upsampler='realesrgan'`)
  or `cv2.resize` linear (`realesrgan/utils.py`).

### nunif (waifu2x successor)

- `nagadomi/nunif`, MIT, active (pushed 2026-10-20). `nunif/device.py` picks `mps` when CUDA is absent.
  `INSTALL-macos.md` installs Python 3.12 via Homebrew and `requirements-torch.txt`: a separate venv,
  not `.venv`.
- `waifu2x/ui_utils.py`: `--style art | photo | scan | art_scan` (swin_unet models), `--noise-level 0–3`,
  `--tile-size`. `waifu2x/utils.py`: `AlphaBorderPadding` fills transparent texels' RGB from their
  neighbours before the net; alpha is upscaled by the scale model (as 3 channels) or bilinear when that
  model is missing; an all-opaque alpha is skipped.
- `nunif/utils/render.py` pads tiles with `mode="replicate"`: seams on wrap.
- Weights: `waifu2x_pretrained_models_*.zip` on the nunif `0.0.0` release, MIT repo. README's licence
  note concerns PyAV's GPL ffmpeg in binary builds only.

### chaiNNer

- 0.26.0 (2026-10-18), `chaiNNer-0.26.0-macos-universal.dmg`, GPL-3.0. README: "Apple Silicon Macs are
  supported with PyTorch MPS acceleration. ONNX only supports the CPU Execution Provider, and NCNN may not
  work properly on some configurations." Node-graph GUI; CLI usage is only in the wiki. Good for picking
  a model on sample textures; not a `tools/` dependency.

### Upscayl

- `upscayl/upscayl` v2.15.0 (mac dmg/zip) and `upscayl/upscayl-ncnn` (`upscayl-bin`, release
  20251207, macOS job builds x86_64 on macos-13 and arm64 on macos-14 then a universal job). AGPL-3.0.
- Bundled models (`resources/models`): `ultrasharp-4x`, `remacri-4x`, `digital-art-4x`, … OpenModelDB
  lists 4x-UltraSharp and 4x-Remacri as CC-BY-NC-SA-4.0. Avoid for anything redistributed.

### Core ML

- No maintained Core ML upscaler CLI turned up. `imxieyi/waifu2x-mac` (MIT) is an app, last pushed
  2023-01, no releases. `john-rocky/CoreML-Models` has no licence and ships other models. Converting a
  model ourselves needs `coremltools` 9.0, whose arm64 wheels stop at cp313 (no cp314 for `.venv`).
  Core ML would buy ANE speed we don't need for an offline batch job.

## Sources

- https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan (releases v0.2.0, `.github/workflows/release.yml`,
  `LICENSE`, `src/realesrgan.cpp`, `src/realesrgan_preproc.comp`)
- https://github.com/xinntao/Real-ESRGAN (`LICENSE` BSD-3-Clause, `README.md`, `docs/model_zoo.md`,
  `realesrgan/utils.py`, issues 783/859/891)
- https://github.com/nihui/waifu2x-ncnn-vulkan (release 20250915, `release.yml`, `src/waifu2x.cpp`)
- https://github.com/nihui/realcugan-ncnn-vulkan (release 20220728, `release.yml`, `src/realcugan.cpp`)
- https://github.com/bilibili/ailab/blob/main/Real-CUGAN/LICENSE
- https://github.com/nagadomi/waifu2x (MIT)
- https://github.com/nagadomi/nunif (`README.md`, `INSTALL-macos.md`, `waifu2x/ui_utils.py`,
  `waifu2x/utils.py`, `nunif/utils/render.py`, `nunif/device.py`)
- https://github.com/chaiNNer-org/spandrel (`README.md`), https://pypi.org/project/spandrel/
- https://github.com/chaiNNer-org/chaiNNer (release v0.26.0, `README.md`)
- https://github.com/upscayl/upscayl, https://github.com/upscayl/upscayl-ncnn (`release.yml`)
- https://github.com/OpenModelDB/open-model-database (`data/models/4x-UltraSharp.json`, `4x-Remacri.json`)
- https://github.com/Tencent/ncnn (`.github/workflows/release-python.yml`, `setup.py`), https://pypi.org/project/ncnn/
- PyPI JSON for `torch`, `onnxruntime`, `coremltools`, `realesrgan`, `basicsr`, `realesrgan-ncnn-py`,
  `realcugan-ncnn-py`, `waifu2x-ncnn-py`
- This repo: `tools/dtx.py`, `TronViewer/Assets/Tron/Scripts/DtxLoader.cs`, DTX header survey of
  `extracted/` (2026-10-20)
