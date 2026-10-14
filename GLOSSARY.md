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
The command a level runs when it loads (`StartupCommand`), on the level's first frame. It goes through the command language, so it is behavior, not live at start. The start point's command (`GameStartPoint` `Command`) runs right after it, on the player's first update, once per level.
_Avoid_: init script, level script

### Behavior

**Command**:
A string in the level's command language that the engine runs: `msg`, `delay`, `loop`, `rand` and the like, nested with parentheses and separated by `;`.
_Avoid_: script, event (an event is a moment that runs a command)

**Message**:
What a `msg` command delivers to one or more named objects, such as `on`, `off`, `trigger`, `hidden 1` or `lock`; each class decides what it does with it.
_Avoid_: event, signal, command (the command is the whole `msg` line)

**Trigger**:
A level volume that runs its commands when the player enters it or when it receives `trigger`; it can be locked and limited to a number of activations.
_Avoid_: zone, sensor, switch (a switch is a world model the player uses)

**Relay**:
An object that exists only to pass commands on: triggers fired by message, event counters, command objects and groups.
_Avoid_: logic object, controller

**Command object**:
A `CommandObject`: a timeline that runs its commands at set times after it is started.
_Avoid_: sequence, cutscene (cutscenes also need cameras and dialogue)

**Event counter**:
An `EventCounter`: a count that `inc` and `dec` messages step, running the command set for each value it reaches; Tron's `reset` puts it back to its starting value.
_Avoid_: counter variable (the command language's variables are something else)

**Door**:
A `SlidingDoor` or `RotatingDoor`: a world model that opens and closes on use or on messages, playing a sound and running a command as it starts and finishes each move. Lifts are doors.
_Avoid_: gate, elevator (an elevator is a door that moves up)

**Switch**:
A `SlidingSwitch` or `RotatingSwitch`: a world model the player uses to run commands, turning on and off like a door (most don't move).
_Avoid_: button, lever, trigger (a trigger is a volume)

**Use**:
The player's action on the door or switch in front of them (key E in the viewer).
_Avoid_: activate (that is also a message), interact

**Permission set**:
One of eight keys (`Key1`..`Key8`) a door, switch or other object can require; the player gets them from archive bins or scripts. The viewer grants all of them.
_Avoid_: keycard, access level

**Teleport**:
The player's move to a `TeleportPoint` on a `teleport` message: on its next update, facing the point's pitch and yaw, dropped to the floor, stopped.
_Avoid_: warp, respawn (the viewer's R/T keys pick a start point, not a teleport)

**Screen fade**:
The black overlay `fadein`/`fadeout` ease over a time; after a fade-out the screen stays black until a fade-in.
_Avoid_: blackout, transition

**Fade safety net**:
The viewer's own fade-in (not the game's) after 10 s of black with no fade-in pending, for fade-ins that come from systems the viewer doesn't run (cameras, dialogue, the next level); counted in the unhandled report as `SAFETYNET Player FADEIN`.
_Avoid_: auto fade-in (the game has none)

**Render variable**:
A client console variable the renderer reads every frame (fog color and distances, FarZ, sky and glow fog, glow filter). Ramps and sines move it; a WorldProperties message copies every world variable back from the level's values.
_Avoid_: cvar alone (most console variables aren't render variables), world property (that's the server's copy)

### Style baseline

**Style baseline**:
The levels measured as numbers (rooms, corridors, their graph, surface mix, objects, light) for the sibling project mus-y-sinak: `tools/baseline.py`, `docs/research/style-baseline.json`.
_Avoid_: level stats, rules

**Reachable floor**:
The floor cells a walking player can get to, flooded from the start points, exit triggers and AI volumes over the physics BSP.
_Avoid_: navmesh, walkable area (AI volumes are the designers' own, partial, mark of it)

**Room**:
A part of the reachable floor wide enough to hold a core (about 5.2 m across), grown back to its walls; derived, not placed by the designers.
_Avoid_: AI region (an AI territory), area, zone

**Corridor**:
Reachable floor left over between rooms: narrower than a room anywhere along it.
_Avoid_: hallway, passage (an opening between two rooms is part of a room)

**Surface family**:
The kind of surface a world triangle is: floor-interior, floor-exterior, wall, ceiling, glass (a Translucent world model) or emissive (an Additive one).
_Avoid_: material type, texture type

**Bench glTF**:
One level's drawn world geometry as a `.glb` in metres, one primitive per surface family plus the start point, for mus-y-sinak to try its shaders on; written under `export/bench/`, never committed.
_Avoid_: level export (that is the viewer's `level.bin`)

**Level kind**:
Interior (at least 70% of the reachable floor has a ceiling), open (less, or past the flood cap) or minor (under 500 m²); only interior levels feed the baseline.
