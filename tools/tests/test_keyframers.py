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


# Key commands go through the command manager (g_pCmdMgr->Process). Only messages to the keyframer itself
# are part of how its path runs; messages to any other object belong to the behavior map.
def test_a_key_command_keeps_only_the_messages_to_its_own_keyframer():
    import keyframer
    cmds = keyframer.self_commands("msg CubeWM03 (hidden 0); msg CubeWM03KF PAUSE; msg Track02Control TRIGGER",
                                   "CubeWM03KF", "Cube03_Key", 4)
    assert cmds == [{"verb": "PAUSE", "delay": 0.0, "key": -1}]


def test_self_messages_match_the_name_in_any_case_and_take_parenthesized_arguments():
    import keyframer
    assert keyframer.self_commands("msg port01kf pause;msg com01use02enabler unlock", "Port01KF", "k", 5) == [
        {"verb": "PAUSE", "delay": 0.0, "key": -1}]
    assert keyframer.self_commands("msg plat1framer (resume)", "plat1framer", "k", 3) == [
        {"verb": "RESUME", "delay": 0.0, "key": -1}]


def test_a_delayed_self_message_runs_that_many_seconds_later():
    import keyframer
    cmds = keyframer.self_commands("msg plat1framer (pause);delay 2 (msg plat1framer (resume))",
                                   "plat1framer", "plat1key", 3)
    assert cmds == [{"verb": "PAUSE", "delay": 0.0, "key": -1}, {"verb": "RESUME", "delay": 2.0, "key": -1}]
    assert keyframer.self_commands("delay .5 (msg DC01.DCube01KF RESUME)", "DC01.DCube01KF", "k", 4) == [
        {"verb": "RESUME", "delay": 0.5, "key": -1}]


def test_reverse_is_backward():
    import keyframer
    assert keyframer.self_commands("msg TranslucentKF reverse", "TranslucentKF", "k", 5) == [
        {"verb": "BACKWARD", "delay": 0.0, "key": -1}]


def test_goto_names_a_key_by_base_name_and_index():
    # KeyFramer::FindKey: the base name (any case), then "0", "01".."09", "10".. by key index.
    import keyframer
    assert keyframer.self_commands("msg AFinder05KF (Goto AFinder05Key02)", "AFinder05KF", "AFinder05Key", 15) == [
        {"verb": "GOTO", "delay": 0.0, "key": 2}]
    assert keyframer.self_commands("msg K (goto basekey12)", "K", "BaseKey", 15) == [
        {"verb": "GOTO", "delay": 0.0, "key": 12}]
    # A key that isn't there: the engine prints an error and does nothing.
    assert keyframer.self_commands("msg K (goto BaseKey2)", "K", "BaseKey", 15) == []
    assert keyframer.self_commands("msg K (goto BaseKey20)", "K", "BaseKey", 15) == []


def test_messages_the_keyframer_does_not_handle_are_left_out():
    import keyframer
    assert keyframer.self_commands("msg K TRIGGER; msg K (hidden 1); ", "K", "k", 3) == []
