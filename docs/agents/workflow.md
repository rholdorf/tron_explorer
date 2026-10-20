# Workflow

How to export, drive the Unity viewer, build, and measure. Read this before touching `tools/` or `TronViewer/`.

## Basics

- **Unity**: Editor `6000.3.26f1`, project `TronViewer/`, scene `Assets/Scenes/Explorer.unity`. Drive it through the `unity` CLI (skill `unity-cli`) with `UNITY_PROJECT_PATH=/Users/rui/src/pg/tron_explorer/TronViewer`; run `unity status` first. If the Editor is closed, **ask the user** before reopening it (`unity open TronViewer`). There is one Editor, on the main checkout: agents in worktrees must not drive it.
- **Export** after changing `tools/`: `.venv/bin/python -I tools/export_level.py extracted export` (~13 s, all 63 levels + models; the first run also writes the levels' sound files and their dialogues' voices to `export/sounds/`, ~500 MB, decoding the MP3-in-WAV ones with macOS `afconvert`, and later runs skip unchanged ones). It also writes `export/hud/`: the game strings from `cres.dll`, the HUD font (Tw Cen MT rendered to an atlas with Pillow), the subtitle layout and the HUD's interface sounds. If the format changed, bump `FORMAT_VERSION` in Python and in C# (`LevelBuilder.FormatVersion`, `ModelLibrary.FormatVersion`); levels exported before the bump will not load.
- **Bench glTF** (#40, for mus-y-sinak): `.venv/bin/python -I tools/bench_gltf.py extracted retailsingleplayer/m01-01` writes `export/bench/m01-01.glb` (~6 s, 377 primitives). One primitive per family × texture × animated × overlay, render roles in each primitive's `extras` (conventions in the module docstring and `asset.extras.primitiveExtras`). x is mirrored so Unity's glTF importers land on the viewer's coordinates. Tron 2.0 levels are vertex-lit (m01-01 has no lightmaps): the light hint is `vertexLight`. mus-y-sinak's camera poses (`docs/reference-panel.json` there: `eye` in metres, `yaw`/`pitch` in degrees, vertical `fov`) are already in the viewer's frame: camera position = `eye` (Unity units = LithTech units × `LT.Scale` = metres), rotation `Quaternion.Euler(pitch, yaw, 0)` as `PlayerController` does (positive pitch looks down), `Camera.fieldOfView = fov`. Place the body at `eye - Cam.localPosition`. Checked against `GameStartPoint` and three shots (#45).
- **Tests**: `.venv/bin/python -I -m pytest tools/tests -q`. They read game data from `/Users/rui/src/pg/tron_explorer/extracted` (override with `TRON_EXTRACTED`), so they also run from a worktree. A worktree has no `extracted/` or `export/` of its own; export to a scratch directory, never into the main checkout's `export/`.
- **Measure performance only in the player build**, never in the Editor. App: `-level <level> -benchmark 8` writes a `BENCH` line to the log and quits; `-benchat "x y z yaw pitch"` (LT units, degrees) measures from there in noclip and `-benchcmd "<command>"` runs a level command after the warm-up (m10-04's 375 explosion SpecialFX: `msg <name> ON` for each object whose FxName holds `Exlpo`, joined with `; `, at `-benchat "-382 79 8378 0 15"`). Reference-panel captures (#46): `Build/TronExplorer.app/Contents/MacOS/* -level retailsingleplayer/m01-01 -shots ../mus-y-sinak/docs/reference-panel.json -out ../mus-y-sinak/reference/tron2 -screen-width 1706 -screen-height 772 -screen-fullscreen 0` waits out the level-start fade, writes one 1706×772 PNG per posed shot (no HUD; triggers keep the spawn box while the camera flies) and logs a `SHOTS` line. `-frames "<seconds> ..." -out <dir>` saves the screen as shown (HUD and subtitles too) at those times after the load to `<dir>/<seconds>.png`, then quits (add `-mute` to any run to start muted, as M does): what the build shows, to compare with the game's video (the agent can't screenshot the player's window). Baseline at 1080p (2026-10-12): intro ~1.2 ms, m10-04 ~1.3 ms, m01-02 ~1.4 ms, m01-01 ~2.0 ms, m02-04 ~2.5 ms per frame; with particles (2026-10-18): m01-01 1.6 ms, m10-04 1.4 ms, m10-04 with every explosion fired 1.8 ms (p95 2.9 ms). With effect models (2026-10-18): m01-01 1.7 ms, m10-04 1.4 ms, m02-01 1.6 ms, m09-03 at `-benchat "-7097 6074 -7071 225 10"` 1.15 ms, with its 29 `WORLDS_WallDisplay_Debris` SpecialFX fired (464 models) 1.2 ms (p95 1.9 ms). With effect sprites (2026-10-18): m01-01 1.7 ms, m10-04 1.3 ms, m10-04 with every explosion fired 2.0 ms (p95 3.0 ms), m09-02 1.1 ms. With lightning and trails (2026-10-18): m01-01 1.7 ms, m10-04 1.35 ms (single runs vary by 0.2 ms: repeat before reading a change), m06-04 1.3 ms, m10-02 at `-benchat "8680 352 -18470 0 0"` 1.17 ms, with `msg lightning1 ON; msg lightning2 ON; msg lightning3 ON` 1.19 ms. With camera jitter, sprite systems and dynamic lights (2026-10-18): m01-01 1.7 ms, m10-04 1.4 ms, intro at `-benchat "-8620 -72420 24560 225 0"` 2.03 ms, with `msg jetdigitization on` 2.74 ms (its light relights the ~200 effect models it reaches every frame, ~0.6 ms). With cutscenes (2026-10-18): a plain `-benchmark` on a level that opens with a scene camera (intro, m10-04, m07-02, ...) measures from that camera while its scene plays; use `-benchat` to measure from the player's view. m01-01 1.7 ms, m10-04 plain 1.4 ms (from its opening scene camera), at `-benchat "-382 79 8378 0 15"` 1.5 ms, with every explosion fired 2.15 ms (p95 3.2 ms), intro plain (its opening scene) 1.5 ms.
- **Commits**: the user asks for commits and pushes explicitly; they go straight to `main`. The hook `~/.claude/hooks/block-git-push.py` allows push in this repository.
- **Format reference**: `bibendovsky/ltjs` on GitHub, via `gh api repos/bibendovsky/ltjs/contents/<path> --jq .content | base64 -d`.

## Helper scripts

Recreate them in the session scratchpad.

```zsh
# Before capturing anything: keep the unfocused Editor ticking, then unpause after editor_play
# (Play mode can start paused; Time.frameCount stuck at 2 means frozen).
unity command set_autotick
unity command editor_play
unity command eval 'UnityEditor.EditorApplication.isPaused = false; UnityEngine.Application.runInBackground = true; return 1;'

# load a level in Play mode
unity command eval 'UnityEngine.Object.FindFirstObjectByType<Tron.TronExplorer>().Load("m01-01"); return 1;' --timeout 60000

# cap.sh out.png: capture the Editor's Game view (in Play mode)
unity command capture_game_view --no-banner --format json 2>/dev/null | .venv/bin/python -I -c "
import json,sys,base64; d=json.load(sys.stdin); open(sys.argv[1],'wb').write(base64.b64decode(d['data']['result']['base64']))" "$1"

# tp.sh x y z yaw pitch out.png: noclip to a point (LithTech units) and capture
unity command eval "var p = UnityEngine.Object.FindFirstObjectByType<Tron.PlayerController>(); p.Noclip = true; p.transform.position = new UnityEngine.Vector3($1f,$2f,$3f) * Tron.LT.Scale; p.SetView($4f,$5f); return 1;" --no-banner >/dev/null; sleep 1; ./cap.sh $6

# aim.sh tx ty tz ox oy oz out.png: stand at target+offset (Unity units) looking at the target, and capture.
# Find a target with an eval over Renderers, e.g. r.name.Contains("archivebin") -> r.bounds.center.
unity command eval "var p = UnityEngine.Object.FindFirstObjectByType<Tron.PlayerController>(); p.Noclip = true; var t = new UnityEngine.Vector3($1f,$2f,$3f); var e = t + new UnityEngine.Vector3($4f,$5f,$6f); p.transform.position = e; var d = t - e; p.SetView(UnityEngine.Mathf.Atan2(d.x,d.z)*UnityEngine.Mathf.Rad2Deg, -UnityEngine.Mathf.Asin(d.normalized.y)*UnityEngine.Mathf.Rad2Deg); return 1;" --no-banner >/dev/null; sleep 2; ./cap.sh $7

# build (Editor open, outside Play mode)
unity command eval --timeout 900 -- --code 'var r = UnityEditor.BuildPipeline.BuildPlayer(new UnityEditor.BuildPlayerOptions { scenes = new[]{"Assets/Scenes/Explorer.unity"}, locationPathName = "/Users/rui/src/pg/tron_explorer/Build/TronExplorer.app", target = UnityEditor.BuildTarget.StandaloneOSX }); return r.summary.result + " " + r.summary.totalErrors;' --timeout 900000
```

Press keys in Play mode through the Input System: `unity command simulate_key` no longer reaches it (the viewer reads `Keyboard.current`), so queue key state events instead (key.sh: G toggles glow, Space skips a scene, V free flight):

```zsh
# key.sh <Key>: press and release
unity command eval "UnityEngine.InputSystem.InputSystem.QueueStateEvent(UnityEngine.InputSystem.Keyboard.current, new UnityEngine.InputSystem.LowLevel.KeyboardState(UnityEngine.InputSystem.Key.$1)); return 1;" --no-banner >/dev/null; sleep 0.5
unity command eval "UnityEngine.InputSystem.InputSystem.QueueStateEvent(UnityEngine.InputSystem.Keyboard.current, new UnityEngine.InputSystem.LowLevel.KeyboardState()); return 1;" --no-banner >/dev/null; sleep 0.3
```

To see animated effects in the unfocused Editor, advance time by hand instead of waiting: `TextureEffects.startTime` (private, via reflection) minus N seconds, then `TextureEffects.Update()`.

Real-game reference frames are in `reference/` (gitignored); compare captures against them.

## Pitfalls

- `Application.runInBackground = true` via eval **outside** Play mode is written to `ProjectSettings.asset` and ships in the build. Only set it after `editor_play`, and check `git status` before committing.
- `unity recompile` often returns "Network error": that's the domain reload. Wait with `unity status --until-ready` and look for `error CS` in the console (`unity command console`).
- `ShaderUtil.GetShaderMessages` misses Metal errors: render and look for `Shader error` in the console. Magenta screen = broken shader.
- The code editor's LSP reports false errors on `.cs` files that are new or unchanged; the Unity compiler is the reference.
- Python: `r.p += r.u32() * n` loses the counter's 4 bytes (`r.p` is read before `u32()` advances). Read the counter into a variable first.
