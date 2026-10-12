# How triggers, doors and switches behave

Research for #30 (map #28). Question: the engine rules for `Trigger` and its subclasses, the
`ActiveWorldModel` family (doors, switches, sliding/rotating world models), the player's use, and Tron's
permission sets (`Key1..Key8`) and `ActivateType` labels. The trigger and door tickets implement from this.

Sources:
- **ltjs** (`bibendovsky/ltjs`, NOLF2 code that Tron 2.0 builds on): `game/objectdll/objectshared/`
  `trigger.cpp`, `exittrigger.cpp`, `noplayertrigger.cpp`, `activeworldmodel.{h,cpp}`, `door.cpp`,
  `switch.cpp`, `sliding*.cpp`, `rotating*.cpp`, `worldmodel.cpp`, `playerobj.cpp` (`DoActivate`);
  `game/shared/keymgr.cpp`; `game/clientshelldll/clientshellshared/targetmgr.cpp`, `playermgr.cpp`;
  `engine/runtime/world/src/fullintersectline.cpp`.
- **Retail Tron** `extracted/object.lto` and `extracted/cshell.dll`, disassembled with
  `objdump -d --x86-asm-syntax=intel` (addresses below), and `extracted/attributes/`
  (`activatetypes.txt`, `triggertypes.txt`, `soundbutes.txt`, `keyitems.txt`, `layout.txt`).
- Prop counts: the 38 `retailsingleplayer` levels exported to `export/levels/retailsingleplayer/*/level.json`.

Where Tron's binary was checked it matches ltjs, except for the permission-set gate, which ltjs doesn't have.

## Answer in one table

| Prop / class (placed) | Behavior |
|---|---|
| `Trigger` (2,849), `PlayerTriggerable` (969) | Box of half-extents `Dims` around its position (axis-aligned, rotation ignored). The player touching it, or a `TRIGGER` message, runs `Command1..10` (each non-empty one, in order). |
| `Trigger`, `PlayerTriggerable` 0 (1,880) | Message-only: runs its commands only on `TRIGGER`. |
| `NoPlayerTrigger` (105) | Message-only. On `TRIGGER` it waits, polling every 0.1 s, until no player is inside its box, then runs its commands. |
| `ExitTrigger` (39) | Message-only (touch is switched off in its constructor); all 39 are targeted by some command. Runs its commands, then the level/mission switch (out of scope here: count it). |
| `SlidingDoor` (310), `RotatingDoor` (24) | `ActiveWorldModel` with door prop names: `StartOpen`/`TriggerClose`/`RemainOpen`/`OpenAway`, `Opening/Open/Closing/ClosedSound`, `Opening/Open/Closing/ClosedCommand`, `OpeningTime`/`ClosingTime`/`OpenWaitTime`/`CloseWaitTime`, plus `DoorLink` and the `TRIGGERCLOSE` message. |
| `SlidingSwitch` (119), `RotatingSwitch` (3) | `ActiveWorldModel` with the generic names (`StartOn`, `TriggerOff`, `RemainOn`, `PowerOn/On/PowerOff/OffSound` and `...Command`, `PowerOnTime`...). All have `PlayerActivate`. 98 of the sliding ones have `MoveDist` 0: they don't move and turn on at once. |
| `SlidingWorldModel` (101), `RotatingWorldModel` (30) | Same machine, generic names; driven by messages (1 has `PlayerActivate`). |
| `PlayerActivate` | The player's use can drive it. 58 sliding doors, 7 rotating doors, all switches. |
| `Key1..Key8` (`PermissionSets` is only the group header) | Permission sets the user must hold, all of them. The viewer grants every set, so the gate always passes. |
| `Locked` | A locked AWM ignores use and `TRIGGER`/`ON`/`OFF`: it plays `LockedSound` and runs `LockedCommand` instead. A locked trigger ignores touch and `TRIGGER`. `LOCK`/`UNLOCK` messages change it. |
| `ActivateType` | The use prompt's text per state (`activatetypes.txt`); grey when locked. |

## The use key

Client (`CPlayerMgr::OnCommandOn(COMMAND_ID_ACTIVATE)` → `DoActivate`, `CTargetMgr::CheckForIntersect`):

