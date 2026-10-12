"""SoundFX that start on, as the exporter hands them to the viewer (ticket #24).

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


def test_a_soundfx_that_starts_on_plays_its_file_with_its_props():
    [s] = ambient.sound_fx([obj(Volume=80, PitchShift=1.8, Priority=3, Ambient=False, Loop=False)])
    assert s == {"name": "amb_01", "pos": [1.0, 2.0, 3.0], "file": "snd\\amb\\drone10.WAV",
                 "inner": 1500.0, "outer": 5500.0, "volume": 80, "pitch": 1.8, "priority": 3,
                 "ambient": 0, "loop": 0}


def test_only_soundfx_that_start_on_and_name_a_sound():
    others = [obj(name="off", start_on=False), obj(name="silent", Sound="  "),
              dict(obj(name="bute"), **{"class": "SoundButeFX"})]
    assert [s["name"] for s in ambient.sound_fx(others + [obj(name="on")])] == ["on"]


def test_single_player_levels_have_468_live_soundfx_none_naming_a_soundbute(world, extracted):
    # A SoundFX naming a soundbute would play through CGameSoundMgr (a random PathN, the soundbute's
    # flags and priority); no live one does, so the export only carries file paths.
    import glob
    import os
    import sounds
    from conftest import EXTRACTED
    root = os.path.join(EXTRACTED, "worlds")
    found = {}
    for path in sorted(glob.glob(os.path.join(root, "retailsingleplayer", "*.dat"))):
        found[os.path.basename(path)[:-4]] = ambient.sound_fx(world(os.path.relpath(path, root)[:-4]).objects)
    live = [s for v in found.values() for s in v]
    assert len(live) == 468
    assert len(found["m03-01"]) == 55
    soundbutes = sounds.SoundButes(extracted)
    assert not [s["file"] for s in live if soundbutes.is_soundbute(s["file"])]
    # the one that doesn't loop: m02-02's teleport sound, once at start
    assert [(s["name"], s["file"]) for s in live if not s["loop"]] == [("Teleport", "snd\\event\\Teleport.WAV")]


def test_level_json_lists_the_live_soundfx(extracted, tmp_path):
    import json
    import os
    import export_level
    import export_models
    name = "retailsingleplayer/m03-01"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] >= 13   # SoundFX since format 13
    assert len(meta["soundFX"]) == 55
    amb = next(s for s in meta["soundFX"] if s["name"] == "amb_01")
    assert amb == {"name": "amb_01", "pos": [-3328.0, 512.0, 2528.0], "file": "snd\\amb\\drone10.WAV",
                   "inner": 1500.0, "outer": 5500.0, "volume": 100, "pitch": 1.0, "priority": 0,
                   "ambient": 1, "loop": 1}
