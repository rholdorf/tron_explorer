"""Keyframers (KeyFramer) that start active and move their targets along their path (ticket #26).

Format and motion rules: docs/research/keyframer-paths.md (branch research/keyframer-paths), from ltjs
world_blind_object_data.cpp and keyframer.cpp, checked byte-for-byte against the retail levels.
"""
import glob
import os

import pytest

import dat85
from conftest import EXTRACTED


def single_player_levels():
    root = os.path.join(EXTRACTED, "worlds")
    return [os.path.relpath(p, root)[:-4]
            for p in sorted(glob.glob(os.path.join(root, "retailsingleplayer", "*.dat")))]


def test_blind_object_data_is_one_keyframer_chunk_per_keyframer(world):
    w = world("retailsingleplayer/m01-01")
    n_keyframers = sum(o["class"] == "KeyFramer" for o in w.objects)
    assert len(w.blind) == n_keyframers > 0
    assert all(cid == dat85.KEYFRAMER_BLINDOBJECTID for cid, _ in w.blind)


def test_a_path_is_its_keys_with_commands_and_running_time(world):
    import keyframer
    w = world("retailsingleplayer/m05-02")
    kf = next(o for o in w.objects if o["props"].get("Name") == "target01kf")
    keys = keyframer.read_keys(w.blind[int(kf["props"]["KeyDataIndex"])][1])
    assert len(keys) == 13
    assert keys[0]["command"] == "msg target01kf forward"
    assert keys[12]["command"] == "msg target01kf reverse"
    assert keys[1]["command"] == "" and keys[1]["sound"] == ""
    times = [k["time"] for k in keys]
    assert times == sorted(times)        # running sum of the time deltas


def test_every_keyframer_path_parses_to_the_end_of_its_chunk(world):
    import keyframer
    keys = 0
    for level in single_player_levels():
        w = world(level)
        for o in w.objects:
            if o["class"] == "KeyFramer":
                keys += len(keyframer.read_keys(w.blind[int(o["props"]["KeyDataIndex"])][1]))
    assert keys == 179216