1. Every frame a ray goes from the **camera** along its forward axis. The first thing it hits is the target.
   It hits the static world (stops the ray) and any object that is **solid or has `Rayhit`**
   (`fullintersectline.cpp` `i_ISCallback`: `FLAG_RAYHIT|FLAG_SOLID`). So the 34 non-solid switches still
   take the ray (all 119 switches have `Rayhit` 1). Non-solid objects without `Rayhit` are skipped, and the
   filter (`ActivateFilterFn`) also lets a non-solid object through only if it can be activated.
   Polys of surface type `Invisible` are skipped.
2. The target is in range when the distance from the camera to the **hit point** is at most
   `ActivationDistance`. Tron's `cshell.dll` hard-codes that console variable to **100** units
   (`0x100b75a9: push 0x40590000` = 100.0 double; `ActivationDistanceLong` = 200, `TargetDistance` = 1000;
   no attribute file sets them).
3. On key press, if the target is in range, the client sends it; the server (`CPlayerObj::DoActivate`)
   sends the target the message `ACTIVATE`. Out of range: nothing happens.

**Which object wins**: the nearest thing along the ray, nothing else. A wall in front of a switch blocks it;
a door's attached world models relay `ACTIVATE` to the door (below), so aiming at any of them works.

Server side (`ActiveWorldModel::Activate`, Tron `object.lto` `0x1016a100`):

1. Only characters can activate; an AI needs `AIActivate`, the player needs `PlayerActivate`.
2. **Permission-set gate** (Tron only): `0x101667a0` reads the player's permission sets and
   `0x100c4140` returns `(have & required) == required`, where `required` is the `Key1..Key8` bitmask
   (object field `+0x944`). On failure: play soundbute `ActiveWorldModelInvalidPSet`
   (`snd\event\invalidPset.wav`), run `InvalidPSetCommand` if set, and stop. Every set granted ⇒ always passes;
   `InvalidPSetCommand` never runs.
3. Remember the activator, then `HandleTriggerMsg` (the state machine below).

**Use prompt** (`CTargetMgr`, `activatetypes.txt`, `layout.txt`): in range and the AWM has an
`ActivateType`, the HUD shows `StateON` text when the AWM is on/powering on and `StateOFF` text when
off/powering off (`-1` = no text). Locked (`SetDisabled`) shows it in `ActivationTextDisColor` (128,128,128)
instead of `ActivationTextColor` (255,255,0); position `(320,300)` on a 640×480 layout, size 14, centered.
Text comes from `cres.dll` string IDs 9500–9549; the file's comments carry the English text
("Open Door"/"Close Door", "Lower/Raise Forcefield"...). 22 distinct types are used on switches (8 have `<none>`),
`Door Open-Close` (48) and `Security Locker Open-Close` (3) on doors; 259 doors have `<none>` and show no
typed text.

## Trigger rules (`trigger.cpp`)

Props read: `Dims` (half-extents: `NoPlayerTrigger` tests `pos ± Dims`), `Command1..10`, `TriggerDelay`,
`SendDelay`, `NumberOfActivations`, `ActivationCount`, `Locked`, `PlayerTriggerable`, `AITriggerable`,
`ActivationSound`/`SoundRadius`, `WeightedTrigger`/`Message1Weight`, `TimedTrigger`/`Min/MaxTriggerTime`,
`TriggerTouch`/`CommandTouch`, `AttachToObject`, `HUDLookAtDist`/`HUDAlwaysOnDist`/`TriggerType`.

- **Touch** (`ObjectTouch`): the engine's touch notify while the player's box overlaps the trigger box.
  Rejected if the toucher is the player and `PlayerTriggerable` is 0 (AI and bodies: out of scope).
  `PlayerKey` is `<None>` everywhere. In the viewer: test player-box/trigger-box overlap every frame; the
  gates below make "every frame while inside" correct.
- **`DoTrigger`** (touch and the `TRIGGER` message): if `now < lastTouch + TriggerDelay`, ignore. Else set
  `lastTouch = now` (even if locked) and, if active and not locked, `RequestActivate`.
- **`RequestActivate`**: becomes inactive (further touches ignored) and waits `SendDelay` seconds, then
  `Activate` and becomes active again.
