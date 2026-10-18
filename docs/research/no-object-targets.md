# Messages that name no object

Research for #49 (map #28). Question: in the 38 single-player levels, which `msg` targets name no object
in their level (the viewer's `(no object)` row)? Sort them into groups: names a spawner gives the objects
it creates, objects of another level, typos or deleted objects, engine-side names, anything else. For
each group, should the viewer handle it, report it as a system we don't have, or report it as dead?

## Answer

The levels hold 27,830 `msg` targets. 23,206 name an object of their level, 2,921 are the player, and
303 are `<CAIHuman>`, which means the spawner's new object. **1,400 name no object.** (The ticket says
1,404. The 4 teleport points that name nothing (#31) are message arguments, not `msg` targets, and are
not counted here.) The holders the viewer runs (triggers, command objects, event counters, doors,
switches, keyframer keys, startup and start-point commands, IONodes) send 1,172 of them. The other 228
are in dialogue, AI, AI nodes, BinaryBits, SecRezzers and spawners, which the viewer doesn't run.

| Group | Targets | Names | Levels | From a holder the viewer runs | Viewer |
|---|---:|---:|---:|---:|---|
| **Spawned**: the name a `spawn <name>` gives the object a Spawner creates | 464 | 195 | 30 | 344 | System we don't have |
| Spawn sent to a spawner that isn't in the level | 23 | 20 | 10 | 19 | Dead |
| Object of another level (copied commands or prefabs) | 175 | 102 | 22 | 157 | Dead |
| Prefab instance not in the level (`A.B`, no `A.` object) | 257 | 257 | 10 | 256 | Dead |
| Prefab part not in the level (`A.` objects exist, `A.B` doesn't) | 106 | 87 | 16 | 96 | Dead |
| Renamed to switch it off (`*challKF`) or misspelt (`climgKF`) | 9 | 7 | 6 | 8 | Dead |
| Gone: no trace in any world | 366 | 276 | 31 | 292 | Dead |
| Engine-side names | 0 | | | | |
| **Total** | **1,400** | | 35 | **1,172** | |

- **Spawned (464)**: what these objects are is in the spawners' templates: CAIHuman 408, AILightCycle 45,
  PatchRoutine 6, CThorne 5. All are characters or AI. Their messages are `remove` 187, `goalscript`
  157, `teleport` 23, `addgoal` 15 and other AI words. In the game the name exists only after the
  spawn, and until then the message goes nowhere, as it does in the viewer. The characters map will
  spawn them. Until then the viewer should count them in their own row, `MSG (spawned <class>) <word>`,
  not under `(no object)`, so that the report tells a system we don't have apart from dead messages.
- **Spawned under a template's own name (356 more, not in the 1,400)**: 355 targets name an object
  that is a `Template` in the level and that a `spawn` also uses as the new name (`spawn Mercury`).
  The game never creates a template object (`GameBase::ReadProp`; Tron's `object.lto` reads `Template`
  at `0x100a91aa`), so these targets also exist only after the spawn. The viewer joins every level
  object, templates included, so it delivers them to the template and reports them as
  `MSG CAIHuman …` (330), `SpecialFX` (18) or `AILightCycle` (8). The viewer should leave templates
  out of the registry and count these targets as spawned too. Then all **819** messages to spawned
  objects land in one row. The last of the 356 names a template that no `spawn` uses: in the game it
  reaches nothing.
- **Dead (936)**: nothing in the game ever has these names, so the engine drops the message without a
  word. The viewer should do the same, and count them as dead in the report (`MSG (no object) <word>`
  as today), never "fix" them by matching close names. There are no sub-cases that need handling: the
  groups only explain where the names came from.
- **Engine-side names: none.** The only names the engine resolves without an object are `player`,
  `ActivePlayer` and `OtherPlayers`, compared with `_stricmp` (Tron `object.lto` `0x100c293e`, as in ltjs
  `SendTriggerMsgToObjects`). The viewer already handles all three. Cameras, dialogue and client-side
  objects are ordinary named objects: when one is missing, it is just gone.

## How a target name resolves

From ltjs `commandmgr.cpp` / `serverutilities.cpp` (`docs/research/command-language.md`, section "msg"),
checked against Tron's `object.lto`:

- A target is looked up by name in the current world only, ignoring case. When no object has the
  name, the first lite object (CommandObject, Group) with it gets the message. If there is none, the
  message is dropped and nothing is printed.
- **Templates.** `GameBase::ReadProp` saves every object whose `Template` prop is true with
  `CObjectTemplateMgr::AddTemplate` and returns false, so the object is never created. Tron does the
  same: `object.lto` `0x100a91aa` looks up `"Template"`. The levels have 643 templates: CAIHuman 590,
  AILightCycle 44, SpecialFX 6, PatchRoutine 2, CThorne 1. An object with an empty name is named
  `noname<N>` (`0x100a91e3`, format `noname%d`).
- **Spawner** (`spawner.cpp` `Spawner::OnTrigger`; the same tokens in Tron at `0x101411ef`):
  - `spawn [name]` copies the template named by the spawner's `Target` prop at the spawner's position.
  - `spawnfrom <object> [name]` does the same at the position of that object.
  - The copy takes the given name. Without one, the name is empty (Tron's default is an empty string at
    `0x103252bc`), so `ReadProp` names it `noname<N>` and nothing can address it by name.
  - The spawner then runs its `InitialCommand` with the new object as the active target. That is the
    only way the 303 `<CAIHuman>` targets reach an unnamed spawn.
  - The levels hold 835 Spawners. Their `Target` templates are CAIHuman 772, AILightCycle 43,
    SpecialFX 6 and PatchRoutine 6, plus CThorne 1. 7 targets name no template.
  - Spawn messages that reach a Spawner directly or through a Group: 499 named and 306 unnamed.
- Tron's `SecRezzer` (43, `Target` = a `SRn.BackUp` template) also spawns. None of the 1,400 names
  looks like one of its spawns, so how it names its spawns was not decoded.

## The groups

Exclusive and tried in this order:

1. **Spawned (464).** The target's name is the `<name>` of a `spawn <name>` (or the third word of
   `spawnfrom`) sent to a Spawner of the same level. The group counts every such name, whether or not
   the spawn message is ever reached. The biggest are m02-02 `Mercury` (35, `AskIcon`), m06-02 `cinjet`
   (22, `remove`), m07-04 `Alan` (12) and m07-04 `cinjet` (11). The holders are triggers (342),
   dialogue (91), AI nodes (15), characters (11), spawners' `InitialCommand` (3) and command
   objects (2).
2. **Spawn to a missing spawner (23).** The message is `spawn`/`spawnfrom` and its target names no
   object. Examples: m02-01 `stage2spawner04`, `stage3spawner03/04`, `mp04spawner`, `fp01spawner`
   (race and pit resets); m04-02 `cindw4SP`..`cindw10SP` (the even-numbered spawners of a cutscene);
   m07-02 `icb01..03spawner` (in AI `DeathCommand`s). What they would spawn doesn't exist either.
3. **Renamed or misspelt (9).** There are two cases.
   - **Renamed to switch the object off (6).** The level has the same name with a `*` added, the
     designers' way of switching an object off: m02-01 `*challKF` (2) and `chatter1DO*` (1), m04-03
     `*pan1rKF*` (1), m10-04 `*bridgetimer` (2).
   - **Misspelt (3).** One letter off a name in the level, with the same digits: m03-01 `answerDO`
     (`answersDO`), m04-01 `climgKF` (`climbKF`), m11-01 `sm_group` (`sr_group`).

   They are dead in the game too, so the viewer must not match them.
4. **Object of another level (175).** The name is an object in another world (163 in another
   single-player level, 12 only in multiplayer). These are commands copied from other levels or
   prefabs: intro's `murder.trig` and `ByteKF03` (from m01-01), the `DS1.End*` data-stream prefab names
   found in eight levels, and m01-01's dialogue triggers `12006_Dialogue` and others, which also name
   nothing in intro. m05-02's `null` (12, a placeholder target) only happens to name an object in
   `discarena04`.
5. **Prefab instance not in the level (257).** A DEdit prefab name `instance.part` where no object of
   the level starts with `instance.`. intro and m11-01 have 105 each: their `*_starter` CommandObjects
   turn `on` the keyframers of 105 prefab instances that aren't in the level (`linesystems00..19.ls_kf`,
   `cubes00..09.c_kf`, the odd-numbered `big_triangle_groups_1xx.btg1_kf`…). The rest: m06-03 20
   (`GridPopUpNN.Reset`), m08-01 14, and 13 in six other levels.
