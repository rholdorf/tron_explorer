# Player messages we keep: teleport, fades, fog

Ticket #31 (map #28). Question: what exactly do `msg player (teleport <point>)`, `FADEIN`/`FADEOUT`,
`RAMPCONSOLEVAR` (and its sibling `SINCONSOLEVAR`) and the `WorldProperties` fog messages do, and what
must the viewer do for each?

## Answer

- **Teleport** puts the player at a `TeleportPoint`, turns the view to the point's rotation (pitch,
  yaw and roll), drops the player onto the floor below the point, and zeroes the player's velocity.
  It happens on the player's next update, not inside the command. A target that is not a
  `TeleportPoint` is ignored.
- **FADEIN / FADEOUT `<time>` [n]** draw a black full-screen overlay whose alpha eases over `time`
  seconds. After a fade-out the screen stays black until a fade-in. Fades never block input. A time
  under 0.1 s is rejected. The second argument is sent to the client, but what the client does with it
  is unknown (see "Open points").
- **RAMPCONSOLEVAR `<cvar> [start] <end> <period>`** is Tron-only and runs on the client. It moves a
  console variable linearly from `start` (or from its current value) to `end` over `period` seconds,
  then holds `end`. **SINCONSOLEVAR `<cvar> <min> <max> <period>`** loops a sine with that period until
  `off`/`stop` (keep the current value) or `revert`/`restore` (put back the value from before the sine).
  Both replace any ramp or sine already running on the same variable. A variable the client doesn't
  know is ignored.
- **WorldProperties** messages (`FOGCOLOR r g b`, `FOGENABLE`, `FOGNEARZ`, `FOGFARZ`,
  `SCREENGLOWFOGENABLE`/`NEARZ`/`FARZ`) set the server's copy of the variable. Then *every* world
  property variable (FarZ, fog, sky fog, glow fog, …) is copied again from the server to the client.
  That copy overwrites any value a ramp left on the client. `FARZ` is not a WorldProperties message:
  its 2 uses do nothing in the game.

All of these end up as client console variables that the renderer reads every frame. So the viewer
needs one **render-variable table** (name → float, case-insensitive), seeded from the level's
`WorldProperties` at load. Shader globals and camera far planes are rebuilt from it each frame. Ramps,
sines and WorldProperties messages all write to that table.

## What the viewer must do

| Message (target) | Uses | Viewer |
|---|---:|---|
| `teleport <TeleportPoint>` (player) | 173 (169 resolve; 4 name no object) | On the next frame: position = point; view pitch/yaw = point `rot[0]`/`rot[1]` (roll ignored); drop to floor (ray down 10,000 units; if the gap is more than the half-height, stand on the hit); velocity = 0. Unknown target: count it in the console, do nothing. |
| `teleport` (AI / other) | 86 | Out of scope (characters map): count. |
| `fadein <t> [n]` (player) | 148 (+18 `fadein.5`) | Black overlay, alpha from 1 to 0 over `t`, eased (formula below). |
| `fadeout <t> [n]` (player) | 85 | Black overlay, alpha from 0 to 1 over `t`, then black until the next fade-in. |
| `fadein.5` (player) | 18 | **Not** a FADEIN: the engine splits arguments only on whitespace, so the message name is `fadein.5` and the player doesn't handle it. Count it as unknown. |
| `rampconsolevar` (player) | 826 | Linear ramp on the render-variable table (variables below). |
| `sinconsolevar` (player) | 18 | Sine on the render-variable table, plus `off`. |
| `fogcolor r g b` (WorldProperties) | 352 | Set FogR/G/B, then re-copy all world variables (below). |
| `fogfarz` / `fognearz` / `fogenable` (WorldProperties) | 19 / 6 / 4 | Set the variable, then re-copy. |
| `screenglowfogfarz` / `nearz` / `enable` (WorldProperties) | 4 / 3 / 3 | Set the variable, then re-copy; the glow pass needs glow fog (below). |
| `farz` (WorldProperties) | 2 | No-op in the game; count as unknown. |

The engine runs the level-start fade too: on the first update the client fades in from black over
`ScreenFadeInAtLevelStartTime` (default 1.5 s), unless `ScreenFadeAtLevelStart` is 0
(`gameclientshell.cpp` `FirstUpdate`, defaults at lines 945–946).

### Render variables the levels touch

Every variable named by a `rampconsolevar` / `sinconsolevar` in the 38 single-player levels, with the
render state it feeds (renderer variable names and types from ltjs
`render_a/src/sys/d3d/rendererconsolevars.h`):

