# Tron 2.0 Explorer

Walk through Tron 2.0 (LithTech Jupiter) levels natively on macOS.

**No game data is included.** You need your own Tron 2.0 installation (e.g. the GOG release);
the tools read its `.rez` archives locally.

```
<Tron 2.0 install>  (Windows install, read-only)
   │  tools/rez.py            extract .rez archives (in engine load order, patches override)
   ▼
extracted/                    raw game files (worlds/*.dat, tex/*.dtx, attributes/*.txt, ...)
   │  tools/export_level.py   DAT v85 -> runtime format (uses tools/dat85.py)
   ▼
export/levels/<level>/level.json + level.bin, export/levels.json
   │
TronViewer/ (Unity 6000.3, URP)  loads export/ + extracted/ at runtime
Build/TronExplorer.app        native build
```

## Regenerating

```sh
./setup.sh "/path/to/TRON 2.0"   # extract all .rez + export all 63 worlds (~1 min)
```

Then open `TronViewer` in Unity and press Play (scene `Assets/Scenes/Explorer.unity`), or run
`Build/TronExplorer.app`. The app finds the data by walking up from its own location until it
sees `export/levels.json`; override with `-tronroot <dir>` or `TRON_EXPLORER_ROOT`.
`-level m01-01` loads a level directly; add `-benchmark 8` to log frame times at the start point
(vsync off, one `BENCH` line in the player log) and quit.

## Controls

WASD move · mouse look · Space jump · Shift walk · C/Ctrl crouch · N noclip (Alt = fast) ·
G screen glow · R respawn · T next start/teleport point · Tab/Esc level menu · F1 help.

## Fidelity notes

- **Geometry/UV/textures**: render blocks from the DAT render section (44-byte vertices:
  pos, uv0, uv1, D3DCOLOR, normal), split by section texture. World models (doors, lifts,
  glass…) are placed at their object's `Pos`/`Rotation` so they can move later.
- **Lighting**: baked per-vertex color, combined as in `d3d_rendershader_gouraud.cpp` with the
  game's `Saturate 1` (MODULATE2X). Math is done in gamma space like D3D9.
- **Lightmaps**: `lightmap_texture` sections are drawn by the game as a lightmap pass (shader 2
  section: own copy of the triangles, uv0 = lightmap uv) followed by the texture multiplied over
  it. The exporter packs all section lightmaps into one atlas per level (in `level.bin`), matches
  the texture-pass triangles to their lightmap triangles by vertex position and gives them uv2;
  the shader does both passes in one, fog included (`d3d_rendershader_lightmap.cpp`).
- **Light groups** (switchable lights) are added to vertex colors and lightmaps with their
  initial color. Toggling them from scripts is part of the behavior phase.
- **Textures**: DTX v-5 loaded straight to GPU (DXT1/DXT5, DXT3 re-encoded as DXT5, BGRA32).
  Command string honored: `AlphaRef`, `EnvMap`/`EnvMapAlpha` (ADDSIGNED), `DetailTex`.
  DTX fullbright flag = alpha is a self-illumination mask, and drives the screen glow.
- **Screen glow**: same algorithm and kernel as `screenglowmgr.cpp`, with the values from the
  game's `autoexec.cfg` (256² buffer, 24-tap filter, amp 0.1, radius 3).
- **Sky**: sky world models (named by `SkyPointer`) drawn first from the sky center.
- **Fog**: linear fog from `WorldProperties` (`FogNearZ/FarZ/Color`).
- **Collision**: solid polygons of the `PhysicsBSP` world model, the invisible player blockers
  section, and the BSP of each solid world model (`Solid` property).
- **Movement**: `attributes/serverbutes.txt [Player]` (Run 280, Walk 115, Jump 700 u/s),
  player dims 24×53×24. 1 LithTech unit = 0.017 m (`LT.Scale`).
- **Texture effects**: the compiled texture scripts (`tex/texfx/*.tfs`) run in a port of the engine's
  bytecode interpreter (`texturescriptinterpreter.cpp`), so every effect group (`.tfg`): pan,
  rotate, warble, world-position env panning… builds the same per-frame texture matrix as in game,
  on the base texture or env map channel.
- Animated `.spr` sprites cycle at their frame rate.

## Not yet (behavior phase)

Every object and all its properties are already exported in `level.json` (`objects[]`), e.g.
`SlidingDoor`/`RotatingDoor` (`MoveDir`, `MoveDist`, `OpeningTime`, `PermissionSets`…),
`Trigger` (`Command1..10`), `CAIHuman` (`ModelTemplate`, `Brain`, `GoalSet`), `Spawner`,
`CommandObject`, `KeyFramer`. Next steps: a `.txt`/bute parser for `attributes/` (weapons,
keyitems/permissions, aibutes, modelbutes), the LithTech command language (`msg X (on)` …)
used by triggers and the level `StartupCommand`, then doors/lifts, the disc, LTB models and AI.

## Format references

- ltjs (LithTech Jupiter source port): `world_shared_bsp.cpp`, `de_mainworld.cpp`,
  `d3d_renderblock.cpp`, `dtxmgr.h`, `screenglowmgr.cpp`
- leoschur/kaitai_lithtech_dat_struct (DAT v85 Kaitai template)
