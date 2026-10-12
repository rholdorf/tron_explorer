"""Ambient sounds live at start, as the viewer plays them: SoundFX that start on (ticket #24).

Engine rules (ltjs serversoundfx.cpp SoundFX::PlaySound, checked against retail object.lto 0x1022f58b;
docs/research/ambient-sound.md on branch research/ambient-sound):
- StartOn: InitialUpdate plays the sound at level start; nothing else starts one without a message.
- A file name plays that file at the object's position: Priority, Inner/OuterRadius as they are,
  Volume only when < 100 (else 100), PitchShift, Ambient (unpanned) or 3D, Loop. A non-looping one plays
  once and is killed after its duration. PlayAttached attaches it to the SoundFX itself, which never moves.
- Filter (EAX/DX8 filters, off in the user's cfg) and reverb are left out.
"""

CLASS = "SoundFX"


def sound_fx(objects):
    """SoundFX that start on, from a level's objects (dat85): name, position, sound file (the game's
    path), radii, volume (0-100), pitch, priority, ambient and loop (0/1)."""
    out = []
    for o in objects:
        p = o["props"]
        if o["class"] != CLASS or not p.get("StartOn", False) or not p.get("Sound", "").strip():
            continue
        out.append({"name": p.get("Name", ""), "pos": list(p.get("Pos", [0.0, 0.0, 0.0])),
                    "file": p.get("Sound", ""),
                    "inner": float(p.get("InnerRadius", 0.0)), "outer": float(p.get("OuterRadius", 0.0)),
                    "volume": min(int(p.get("Volume", 100)), 100), "pitch": float(p.get("PitchShift", 1.0)),
                    "priority": int(p.get("Priority", 0)), "ambient": int(bool(p.get("Ambient", True))),
                    "loop": int(bool(p.get("Loop", True)))})
    return out