- **`Activate`**:
  1. `++count < ActivationCount` ⇒ stop (counts touches; reset to 0 when reached). 2,823 have 1.
  2. `NumberOfActivations > 0` and already fired that many times ⇒ stop for good (the object stays).
     `<= 0` = unlimited (696 are 0, 285 are -1).
  3. Play `ActivationSound` (none set in SP levels).
  4. Run `Command1..10` through the command manager (sender = toucher). `WeightedTrigger` (unused) would
     pick one of `Command1`/`Command2`.
  5. `TriggerTouch` + `CommandTouch` (11 / none set) would run a command on the toucher.
- **Messages**: `TRIGGER`, `LOCK`, `UNLOCK` (nothing else; `UNLOCK` doesn't fire it).
- Player-touch triggers in the data: 770 fire once (`NumberOfActivations` 1), 190 unlimited
  (111 of them with `TriggerDelay` 0, typically teleport pads that lock themselves in their own command),
  173 start locked.
- `TimedTrigger` and `AttachToObject` are unused (0 in SP). `HUDLookAtDist`/`HUDAlwaysOnDist` with a
  `TriggerType` (`TransAM`, `Exit Trigger` icons in `triggertypes.txt`) draw a HUD icon: out of scope.

## ActiveWorldModel rules (`activeworldmodel.cpp`, `door.cpp`)

States: **Off**, **PowerOn** (opening), **On**, **PowerOff** (closing), **Pause**. Doors are the same
machine with renamed props:

| Generic prop | Door prop | Meaning |
|---|---|---|
| `StartOn` | `StartOpen` | Start by powering on at load (not snapped open: it moves) |
| `TriggerOff` | `TriggerClose` | A trigger while on turns it off (toggle) |
| `RemainOn` | `RemainOpen` | Stay on; with neither this nor `TriggerOff` it auto-offs after `OnWaitTime` |
| `RotateAway` | `OpenAway` | Rotating: swing away from the activator |
| `PowerOnTime` | `OpeningTime` | Seconds to move on |
| `PowerOffTime` | `ClosingTime` | Seconds to move off; **0 means use `PowerOnTime`** |
| `OnWaitTime` | `OpenWaitTime` | Minimum time on before it can go off (and the auto-off delay) |
| `OffWaitTime` | `CloseWaitTime` | Minimum time off before it can go on again |
| `PowerOn/On/PowerOff/OffSound` | `Opening/Open/Closing/ClosedSound` | Played on entering each state |
| `PowerOn/On/PowerOff/OffCommand` | `Opening/Open/Closing/ClosedCommand` | Run on entering each state |

**Geometry** (`OnObjectCreated`):
- Sliding: `MoveDir` is in the world model's own frame (turned by its initial rotation, normalized; zero ⇒
  up). Off position = placed position; on = off + `MoveDir × MoveDist`. Recomputed from the current
  position when it leaves Off/On (so a keyframer may carry it).