6. **Prefab part not in the level (106).** The instance exists but not that part, mostly a switch
   prefab without its `Off` trigger (`ExitSwitch.OffTrigger`, `M09Switch01..04.Off`,
   `*.BitRelayOFF`). Also m04-02's `DS4.End*` (28): the level's `DS4` data-stream instance has no `End`
   parts. And m07-02's `popNN.ick0` (18): the instances only have `popNN.ick0kf` and `popNN.ick0wm`.
7. **Gone (366).** None of the above. Typical: m07-02 `doomfx` (7), m01-02 `ZBackup01_INT` (5), m02-04
   `EventTrigger03` (5), m06-01 `liftrail` (5), m02-01's objective triggers `obj01add`/`obj02complete`,
   and the `DistractionNodeNN` names in m04-01, m04-03 and m05-04.

## Per level

Targets with no object, by group. The last column is not part of the 1,400: these are targets that
name a template, which the viewer delivers to the template object.

| Level | No object | Viewer runs the holder | Spawned | Spawn to a missing spawner | Other level | Prefab instance gone | Prefab part gone | Renamed / misspelt | Gone | To a template (spawned; resolves in the viewer) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fin | 1 |  |  |  |  |  |  |  | 1 |  |
| intro | 192 | 177 | 3 |  | 47 | 105 | 2 |  | 35 |  |
| m01-01 | 64 | 55 | 7 | 1 | 34 |  | 2 |  | 20 | 5 |
| m01-02 | 41 | 31 | 3 | 1 | 8 | 4 | 8 |  | 17 | 20 |
| m02-01 | 88 | 78 | 29 | 8 | 3 |  |  | 3 | 45 | 60 |
| m02-02 | 64 | 44 | 39 | 2 |  | 1 | 9 |  | 13 | 8 |
| m02-03 | 35 | 27 | 15 |  | 5 |  | 4 |  | 11 | 4 |
| m02-04 | 72 | 58 | 24 |  | 7 | 2 | 9 |  | 30 |  |
| m03-01 | 15 | 12 | 3 |  |  |  | 2 | 1 | 9 | 24 |
| m04-01 | 11 | 11 |  |  | 1 |  |  | 1 | 9 | 9 |
| m04-02 | 89 | 89 | 22 | 4 | 24 | 3 | 28 |  | 8 | 13 |
| m04-03 | 49 | 44 | 34 |  | 2 | 1 |  | 1 | 11 | 17 |
| m05-01 | 21 | 13 | 19 |  |  |  |  |  | 2 | 18 |
| m05-02 | 55 | 55 | 32 |  | 19 |  |  |  | 4 | 3 |
| m05-03 | 22 | 20 | 12 |  | 3 | 2 |  |  | 5 |  |
| m05-04 | 22 | 16 | 5 |  | 1 |  | 1 |  | 15 | 9 |
| m06-01 | 60 | 46 | 50 | 1 | 1 |  |  |  | 8 | 30 |
| m06-02 | 68 | 40 | 47 | 1 |  |  |  |  | 20 | 52 |
| m06-03 | 40 | 35 | 7 |  |  | 20 |  |  | 13 | 8 |
| m06-03cin | 2 | 1 |  |  | 1 |  |  |  | 1 |  |
| m06-04 | 5 | 2 | 1 |  | 1 |  | 3 |  |  | 10 |
| m07-01cin | 1 |  |  |  | 1 |  |  |  |  |  |
| m07-02 | 78 | 66 | 27 | 3 | 1 |  | 18 |  | 29 | 4 |
| m07-03 | 10 | 10 | 3 |  | 4 |  |  |  | 3 | 1 |
| m07-04 | 32 | 14 | 30 |  | 1 |  |  |  | 1 | 15 |
| m08-01 | 28 | 27 | 2 |  |  | 14 | 8 |  | 4 |  |
| m09-01 | 38 | 24 | 4 | 1 | 7 |  | 5 |  | 21 | 16 |
| m09-02 | 6 | 6 | 2 |  |  |  |  |  | 4 |  |
| m09-03 | 15 | 8 | 4 |  | 1 |  | 5 |  | 5 | 10 |
| m10-01 | 2 | 2 |  |  |  |  | 1 |  | 1 |  |
| m10-02 | 16 | 16 | 6 | 1 | 3 |  | 1 |  | 5 | 20 |
| m10-03 | 13 | 13 | 13 |  |  |  |  |  |  |  |
| m10-03cin | 1 | 1 | 1 |  |  |  |  |  |  |  |
| m10-04 | 20 | 7 | 14 |  |  |  |  | 2 | 4 |  |
| m11-01 | 124 | 124 | 6 |  |  | 105 |  | 1 | 12 |  |
| **Total** | **1,400** | **1,172** | **464** | **23** | **175** | **257** | **106** | **9** | **366** | **356** |

