# Workflow

How to export, drive the Unity viewer, build, and measure. Read this before touching `tools/` or `TronViewer/`.

## Basics

- **Unity**: Editor `6000.3.26f1`, project `TronViewer/`, scene `Assets/Scenes/Explorer.unity`. Drive it through the `unity` CLI (skill `unity-cli`) with `UNITY_PROJECT_PATH=/Users/rui/src/pg/tron_explorer/TronViewer`; run `unity status` first. If the Editor is closed, **ask the user** before reopening it (`unity open TronViewer`). There is one Editor, on the main checkout: agents in worktrees must not drive it.
- **Export** after changing `tools/`: `.venv/bin/python -I tools/export_level.py extracted export` (~13 s, all 63 levels + models; the first run also writes the levels' sound files to `export/sounds/`, ~500 MB, decoding the MP3-in-WAV ones with macOS `afconvert`, and later runs skip unchanged ones). If the format changed, bump `FORMAT_VERSION` in Python and in C# (`LevelBuilder.FormatVersion`, `ModelLibrary.FormatVersion`); levels exported before the bump will not load.
- **Bench glTF** (#40, for mus-y-sinak): `.venv/bin/python -I tools/bench_gltf.py extracted retailsingleplayer/m01-01` writes `export/bench/m01-01.glb` (~6 s, 377 primitives). One primitive per family × texture × animated × overlay, render roles in each primitive's `extras` (conventions in the module docstring and `asset.extras.primitiveExtras`). x is mirrored so Unity's glTF importers land on the viewer's coordinates. Tron 2.0 levels are vertex-lit (m01-01 has no lightmaps): the light hint is `vertexLight`. mus-y-sinak's camera poses (`docs/reference-panel.json` there: `eye` in metres, `yaw`/`pitch` in degrees, vertical `fov`) are already in the viewer's frame: camera position = `eye` (Unity units = LithTech units × `LT.Scale` = metres), rotation `Quaternion.Euler(pitch, yaw, 0)` as `PlayerController` does (positive pitch looks down), `Camera.fieldOfView = fov`. Place the body at `eye - Cam.localPosition`. Checked against `GameStartPoint` and three shots (#45).
- **Tests**: `.venv/bin/python -I -m pytest tools/tests -q`. They read game data from `/Users/rui/src/pg/tron_explorer/extracted` (override with `TRON_EXTRACTED`), so they also run from a worktree. A worktree has no `extracted/` or `export/` of its own; export to a scratch directory, never into the main checkout's `export/`.
- **Measure performance only in the player build**, never in the Editor. App: `-level <level> -benchmark 8` writes a `BENCH` line to the log and quits. Baseline at 1080p (2026-10-12): intro ~1.2 ms, m10-04 ~1.3 ms, m01-02 ~1.4 ms, m01-01 ~2.0 ms, m02-04 ~2.5 ms per frame.
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

Toggle glow in Play mode with `unity command simulate_key -- --key G`. To see animated effects in the unfocused Editor, advance time by hand instead of waiting: `TextureEffects.startTime` (private, via reflection) minus N seconds, then `TextureEffects.Update()`.

Real-game reference frames are in `reference/` (gitignored); compare captures against them.

## Pitfalls

- `Application.runInBackground = true` via eval **outside** Play mode is written to `ProjectSettings.asset` and ships in the build. Only set it after `editor_play`, and check `git status` before committing.
- `unity recompile` often returns "Network error": that's the domain reload. Wait with `unity status --until-ready` and look for `error CS` in the console (`unity command console`).
- `ShaderUtil.GetShaderMessages` misses Metal errors: render and look for `Shader error` in the console. Magenta screen = broken shader.
- The code editor's LSP reports false errors on `.cs` files that are new or unchanged; the Unity compiler is the reference.
- Python: `r.p += r.u32() * n` loses the counter's 4 bytes (`r.p` is read before `u32()` advances). Read the counter into a variable first.
