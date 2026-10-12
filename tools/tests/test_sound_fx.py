"""SoundFX, as the exporter hands them to the viewer: the ones that start on (ticket #24) and the ones a
message turns on later (ticket #33).

Engine rules: SoundFX::PlaySound (ltjs serversoundfx.cpp, retail object.lto 0x1022f58b) and
docs/research/ambient-sound.md (branch research/ambient-sound).
"""
import pytest

import ambient


def obj(name="amb_01", start_on=True, **props):
    p = {"Name": name, "Pos": [1.0, 2.0, 3.0], "Rotation": [0.0, 0.0, 0.0, 0.0], "StartOn": start_on,
         "Sound": "snd\\amb\\drone10.WAV", "Priority": 0, "OuterRadius": 5500.0, "InnerRadius": 1500.0,
         "Volume": 100, "PitchShift": 1.0, "Ambient": True, "Loop": True, "PlayAttached": False,
         "Filter": "UnFiltered"}
    p.update(props)
    return {"class": "SoundFX", "props": p}


def test_a_soundfx_plays_its_file_with_its_props():
    [s] = ambient.sound_fx([obj(Volume=80, PitchShift=1.8, Priority=3, Ambient=False, Loop=False)])
    assert s == {"name": "amb_01", "obj": 0, "startOn": True, "pos": [1.0, 2.0, 3.0],
                 "file": "snd\\amb\\drone10.WAV", "files": [], "inner": 1500.0, "outer": 5500.0, "volume": 80,
                 "pitch": 1.8, "priority": 3, "ambient": 0, "loop": 0}


def test_soundfx_that_start_off_are_exported_too_waiting_for_on():
    others = [obj(name="off", start_on=False), obj(name="silent", Sound="  "),
              dict(obj(name="bute"), **{"class": "SoundButeFX"})]
    found = ambient.sound_fx(others + [obj(name="on")])
    assert [(s["name"], s["obj"], s["startOn"]) for s in found] == [("off", 0, False), ("on", 3, True)]


def test_a_soundfx_naming_a_soundbute_plays_one_of_its_files(extracted):
    # SoundFX::PlaySound: a name that is a soundbute plays through the sound manager, which picks one of
    # its files (m05-01's light sounds, off at start, name "light_oneoffs").
    import sounds
    [s] = ambient.sound_fx([obj(Sound="light_oneoffs")], sounds.SoundButes(extracted))
    assert s["files"] == ["snd/amb/1_light_01.wav", "snd/amb/1_light_02.wav", "snd/amb/1_light_03.wav",
                          "snd/amb/1_light_04.wav"]


def test_single_player_levels_have_1360_soundfx_468_live_none_of_those_naming_a_soundbute(world, extracted):
    # A live SoundFX naming a soundbute would play through CGameSoundMgr (a random PathN, the soundbute's
    # flags and priority); none does, only two that start off (m05-01).
    import glob
    import os
    import sounds
    from conftest import EXTRACTED
    root = os.path.join(EXTRACTED, "worlds")
    soundbutes = sounds.SoundButes(extracted)
    found = {}
    for path in sorted(glob.glob(os.path.join(root, "retailsingleplayer", "*.dat"))):
        found[os.path.basename(path)[:-4]] = ambient.sound_fx(world(os.path.relpath(path, root)[:-4]).objects,
                                                              soundbutes)
    assert sum(len(v) for v in found.values()) == 468 + 892
    live = [s for v in found.values() for s in v if s["startOn"]]
    assert len(live) == 468
    assert len([s for s in found["m03-01"] if s["startOn"]]) == 55
    assert not [s["file"] for s in live if s["files"]]
    assert [s["name"] for v in found.values() for s in v if s["files"]] == ["1_light_snd_01", "1_light_snd_02"]
    # the one that doesn't loop: m02-02's teleport sound, once at start
    assert [(s["name"], s["file"]) for s in live if not s["loop"]] == [("Teleport", "snd\\event\\Teleport.WAV")]


def test_level_json_lists_the_soundfx(extracted, tmp_path):
    import json
    import os
    import export_level
    import export_models
    name = "retailsingleplayer/m03-01"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] >= 16   # SoundFX that start off since format 16
    assert len([s for s in meta["soundFX"] if s["startOn"]]) == 55
    assert len(meta["soundFX"]) == 95
    amb = next(s for s in meta["soundFX"] if s["name"] == "amb_01")
    assert meta["objects"][amb["obj"]]["name"] == "amb_01"
    assert amb == {"name": "amb_01", "obj": amb["obj"], "startOn": True, "pos": [-3328.0, 512.0, 2528.0],
                   "file": "snd\\amb\\drone10.WAV", "files": [], "inner": 1500.0, "outer": 5500.0,
                   "volume": 100, "pitch": 1.0, "priority": 0, "ambient": 1, "loop": 1}