| Variable | Ramp uses (from current / explicit start) | Sine uses | Feeds | Viewer today |
|---|---|---:|---|---|
| `FogR`, `FogG`, `FogB` (int 0–255) | 7/201, 8/201, 9/311 | 2, 1(+1 off), 1(+1 off) | world/model fog color `_LTFogColor` | set once at load |
| `FogNearZ`, `FogFarZ` | 7/2, 9/43 | 4, 4 | `_LTFogParams.xy` | set once at load |
| `FarZ` | 4/4 | – | main camera far plane | set once at load |
| `SkyFogNearZ`, `SkyFogFarZ` | 3/4, 3/4 | – | sky camera `skyFogParams` | set once at load |
| `ScreenGlowFogNearZ`, `ScreenGlowFogFarZ` | 2/0, 2/0 | – | glow-pass fog (to black) | **missing** |
| `ScreenGlowUVScale`, `ScreenGlowGaussAmp1` | – | 2, 2 | glow blur spread and weights | constants in `TronExplorer` |
| `fogb128` (typo) | 2/0 | – | nothing: unknown variable, ignored | – |

Variables that only WorldProperties messages set (no ramp): `FogEnable`, `ScreenGlowFogEnable`.

`FogEnable` must become live too: a `FOGENABLE 0` turns fog off mid-level in intro.

The glow pass needs glow fog. In the engine the glow buffer is fogged **towards black**, linearly
between `ScreenGlowFogNearZ` and `ScreenGlowFogFarZ`, when `ScreenGlowFogEnable` is set. Its far plane
is `ScreenGlowFogFarZ` instead of `FarZ` (`screenglowmgr.cpp` lines 420–427). The level's starting
values are the `WorldProperties` props `GlowFogEnable`, `GlowFogNearZ` and `GlowFogFarZ`, which the
viewer doesn't read yet. Today `TronWorld.shader` returns glow without fog. The glow filter weights are
rebuilt every frame in the engine (`UpdateGaussianFilter` is called on every glow render,
`screenglowmgr.cpp` line 680), so `ScreenGlowGaussAmp1`/`UVScale` can simply be variables.

### Where the messages are

| Level | Teleport (player) | Fade in/out | Ramp | Sine | WorldProperties fog |
|---|---:|---:|---:|---:|---|
| intro | 12 | 5/1 | 145 | – | 141 color, 5 far, 6 near, 4 enable, 3+3+3 glow fog |
| m01-01 | 4 | 4/3 | – | – | 1 far |
| m01-02 | 7 | 4/3 | – | – | 1 far, 1 glow far, 1 `farz` (no-op) |
| m02-01 | 28 | 19/13 | – | – | 9 far |
| m02-02 | 9 | 3/2 | – | – | 2 far, 1 `farz` (no-op) |
| m02-04 | 6 | 6/5 | – | – | 1 color |
| m04-02 | 10 | 5/1 | 7 | – | 1 color, 1 far |
| m05-01 / m05-02 / m05-04 | 3 / 17 / 5 | 2/2, 10/3, 2/3 | 12 / 12 / – | – / 4 / 4 | – |
| m06-02 | 15 | 5/3 | 2 | 10 | – |
| m07-02 / m07-04 | 9 / 11 | 5/2, 5/2 | 100 / 198 | – | – |
| m10-04 | 5 | 5/4 | 8 | – | – |
| m11-01 | – | 3/0 | 338 | – | 209 color |

Every other level has teleports and fades only (m02-03, m04-01 and m07-01cin also have 1–2 ramps).
Counts are per message after splitting `;` lists, nested parentheses and `delay` bodies. CommandObject
event strings are `time|command`, and the prefix is stripped before splitting.

## Engine details

### Teleport

- `CCharacter::OnTrigger` `TELEPORT` (`character.cpp` lines 925–953) accepts a named object or a
  vector `x,y,z`. A named object that is not a `TeleportPoint` is ignored (`dynamic_cast`, `return
  true`). The teleport is stored and done in `UpdateTeleport` on the next update (lines 4877–4895),
  "since we may have been moving when we caused the trigger". Tron's `object.lto` has the same message
  and errors (`TELEPORT <teleport point> | <vector>`, `Object '%s'is not a TeleportPoint or a vector.`).
- `CPlayerObj::HandleTeleport(TeleportPoint*)` takes the point's position and its `Rotation` prop
  as pitch/yaw/roll (`teleportpoint.cpp` line 41, `GetPropRotationEuler`). `CPlayerObj::Teleport`
  (`playerobj.cpp` lines 4098–4123) sends `MID_PLAYER_ORIENTATION`/`MID_ORIENTATION_ALL`. The client
  sets pitch, yaw and roll from it (`playermgr.cpp` lines 1512–1543). The server then sets the
  position, calls `MoveObjectToFloor` **unconditionally**, and calls `TeleportClientToServerPos`. The
  point's `MoveToFloor` prop is not consulted for the player.
