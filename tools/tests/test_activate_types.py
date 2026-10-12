"""The use prompt's text per ActivateType (ticket #36; docs/research/triggers-doors.md "Use prompt").

attributes/activatetypes.txt names each type and gives a cres.dll string ID per state (StateON, StateOFF;
-1 = no text). The strings themselves weren't extracted: the comment after each ID is the English text,
so that is what the exporter ships. A level carries the types its objects name.
"""
import activate


def test_a_type_has_the_text_of_its_on_and_off_states(extracted):
    t = activate.prompts(extracted)
    assert t["Door Open-Close"] == ("Close Door", "Open Door")
    assert t["ForceField Raise-Lower"] == ("Raise Forcefield", "Lower Forcefield")


def test_a_state_with_id_minus_one_has_no_text(extracted):
    t = activate.prompts(extracted)
    assert t["Communication Bit Overpower"] == ("Overpower Communication Bit", "")
    assert t["Platform Call"] == ("", "Call Platform")


def test_every_type_in_the_file_is_read(extracted):
    assert len(activate.prompts(extracted)) == 41


def test_a_level_carries_the_types_its_objects_name_once_each(extracted, world):
    w = world("retailsingleplayer/m01-02")
    assert activate.level_types(w.objects, extracted) == [
        {"name": "ForceField Raise-Lower", "on": "Raise Forcefield", "off": "Lower Forcefield"},
        {"name": "Power Stream Control Sector Door Open-Close", "on": "Close door to Power Stream Control Sector",
         "off": "Open door to Power Stream Control Sector"},
        {"name": "Power Streams Cycle", "on": "", "off": "Cycle Power Streams"},
    ]


def test_level_json_carries_its_activate_types(extracted, tmp_path):
    import json
    import os
    import export_level
    import export_models
    name = "retailsingleplayer/m04-01"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] == export_level.FORMAT_VERSION == 18
    assert meta["activateTypes"] == [{"name": "Door Open-Close", "on": "Close Door", "off": "Open Door"}]
