# Hand-held weapons on characters

Ticket #15. Sources are the NOLF2 game code in `bibendovsky/ltjs` (`game/objectdll/objectshared/`),
which Tron 2.0's game code builds on, and `attributes/weapons.txt`.

## How a weapon becomes a model

`CAttachments::Attach(position, name)` takes a position (any of them, not only the hands) and a name.
When the name (`"weapon[,ammo]"`) is a weapon, `CreateWeaponAttachment` creates a `CHHWeaponModel`:

- model `HHModel`, skins `HHSkin0..N`, render styles `HHRenderStyle0..N` (the `PV*` fields are the
  player view and aren't used);
- attached with `CreateAttachment(character, model, position name, zero offset, identity rotation)`,
  so the position name is the character model's socket, exactly like attachments from `attachments.txt`;
- `HHModelScale` isn't applied. Only powerups (`weaponitems.cpp`) read it. `HogSuffusion` has
  `<0,0,0>` there and is still drawn in the hand.
- If `HHModel` is empty, `CHHWeaponModel::Setup` calls `HideWeapon(true)`: nothing is drawn.
  `Punch`, `DiscSmack`, `ICLauncherDisc`, `FconHead`, `RiotShield`, `ICShieldDisc`, the `Fcon*`
  weapons and `SeekerPatchDamage` are like this.
- `CWeapon::SetModelObject` plays the model's `Hand` animation (not looping) when it has one. The three
  hand-held models placed characters hold (`ic_disk_hh`, `suffusion_hh`, `ball_hh`) have one node,
  one animation and no `Hand` animation: the pose is the identity. The existing attachment path
  (frame 0 of animation 0 under the socket) draws them as is.

## HolsterWeapons

`CAIHuman::ReadProp` builds a holster string from the object's own `RightHand` and `LeftHand`
properties (not from template defaults; `<none>` counts as empty). With `HolsterWeapons` on and a
non-empty string, `InitialUpdate`, after the default attachments, attaches each hand weapon's
`HolsterAttachment` and then detaches `RIGHTHAND` and `LEFTHAND`, whatever they hold. Tron's
`weapons.txt` has no `HolsterAttachment`, so holstered hands are simply empty. Without hand
properties on the object, `HolsterWeapons` does nothing.

## Numbers (all single-player levels, created characters)

- 29 hand-held weapons drawn: 17 `ic_disk_hh` (IC_RS), 11 `suffusion_hh` (Jet_RS), 1 `ball_hh`
  (HH_Ball_Glow). One more disc is dropped: `kernel_aid.ltb` has no `RightHand` socket.
- 16 characters holster: 30 hand positions emptied (9 `ICRegularDisc`, 7 `HogSuffusion`, and the
  model-less `DiscSmack`/`Punch` in the left hands), so 16 weapons that have a model aren't drawn.
- 44 weapon attachments have no hand-held model and stay hidden.
- The 765 in #9 counted Template objects too; those are no longer created (#10 review).
