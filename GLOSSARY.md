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
A model carried at a socket of a character, such as a weapon or a disc.

**Child model**:
A model whose animations another model borrows (for example, a character's base animation set).
_Avoid_: animation file, anim pack

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