- `MoveObjectToFloor` (`serverutilities.cpp` lines 1076–1108) casts a ray 10,000 units down from the
  position. If the hit is farther than the half-height `dims.y`, it lowers the object to stand 0.1
  above the hit.
- The client then teleports its physics object to the server's position and zeroes acceleration and
  velocity (`cmovemgr.cpp` `OnServerForcePos`, lines 2560–2592).
- Data: all 169 resolvable player targets are `TeleportPoint`s. The 4 unresolved ones are `DS1.EndTP`
  (intro), `DS3.EndTP` and `DS4.EndTP` (m04-02), and `xIONodeActors00.nodetempTP` (m05-04). The game
  ignores them. Exported `rot` is `[pitch, yaw, roll]` in radians. `Spawn` today uses only `rot[1]`.

### Fades

- Server: Tron's `FADEIN`/`FADEOUT` handler (`object.lto` `0x10073b90`, reached from the player's
  `OnTrigger` at `0x10071884`) needs at least 1 argument. It returns false if `time < 0.1`
  (constant at `0x10284728`). It sends `MID_PLAYER_INFOCHANGE` (0x67) with `IC_FADE_SCREEN_ID` (0xb),
  the fade-in flag, **`atoi(arg2)`** as the second type byte (0 if absent), and the time. ltjs always
  sends 0 there (`playerobj.cpp` lines 1909–1924); this is where Tron differs.
- Client (ltjs `interfacemgr.cpp` lines 2497–2508, 4835–4920; `interfacemgr.h` lines 161–203): the
  start of a fade resets the fade state, so a new fade replaces a running one. Each frame the overlay
  alpha is `1 - SlowOn(1 - p)`, with `p = remaining/total` for a fade-in (alpha 1 → 0) and
  `p = elapsed/total` for a fade-out (alpha 0 → 1), clamped to [0, 1].
  `SlowOn(v) = v < 0.5 ? (1 - cos(πv))/2 : v` (`wavefn.cpp` lines 69–93). The overlay is a black
  surface scaled over the screen. When a fade-out is done the screen is cleared to black every frame
  until a fade-in starts. Nothing in the fade path touches input.
- Times used: `.5` (78), `1` (22), `.3` (14), `1.5` (4), `.2` (3), `3`, `.8`, `2.0`, `.25`; the minimum
  is 0.2, so the 0.1 floor never triggers.

### RAMPCONSOLEVAR and SINCONSOLEVAR (Tron-only)

ltjs has neither; `object.lto` registers `RAMPCONSOLEVAR <cvar> [start] <end> <period>` and
`SINCONSOLEVAR <cvar> {off | <min> <max> <period>}`.

- Server, `object.lto`: RAMP handler `0x100690c0`, SIN handler `0x10068e40`. Both are dispatched
  from the player's `OnTrigger` (`0x10066879`/`0x100668b4`). Each copies the variable name (63
  characters max) and sends client message **0x68**, guaranteed, as a sub-id byte and then a payload:
  - sub 0, ramp: name, `hasStart` byte, `start`, `end`, `period` floats (start = 0 when absent).
    There must be 2 (`end period`) or 3 (`start end period`) numbers after the name; otherwise the
    message is rejected.
  - sub 1, sine: name, `min`, `max`, `period`.
  - sub 2: `off` or `stop`. Sub 3: `revert` or `restore` (strings at `0x102cbd68`–`0x102cbd80`).
- Client, `cshell.dll`: message 0x68 is index 0 of the jump table at `0x100a69f6`. It dispatches on
  the sub-id to `0x100a7ad0` (ramp), `0x100a7c40` (sine) and `0x100a7dc0` (stop/revert).
  - Start (ramp and sine): delete any running entry with the same name (string compare), then look the
    variable up (`ILTClient` vtable `+0x18c`). **If the variable doesn't exist, do nothing.** Ramp
    entry: `start = hasStart ? start : current value` (`+0xa8`, float value), `end`, `period`,
    `elapsed = 0`. Sine entry: `period`, `elapsed = 0`, `center = min + max * 0.5`,
    `amplitude = (max - min) * 0.5`, and the current value saved for `revert`.
  - Update `0x100a7900`, every client frame, skipped while two pause flags of the game client shell
    (`+0x7e4c`/`+0x7e4d`) are set: `elapsed += frameTime`.
    - Ramp: value = `start + (end - start) * elapsed / period`. Once `elapsed >= period` the value is
      `end` and the entry is removed after that frame.
    - Sine: `elapsed` wraps modulo `period`, and value = `center + amplitude * sin(2π * elapsed /
      period)` (constant `6.2831855` at `0x101e9378`).
    - The value is written with the console string `"%s %4.2f"` (`0x1021f7ac`), so it is rounded to 2
      decimals. Int variables (`FogR/G/B`) truncate.
  - Stop (`0x100a7dc0`): remove the entry; for sub 3, first write back the saved value (`"%s %4.2f"`
    again).
