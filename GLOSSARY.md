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
A model whose animations another model borrows: the ones its `.ltb` lists (for example, a character's base animation set), and a character's own `ChildModel_1..3` files (its cutscene animations). A character plays an animation by name from its model first, then those, the first that has the name; the switch blends in over the animation's blend time, or cuts when it has none.
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

**Spawn name**:
The name a `spawn` or `spawnfrom` message gives the object a Spawner creates from its template. The object exists only after the spawn, so the viewer, which doesn't spawn, reports messages to it as `(spawned <class>)`.
_Avoid_: template name (a spawn can reuse a template's name, but templates themselves never exist)

**Dead target**:
A `msg` target that names nothing in the level, now or ever: renamed, misspelt, from another level or a missing prefab part. The engine drops the message without a word; the viewer counts it under `(no object)` and never matches a close name.
_Avoid_: broken link, missing object (a spawned object is missing only until its spawn)

**Trigger**:
A level volume that runs its commands when the player enters it or when it receives `trigger`; it can be locked and limited to a number of activations.
_Avoid_: zone, sensor, switch (a switch is a world model the player uses)

**Relay**:
An object that exists only to pass commands on: triggers fired by message, event counters, command objects and groups.
_Avoid_: logic object, controller

**Command object**:
A `CommandObject`: a timeline that runs its commands at set times after it is started.
_Avoid_: sequence, cutscene (cutscenes also need cameras and dialogue)

**Cutscene**:
A scene the level plays through a dialogue whose lines, as they are spoken, cut and move scene cameras and make actors play named animations or jump to places. While a scene camera is on the player can't move, and may skip the scene where the camera allows it. Cutscenes run in the `*cin` levels and inside ordinary levels alike.
_Avoid_: cinematic alone (the `*cin` levels are only some of them), movie (the game's Bink videos are another thing)

**Dialogue**:
A placed object that speaks up to twenty lines in turn, each a game string read by a named speaker after its own delay, each able to run a command as it starts; commands run when it starts, finishes and is cleaned up.
_Avoid_: conversation, transmission (a one-line HUD message), subtitle (only the text of a line)

**Scene camera**:
A placed `Camera` the view switches to while it is on: it goes to named camera points and changes its field of view on command.
_Avoid_: camera alone (the player has one too), camera point (a place a scene camera goes to)

**Letterbox**:
The black bars over the top and bottom of the screen while a cinematic (`Type 1`) scene camera is the view, fading in and out.
_Avoid_: widescreen, bars

**Skip**:
The skip key (Space) during a scene: every scene camera that is on and can be skipped runs its cleanup command and turns off, and the cleanup ends the rest of the scene.
_Avoid_: cancel, abort (`ABORT` is a command verb)

**Free flight**:
The explorer's key (V) during a scene: the view leaves the scene camera and flies from where it looked while the scene runs on, until the key again or the scene's end gives the view back.
_Avoid_: noclip (the player's own flying), free camera

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
The player's action on the usable object in front of them (key E in the viewer): a door, a switch, a binary bit or a security rezzer.
_Avoid_: activate (that is also a message), interact

**Binary bit**:
A `BinaryBit`: a small model the player uses as a two-state switch. Its byte shows blue while powered down, amber for yes and red for no; using it powers it up or flips it, the matching shape growing out of the byte.
_Avoid_: bit alone (it is also a data bit), byte

**Security rezzer**:
A `SecRezzer`: a model that spawns guards when an AI turns it on; the player can only disable it by use, folding its panels shut.
_Avoid_: spawner (that is the `Spawner` class), rezzer alone

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

**Mission text**:
The orange block a `missiontext <id>` message types into the upper left, letter by letter, then holds and fades; a new one replaces it at once.
_Avoid_: objective (the HUD's objective list is another thing), subtitle (that's dialogue)

**Transmission**:
A one-line message a `transmission <id>` message shows at the top centre, light blue, fading in and out; at most two show, the newest lowest.
_Avoid_: radio message, announcement alone (the announcement queue is where Tron draws it, not the message)

**Game string**:
A text in the game's string table (`cres.dll`) that a message names by number; it may carry `<color r g b>` tags that recolour the rest of the text.
_Avoid_: localized string, resource text

### Effects

**Effect group**:
A named ClientFX effect from the game's `.fxf` files: a loop of `Phase` ms holding fx keys, each an effect type (particle system, sprite, effect model, effect sound, chunk, lightning, trail…) with a start, an end, props and colour/scale keys. Names match case-insensitively; the first group loaded wins.
_Avoid_: FX (too broad), particle effect (one type among several), FxED group (the editor's name)

**Fx key**:
One effect inside an effect group, `Type;label` in the file: it runs from its start to its end in each phase, its look driven by `Ck` (colour, alpha stored as transparency) and `Sk` (scale) keys.
_Avoid_: effect (ambiguous with the group), keyframe (that is a keyframer's)

**SpecialFX**:
The level object that plays one effect group at its own position, switched by `ON`/`OFF`. With `Loop` it keeps one instance and shuts it down on OFF; without, each ON fires a new one-shot that plays to its end. HIDDEN/VISIBLE don't touch it.
_Avoid_: ClientFX (that is the effect system, also fired by weapons and characters)

**Group instance**:
One running copy of an effect group, with one effect per fx key created up front. A looping instance follows its SpecialFX and restarts its keys every phase. A one-shot instance stays where it started, plays each key once and ends with its last effect.
_Avoid_: effect (that is one key's part of it), emitter

**Effect type**:
What an fx key is (`ParticleSystem`, `Sprite`, `LTBModel`…), and the viewer's plug-in that draws it. A key whose type has no plug-in yet is still timed but shows nothing; the L report counts these keys as `FX <type> (NO LOOK)`.
_Avoid_: fx class, effect kind

**Effect model**:
An `LTBModel` fx key's model: drawn with its own skins and render styles like a placed model (so it glows through `[GlowRSMap]`), faced and spun by its key, faded and tinted by its colour keys, and playing its clip (its `AniName`, else animation 0) once over and again. A smooth shutdown waits for the clip to end.
_Avoid_: fx model, prop (a prop is a placed object)

**Effect sound**:
A `PlaySound` fx key's sound: it starts on the key's first update and is cut when the key ends, however long the wave, so a looping group plays it again each phase and only a key covering the whole phase plays on unbroken. Heard by the placed sounds' rules (its own radii, volume, priority), positioned unless `PlayLocal`.
_Avoid_: fx sound, ambient sound (a placed SoundFX)

**Chunk**:
An `LTBBouncyChunk` fx key's model: launched along its key's direction, pulled by its gravity, bounced off the world at 70% speed, full bright, coloured and scaled by its keys. It is its own object, so it stands from the moment its group starts until its key ends, whether or not its key has begun. Effects linked to it ride along (m02-01's invisible carriers drag the bike's pieces).
_Avoid_: debris (only m05-01's are), gib, bouncy chunk

**Effect sprite**:
A `Sprite` fx key's sprite: drawn like a ScaleSprite (texture size times its scale, `.spr` frames looping) but additive and unlit, coloured and sized by its keys, fading to black in the fog, its frames starting over each time its key starts. It faces the camera, or with another facing or a spin lies in its parent's axes turned to its normal. It vanishes the moment its key ends; a looping group that starts it again gets it back lit, unbiased and facing the camera (the engine only sets it visible again).
_Avoid_: sprite fx, ScaleSprite (a placed object)

**Lightning bolt**:
One of a `LightningFX` key's bolts: a jagged strip from where the effect is to a node or socket of the effect model it is linked to (its attractors), or to a random point within its radius, made anew every short delay and left where it was made, jittered each frame, camera-facing, coloured and widened by its keys over its own short life. A bolt with nowhere to go (attractors its parent doesn't have, no radius) has no length and shows nothing, as `CHAR_HogEnergySuck`'s placed objects in the game.
_Avoid_: arc, beam (m10-02's beams are world geometry)

**Trail**:
A `PolyTrail` key's ribbon: points dropped where its effect goes every interval, the newest following it, each fading by the key's colour keys over its own life and dropped when old; camera-facing, its texture running along it by distance. When its group shuts down it stops growing and fades out point by point.
_Avoid_: poly tube (ltjs's class name), streak

**Sprite system**:
A `SpriteSystem` key's sprites: bursts of camera-facing quads made about where its effect is and left there, each stretched by its key, coloured and sized by its keys over its own life, drifting by their velocity and gravity. Only the datawraith's return in m09-03cin has one: tall streaks that rise white and turn purple.
_Avoid_: particle system (a different type), effect sprite (one sprite that moves with its effect)

**Camera jitter**:
A `CamJitter` key's shake: every update it moves the camera a random amount up to its scale on each axis, full within its inner radius of the effect and fading to nothing at its outer radius. The player camera puts the camera back each frame, so it only shakes the view (m10-04's stumble, Ma3a's bouncing sphere, the lasers in m10-03cin).
_Avoid_: screen shake, camera shake (the game's own word for its other shakes)

**Dynamic light**:
A `DynaLight` key's light: a point light where its effect is, coloured by its keys (flickering, with Flicker), its radius its scale. In Tron it lights models and lit sprites but never the world (the game leaves dynamic world lighting off). A model gets it like the other lights in its four-light list, so where the level already lights a model fully (Alan by the digitizer in the intro) it adds nothing to see.
_Avoid_: light group (placed lights switched together), DynaLight object

**ScaleSprite**:
A placed object that is one sprite (`.spr`, its frames looping at the file's rate): sized by its texture times its scale, facing the camera or lying in its own axes (rotatable), lit by the level, switched by ON/OFF and HIDDEN/VISIBLE alike. m07's status lights are ScaleSprites in threes (on, off, no power) of which only one starts on. With `CreateSprite` it also has a lens flare: a second sprite that grows as the camera looks straight at it (Ma3a's).
_Avoid_: sprite (an effect's Sprite is a different thing), billboard (only some face the camera), decal

**Chained group**:
The effect group a `CreateFX` key names: started as an instance of its own the moment its parent group starts (not at the key's start time), at the parent's place, then left alone: shutting the parent down doesn't reach it, and a looping parent never starts it again.
_Avoid_: child effect, sub-effect

**Smooth shutdown**:
How an effect ends when its key ends or its instance shuts down: smooth lets it finish (particles drain), otherwise it is cut at once. Both the key's `SmoothShutDown` and the SpecialFX's `SmoothShutdown` must allow it.
_Avoid_: fade out (a smooth shutdown doesn't fade by itself)

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

**Overlay**:
A world triangle lying just in front of another texture's surface and drawn over it: a decal. A property of the triangle, not of its texture; the same texture can be an overlay in one place and a surface in another.
_Avoid_: decal (fine in speech, but the bench says overlay), detail (a texture folder name)

**Glow**:
The share of a fullbright texture that lights itself, given by its alpha channel: where alpha is high the texel ignores the level's lighting and feeds the glow. A texture that isn't fullbright has no glow.
_Avoid_: emissive (that is the surface family of Additive world models), self-illumination

**Reference-panel capture**:
A render of a level with its original textures and lightmaps from one of mus-y-sinak's reference-panel camera poses, shown beside the film frame and mus-y-sinak's own render of the same shot.
_Avoid_: screenshot (any capture), shot (mus-y-sinak's name for the pose itself)

**Bench glTF**:
One level's world geometry as drawn at start, as a `.glb` in metres, for mus-y-sinak to try its shaders on: one primitive per surface family, texture, animated and overlay, each carrying its render roles (blend, overlay, glow, light, colour), plus the start point; written under `export/bench/`, never committed.
_Avoid_: level export (that is the viewer's `level.bin`)

**Level kind**:
Interior (at least 70% of the reachable floor has a ceiling), open (less, or past the flood cap) or minor (under 500 m²); only interior levels feed the baseline.
