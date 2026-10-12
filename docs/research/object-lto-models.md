# Models that object code attaches without an attribute file

Research for #16 (map #1, follows #12 and #13). Question: `object.lto` attaches models that no attribute
file lists (ArchiveBin's `ArchiveBin_Frame`). Which other classes placed in the single-player levels do
the same? What do we miss today, and which of those are static?

## Answer

Five classes placed in `retailsingleplayer` get a model from object code. Four of them have a static spawn
look and are now exported. One is animation-driven and is left for the behavior phase.

| Class (placed) | What the code does | Status |
|---|---|---|
| `ArchiveBin` (167) | Attaches `ArchiveBin_Frame` at `Frame` (#13), then one **berry** per item at `Socket<n>` | berries implemented (279) |
| `IONode` (25) | Its own model is the hard-coded template `IONode`, shown with the "off" skin | implemented |
| `Optimizer` (18) | Its own model is the hard-coded template `Optimizer`, with skins 0–2 (the "on" set) | implemented |
| `TronTurret` (14) | Model from proptypes `PropType`, kept at its `Parent` object's `ParentSocket` | implemented |
| `BinaryBit` (36) | Hard-coded `Props/Models/BinaryBit.ltb` with styles `BinaryBit_Idle/Yes/No` | behavior (see below) |

`SecRezzer`'s "active look" is state: skin 0 at idle (what we draw), skin 2 (`_On`) for select/run, skin 1
(`_Off`) for disable, and skin 3 (`_Spawn`) for spawn. It goes to the behavior phase.

## Method

`extracted/object.lto` is a PE32 i386 DLL, disassembled with `objdump -d --x86-asm-syntax=intel`, with
string and pointer cross-references worked out from the PE section table. I swept:

- every call to `CModelButeMgr::GetModelId` (`0x100bc220`, 26 sites) and its siblings `GetModelFilename`
  (`0x100bd380`), `GetSkinFilename(id, i)` (`0x100bd400`), `CopySkinFilenames` (`0x100bd450`) and
  `CopyRenderStyleFilenames` (`0x100bd4a0`);
- every `ILTServer::CreateAttachment` call (`g_pLTServer` `0x10344b28`, vtable `+0x134`, 27 sites);
- every string literal ending in `.ltb`/`.dtx`.

I then mapped each site to its class (the class-name string in the same code block, `GameBase`
registration, vtables) and checked the classes against the object counts in the 38 single-player `.dat`
files.

### GetModelId sites

| Site | Name | Class | Placed in SP? | Notes |
|---|---|---|---|---|
| `0x1000d453` | `ModelTemplate` prop | ArchiveBin | yes | already exported |
| `0x1000f526` | `ArchiveBin_Frame` | ArchiveBin | yes | #13 |
| `0x1000fa31` | `SubroutineBerry` / `PSetBerry` / `DocumentBerry` | ArchiveBin → `Berry` | yes | **berries** |
| `0x100179cb` | `CoreDump` | CoreDump | no | spawned at runtime (`tetra%d`) |
| `0x10022650`, `0x100231cd`, `0x1002344d`, `0x100238b9` | `IONode` | IONode | yes | **implemented** |
| `0x1002c53c` | `ModelTemplate` (default `Default`) | LightCycleVolume | no | |
| `0x100301ec`, `0x10031138` | `Optimizer` | Optimizer | yes | **implemented** |
| `0x100436b4`, `0x100436ef` | `Secrezzer`, then the `ModelTemplate` prop | SecRezzer | yes | already exported |
| `0x10051a48` | `GridCyclist` | light-cycle AI | — | template has no `ModelFile` |
| `0x10059170` | `ModelTemplate` prop | CThorne (1, `Thorn`) | yes | a character, not `CAIHuman` |
| `0x10070160`, `0x1007416c`, `0x100f0811` | `Player` | player | — | |
| `0x100bba78` | `MultiplayerModels` | multiplayer | — | |
| `0x1011e7fd`, `0x1011e8cd`, `0x1015f224`, `0x1012ffb5` | `ModelTemplate` / `ModelId` | AI | yes | characters (#9) |
| `0x101434dc` | `ModelTemplate` | GameStartPoint | — | player model |
| `0x1022b661` | `Speaker` | Speaker (25) | yes | template has no `ModelFile`: nothing to draw |
| `0x1000c8bf` | — | ArchiveBin DEdit plugin | — | editor only |

### CreateAttachment sites

`Frame` (ArchiveBin) and `Socket%d` (berries) are the only ones that matter for SP props. The rest are:

- characters and weapons: `CHHWeaponModel` (#15), `ThorneBall` (CThorne), carried bodies;
- WorldModel `Attachments`, which move level objects that are already placed;
- `CServerMark` decals and AI;
- NOLF2 leftovers (`Snowmobile`, `Light` flashlight, `GreenLight`, `Disabler`, `Decipher`, `TimeBomb`,
  `Bug`), whose classes aren't placed in Tron's levels.

### .ltb literals

- `Props/Models/BinaryBit.ltb` and `props\rs\BinaryBit_{Idle,Yes,No}.ltb` belong to BinaryBit.
- `Props\Models\Alarm.ltb` is Alarm's default `Filename`. The levels set it, so it's already exported.
- The rest are NOLF2 leftovers whose classes Tron doesn't place: `DoorKnob_01R`, `GtSecrtyCam`, `Keypad`,
  `Lock`, `PuAmmoBox`, `Snowmobile`, `SpotLight`, `Flashlight_hh`, `Codedec_hh`, `hero_action`, and the
  `1x1_square` dims debug model.

## Details per class

### ArchiveBin berries (`0x1000f730`, `0x1000f800`)

- `ReadProp` reads `Type1..Type6` into 6 item slots. The type is its index in the string table at
  `0x10284410`: `Subroutine, Procedural, Primitive, Permission Set, Email, Custom, HelpFile`. `<none>` is
  -1.
- Setup (`0x1000d23e`) calls the frame code and then `0x1000f800`. That function first calls
  `0x1000f730`, which takes the model's socket count N and builds a list of the N-1 item sockets
  (`Socket1..Socket9`; `Frame` is last). It **shuffles them with `rand()`** (a Fisher–Yates shuffle) and
  deals item k's type to the k-th shuffled socket.
- For each socket that has an item, it picks the template: type 0 gives `SubroutineBerry`, type 3 gives
  `PSetBerry`, and anything else gives `DocumentBerry`. Then it calls `GetModelFilename`,
  `CopySkinFilenames` and `CopyRenderStyleFilenames`, uses `GetSocketTransform(i)` for the position,
  creates `GetClass("Berry")` (`OT_MODEL`, `FLAG_VISIBLE`) and calls `CreateAttachment(bin, berry,
  "Socket<i+1>", 0, identity)`.
- All three templates use `ArchiveObject.ltb` (pieces `Berry` with tex 0 and style 0 `Archiveberry`, `Cube`
  with tex 1 and style 1 `ArchiveCube`). Only `Skin0` differs: `archive_CubeInternal` is the subroutine
  look, `_Blue` the permission set and `_Green` the document.
- **The exporter keeps item order**: item k goes to `Socket{k}`. The game's order depends on `rand()`
  state at load time, so no fixed order is more right than another.
- Across the single-player levels this gives 279 berries: 120 subroutine, 83 permission set and
  76 document.

### IONode (`0x10022650`, update state machine `0x10022480`)

- `ReadProp` copies the template's model, all 5 skins and both styles.
- `InitialUpdate` sets `FLAG_VISIBLE` and schedules an update.
- In the update, state 0 (set by the constructor) calls vtable `+0x68` = `0x10023090`. That function sets
  the skins to `[Skin4, Skin1, Skin2, Skin3]`, which is `IONode_Off` on the `Sphere` piece, then moves to
  state 1. The "on" skins (`0x10023310`: `Skin0..3`) only come with later states (behavior).
- **Spawn look: `[IONode_Off, IONodeFace, IONodeRing1, IONodeRing2]`.** `MoveToFloor` is false on all
  25 nodes.

### Optimizer (`0x100301ec`)

- If the template has exactly 6 skins and skins 0–2 exist, `ReadProp` uses skins 0–2:
  `Optimizer_1, Optimizer_2, chrome`. Its flags include `FLAG_VISIBLE`.
- Death (`0x10031128`) switches to skins 3–5, the `_Off` set.
- It rides a `KeyFramer` (behavior).

### TronTurret (`0x1006b790`, `0x1006c960`, `0x1006d590`)

- `ReadProp` takes `PropType` through the prop-type manager: proptypes `[PropType18]` `Turret`, which gives
  `TankTurret.ltb`, skins `Tank1, Tank2, Tank4, chrome` and styles `Tank1` and `Jet_RS`.
- At setup it looks up the object named `Parent` (for example `Tank01.Body`, a `PropType` `Tank`), then
  `GetSocket(parent, ParentSocket)`.
- Every update it takes `GetSocketTransform(parent, socket)`, or the parent's position and rotation if
  there's no socket, and places itself there. **For a static frame that is a socket attachment.**
- Turning toward its `Target` is behavior.
- All 14 turrets (m05-02 and m05-03) find their tank, at `TurretSocket`.

### BinaryBit: behavior phase

`ReadProp` (`0x10012df8`) sets the model to `Props/Models/BinaryBit.ltb` with no skins, and the styles
to `RS0 = BinaryBit_Idle`, `RS1 = _Yes` and `RS2 = _No`. The model has three pieces: `Byte1` (style 0),
`d_Pyramid` (style 1) and `d_NewSpike` (style 2). At bind pose all three shapes overlap. The animations
(`PoweredDown`, `Idle`, `Yes`, `No`) decide which shape shows. The spawn state depends on the object's
properties:

- `InitialUpdate` (`0x10013830`) plays `PoweredDown`.
- If `EnergyRequired` is 0, it powers up (`0x10013e70`): `StartOnInSocket` gives `ChangeState(2)` (slot 0
  becomes `BinaryBit_Yes`); otherwise `ChangeState(3)` (slot 0 becomes `BinaryBit_No`).

Drawing the bit correctly needs props posed by an animation frame and per-state style swaps. Until then,
the bind pose would show all three shapes on top of each other, so it isn't drawn.

## Behavior phase list

- BinaryBit: everything above (36 placed).
- ArchiveBin: the `rand()` socket shuffle, the bins' `Spin` animation (berries ride the item sockets),
  berries removed when withdrawn.
- IONode: the off/on skin swap and the `Default`/`Open`/`Close` animations.
- Optimizer: the death skins (3–5) and the `KeyFramer` path.
- TronTurret: aiming, and following its tank's `KeyFramer`.
- SecRezzer: the skin per state (idle 0, select/run 2 `_On`, disable 1 `_Off`, spawn 3 `_Spawn`).
- CoreDump (`CoreDump_tetras.ltb`, runtime-spawned) and LightCyclePowerup (ClientFX
  `WORLDS_lcpowerup_<type>`): not placed models.
- CThorne (`Thorn`, 1 in the levels): a character outside `CAIHuman`, so outside this map's character
  scope.

## Implementation

- `tools/export_models.py`:
  - `Resolver.resolve` handles `IONode`, `Optimizer` and `TronTurret`;
  - `Resolver.template(name)` replaces `export_level.template_model`;
  - `Resolver.bin_items(obj)` gives the berry templates.
- `tools/export_level.py`: `model_instances` emits each bin's berries with `parent` set to the bin's
  instance and `socket` set to `Socket<k>`. It emits turrets last, with `parent` set to the instance of the
  object named `Parent` and `socket` set to `ParentSocket`. Level format v11.
- `LevelBuilder.BuildModels` gives a non-skinned instance whose model has sockets its node Transforms at
  the bind pose, so attachments can hang from props.
- Tests: `tools/tests/test_object_models.py`.
