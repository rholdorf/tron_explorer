"""Keyframers (KeyFramer) and the targets they move along their path: the ones that start active (ticket
#26) and the ones a message starts later (ticket #33).

Format and motion rules: docs/research/keyframer-paths.md (branch research/keyframer-paths), from ltjs
world_blind_object_data.cpp and keyframer.cpp, checked byte-for-byte against the retail levels. The
messages a keyframer handles and its key commands run in the viewer (KeyframerMotion.cs, Commands.cs;
tools/tests/test_keyframer_motion.py).
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


def test_keyframers_carry_their_settings_targets_and_keys_with_their_commands_as_text(world):
    # ADR 0001: a key's command ships as the level's text; the viewer runs it when the key is reached
    # (KeyFramer::ProcessCurrentKey: g_pCmdMgr->Process(cmd, keyframer, keyframer)).
    import keyframer
    w = world("retailsingleplayer/m05-02")
    kf = {k["name"]: k for k in keyframer.keyframers(w.objects, w.blind)}["target01kf"]
    obj = next(o["props"] for o in w.objects if o["props"].get("Name") == "target01kf")
    assert w.objects[kf["obj"]]["props"] is obj
    assert kf["targets"] == [n for n in obj["ObjectName"].split(";") if n]
    assert kf["baseKeyName"] == obj["BaseKeyName"]
    assert (kf["startActive"], kf["startPaused"]) == (obj["StartActive"], obj["StartPaused"])
    assert kf["looping"] == obj["Looping"] and kf["totalPathTime"] == obj["TotalPathTime"] == 0.0
    assert len(kf["keys"]) == 13
    assert kf["keys"][0]["command"] == "msg target01kf forward"
    assert kf["keys"][12]["command"] == "msg target01kf reverse"
    # Empty parts are left out (m07-02 alone has 79,102 keys): no command, no Bezier controls.
    assert set(kf["keys"][5]) == {"pos", "pyr", "time"}
    assert set(kf["keys"][0]) == {"pos", "pyr", "time", "command"}


def test_key_numbers_are_the_shortest_text_that_reads_back_as_the_same_float32(world):
    # The keys' f32 values and the running time (summed in f32 by the viewer's reading) are written as the
    # shortest decimal that parses back to the same float32, e.g. -1.29878 rather than -1.2987799644470215.
    import struct
    import keyframer
    w = world("retailsingleplayer/m07-02")
    kfs = keyframer.keyframers(w.objects, w.blind)
    raw = keyframer.read_keys(w.blind[int(w.objects[kfs[0]["obj"]]["props"]["KeyDataIndex"])][1])
    f32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]   # noqa: E731
    for k, r in zip(kfs[0]["keys"], raw):
        assert [f32(v) for v in k["pos"] + k["pyr"]] == [f32(v) for v in r["pos"] + r["pyr"]]
        assert f32(k["time"]) == f32(r["time"])
        assert all(len(repr(v)) <= 15 for v in k["pos"] + k["pyr"])


def test_wavetype_and_active_sound(world):
    import keyframer
    found = [k for level in single_player_levels() for k in keyframer.keyframers(world(level).objects,
                                                                                   world(level).blind)]
    live = [k for k in found if k["startActive"] and not k["startPaused"]]
    assert sum(k["wave"] == 1 for k in live) == 9        # Sine (Linear 0, Sine 1, SlowOff 2, SlowOn 3)
    sounds = [k for k in live if k["activeSound"]]
    assert len(sounds) == 30
    assert all(k["soundRadius"] > 0 for k in sounds)


def test_keyframers_that_start_inactive_or_paused_are_exported_waiting_for_a_message(world):
    # KeyFramer::Update's first pass: GoActive if StartActive or StartPaused, then Pause for StartPaused
    # (RESUME continues it); one that is neither waits for ON.
    import keyframer
    w = world("retailsingleplayer/m03-01")
    found = keyframer.keyframers(w.objects, w.blind)
    assert len(found) == 33
    port = next(k for k in found if k["name"] == "port01kf")
    assert port["startActive"] and port["startPaused"]
    assert sum(not k["startActive"] and not k["startPaused"] for k in found) == 25


def test_single_player_levels_have_2135_keyframers_138_live(world):
    # 147 StartActive, 9 of them also StartPaused (m03-01's port/display keyframers, m08-01 Finder07KF).
    import keyframer
    found = [k for level in single_player_levels()
             for k in keyframer.keyframers(world(level).objects, world(level).blind)]
    assert len(found) == 2135
    assert len([k for k in found if k["startActive"] and not k["startPaused"]]) == 138
    assert all(k["keys"] for k in found)


def test_level_json_lists_the_keyframers(extracted, tmp_path):
    import json
    import export_level
    import export_models
    name = "retailsingleplayer/m05-02"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] == export_level.FORMAT_VERSION == 22
    kfs = {k["name"]: k for k in meta["keyframers"]}
    assert len(kfs) == 90
    world_models = {wm["name"] for wm in meta["worldModels"]}
    assert set(kfs["target01kf"]["targets"]) <= world_models
