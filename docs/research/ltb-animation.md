# LTB animations, child models and bone sets

Research for [#4](https://github.com/rholdorf/tron_explorer/issues/4) (map [#1](https://github.com/rholdorf/tron_explorer/issues/1)), 2026-10-12.

Primary source: `bibendovsky/ltjs` at commit
[`46aca18`](https://github.com/bibendovsky/ltjs/tree/46aca1800c8b8d6761bc9314dcd8330f82c77998)
(abbreviated `ltjs:` below). The Tron 2.0 server object DLL (`game/objectdll/tron/object.dsp`) is built on
`game/objectdll/objectshared` (`/I "..\ObjectShared"`), so the AI, `MoveObjectToFloor` and
animation-table code cited below is the code Tron links. All the numbers come from throwaway decoders run
against the real files in `extracted/` (855 model `.ltb`s load; the 17 that don't are the existing
`ltb.py` failures, not animation problems).

## Answers in short

- **Animation data** follows the child-model names. For each animation the file stores its dims, name,
  compression, interpolation time and keyframes. Then, for each node in tree (preorder) order, it stores a
  position channel and a rotation channel. Each channel holds either `nKeys` values, one constant value, or
  none. Of the four `ANCMPRS_*` kinds, the game uses all four: 3 (`REL_16_ROT_ONLY`) for 2178 animations,
  2 (`REL_16`) for 1123, 0 (none) for 191 and 1 (`REL`) for 98. No animation uses vertex animation. Sockets
  and per-animation bindings (dims plus a root translation) come after the animations. The decoder reaches
  the exact end of every file.
- **Child models** are resolved relative to the parent's directory. Their animations are appended after the
  parent's own, and they're applied **by node index**, not by name. A name lookup returns the first
  case-insensitive match.
- **SkinnedMeshRenderer fits.** Every skeletal mesh in the game is "render direct" (none use matrix
  palettes). A bone set has 1 to 4 bones, every vertex belongs to exactly one set, and every triangle stays
  inside its set's vertex range. The result is at most 4 influences per vertex, with the last weight
  implicit. The bind pose is the node's global transform, and the skin matrix is `animatedGlobal ×
  inverse(bindGlobal)`. Frame 0 of `zlot3.ltb`'s `base` animation rebuilds the bind pose to within 0.003
  units. I found no blockers.
- **MoveToFloor** casts a ray 10000 units straight down from the object's position. If the hit is farther
  away than `dims.y`, the object drops to `hit.y + dims.y + 0.1`. It never moves an object up. `dims` is the
  user dims of the model's current animation (animation 0 at spawn), scaled by the prop's scale.
- **Idle animation:** a `CAIHuman` starts in state `HumanIdle`. That state asks the model's animation table
  (`Animation=` in `modelbutes.txt`) for `{Posture=Stand, WeaponPosition=Down, Weapon=W}`. `W` comes from
  the right-hand weapon's `AIWeaponType`: Ranged gives Weapon1, Melee gives Weapon2, anything else (or no
  weapon) gives Weapon3. The result depends on the template: zealots get `Zlt_Idle4`, IC regulars
  `IC_IdleUnarmed`, programs `Gen_Idle01` or `FP_Idle`, and templates that use `AnimationsTemp.txt` get
  `Base` (the full table is below).

## 1. Binary layout after `anims_offset`

`ltb.py` already stops at `m.anims_offset`, right after the child-model names. From there
(ltjs: `Model::Load`, [model_load.cpp#L1023-L1082](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model_load.cpp#L1023-L1082)):

```
u32 nAnims
nAnims ×  AnimInfo                                   (AnimInfo::Load  L487-L496)
    f32[3]  dims            # "user dims", half-extents; read BEFORE the name
    str16   name                                     (ModelAnim::Load L378-L438)
    u32     compression     # ANCMPRS_* (L26-L31)
    u32     interpolationMS # blend-in time when switching to this anim (200 typical, 0 = no blend)
    u32     nKeys
    nKeys × { u32 timeMs; str16 command }            # command strings: "FOOTSTEP_KEY 1", "FIRE RightHand", ...
    for node in preorder(node tree):                 (LoadAnimNodesRecurse L352-L376, AnimNode::Load L275-L349)
        compression 0:  u8 isVertexAnim
                        if 0: nKeys × f32[3] pos, then nKeys × f32[4] quat
                        if 1: nKeys × { u32 n; n × f32[3] }   (vertex animation; never used by Tron)
        compression 1:  u32 nPos; nPos × f32[3];  u32 nRot; nRot × f32[4]
        compression 2:  u32 nPos; nPos × i16[3];  u32 nRot; nRot × i16[4]
        compression 3:  u32 nPos; nPos × f32[3];  u32 nRot; nRot × i16[4]
u32 nSockets; each: u32 node, str16 name, f32[4] rot, f32[3] pos, f32[3] scale     (LoadSockets L672-L704)
for each child model INCLUDING self (index 0 = self):                              (LoadAnimBindings L611-L669)
    u32 n; n × { str16 animName; f32[3] dims; f32[3] translation }
```

Channel decoding (ltjs: [model.h#L200-L372](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model.h#L200-L372)):

| count | meaning |
|---|---|
| `0` | null channel: position `(0,0,0)`, rotation identity `(0,0,0,1)` |
| `1` | constant: index 0 for every frame |
| `nKeys` | one value per keyframe |

- `i16` position: `v / 16.0` (the "1.11.4" fixed-point format).
- `i16` quaternion: `v / 32767.0` per component, in `(x, y, z, w)` order like `LTRotation::m_Quat`.
- Survey: the 202,302 channels all have a count of 0, 1 or `nKeys`. No other count appears.

The node order for animation data is the recursive tree order, which is also the stored node index order.
`ltb.py`'s `m.nodes` sorted by index works directly.

Keyframe times are milliseconds and start at 0. 1001 consecutive pairs have **equal** times (never
decreasing), so an exporter must nudge or drop duplicates for Unity curves.

### Bindings: dims and root translation

The binding lists after the sockets are the authority for `AnimInfo::m_vDims` and `m_vTranslation`
(LoadAnimBindings writes into the `AnimInfo` it finds by name and owner).

- The self list always mirrors the own animations: same names, same order, same dims (all 855 models).
- The child lists are **always empty** in Tron's files (99 lists checked). A borrowed animation therefore
  keeps the dims and translation from the child model's own self list.
- `translation` is added to the **root node's** position every frame (ltjs: `TransformMaker::InitTransform`,
  [transformmaker.cpp#L178-L184](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/transformmaker.cpp#L178-L184)).
  Example: `Base_Zlot.ltb` `Zlt_WalkUnarmed` has `(0, 4, 0)` and `Zlt_Idle4` has `(0, 0, 0)`.

Every model has at least one animation. In 300 of the 855 models, animation 0 is named `base`, often a
single-key pose.

## 2. Evaluating a pose

ltjs: `TransformMaker::Recurse`, [transformmaker.cpp#L253-L338](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/transformmaker.cpp#L253-L338).

- The keyed position and rotation are the node's **local (parent-relative)** transform:
  `global[n] = global[parent] × TR(quat, pos)`, with `global[root]` = the object transform.
- **`MNODE_ROTATIONONLY` (flag `0x2`, 1839 nodes):** the keyed position is ignored. The node uses its
  bind-pose offset from its parent instead (`m_vOffsetFromParent`, computed in `SetNodeParentOffsets`,
  [model.cpp#L891-L913](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model.cpp#L891-L913)).
  Flag `0x1` (141 nodes) doesn't affect animation.
- **Interpolation:** between two keys, position is interpolated linearly and rotation with slerp, using the
  fraction `(t - tPrev) / (tCur - tPrev)` (animtracker.cpp).
- **Looping:** looping time wraps with `t %= lastKeyTime`
  ([animtracker.cpp#L442-L446](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/animtracker.cpp#L442-L446)).
  There is no blend from the last key back to the first, so the clip length is the last key's time.
- **Rendering transform:** `cachedGlobal[i] × node[i].InvGlobalTransform`
  ([objectmgr.cpp#L1166-L1178](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/shared/src/objectmgr.cpp#L1166-L1178)).
  The node `transform` that `ltb.py` reads is that global bind matrix. ModelEdit took it from the first
  frame of the first animation ([model.h#L651-L656](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model.h#L651-L656)).

**Verified:** frame 0 of `zlot3.ltb` → `base` (compression 2), evaluated as above, reproduces every node's
bind matrix within 0.003 units. The test uses column vectors with the translation in `m[0..2][3]`, which is
`ltb.py`'s row-major `m[row][col]`. Frames of `Base_Zlot.ltb` animations applied to `zlot3`'s skeleton give
plausible poses: node heights stay within the ±48 dims.

Coordinates: LithTech, like Unity, is left-handed and Y-up. The viewer already uses raw LT positions, so
quaternions `(x, y, z, w)` and positions go straight across. A Unity `Matrix4x4` only needs the storage
transposed: Unity is column-major in memory but uses the same column-vector math.

## 3. Child models

| Rule | Source |
|---|---|
| Names are stored **without a directory** (e.g. `Base_Zlot.ltb`, `anim\gen_lightcycle.ltb`, `cinematic\mission11\m11_ralan.ltb`). The engine joins each one to the **parent's directory** (`ServerLoadChildModelCB`). The file system is case-insensitive. | [servermgr.cpp#L1404-L1428](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/server/src/servermgr.cpp#L1404-L1428) |
| Children can't have children ("Recursive loading is NOT supported"; error 15). At most 32 child models. | model_load.cpp#L977, #L995-L999; model.h#L42 |
| The parent's animation list is its own animations, followed by each child's animations in child order (`m_AnimOffset`). | [model_load.cpp#L1057-L1074](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model_load.cpp#L1057-L1074) |
| A child animation drives the **parent's** node `i` with the child's channel `i`. `TransformMaker` calls `GetAnimNode(iNode)` with the parent's node index, and nodes are never matched by name. | transformmaker.cpp#L172-L173 |
| Lookup by name (`Model::FindAnim`) is a linear, case-insensitive scan, and the first match wins. A parent's own `base` therefore shadows a child's `base`. | [model.cpp#L841-L863](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model.cpp#L841-L863) |

What the survey found:

- 34 parents, 18 distinct child lists. Every child resolves, and none has children of its own.
- Every parent/child pair has the **same node count**.
- Names often differ only at the root (`null` vs `base_zlot_null`). A few differ in the face nodes:
  - `alan.ltb` has `face_rmouthcorner` and `face_lmouthcorner` swapped compared with `Base_General_Recoil`.
  - `i_no.ltb` uses `face_lcorner` where `Base_General_Recoil` has `face_lmouthcorner`.

  Mapping by index is what the game does, so mapping by index is faithful (any glitch is in the original
  too).
- Duplicate names across self and children are common (`base`, `prodloop`, `energyclaw_idle`), so
  first-match order matters.

**Extra child models on the level object:** `CCharacter` has `ChildModel_1..3` properties (group
`AddChildModel`, [character.cpp#L75-L78](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/character.cpp#L75-L78)).
`CAI` appends them after the file's children (`createstruct.m_Filenames[n+1]`,
[ai.cpp#L1519-L1533](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/ai.cpp#L1519-L1533)).
These paths are full game paths such as `Chars\models\Cinematic\mission11\M11_rAlan.ltb`. 178 of the 836
`CAIHuman`s set at least one, mostly cinematic animation packs. They only matter when something plays one
of their animations. The `Initial` command (`goalscript animate anim=...`) does that for 85 characters, but
that's the command language and out of scope. One such child, `cinematic/mission02/m0204_jet.ltb`, is among
the 17 files that fail to load.

## 4. Bone sets → Unity `SkinnedMeshRenderer`

ltjs: `BoneSetListItem`, [d3dmeshrendobj_skel.h#L26-L35](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/render_a/src/sys/d3d/d3dmeshrendobj_skel.h#L26-L35).
`CD3DSkelMesh::Render` (`eD3DRenderDirect`) and `SetTransformsToBoneSet`:
[d3dmeshrendobj_skel.cpp#L347-L535](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/render_a/src/sys/d3d/d3dmeshrendobj_skel.cpp#L347-L535).

- Each bone set `{u16 firstVert, u16 vertCount, u8 bones[4], u32 indexEnd}` loads world matrices 0..n-1
  with `bones[k]`, stopping at the first `0xFF`. The set then draws triangles `[prevIndexEnd, indexEnd)`
  over vertices `[firstVert, firstVert + vertCount)`.
- The blend is D3D fixed-function `D3DVBF_{n-1}WEIGHTS`. A vertex in a set with `n` bones uses its first
  `n-1` stored weights, and the last weight is `1 - Σ`. The number of stored weight floats per vertex is
  mesh-wide (`maxBonesPerTri - 1`, which `ltb.py` already decodes as `weights`). Extra floats in sets with
  fewer bones are ignored.
- `bones[k]` are **model node indices**, the same index space as `m.nodes`. So the Unity `bones[]` array is
  simply all nodes, and `bindposes[i]` is the inverse of node `i`'s global bind matrix.

Survey of all 510 skeletal render objects in 140 models:

| Check | Result |
|---|---|
| Render-direct meshes | 510 |
| Matrix-palette meshes | **0** |
| Bones per bone set | 1: 921, 2: 2136, 3: 2160, 4: 1695 (**max 4**) |
| Vertices in more than one set / in no set | **0 / 0** |
| Sets with a triangle outside their vertex range | **0** |
| Sets with a negative explicit or implicit weight | **0** |
| Largest skeleton | 95 nodes (characters: 25–38) |

That gives a fit with no blockers:

- Up to 4 influences per vertex. Unity's default quality is 4 bones. If you use the `BoneWeight1` API,
  sort influences by weight, descending.
- Bone count is far below any limit.
- Bind poses come straight from the node matrices.

Vertex-animated (type 6) pieces don't occur in `chars/models`. Rigid (type 4) pieces on characters follow
`mesh.bone` with the same `global × inverse(bind)` matrix, so they are a 1-bone skin with weight 1, or a
child `Transform` with the bind offset applied. Use LOD 0.

## 5. MoveToFloor

`MoveObjectToFloor`, [serverutilities.cpp#L1076-L1108](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/serverutilities.cpp#L1076-L1108):

```
from = objectPos; to = objectPos + (0, -10000, 0)
hit  = IntersectSegment(from, to, IGNORE_NONSOLID | INTERSECT_OBJECTS | INTERSECT_HPOLY)
if hit and (pos.y - hit.y) > dims.y:  pos.y = hit.y + dims.y + 0.1     # only ever moves down
```

- **Characters:** `MoveToFloor` defaults to TRUE
  ([character.cpp#L66](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/character.cpp#L66),
  read at #L780). On initial update, `dims` is set from `GetModelAnimUserDims(current animation)` and then
  the object is moved, both before any AI update
  ([character.cpp#L1392-L1402](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/character.cpp#L1392-L1402)).
  At that point the current animation is animation 0. For zealots that's `base` with dims `(24, 48, 24)`,
  and their bind-pose mesh spans y −51.8 to 50.8, so the origin is the body's centre. 737 of the 836
  placed `CAIHuman`s have `MoveToFloor=True`.
- **Props:** `MoveToFloor` also defaults to TRUE
  ([prop.cpp#L49](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/prop.cpp#L49)).
  `dims` is the animation-0 user dims × the prop's `Scale`
  ([prop.cpp#L664-L677](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/prop.cpp#L664-L677)),
  and the move happens on the first update
  ([prop.cpp#L1777-L1783](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/prop.cpp#L1777-L1783)).
- **Ignore** the `Dims` property on the level object (`24, 53, 24` on 835 `CAIHuman`s): MoveToFloor uses the
  animation dims.
- **Unity:** raycast down against the level's solid geometry and world models, starting at the object's
  position. Only lower the object, and only when the gap exceeds `dims.y`. `dims.y` is the half-height
  (the model origin is at mid-body).

## 6. Default idle animation

Chain (all in `objectshared`):

1. **State.** `CAIHuman` init ends with `SetState(kState_HumanIdle)`
   ([aihuman.cpp#L1858](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/aihuman.cpp#L1858)).
2. **Props the state sets.** `CAIHumanStateIdle::UpdateAnimation` sets `Posture = m_ePose` (Stand) and
   `WeaponPosition = Down`
   ([aihumanstate.cpp#L251-L257](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/aihumanstate.cpp#L251-L257)).
   `CAIHuman::UpdateAnimation` adds `Weapon = GetCurrentWeaponProp()`, and `Movement = Hover` for hovering
   AIs
   ([aihuman.cpp#L1644-L1677](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/aihuman.cpp#L1644-L1677)).
3. **Weapon prop.** It comes from the weapon attached at `RightHand` (`AIWeaponType` in `weapons.txt`):
   `1` Ranged gives Weapon1, `2` Melee gives Weapon2, and anything else or no weapon gives Weapon3
   ([ai.cpp#L3037-L3046](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/ai.cpp#L3037-L3046),
   [#L3154-L3177](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/ai.cpp#L3154-L3177)).
   The level object's `RightHand` property names the weapon (`ICRegularDisc`, `BallLauncher`, `RiotShield`,
   …). Examples: `ICRegularDisc` is Ranged, so Weapon1. `RiotShield` is Melee, so Weapon2.
4. **Lookup.** `CAnimationMgr::FindAnimation` searches the model's animation table, in three steps
   ([animationmgr.cpp#L1349-L1446](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/animationmgr.cpp#L1349-L1446);
   prop equality: [animationmgr.h#L55-L58, #L107-L118](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/game/objectdll/objectshared/animationmgr.h#L55-L58)):
   - **Exact match:** look for rows whose props equal the request exactly, with `None` matching only
     `None`.
   - **Wildcard match:** if none, take the first row in file order whose props match with `Any…`
     wildcards.
   - **Ties:** if several rows have identical props, pick one at random.
   - **No match:** fall back to the `Base None {}` row.

Simulating this lookup on every template in `modelbutes.txt` gives:

| Template (`Animation=`) | Weapon1 | Weapon2 | Weapon3 / none |
|---|---|---|---|
| Zealot, Zealot2, Zealot3, Zealot_multi (`Animations_Zealot`) | `Zlt_Idle4` | `Zlt_Idle4` | `Zlt_Idle4` |
| IC_Regular*, Kernel_Aid (`Animations_regular`) | `IC_IdleUnarmed` | — (`Base`) | `IC_IdleUnarmed` |
| IC_Shield* (`animations_ICShield`) | — | random `IC_ShieldIdle1..5` | `IC_ShieldIdle1` |
| IC_Launcher* (`animations_ICLauncher`) | `Launcher_Idle` | — | `Launcher_Idle` |
| IC_Kernel (`Animations_ICKernel`) | `IC_IdleUnarmed1` | `Launcher_Idle` | `IC_IdleUnarmed1` |
| Male_Program*, I-No, Alan_TronWorld, Lightcyclist*, DJ, Romie (`Animations_General`) | — | — | `Gen_Idle01` |
| Female_Program*, Mercury, Female_Punk (`Animations_GeneralFemale`) | `FP_Idle` | — | random `FP_Idle` / `FP_Idle2` |
| DataWraith* (`Animations_Netrunner`) | `Net_Idle1` | `Net_Idle1` | `Net_Idle1` |
| ResourceHog (`animations_ResourceHog`) | `Rhog_StAim` | — | `Rhog_Idle0` |
| Rectorscript | `Rect_ClosedIdle` | `Rect_ClosedIdle` | `Rect_ClosedIdle` |
| Seeker | `Seek_Idle` | `Seek_Idle` | `Seek_Idle` (but `seeker.ltb` fails to load) |
| FconMonster | `idle` | `idle` | `idle` |
| Ma3a, Byte, Ma3a_Enormous (`AnimationsHover`, hovering) | — | — | `Hover` |
| Alan_Bradley, Jet_Bradley, Encom/Fcon employees, Lead_Technician, Crown, Popoff, Baza, Guest, DataWraith_Prep/Crown (`AnimationsTemp`) | `Base` | `Base` | `Base` |
| M07S01_* (`Animations_M0701`), Ma3a_Cine (`AnimationsBase`) | `Base` | — | `Base` |

"—" means no row matches, so the result is the `Base` fallback. Every resolved name exists in the model or
its children, except in the `multi/*` multiplayer models, which aren't placed as `CAIHuman`. The
`HumanIdle` state lasts only until the goal set (`GoalSet`, e.g. `ZLotPatrol`) takes over, but the map
excludes behavior, so this is the faithful "standing idle".

## 7. Implications for the tickets

- **#9 (bind pose):** unchanged. Use `bones` = all `m.nodes` (index order) and `bindposes[i] =
  inverse(node.transform)` (transposed into Unity storage). Per vertex, take its bone set's `bones[0..n-1]`
  with weights `w[0..n-2]` plus `1 - Σ`. Rigid pieces are 1-bone skins on `mesh.bone`. No matrix-palette
  path is needed.
- **#10 (idle + MoveToFloor):**
  - Add `load_anims` to `ltb.py` (layout in §1). It decodes all 855 loadable models to EOF.
  - Resolve children relative to the parent's directory, and append their animations in order.
  - Pick the idle animation with the rule in §6. That needs a small parser for the animation tables plus
    `RightHand` → `weapons.txt` `AIWeaponType`; a fixed per-template name list would also work.
  - Export only the clip(s) each placed character needs. Each clip has per-node local TR curves, root
    translation added, ROTATIONONLY nodes using the bind offset, wrap-mode loop, length = last key time,
    and duplicate key times nudged.
  - Apply MoveToFloor using animation 0's dims (props also × scale).
  - Load-time risk: `base_zlot.ltb` alone has 77 animations. Decode lazily, or only the idle clip.
- **Not blockers but worth noting:** `seeker.ltb` (5 placed Seekers) and the cinematic child
  `m0204_jet.ltb` fail in `ltb.py` before the animation section, so they belong with the "8 failing files"
  work. Extra `ChildModel_N` level properties and `Initial` animate commands are behavior and stay out of
  scope.

## Sources

ltjs at `46aca1800c8b8d6761bc9314dcd8330f82c77998`:

- Engine model code:
  - [`engine/runtime/model/src/model_load.cpp`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model_load.cpp)
  - [`model.h`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model.h)
  - [`model.cpp`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/model.cpp)
  - [`transformmaker.cpp`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/transformmaker.cpp)
  - [`animtracker.cpp`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/model/src/animtracker.cpp)
- Engine loading, transforms and rendering:
  - [`engine/runtime/server/src/servermgr.cpp`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/server/src/servermgr.cpp)
  - [`engine/runtime/shared/src/objectmgr.cpp`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/shared/src/objectmgr.cpp)
  - [`engine/runtime/render_a/src/sys/d3d/d3dmeshrendobj_skel.{h,cpp}`](https://github.com/bibendovsky/ltjs/blob/46aca1800c8b8d6761bc9314dcd8330f82c77998/engine/runtime/render_a/src/sys/d3d/d3dmeshrendobj_skel.cpp)
- Game code in `game/objectdll/objectshared/` (linked by `game/objectdll/tron/object.dsp`):
  - `serverutilities.cpp`, `character.cpp`, `prop.cpp`
  - `ai.cpp`, `aihuman.cpp`, `aihumanstate.cpp`
  - `animationmgr.{h,cpp}`
- Game data in `extracted/`:
  - Models: `chars/models/*.ltb` and all 855 loadable model `.ltb`s
  - Attributes: `attributes/modelbutes.txt`, `attributes/animations*.txt`, `attributes/weapons.txt`
    (`AIWeaponType` doc comment)
  - Levels: `CAIHuman` objects in `worlds/**/*.dat` (via `tools/dat85.py`)
