"""Sound files: which files a level's sound names play, and their export as 16-bit PCM WAV.

A sound name (SoundFX Sound, SoundButeFX SoundBute, KeyFramer ActiveSound, the state sounds of doors,
switches and moving world models) is looked up as a soundbute
first and taken as a file path otherwise (CGameSoundMgr FillPSIFromButeOrParams). A soundbute plays one
of its Path0..N files; missing keys come from its Parent chain (CHierarchicalButeMgr).
"""
import functools
import os
import shutil
import struct
import subprocess

import butes

WAVE_FORMAT_PCM = 1


def wav_codec(path):
    """The fmt chunk's format tag of a RIFF WAVE file (1 = PCM, 0x55 = MPEG layer 3)."""
    with open(path, "rb") as f:
        riff = f.read(12)
        if riff[:4] != b"RIFF" or riff[8:] != b"WAVE":
            raise ValueError(f"{path}: not a RIFF WAVE file")
        while True:
            head = f.read(8)
            if len(head) < 8:
                raise ValueError(f"{path}: no fmt chunk")
            cid, n = head[:4], struct.unpack("<I", head[4:])[0]
            if cid == b"fmt ":
                return struct.unpack("<H", f.read(2))[0]
            f.seek(n + (n & 1), 1)


def export_file(extracted, rel, out_root):
    """Writes one sound file to <out_root>/sounds/<rel> as 16-bit PCM WAV and returns its path, or None if
    the game data doesn't have it. PCM files are copied as they are (their cue/LIST chunks are kept for
    loop regions); MP3-in-WAV files are decoded with macOS's afconvert, so the viewer only reads PCM.
    Skips a file already exported from the same source."""
    src = os.path.join(extracted, rel)
    if not os.path.isfile(src):
        return None
    dst = os.path.join(out_root, "sounds", *rel.split("/"))
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if wav_codec(src) == WAVE_FORMAT_PCM:
        shutil.copyfile(src, dst)
    else:
        tmp = dst + ".tmp"
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", src, tmp], check=True, capture_output=True)
        os.replace(tmp, dst)
    return dst


# ActiveWorldModel's state sounds (ReadProps), and a door's names for them (Door::ReadProps, which
# override the generic ones when set)
AWM_SOUNDS = ("PowerOnSound", "OnSound", "PowerOffSound", "OffSound", "LockedSound")
DOOR_SOUNDS = ("OpeningSound", "OpenSound", "ClosingSound", "ClosedSound")

# The sound name properties of each class that plays one, in the order they're listed
SOUND_PROPS = {"SoundFX": ("Sound",), "SoundButeFX": ("SoundBute",), "KeyFramer": ("ActiveSound",)}
for _cls in ("SlidingWorldModel", "RotatingWorldModel", "SlidingSwitch", "RotatingSwitch"):
    SOUND_PROPS[_cls] = AWM_SOUNDS
for _cls in ("SlidingDoor", "RotatingDoor"):
    SOUND_PROPS[_cls] = DOOR_SOUNDS + AWM_SOUNDS


def sound_names(objects):
    """The sound names a level's objects (level.json form) play, live at start or not, in object order."""
    out = []
    for o in objects:
        keys = SOUND_PROPS.get(o["cls"], ())
        props = {p["k"]: p["s"] for p in o["props"] if p["t"] == "s"}
        out.extend(name for name in (props.get(k, "") for k in keys) if name.strip())
    return out


class SoundButes:
    def __init__(self, extracted):
        self.sections = {k.lower(): v for k, v in
                         butes.load(os.path.join(extracted, "attributes", "soundbutes.txt")).items()}

    def _chain(self, name):
        """The soundbute's section, then its Parent's, and so on."""
        seen = set()
        while name and name.lower() in self.sections and name.lower() not in seen:
            seen.add(name.lower())
            s = self.sections[name.lower()]
            yield s
            name = s.get("parent")

    def _paths(self, name):
        return next((p for p in (butes.indexed(s, "path") for s in self._chain(name)) if p), [])

    def get(self, name, key, default=None):
        """A soundbute's key (lower case), inherited from its Parent chain when it doesn't set it."""
        return next((s[key] for s in self._chain(name.strip()) if key in s), default)

    def is_soundbute(self, name):
        return name.strip().lower() in self.sections

    def files(self, name):
        """The files a sound name can play, as extracted paths (forward slashes, lower case)."""
        if self.is_soundbute(name):
            return [butes.norm(p) for p in self._paths(name.strip())]
        return [butes.norm(name)]


@functools.lru_cache(maxsize=None)
def soundbutes(extracted):
    """The game's soundbutes, read once per game data directory."""
    return SoundButes(extracted)


def export_sounds(extracted, level_objects, out_root, extra=None):
    """Exports every file the levels' sound names can play. level_objects: {level: objects (level.json
    form)}; extra: {level: more sound names} (the soundbutes its models' clips play). Returns (exported
    files, sorted; {missing file: [levels naming it]})."""
    bute = soundbutes(extracted)
    users = {}
    for level, objects in level_objects.items():
        for name in sound_names(objects) + list((extra or {}).get(level, [])):
            for rel in bute.files(name):
                lv = users.setdefault(rel, [])
                if level not in lv:
                    lv.append(level)
    exported, missing = [], {}
    for rel in sorted(users):
        if export_file(extracted, rel, out_root):
            exported.append(rel)
        else:
            missing[rel] = users[rel]
    return exported, missing