- Rotating: on angles = placed angles + `RotationAngles` (degrees, pitch/yaw/roll), turned about
  `RotationPoint` (a `Point` object's position, removed from the world; else its own position).
  `OpenAway`/`RotateAway`: on powering on, it tries both signs and picks the one whose end position is
  farther from the activator.

**Move** (`UpdatePowerOn`/`UpdatePowerOff`, every frame): `percent = t / time`; step
`= GetWaveformValue(MoveDist / time, percent) × frameTime` along the remaining direction, snapping to the
end when the step overshoots or `percent ≥ 1`; `t += frameTime` after each frame that moved. Same waveforms
as spinners/keyframers (`tools/waveform.py`: Linear, Sine, SlowOff, SlowOn). Rotating does the same per
angle. Sliding with `MoveDist` 0 reaches its end on the first frame. Arrival ⇒ `SetOn` / `SetOff`.
Power-on waits `MoveDelay` before moving; power-off checks `start + MoveDelay` against a start that already
includes it, so it waits **2 × MoveDelay** (3 doors have 5 s).

**Blocking**: unless `ForceMove` (or `ForceMoveOn` while opening / `ForceMoveOff` while closing), before each
step it tests whether the new pose would intersect a **player**; if so it doesn't move this frame (and `t`
doesn't advance): the door waits for the player to leave. Only players block. Rotating: a player it would
move away from doesn't block.

**`HandleTriggerMsg`** (use, `TRIGGER`, and `ON`/`OFF` when they apply):
1. Locked ⇒ `LockedSound` + `LockedCommand`, stop. (ltjs lets a character whose keys control the object
   through; Tron's `keyitems.txt` has two NOLF2 briefcases controlling nothing, so locked is locked.)
2. Off: if `now ≥ stopTime + OffWaitTime` ⇒ PowerOn.
3. PowerOn or PowerOff: reverse (`ChangeDir`), unless `ForceMove`/`ForceMoveOn`/`ForceMoveOff` for that
   direction, or reversing would hit the activator.
4. On: with `TriggerOff`, if `now ≥ stopTime + OnWaitTime` ⇒ PowerOff. Without it ⇒ restart the on timer
   (`SetOn(true)`: nothing visible; re-arms the auto-off).

**Entering a state** (sounds and commands; commands go through the command manager with the AWM as sender):
- PowerOn: `PowerOnSound`, `PowerOnCommand`, prompt state = on.
- On: `OnSound`, `OnCommand`, stopTime = now. Then: `TriggerOff` or `RemainOn` ⇒ stay; else after
  `OnWaitTime` ⇒ PowerOff (auto-close).
- PowerOff: `PowerOffSound`, `PowerOffCommand`, prompt state = off.
- Off: `OffSound`, `OffCommand`, stopTime = now. At load (not `StartOn`) it is set Off silently: no sound,
  no command.

So for doors: `TriggerClose` 1 = toggle; `TriggerClose` 0 + `RemainOpen` 1 = opens once and stays;
`TriggerClose` 0 + `RemainOpen` 0 = opens, auto-closes after `OpenWaitTime`, re-use while open extends it.

**Sounds** (`StartSound`): each state's sound first stops the previous one (so an empty `OnSound` silences a
looping opening sound). 3D, from the object (or object + `SoundPos` if non-zero), outer radius `SoundRadius`,
inner 0.25 × it; looped when `LoopSounds`. The name can be a soundbute (the invalid-pset sound is one).

**Messages** (`OnTrigger`): `ACTIVATE` (as use, checks `PlayerActivate` and the pset gate), `TRIGGER`,
`LOCK`, `UNLOCK` (also grey/normal prompt), `ON` (only when Off/PowerOff), `OFF` (only when On/PowerOn),
`SETPOWERONMULTIPLIER <f>` (scales the next power-on time; reset on reaching On), `PAUSE` (freeze while
moving), `RESUME`. Doors add `TRIGGERCLOSE` (On/PowerOn and past `OnWaitTime` ⇒ PowerOff). WorldModel base
messages (hide/show...) belong to the command-language ticket.

**`DoorLink`** (12 doors): when a door starts opening from a trigger with a non-AI activator, the linked
door is triggered too if it is Off or closing (one hop; the link isn't followed back).

**Attachments** (18 doors have `Attachments`): attached objects move with the door; an attached world model
relays `ACTIVATE` to its parent and copies its can-activate flag (`WorldModel::SetActivateParent`,
`HandleActivateMsg`). Tron adds `AllowParentActivateOwnership` (default 1), not traced further. Several
names are brush world models not exported as objects (`worldmodel9`, `exit_elevator_additive`).

## For the implementing tickets

- The pieces the viewer already has fit: waveform shapes (`Spinner.SpinUp`/`tools/waveform.py`), world
  models as GameObjects, and riding (`Riding.Carry`): lifts are `SlidingDoor`s (`Lift`, `elevator`), so the
  player must ride doors like keyframed world models.
- Use: E, ray from the camera, first hit, 100 units to the hit point, `PlayerActivate`; no pset check needed.
- Triggers: AABB overlap with the player box each frame, then the gates above.
- Out of scope but counted: AI activation, `ExitTrigger`'s level switch, the trigger HUD icons, door knob
  animations, AI disturbance stimuli.

## Open points

- Tron's `HandleTriggerMsg` locked branch was taken from ltjs, not re-checked in `object.lto` (the outcome
  is the same either way: no key controls anything).
- What the prompt shows for a `PlayerActivate` AWM with `ActivateType` `<none>` in Tron (NOLF2 shows a
  generic "Use"); not traced in `cshell.dll`.
- The `cres.dll` strings 9500–9549 weren't extracted; the comments in `activatetypes.txt` are the text.
