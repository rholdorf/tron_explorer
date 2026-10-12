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
