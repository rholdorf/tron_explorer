# Trial 4× upscale of representative DTX textures

Task #100 (map #91, remaster mode). Follows [arm64-ai-upscaler.md](https://github.com/rholdorf/tron_explorer/blob/research/arm64-ai-upscaler/docs/research/arm64-ai-upscaler.md) (#95).
Question: do the ncnn-vulkan upscalers actually run on this machine, and what do their 4× results look like
per texture category? Run 2026-10-21 on an Apple M3 Pro, macOS 27 arm64, no Rosetta, entirely in scratch.

## Answer

- **They run natively and find the GPU.** Both are universal binaries; ncnn picks `[0 Apple M3 Pro]` through
  the statically linked MoltenVK, even the 2022 Real-ESRGAN build.
- **Model: waifu2x `cunet`, noise level 3, scale 4** (`w2x-n3`) is the most faithful. It cleans the DXT
  blocks and invents nothing. `realesr-animevideov3` (`esr-av3`) comes close, softer and 2× faster.
  **`realesrgan-x4plus-anime` is rejected**: it hallucinates. It paints jagged white "text" into the grey bevels of
  `firewallm09_w20`, adds brush strokes to Jet's beard and smears `digicubes_14`.
- **Alpha: never through the net, and never with Pillow's RGBA resize.** Run alpha through the net as grey RGB
  and it sharpens the masks into hard steps, invents lines (`m10q_l19`, `digicubes_14`) and rings (`m04x_t07`).
  The mean difference from bicubic alpha is up to 28/255, the maximum over 200. The CLIs' own alpha path *is* bicubic: it matches
  per-channel Pillow bicubic to within ~1/255. Pillow's `Image.resize` on an RGBA image premultiplies, so
  wherever alpha is 0 it **blackens the RGB**. On fullbright textures that is most of the texture, because alpha
  is the glow mask, not coverage (`labwall04`: 98 % of texels under 128). The pipeline must resize
  RGB and A as separate channels.
- **Wrap padding works.** Without it, `m07b_f03` and `m06grid09` seam at the wrap edge: the edge step is 36.6× and
  3.3× the mean interior step, against 3.0× and 0.1× padded. Pad 16 texels each side, or a whole tile when
  the side is ≤ 64 px, then crop.

## Per category

Contact sheets (2×2 tile around the wrap corner, 256 px crop of the 4× result) are game imagery, so they stay
out of this public repo: `reference/hd-texture-trial/<category>.png` locally (gitignored); `sheet.py` regenerates them.

| Category | Sheet | Verdict |
|---|---|---|
| World, tiling | `world.png` | Small gain: the geometry is flat colour and clean lines. `w2x-n3` removes DXT blotches (`m07b_f03`) without seams. Worth it, low risk. |
| Fullbright with glow alpha | `glow.png` | RGB: `w2x-n3` / `esr-av3` fine. Alpha (glow mask): bicubic, separately. `x4plus-anime` invents detail in dark grey areas. |
| Model and prop skins | `models.png` | **Largest gain.** 128–256 px faces and torsos lose their DXT blocks and pixel stair-steps; `w2x-n3` keeps the painted look. |
| Effect sprites | `effects.png` | **No gain.** Soft additive gradients: bicubic looks the same; AI only risks artefacts. Exclude. |
| HUD art | `hud.png` | Mixed: the AI cleans tiny icons (`pset_icon_2`, 32 px), but waifu2x turns the scanlines of `helpimg_hogs` into moiré. Hangs on #101. |

## Cost

Padded input 1.75 Mpx (18 textures) in folder mode, wall clock including startup: `esr-av3` 1.8 s,
`w2x-n3` 3.8 s, `x4plus-anime` 7.5 s. A single 512² texture: 0.5 s / 1.0 s / 1.7 s. That extrapolates to
~25 min (`esr-av3`), ~45 min (`w2x-n3`) or ~1.5 h (`x4plus-anime`) for all 8,500 DTX (698 Mpx), less for only the textures the levels
reference. PNG output at 4× runs ~0.5 B per output pixel, so ~5–6 GB for every DTX.

## How to rerun

```sh
S=<scratch>
# binaries (unsigned: xattr -dr com.apple.quarantine $S/bin)
curl -LO https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip   # binary + models
curl -LO https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/20250915/waifu2x-ncnn-vulkan-20250915-macos.zip
# unzip to $S/bin/esr2 and $S/bin/w2x
.venv/bin/python -I docs/research/hd-texture-trial/trial.py $S && .venv/bin/python -I docs/research/hd-texture-trial/sheet.py $S
```

Pitfalls met:
- The `Real-ESRGAN-ncnn-vulkan` v0.2.0 macOS zip ships **without models**. Use the `realesrgan-ncnn-vulkan-20220424-macos.zip`
  from the main Real-ESRGAN release.
- Real-ESRGAN finds its models relative to the cwd and **exits 0 having written nothing** when it can't: always pass `-m`.
- The seam metric (edge step / interior step) is noisy on near-black textures (`labwall04`); judge seams on the sheets.
