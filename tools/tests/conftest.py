import glob
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

EXTRACTED = os.environ.get("TRON_EXTRACTED", "/Users/rui/src/pg/tron_explorer/extracted")


@pytest.fixture(scope="session")
def extracted():
    if not os.path.isdir(os.path.join(EXTRACTED, "worlds")):
        pytest.skip(f"game data not found at {EXTRACTED} (set TRON_EXTRACTED)")
    return EXTRACTED


@pytest.fixture(scope="session")
def world(extracted):
    """Loads (and caches) a level by its path under worlds/, without .dat."""
    import dat85
    cache = {}

    def load(name):
        if name not in cache:
            cache[name] = dat85.load(os.path.join(extracted, "worlds", name + ".dat"))
        return cache[name]
    return load


PROP = re.compile(r"(?i)((?<!custom)(command|cmd)\d*$|^EventT\d+E\d+$|^(Initial|ActivateOn|ActivateOff|"
                  r"OnWithdraw\d*|OnActivate|OnOptimize)$)")


def level_commands(w):
    """(class, property, command string) for every command string in a loaded level."""
    import keyframer
    out = []
    for o in w.objects:
        for k, v in o["props"].items():
            if not isinstance(v, str) or not PROP.search(k):
                continue
            if re.fullmatch(r"(?i)EventT\d+E\d+", k):
                v = v.split("|", 1)[1] if "|" in v else ""
            if v.strip() and v.strip() != "<none>" and not re.fullmatch(r"[\d.\s-]+", v):
                out.append((o["class"], k, v))
        if o["class"] == "KeyFramer":
            index = o["props"].get("KeyDataIndex", -1.0)
            if 0 <= index < len(w.blind):
                out += [("KeyFramer", "key", k["command"]) for k in keyframer.read_keys(w.blind[int(index)][1])
                        if k["command"].strip()]
    return out


@pytest.fixture(scope="session")
def corpus(extracted):
    """Every command string in the 38 single-player levels: (level, class, property, string). Every
    non-empty string property the engine reads as a command (a name ending in Command / Cmd with an
    optional number, not CustomCmd*; CommandObject events EventTnEm, the part after '|'; AI Initial /
    ActivateOn / ActivateOff; ArchiveBin OnWithdrawN; Optimizer OnActivate / OnOptimize), and every
    KeyFramer key command. "<none>" (the editor's empty value) and numbers aren't commands."""
    import dat85
    out = []
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        name = os.path.basename(f)[:-4]
        out += [(name, *c) for c in level_commands(dat85.load(f))]
    return out