m07-02cin, m09-02cin and m09-03cin have none.

## What this changes for the viewer

- **A `spawned` row in the report.** For each level, collect the names that `spawn <name>` /
  `spawnfrom <obj> <name>` messages to its Spawners give, with the class of the spawner's `Target`
  template. A target with one of those names and no object counts as `MSG (spawned <class>) <word>`
  instead of `MSG (no object) <word>`. When the characters map adds spawning, the Spawner can join
  the new object at spawn time, as the engine does, and the row goes away.
- **Templates don't join.** Objects with `Template` true never exist in the game, so `JoinCommands`
  should skip them. Their 356 targets then count as spawned (355) or no object (1), as in the game.
  The exporter already skips them when it places models (`tools/export_models.py`, "a Template object
  is saved as a spawner template and never created").
- **Everything else stays `(no object)`** and is dead in the game as well: 936 targets, 828 of them
  from holders the viewer runs. No names should be matched or fixed.

## Method

- Corpus: `tools/tests/conftest.py` `corpus` (16,418 command strings from the exporter's `.dat`
  reader, `tools/dat85.py`). Strings that run were walked as in `test_command_corpus.py`. AI mixed
  messages were split the AI's way and their valid parts walked. Nested commands of `delay`/`loop`/
  `rand*` and commands sent as messages were followed. Every `msg` target is the first statement of its
  target word (`tools/commands.py`), with `<Class>` stripped. Total: 27,830 targets, the corpus test's
  `MSG` count.
- Resolution: a target names an object if an object of the same level has that `Name`, ignoring case
  (as `CommandMgr.Send` and the engine look it up). `player`/`ActivePlayer`/`OtherPlayers` are the
  player. An empty name after `<Class>` is the active target. No level object has `SinglePlayer` false,
  so templates are the only objects the game doesn't create.
- Spawn names: `spawn`/`spawnfrom` messages whose target is a Spawner of the level, with the new name
  taken from the message words. Template classes come from the template object named by the spawner's
  `Target`.
- Other level: names of every object in every `.dat` under `extracted/worlds/` (single-player,
  multiplayer, light cycle). Misspelt: Levenshtein distance 1 to a name in the level, same digits,
  at least 4 characters, no `.`. Renamed: the same name once everything but letters and digits is
  removed.
- Tron's `object.lto` was disassembled with `objdump -d --x86-asm-syntax=intel`. Its `_stricmp` and
  `strstr` imports were read from the PE import table, and the string addresses from `.rdata`
  (file offset = address − `0x10000000`).
- Not covered: which of these messages are ever reached in play. A target counts if its string runs
  at all.
