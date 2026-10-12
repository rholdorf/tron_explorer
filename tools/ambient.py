"""Placed sounds, as the viewer plays them: SoundFX (ticket #24) and SoundButeFX (ticket #25), the ones
live at start and, since ticket #33, the ones a message (ON, OFF, TOGGLE...) switches on later.

Engine rules (ltjs serversoundfx.cpp SoundFX::PlaySound, checked against retail object.lto 0x1022f58b;
docs/research/ambient-sound.md on branch research/ambient-sound):
- StartOn: InitialUpdate plays the sound at level start; nothing else starts one without a message.
- A file name plays that file at the object's position: Priority, Inner/OuterRadius as they are,
  Volume only when < 100 (else 100), PitchShift, Ambient (unpanned) or 3D, Loop. A non-looping one plays
  once and is killed after its duration. PlayAttached attaches it to the SoundFX itself, which never moves.
- A soundbute name plays one of the soundbute's files (the sound manager picks one per play).
- Filter (EAX/DX8 filters, off in the user's cfg) and reverb are left out.
"""

CLASS = "SoundFX"
BUTE_CLASS = "SoundButeFX"
INNER_RADIUS_PERCENT = 0.25   # CGameSoundMgr SMGR_DEFAULT_INNERRADIUSPERCENT


def sound_fx(objects, soundbutes=None):
    """Every SoundFX that names a sound, from a level's objects (dat85): name, obj (its index in the
    level's objects, its command-manager id), startOn, position, sound file (the game's path), files
    (the soundbute's files when the name is one, else empty), radii, volume (0-100), pitch, priority,
    ambient and loop (0/1)."""
    out = []
    for i, o in enumerate(objects):
        p = o["props"]
        sound = p.get("Sound", "")
        if o["class"] != CLASS or not sound.strip():
            continue
        bute = soundbutes is not None and soundbutes.is_soundbute(sound)
        out.append({"name": p.get("Name", ""), "obj": i, "startOn": bool(p.get("StartOn", False)),
                    "pos": list(p.get("Pos", [0.0, 0.0, 0.0])), "file": sound,
                    "files": soundbutes.files(sound) if bute else [],
                    "inner": float(p.get("InnerRadius", 0.0)), "outer": float(p.get("OuterRadius", 0.0)),
                    "volume": min(int(p.get("Volume", 100)), 100), "pitch": float(p.get("PitchShift", 1.0)),
                    "priority": int(p.get("Priority", 0)), "ambient": int(bool(p.get("Ambient", True))),
                    "loop": int(bool(p.get("Loop", True)))})
    return out


def sound_bute_fx(objects, soundbutes):
    """SoundButeFX, from a level's objects (dat85): name, obj (its index in the level's objects, its
    command-manager id), startOn, position, the files its soundbute picks from (extracted paths), radii,
    MinDelay/MaxDelay (s) and ambient (0/1).

    Engine rules (ltjs soundbutefx.cpp SoundButeFX::Update, retail object.lto 0x1022c1d0; research §7):
    the first sound plays at level start; the next one at max(start of the last + U(MinDelay, MaxDelay),
    end of the last) (WaitUntilFinished, set on every one); each play a uniformly random PathN (no
    Weight keys in Tron), not looping, at volume 100, pitch 1 and priority 0 whatever the soundbute says;
    Ambient unpanned, else 3D. NumPlays is -1 (forever) on every one. Radii as PlaySoundFromPos takes
    them: an outer radius with no inner one gets 0.25 x outer, and a radius left at -1 is the
    soundbute's. A name that isn't a soundbute (none in the game data) or has no files ([None]) is
    skipped.
    """
    out = []
    for i, o in enumerate(objects):
        p = o["props"]
        bute = p.get("SoundBute", "").strip()
        if o["class"] != BUTE_CLASS or not soundbutes.is_soundbute(bute):
            continue
        files = soundbutes.files(bute)
        if not files:   # the empty [None] soundbute
            continue
        outer, inner = float(p.get("OuterRadius", -1.0)), float(p.get("InnerRadius", -1.0))
        if outer > 0 and inner < 0:
            inner = outer * INNER_RADIUS_PERCENT
        out.append({"name": p.get("Name", ""), "obj": i, "startOn": bool(p.get("StartOn", True)),
                    "pos": list(p.get("Pos", [0.0, 0.0, 0.0])), "files": files,
                    "inner": inner if inner > -1 else float(soundbutes.get(bute, "innerradius", 0.0)),
                    "outer": outer if outer > -1 else float(soundbutes.get(bute, "outerradius", 0.0)),
                    "minDelay": float(p.get("MinDelay", 0.0)), "maxDelay": float(p.get("MaxDelay", 0.0)),
                    "ambient": int(bool(p.get("Ambient", True)))})
    return out