- The decoded sine center is `min + max/2`, not `(min + max)/2`. The two agree when `min = 0`
  (`fogr 0 100`, `fogg 0 100`, `fogr 0 200`), but not for `fogfarz 2000 3000`,
  `fognearz -400 200` or `screenglowuvscale 1 1.5`. With `min ≠ 0` the value swings between
  `1.5·min` and `max + min/2`. This reading comes from the x87 stack offsets in `0x100a7d27`–`0x100a7d67`.
  The viewer should use the binary's formula, because that is what the game shows.
- Ramp shapes in the data: 4-argument ramps with explicit start (770, e.g. intro `title_commands`
  `rampconsolevar fogb 255 128 0.3`, m11-01's flashes) and 3-argument ramps from the current value (56,
  e.g. intro `Digitization_trigger` `rampconsolevar fogr 255 16`). `farz 25001 25000 0.1` is a 0.1 s
  ramp used to force a FarZ.

### WorldProperties

- Messages registered by Tron's `WorldProperties` (`object.lto` strings): `FOGCOLOR <r> <g> <b>`,
  `FOGENABLE`, `FOGNEARZ`, `FOGFARZ`, `SKYFOGENABLE`, `SKYFOGNEARZ`, `SKYFOGFARZ`,
  `SCREENGLOWFOGENABLE`, `SCREENGLOWFOGNEARZ`, `SCREENGLOWFOGFARZ`. There is no `FARZ` message; the
  only `FarZ` strings in that area are the property and the server variable (the property table at
  `0x101ae3d9`). ltjs (`worldproperties.cpp` lines 700–870) shows the pattern for the fog ones:
  `SetGameConVar(name, arg)` and then `SendClientsChangedValues()`.
- The client answers `MID_CHANGE_WORLDPROPERTIES` with `ResetDynamicWorldProperties`
  (`playermgr.cpp` line 4747, `gameclientshell.cpp` lines 4149–4195). That re-copies **all** of `FarZ`,
  `FogEnable`, `FogNearZ`, `FogFarZ`, `FogR/G/B`, `SkyFog*`, `VFog*` and the shadow variables from the
  server to the client. Tron's `cshell.dll` keeps the `ScreenGlowFog*` names next to that list, so
  they are re-copied too (inferred from the string table, not traced).
- Consequence: any `WorldProperties` fog message resets every world variable a ramp or a sine had
  changed back to the server's value (the level props plus earlier WorldProperties messages). A running
  ramp or sine then writes again on its next frame.
- `FogR/G/B` are ints 0–255 in the renderer. The viewer divides by 255, as it does at load today.
- Targets are named `WorldProperties0` or `WorldProperties`, matched case-insensitively. Every target
  in the data resolves.

## Open points

- **Second fade argument** (11 uses: `fadein 1 1`, `fadein 0.2 1`, `fadeout 4 1`, …). Tron sends it
  as `nType2`, but I didn't find the `IC_FADE_SCREEN_ID` case in `cshell.dll`. The viewer can ignore
  it until a frame from the game shows a difference.
- Whether the player's view roll from a TeleportPoint matters: all seen points have roll 0.

## Method

- Data: a command tokenizer over every string prop of the 38 exported `retailsingleplayer` levels.
  It splits on `;` at any depth and descends into parentheses and `delay`/`rand` bodies. Each
  `msg <target> <message>` is resolved to the target's class in the same level.
- ltjs (`bibendovsky/ltjs`, read via `gh api`): `objectshared/playerobj.cpp`, `character.cpp`,
  `teleportpoint.cpp`, `worldproperties.cpp`, `serverutilities.cpp`;
  `clientshellshared/gameclientshell.cpp`, `playermgr.cpp`, `interfacemgr.cpp/.h`, `cmovemgr.cpp`;
  `shared/wavefn.cpp`; `render_a/src/sys/d3d/rendererconsolevars.h`, `screenglowmgr.cpp`.
- Tron retail: `extracted/object.lto` and `extracted/cshell.dll`, disassembled with
  `objdump -d --x86-asm-syntax=intel`. Token statics were followed from string VA → `CToken` global →
  compare site → handler. The client message switch was found from `add eax, -0x68` at `0x100a69d9`.
