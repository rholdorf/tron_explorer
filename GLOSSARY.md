# Tron 2.0 Explorer

A faithful walkthrough of Tron 2.0's LithTech levels on macOS, rebuilt from the game's own files.

## Language

### Models

**Model**:
A LithTech `.ltb` mesh with its pieces, nodes and (optionally) animations.
_Avoid_: mesh (for the whole file), asset

**Prop**:
A model placed in a level as a static object, resolved through the prop/model attribute files.
_Avoid_: static model, decoration

**Character**:
A `CAIHuman` placed in a level, built from its model template: model, skins, render styles and default attachments.
_Avoid_: NPC, enemy, AI (AI is behavior, not the character)

**Model template**:
The named entry in the model attribute file that says which model, skins, render styles and attachments a character uses.
_Avoid_: model bute, character definition

**Attachment**:
A model carried at a socket of a character or a prop: a character's weapon or disc, an archive bin's berries, a tank's turret.

**Hand-held model**:
The model a weapon shows in a character's hand (the weapon's `HHModel`, with its own skins and render styles); a weapon without one is hidden.
_Avoid_: weapon model, HH model, world model (that is level geometry)

**Berry**:
The model an archive bin shows for each item it holds, attached at one of the bin's item sockets; its look says the item's type (subroutine, permission set, or any other as a document).
_Avoid_: item (that is what the berry stands for), cube

**Child model**:
A model whose animations another model borrows (for example, a character's base animation set).
_Avoid_: animation file, anim pack

**Socket**:
A named point on a model's node where an attachment hangs.
_Avoid_: mount point, bone (a socket rides on a node but isn't one)

**Animation**:
A named, keyframed set of node transforms stored in a model or borrowed from a child model; a character's **idle** is the animation it plays when standing.
_Avoid_: clip (that is the viewer's container for it), anim pack

**Spawner template**:
A level object with `Template` set: kept only as a pattern for spawners and never created in the level itself.
_Avoid_: prefab, archetype

**MoveToFloor**:
The engine rule that drops an object straight down onto the floor below it when it starts higher than its own half-height.
_Avoid_: snapping, grounding

**Render style**:
A type-5 `.ltb` that describes how a model piece is drawn: blending, fullbright, environment (chrome) and passes.
_Avoid_: material, shader (those are the viewer's side)

### Lighting

**Light grid**:
The level's grid of precomputed light samples that the engine uses to light models.
_Avoid_: light probes, lightmap (lightmaps are for world geometry)

**Static light**:
A `Light`, `DirLight` or `ObjectLight` level object that lights models directly (LightObjects on, FastLightObjects off), on top of the light grid.
_Avoid_: dynamic light (that is a runtime light object, such as a muzzle flash)

**Sun**:
The level's `StaticSunLight`: a directional light on models, scaled by how much sky each model sees toward it.

### Living level

**Live at start**:
What a level does on its own from the moment it loads, with nothing from the player and no command: objects that start on (`StartOn`, `StartActive`).
_Avoid_: autoplay, idle (idle is a character animation)

**Ambient sound**:
A sound placed in a level that is live at start: a `SoundFX` that starts on, a `SoundButeFX`, or the sound of an active keyframer.
_Avoid_: background music (music is separate), SFX (too broad)

**Soundbute**:
A named entry in `attributes/soundbutes.txt` listing sound files (`Path0..N`), one picked at random per play. A sound name in a level is a soundbute if one has that name, else a file path.
_Avoid_: sound set, sound group

**World model**:
A piece of level geometry that belongs to an object instead of the static world, so it can move: doors, spinners, keyframer targets.
_Avoid_: model (that is an `.ltb`), brush

**Spinner**:
A `SpinningWorldModel`: a world model that keeps rotating at set speeds per axis.
_Avoid_: rotator (`RotatingWorldModel` is a different class, rotated on command)

**Keyframer**:
A `KeyFramer`: an object that moves its target objects (world models, props, characters) along a path of keys. Its keys can send it commands (pause, resume, reverse, go to a key), which is how a path waits or ping-pongs.
_Avoid_: animation (that is for models), mover, path follower

**Riding**:
Standing on a solid world model that moves or turns, and being carried with it: the player's position follows the world model's move and turns about its position; the view does not turn.
_Avoid_: platform physics, parenting, pushing (pushing the player sideways is `PushObjects`, not riding)

**Startup command**:
The command a level runs when it loads (`StartupCommand`). It goes through the command language, so it is behavior, not live at start.
_Avoid_: init script, level script
