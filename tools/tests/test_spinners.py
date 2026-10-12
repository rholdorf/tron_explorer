"""Spinners (SpinningWorldModel) that start on, as the exporter hands them to the viewer."""
import math

import pytest

import spinner


def obj(name="spin", angles=(0.0, 5.0, 0.0), start_on=True, power_on=10.0, wave="Linear"):
    return {"class": "SpinningWorldModel", "props": {
        "Name": name, "RotationAngles": list(angles), "StartOn": start_on, "PowerOnTime": power_on,
        "Waveform": wave}}


def test_rotation_angles_are_seconds_per_turn():
    # SpinningWorldModel::ReadProps (retail object.lto 0x1022a680): final velocity = 2*pi / RotationAngles.
    [s] = spinner.spinners([obj(angles=(0.0, 5.0, -2.0))])
    assert s["worldModel"] == "spin"
    assert s["velocity"] == pytest.approx([0.0, 2 * math.pi / 5, -math.pi])


def test_power_on_time_and_waveform():
    [s] = spinner.spinners([obj(power_on=2.0, wave="SlowOn")])
    assert s["powerOnTime"] == 2.0
    assert s["waveform"] == 3        # Linear, Sine, SlowOff, SlowOn (AWM_WAVE_*)
    [s] = spinner.spinners([obj(wave="Sine")])
    assert s["waveform"] == 1


def test_waveform_names_match_in_any_case_like_the_engine():
    # ActiveWorldModel::ReadProps compares with _stricmp; an unknown name stays Linear
    assert [spinner.spinners([obj(wave=w)])[0]["waveform"] for w in ("slowoff", "SINE", "Bogus")] == [2, 1, 0]


def test_spinners_that_start_off_are_exported_too_waiting_for_on():
    # A command can turn one on later (ActiveWorldModel ON), so every spinner is exported with startOn.
    others = [obj(name="off", start_on=False), dict(obj(name="door"), **{"class": "RotatingWorldModel"})]
    found = spinner.spinners(others + [obj(name="on")])
    assert [(s["worldModel"], s["obj"], s["startOn"]) for s in found] == [("off", 0, False), ("on", 2, True)]


def test_the_on_off_state_machine_props():
    # ActiveWorldModel::ReadProps / PostReadProp: PowerOffTime 0 takes PowerOnTime.
    props = {"PowerOffTime": 0.0, "TriggerOff": False, "Locked": True, "ForceMove": False, "ForceMoveOn": True,
             "ForceMoveOff": False, "MoveDelay": 0.5, "OnWaitTime": 1.0, "OffWaitTime": 2.0}
    o = obj(power_on=3.0)
    o["props"].update(props)
    [s] = spinner.spinners([o])
    assert (s["powerOffTime"], s["triggerOff"], s["locked"], s["forceMove"], s["forceMoveOn"], s["forceMoveOff"],
            s["moveDelay"], s["onWaitTime"], s["offWaitTime"]) == (3.0, False, True, False, True, False, 0.5, 1.0, 2.0)
    o["props"]["PowerOffTime"] = 4.0
    assert spinner.spinners([o])[0]["powerOffTime"] == 4.0


def test_a_spinner_with_no_speed_is_left_out():
    assert spinner.spinners([obj(angles=(0.0, 0.0, 0.0))]) == []


def test_single_player_levels_have_305_spinners_271_live(world):
    import glob
    import os
    from conftest import EXTRACTED
    root = os.path.join(EXTRACTED, "worlds")
    levels = sorted(glob.glob(os.path.join(root, "retailsingleplayer", "*.dat")))
    found = {}
    for path in levels:
        w = world(os.path.relpath(path, root)[:-4])
        found[os.path.basename(path)[:-4]] = spinner.spinners(w.objects)
    assert sum(len(v) for v in found.values()) == 305
    assert sum(s["startOn"] for v in found.values() for s in v) == 271
    assert len(found["m09-02"]) == 155
    m02 = {s["worldModel"]: s for s in found["m02-04"]}
    assert m02["SpinningWorldModel0"]["velocity"] == pytest.approx([0, 2 * math.pi / 10, 0])
    assert m02["SpinningWorldModel0"]["powerOnTime"] == 1.0


def test_level_json_lists_the_spinners_by_world_model(extracted, tmp_path):
    import json
    import os
    import export_level
    import export_models
    name = "retailsingleplayer/m02-04"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] == export_level.FORMAT_VERSION
    assert len(meta["spinners"]) == 10
    world_models = {wm["name"] for wm in meta["worldModels"]}
    assert all(s["worldModel"] in world_models for s in meta["spinners"])
