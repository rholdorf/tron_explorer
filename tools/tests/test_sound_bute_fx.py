"""SoundButeFX, as the exporter hands them to the viewer (ticket #25).

Engine rules: SoundButeFX::Update (ltjs soundbutefx.cpp, retail object.lto 0x1022c1d0) and
CGameSoundMgr::PlaySoundFromPos / FillPSIFromButeOrParams (ltjs game/shared/soundmgr.cpp);
docs/research/ambient-sound.md §7 (branch research/ambient-sound).
"""
import pytest

import ambient
import sounds

ROUTER = ["snd/amb/1_router2_01.wav", "snd/amb/1_router2_02.wav", "snd/amb/1_router2_03.wav"]


@pytest.fixture(scope="module")
def soundbutes(extracted):
    return sounds.SoundButes(extracted)


def obj(name="rands_01", start_on=True, **props):
    p = {"Name": name, "Pos": [1.0, 2.0, 3.0], "Rotation": [0.0, 0.0, 0.0, 0.0], "RenderGroup": 0,
         "Template": False, "SoundBute": "routerrands", "StartOn": start_on, "NumPlays": -1,
         "MinDelay": 3.0, "MaxDelay": 10.0, "InnerRadius": 100.0, "OuterRadius": 8000.0,
         "WaitUntilFinished": True, "Ambient": False}
    p.update(props)
    return {"class": "SoundButeFX", "props": p}


def test_a_soundbutefx_plays_its_soundbutes_files_with_its_radii_and_delays(soundbutes):
    [s] = ambient.sound_bute_fx([obj(Ambient=True)], soundbutes)
    assert s == {"name": "rands_01", "obj": 0, "startOn": True, "pos": [1.0, 2.0, 3.0], "files": ROUTER,
                 "inner": 100.0, "outer": 8000.0, "minDelay": 3.0, "maxDelay": 10.0, "ambient": 1}


def test_radii_left_at_minus_one_come_from_the_soundbute_or_a_quarter_of_the_outer(soundbutes):
    # PlaySoundFromPos: an outer radius with no inner one gets inner = 0.25 x outer; a radius at -1
    # takes the soundbute's (BaseSFXObjSound: InnerRadius 50, OuterRadius 600).
    [a, b] = ambient.sound_bute_fx([obj(InnerRadius=-1.0, OuterRadius=-1.0),
                                    obj(InnerRadius=-1.0, OuterRadius=4000.0)], soundbutes)
    assert (a["inner"], a["outer"]) == (50.0, 600.0)
    assert (b["inner"], b["outer"]) == (1000.0, 4000.0)


def test_soundbutefx_that_name_a_soundbute_with_files_on_or_off(soundbutes):
    # "None" is the SoundBute prop's default and an empty [None] section in soundbutes.txt. One that starts
    # off waits for ON (SoundButeFX::OnTrigger).
    others = [obj(name="off", start_on=False), obj(name="none", SoundBute="None"),
              obj(name="file", SoundBute="snd\\amb\\drone10.WAV"),
              dict(obj(name="sfx"), **{"class": "SoundFX"})]
    found = ambient.sound_bute_fx(others + [obj(name="on")], soundbutes)
    assert [(s["name"], s["obj"], s["startOn"]) for s in found] == [("off", 0, False), ("on", 4, True)]


def test_single_player_levels_have_38_live_soundbutefx_all_repeating_and_waiting(world, soundbutes):
    import glob
    import os
    from conftest import EXTRACTED
    root = os.path.join(EXTRACTED, "worlds")
    objects = [o for path in sorted(glob.glob(os.path.join(root, "retailsingleplayer", "*.dat")))
               for o in world(os.path.relpath(path, root)[:-4]).objects]
    live = ambient.sound_bute_fx(objects, soundbutes)
    assert len(live) == 38 == len([o for o in objects if o["class"] == "SoundButeFX"])
    # The rules the viewer bakes in: forever (NumPlays -1), the next sound after the last one ends
    # (WaitUntilFinished), and no soundbute that could skip a play (PlayChance < 1)
    props = [o["props"] for o in objects if o["class"] == "SoundButeFX"]
    assert all(p["NumPlays"] == -1 and p["WaitUntilFinished"] for p in props)
    assert {soundbutes.get(p["SoundBute"], "playchance") for p in props} == {1.0}
    assert sum(s["ambient"] for s in live) == 6


def test_level_json_lists_the_live_soundbutefx(extracted, tmp_path):
    import json
    import os
    import export_level
    import export_models
    name = "retailsingleplayer/m03-01"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] >= 14   # SoundButeFX since format 14
    assert [s["name"] for s in meta["soundButeFX"]] == ["blips_01", "blips_02", "blips_03", "blips_04"]
    s = meta["soundButeFX"][2]
    assert meta["objects"][s["obj"]]["name"] == "blips_03"
    assert s == {"name": "blips_03", "obj": s["obj"], "startOn": True, "pos": [-5824.0, 512.0, -1184.0],
                 "files": ROUTER, "inner": 500.0, "outer": 8000.0, "minDelay": 0.0, "maxDelay": 0.0, "ambient": 0}
