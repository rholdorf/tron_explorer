# SecRezzer and BinaryBit state messages

Research for #51 (map #28, follows #16's `docs/research/object-lto-models.md`). Question: which messages
change the look of SecRezzer and BinaryBit, and what does each change? Which of them do the 38
single-player levels send, and what does the viewer lack to show them?

## Answer

Both classes change their look in their own update state machine. Messages only start a state, and
an animation plays out the rest. Skins and render styles change through `SetObjectFilenames`. Some
changes come from model string keys in the animations, and the level's command strings send very few
of the messages that matter.

**BinaryBit** (36 placed in 13 levels; the viewer doesn't draw it today):

- **Messages it takes** (`OnTrigger`-style handler in `ObjectMessageFn` `0x10013320`, `_stricmp` on each
  statement's first word):
  - `ACTIVATE` toggles Yes/No, or powers the bit up.
  - `LOCK` / `UNLOCK` only switch use on and off.
  - `ATSOCKET` ends the power-up flight.
  - `INFOSTRING` sets the use prompt.
  - Everything else goes to GameBase (`HIDDEN`/`VISIBLE`/`SOLID`/`REMOVE`).
  - `ADDPSET`/`REMOVEPSET` are compared by pointer, so they never match.
- **States** `[+0x58]`: 0 powered down, 1 flying to its socket, 2 Yes, 3 No.
- **The look** is the `Byte1` piece's render style slot 0: `BinaryBit_Idle` (blue), `_Yes` (amber) or
  `_No` (red). All three styles are opaque and lit, and differ only in material colour. The pyramid
  and spike pieces sit **inside** the byte (radius ≤ 1.6 vs the byte's inner radius 3.13). The bind
  pose is therefore the correct resting look. #16's "all three shapes overlap" was wrong.
- **Spawn look**, from `EnergyRequired` and `StartOnInSocket`:

  | `EnergyRequired` | `StartOnInSocket` | Bits | Spawn look | Animation |
  |---|---|---|---|---|
  | > 0 (10/15/30) | either | 16 | `BinaryBit_Idle` (blue) | `PoweredDown`, static |
  | 0 | true | 4 (m10-04 `stabit01..04`) | `BinaryBit_Yes` | `PoweredDown`, static |
  | 0 | false | 16 | `BinaryBit_No` | `PoweredDown`, static |

- **Later changes:**
  - **Power-up** (energy > 0, state 0): `ACTIVATE` from the player (after the client's energy
    transfer) or from any non-player sender. The bit goes to state 1, starts the `BinaryBit_Trail`
    ClientFX, runs `PowerUpCommand` and loops **`Idle`**, a 360° tumble of the byte every 3.33 s.
    `ATSOCKET` then calls `DoPowerUp`, which swaps slot 0 to `_Yes` (`StartOnInSocket`) or `_No`
    **with no animation**, and the tumble goes on.
  - **Toggle** (state 2 ↔ 3): `ACTIVATE` plays **`Yes`** or **`No`** (666 ms).
    - The byte shrinks to half and the pyramid (Yes) or spike (No) grows out of it: a uniform 5.4× or
      4.0× vertex-animation scale.
    - At 300 ms the model string key `RS 0 props\rs\BinaryBit_Yes.ltb` (or `_No`) swaps slot 0.
    - At the end, `TurnOnCommand` or `TurnOffCommand` runs and `Idle` loops.
- **Messages sent in the levels' command strings** (94 in all): `LOCK` 46, `ATSOCKET` 26, `REMOVE` 8,
  `UNLOCK` 8, `ACTIVATE` 6.
  - 10 of the `ATSOCKET`s sit in energy-0 bits' own `PowerUpCommand`, which never runs.
  - The 16 that do arrive end the 16 energy > 0 power-ups: 7 from LaunchKF keyframer keys (StartOnInSocket
    false, arrive red) and 9 from `predestruct` command objects (StartOnInSocket true, arrive amber).
  - All 6 `ACTIVATE`s go to energy-0 bits (m02-02 `Door01Socket` ×3 and `Door02Socket` ×1, m04-03
    `BBit01` and `BBit04` ×1 each), so they toggle.
  - Most look changes come from **the player's use**, not from messages. All 36 bits are unlocked, so all
    start usable.

**SecRezzer** (43 placed in 12 levels, drawn today with skin 0):

- **Messages it takes** (`OnTrigger` `0x10044080`, CParsedMsg tokens):
  - `ON`: start spawning, if there's room under `MaxActive`.
  - `OFF`: clear pending spawns, no look change.
  - `IDLE`: stop and deselect.
  - `ACTIVATE`: the player disables it (needs its permission sets and the can-activate flag).
  - `HOOKSENDER`, `ADDPSET` and `REMOVEPSET`.
  - GameBase's messages.
  - A damage message that kills it disables it too (`0x10043bb0`).
- **Look per state.** It changes skin slot 0 and plays an animation (all 6-node skeletal, one piece):

  | State | Entered by | Skin 0 | Animation |
  |---|---|---|---|
  | 0 → 1 idle | spawn | `Skin0` (`SecRezzer` / `_fcon`) | `Idle`: the two side panels turned ±90° (open) |
  | 2–3 select | `ON` | `Skin2` `_On` | `Select` (1.33 s): sliders out ±12.5 |
  | 4–5 run | after Select; again per pending spawn | `Skin2` `_On`; `Skin3` `_Spawn` at the `SPAWN` key (125 ms) | `Run` (1.04 s) |
  | 6 | Run done | (kept) | `Open` (hold) |
  | 7–8 deselect | no spawns left, or `IDLE` | `Skin0` | `Deselect` (0.6 s), then back to idle |
  | 9–11 disable | player `ACTIVATE`, or killed | `Skin1` `_Off` | `Disable` (0.43 s: panels fold), then `Disabled` (hold) |

- **The viewer draws the wrong spawn pose.** It draws the bind pose, which is the folded *Disabled*
  pose. The game spawns it in `Idle`, with the panels open.
- **Messages in the levels' command strings:** 1, an `ON` to m02-03 `SR4.SecRezzer` from a
  `CAIHuman` `DeathCommand`. The real `ON`s come from AI: the `IC_SecRezzer` animation's `OPEN`
  model key makes the AI send `ON` to its node's object (`0x10126b86`, 42 `AINodeUseObject` nodes
  with SmartObject `SecRezzer`). Without AI, the only state change a viewer player can cause is
  **use → disable**.

**What the viewer lacks** (details under "What the viewer needs"):

- BinaryBit export: a hard-coded model and its 3 styles.
- A per-instance runtime swap of a skin slot or a render-style slot.
- A non-character prop posed by an animation frame: SecRezzer `Idle`.
- Animations started at runtime, one-shot, with an end event and model string keys (`RS`,
  `BUTE_SOUND_KEY`, `SPAWN`).
- BinaryBit's `Yes`/`No` vertex animation, which is only a uniform scale per piece.
- Use (E) on models: the use ray only finds world models today.

## Method

`extracted/object.lto` (PE32 i386, no source) disassembled with `objdump -d --x86-asm-syntax=intel`.
String and vtable cross-references come from the PE section table.

- **Engine interface offsets:**
  - `g_pLTServer` (`0x10344b28`): `+0x40` GetAnimIndex, `+0x3c` SetModelAnimation, `+0x48`
    SetModelLooping, `+0x30` model playback state (bit 1 = done), `+0x124` HandleToObject.
  - `g_pCommonLT` (`0x1035005c`): `+0x30` SetObjectFlags, `+0x2c` SetObjectFilenames.
- **The message words** were found as the string compares in each class's message handler.
- **Animations and pieces** were read with `tools/ltb.py`.
  - Vertex-animation frames were decoded by hand: per node, a u8 flag, then per key `u32 n`, `n × f32[3]`.
    `ltb._channels` steps over them.
  - Render styles were read with `tools/renderstyle.py`.
- **Message counts:** every command string of the 38 levels (`tools/tests/conftest.py` `level_commands`,
  the corpus of #29). Each one is walked the way `test_command_corpus.py` walks it: nested commands,
  AI mixed messages, `<Class>` prefixes and `Group` members.
  - Each `msg` statement's targets are resolved by name.
  - The count is one per (target object, statement of the message), by first word. These are
    occurrences in the strings, not executions.

### BinaryBit (`object.lto`)

| Address | What |
|---|---|
| `0x100129b0` | `EngineMessageFn`. Jump table `0x10012c04`: precreate → ReadProp `0x10012c30`; initial update → `0x10013830`; update `0x10012a5d`; model string key → `0x10014260`; save/load. |
| `0x10012c30` | ReadProp: `Key1..8`; `EnergyRequired` → `+0x5c`/`+0x60`; `Locked` → `+0x50`; `StartOnInSocket` → `+0x54` (constructor default 1); `ActivateType`; model `Props/Models/BinaryBit.ltb`, `RS0..2 = BinaryBit_Idle/_Yes/_No`; `PowerUpCommand` `+0x68`, `TurnOnCommand` `+0x6c`, `TurnOffCommand` `+0x70`; `StringOverrideID` `+0x8c`. |
| `0x10013830` | InitialUpdate. Can-activate user flags unless locked; visible; plays `PoweredDown`, not looping. `EnergyRequired == 0`: state 1, then `DoPowerUp`; else the activate-type handler's powered-down prompt. |
| `0x10013940` | `ChangeState(n)`. Same state: no-op. Jump table `0x10013b1c`: **0** "powering down is not supported" (state set anyway); **1** from 0: `0x10013c30` creates SpecialFX `FxName BinaryBit_Trail;Loop 1;SmoothShutdown 1`; **2** from 3: plays `Yes`, clears can-activate, updates on; from 1: `RS 0 = BinaryBit_Yes` (`0x100dba10`, render-style slot setter through `SetObjectFilenames`), no animation; from 0: error, state 2, no look change; **3** the same with `No` / `BinaryBit_No`. |
| `0x10013e70` | `DoPowerUp`: `ChangeState(StartOnInSocket ? 2 : 3)`, can-activate unless locked, removes the trail FX, no more updates. |
| `0x10014190` | `PowerUp`: `ChangeState(1)`, runs `PowerUpCommand`, plays `Idle` looping. |
| `0x10012a5d` | Update. State 1: moves the trail FX to the bit, next update. Otherwise, when the animation is done: state 2 → `HandleOn` `0x10013b30` (`TurnOnCommand`), state 3 → `HandleOff` `0x10013bb0` (`TurnOffCommand`); then `Idle` looping, can-activate unless locked, no more updates. |
| `0x10013320` | `ObjectMessageFn`. MID 1000 (trigger): statements parsed; `ACTIVATE` → `0x10013f10`; `LOCK` → `+0x50 = 1`, clears the can-activate user flags; `UNLOCK` → `+0x50 = 0`, flag back if usable; `ATSOCKET` → error unless state 1, then `DoPowerUp` **in any state**; `INFOSTRING n` → `+0x8c`; `ADDPSET`/`REMOVEPSET` are `cmp` against the literal's address, never true; then GameBase `0x100a84a0`. MID `0x9b` (client): byte 0 in state 0 → `PowerUp`. |
| `0x10013f10` | `HandleActivateMessage`. Locked: nothing. Player without the permission sets: `BinaryBitInvalidPSet`. State 0: energy > 0 → from the player, the energy-transfer request to the client (MID `0x9a`), else `PowerUp` at once; energy 0 → error. State 2 → `ChangeState(3)`; state 3 → `ChangeState(2)`; state 1: nothing. |
| `0x10014260` | Model string keys: `RS <slot> <file>` → render-style slot; `BUTE_SOUND_KEY <name>` → sound. |

`binarybit.ltb`:

- **Pieces:**
  - `Byte1`: skeletal, 360 vertices, style 0, vertex radius 3.32–3.79, inner surface radius 3.13.
  - `d_Pyramid`: vertex-animated, style 1, 24 vertices, radius 0.87.
  - `d_NewSpike`: vertex-animated, style 2, 360 vertices, radius 1.6.
  - Every pyramid and spike vertex is inside the byte's closed mesh (ray parity test).
- **Nodes:** 66 (`BitGroup`, `joint55`, `Jnt1..62`, `d_NewSpike`, `d_Pyramid`).
- **Animations:**
  - `PoweredDown` (66 ms, still).
  - `Idle` and `Idle2` (3333 ms): `joint55` turns 360° about (0.28, -0.92, 0.27). Code never plays
    `Idle2`.
  - `Yes` (666 ms, 21 keys): the byte's joints move from 3.38 to 1.39 and back. The pyramid frames are
    exactly the base mesh × 1 → 5.4 (key 8) → 1, with residual 0. Keys `0 bute_sound_key bb_yes` and
    `300 RS 0 props\rs\BinaryBit_Yes.ltb`.
  - `No`: the same with the spike × 4.0, `bb_no` and `BinaryBit_No`.
- **Styles** (`props/rs/binarybit_*.ltb`): opaque (blend one/zero), z-write, lit. Diffuse: Idle
  (0.2, 0.6, 1.0), Yes (1.0, 0.78, 0), No (1.0, 0, 0).

### SecRezzer (`object.lto`, vtable `0x10285b2c`)

| Address | What |
|---|---|
| `0x10043660` | ReadProp: template `Secrezzer`, or the `ModelTemplate` prop (29 `SecRezzer`, 14 `SecRezzer_Fcon`: `Skin0` `secrezzer`/`secrezzer_fcon`, `Skin1` `_Off`, `Skin2` `_On`, `Skin3` `_Spawn`, `RenderStyle0` `FullBrightOn_Alpha`); `Key1..8`; `MaxActive` `+0x7ac`; `NumberToSpawn` `+0x7b0`; activate type `Disable Secrezzer`. |
| `0x10043a10` | `EngineMessageFn`. Jump table `0x10043b8c`; model string keys: `DEATHFX`, `BUTE_SOUND_KEY`, `SPAWN` → vtable `+0x64` (`0x10045110`). |
| `0x10043e40` | Update. State `+0x7a8`, jump table `0x10044044` over vtable `+0x68..+0x8c`. |
| `0x10044780` | State 0: `Idle`, not looping; skin 0 = template `Skin0` (`GetSkinFilename(id, 0)` `0x100bd400`, `SetObjectFilenames`); → 1. State 1 (`0x10043e59`): with room (active ≤ MaxActive − NumberToSpawn), unlocks the hooked node and sets can-activate. |
| `0x100449e0` | State 2: clears can-activate, skin 0 = `Skin2`, `Select`; → 3. State 3 `0x10044bc0`: when done → 4. |
| `0x10044bf0` | State 4: `Run`, skin 0 = `Skin2`; → 5. State 5 `0x10044d10`: when done → 6 and `Open`. State 6 `0x10044950`: pending spawns → 4, else → 7 (locks the node when full). |
| `0x10045110` | Spawn (the `SPAWN` key in `Run`): a free `SecRezzerPoint`, the spawn, skin 0 = `Skin3`, pending −1. |
| `0x10044d60` | State 7: `Deselect`, pending = 0, skin 0 = `Skin0`; → 8. State 8 `0x10044f30`: when done → 1, can-activate. |
| `0x10044f70` | State 9: clears can-activate, skin 0 = `Skin1`, `Disable`, sends `DISABLE` to the hooked node; → 10. State 10 `0x100450c0`: when done, `Disabled`; → 11. State 11: no more updates. |
| `0x10044080` | `OnTrigger`, CToken compares (tokens built on first call). `ACTIVATE`: needs the can-activate flag and a character sender with the permission sets, else `SecrezzerInvalidPSet`. Only the player (`+0x32c4` set) in state 0–1 → state 9. `ON` (byte table `0x10044698`): states 0–1 with room → pending = `NumberToSpawn`, state 2; states 2–6 and 10: argument stored only; states 7–9 and 11: ignored. `OFF`: pending = 0. `IDLE`: states 2–6 → 7. `ADDPSET`/`REMOVEPSET`: working pset edits. `HOOKSENDER`: hooks the sender (the AI node). Otherwise GameBase `0x100a85a0`. |
| `0x10043bb0` | `ObjectMessageFn`, MID 1001 (damage): after the base handler, if not already in 9–11 and `+0xe0` is set (dead) → state 9, locks the node. |
| `0x10126b86` | CAIHuman model string keys (not SecRezzer code): `OPEN` → `ON`, `CLOSE` → `OFF`, `ACTIVATE` → `ACTIVATE` to the object the AI is using (`+0x109c`). `chars/models/base_ic.ltb` `IC_SecRezzer` has the single key `OPEN` (aigoals.txt `SmartObject4`: "the animation has a trigger in it to start the object"). |

`secrezzer.ltb`:

- **Piece:** one, `model` (skeletal, 3 LODs). Its weights: `JntBase` 1018 vertices, `joint1`/`joint2`
  180 each (the left and right panels, x −9.2..−1.3 / 1.4..9.2, y −18.8..25.3), `joint3`/`joint4`
  124 each (the sliders).
- **Bind pose:** every node unrotated. That is the pose of `base` and of `Disabled`'s last frame.
- **`Idle`:** `joint1` (0, −0.707, 0, 0.707), `joint2` (0, 0.707, 0, 0.707), constant.
- **`Select`:** `joint3`/`joint4` y 0 → ±12.5, keys `SHOW_ATTACHFX 1; bute_sound_key secrez_sel` and
  `HIDE_ATTACHFX 1; SHOW_ATTACHFX 0`.
- **`Run`:** sliders 12.5 → 0 → 0.38 → 0 → 12.5, keys `secrez_run`, `SPAWN` at 125 ms.
- **`Open`:** sliders out.
- **`Deselect`:** sliders back, `secrez_desel`, `HIDE_ATTACHFX 0`.
- **`Disable`:** panels ±90° → 0, `secrez_shutdown`.

## Counts

Placed objects (all `Template` false, `Locked` false):

- **BinaryBit (36):**
  - EnergyRequired: 0 ×20, 10 ×11, 15 ×3, 30 ×2.
  - StartOnInSocket: true ×13, false ×23.
  - Energy > 0 and in socket: 9 (m01-02 `DBit01..04`, m02-04 `DockSocket03/04`, m04-02 `bb01..03`, the
    `predestruct` set).
  - Energy > 0 and not in socket: 7 (intro `BB_01`, m02-02 `RommieBit`, m05-04 `BB1`, m06-04
    `Lower`/`Middle`, m09-01 `B`, m09-03 `FF02Bit`, the `LaunchKF` set).
  - Energy 0 and in socket: 4 (m10-04 `stabit01..04`).
  - Energy 0 and not in socket: 16 (m02-02 `Door01/02Socket` and `BogusBit01..05`, m03-01 `RouterSwitch`,
    m04-03 `BBit01..04`, m06-04 `Relay`, m09-02 `BinaryBit1..3`).
- **SecRezzer (43):**
  - By level: m01-02 5, m02-02 6, m02-03 5, m02-04 2, m04-01 5, m04-02 3, m04-03 3, m09-01 5, m09-02 1,
    m09-03 3, m10-02 4, m10-04 1.
  - `MaxActive`/`NumberToSpawn` 1 except 3 in m04-01 (2).
  - 42 `AINodeUseObject` with SmartObject `SecRezzer` point at them.

Messages in command strings, per level:

| Level | BinaryBit | SecRezzer |
|---|---|---|
| intro | ATSOCKET 1, LOCK 1, REMOVE 1 | |
| m01-02 | ATSOCKET 4, LOCK 8 | |
| m02-02 | ACTIVATE 4, ATSOCKET 3, LOCK 2 | |
| m02-03 | | ON 1 |
| m02-04 | ATSOCKET 2, LOCK 4 | |
| m03-01 | LOCK 1 | |
| m04-02 | ATSOCKET 3, LOCK 6, REMOVE 3 | |
| m04-03 | ACTIVATE 2, ATSOCKET 4, LOCK 16, UNLOCK 8 | |
| m05-04 | ATSOCKET 1, LOCK 1 | |
| m06-04 | ATSOCKET 3, LOCK 3 | |
| m09-01 | ATSOCKET 1, LOCK 1 | |
| m09-02 | ATSOCKET 3, LOCK 3 | |
| m09-03 | ATSOCKET 1 | |
| m10-04 | REMOVE 4 | |
| **total** | **94**: LOCK 46, ATSOCKET 26, REMOVE 8, UNLOCK 8, ACTIVATE 6 | **1**: ON 1 |

Who sends them:

- **ATSOCKET:**
  - 10 from the bits' own `PowerUpCommand`. These are all energy-0 bits, so the commands never run.
  - 9 from command objects (`EventT4E0`).
  - 7 from keyframer keys.
- **LOCK:**
  - 24 from triggers.
  - 9 from `PowerUpCommand`.
  - 9 from command objects.
  - 4 from `TurnOnCommand`.
- **REMOVE:**
  - 4 from m10-04 `TurnOffCommand`.
  - 3 from a trigger.
  - 1 from a `DecisionObject`.
- **UNLOCK:** 8 from m04-03 door open and close commands.
- **ACTIVATE:** 4 from triggers, 2 from command objects.
- **SecRezzer ON:** 1, from a `CAIHuman` `DeathCommand`.
- **Never sent:**
  - To SecRezzer: `OFF`, `IDLE`, `ACTIVATE`, `HOOKSENDER` and the pset words.
  - To BinaryBit: `INFOSTRING`.
  - To either: GameBase's `HIDDEN`/`VISIBLE`/`SOLID`.

## What the viewer has, and needs

What exists today:

- `tools/export_models.py` `Resolver.resolve` has no BinaryBit case, so the 36 bits aren't exported.
  Their `LaunchKF` keyframers find nothing to move.
- SecRezzer resolves through its `ModelTemplate`: skins, styles, and skin 0 drawn.
- `LevelBuilder.BuildModels` draws non-character props as a `MeshRenderer` in the bind pose.
- `ModelAnimator` only loops character clips that start at level load. It has no one-shot clips, no
  end events, no model string keys and no clip start at runtime.
- Only the clips a character idles on are exported (`export_level.main`, `model_files`).
- Vertex-animated pieces are exported at their base mesh, with no frames.
- Materials are fixed per `(style, textures)` at build time.
- `PlayerUse` only targets `ActiveWorldModelObject`.
- The command layer counts unhandled words per class for the L report.

What #53 needs, smallest first:

1. **BinaryBit export.** Hard-coded `props/models/binarybit.ltb`, no skins, styles
   `[BinaryBit_Idle, _Yes, _No]`, slot 0 per the spawn table. At rest the bind pose is the right look
   (inner shapes hidden), so the bits can be drawn static first.
2. **Per-instance swap of one slot at runtime**, a render style (BinaryBit) or a skin (SecRezzer).
   Only slot 0 changes in either class. BinaryBit slot 0 is used by `Byte1` alone; SecRezzer has one
   piece.
3. **SecRezzer posed by `Idle`'s constant frame** instead of the bind pose. Once it animates, the
   panels need skinned or node-posed drawing.
4. **Messages and use:**
   - BinaryBit `ACTIVATE`/`ATSOCKET`/`LOCK`/`UNLOCK`/`INFOSTRING` and SecRezzer
     `ACTIVATE`/`ON`/`OFF`/`IDLE`.
   - Use (E) on both: a hit volume, the can-activate rules above, every permission set granted, the
     BinaryBit energy transfer taken as accepted.
   - Without (5) and (6) the state changes are instant swaps.
5. **Runtime one-shot and looping clips on props**, with an end event (BinaryBit's update waits for
   `MS_PLAYDONE`; so do SecRezzer states 3, 5, 8 and 10) and model string keys (`RS`,
   `BUTE_SOUND_KEY`, `SPAWN`; the sounds are soundbutes the viewer already plays). BinaryBit's `Idle`
   tumble is skeletal (`joint55`), so the bit becomes a skinned prop.
6. **BinaryBit `Yes`/`No` vertex animation as a scale.** Every frame is the base mesh times one
   factor (pyramid ≤ 5.4, spike ≤ 4.0, keys every 33 ms), so a per-piece scale curve about the model
   origin reproduces it exactly.

Out of the viewer's reach (they stay in the L report or need other maps):

- SecRezzer `ON` comes from AI: the `OPEN` key, or the one `DeathCommand`.
- Spawning backup at `SecRezzerPoint`s.
- Damage.
- ClientFX: `BinaryBit_Trail`, the SecRezzer's `SHOW_ATTACHFX` / `Secrezzer_Open/start/Spawn`.
