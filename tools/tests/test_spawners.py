"""Spawned characters (ltjs spawner.cpp; docs/research/cutscene-actors.md, spawned actors): a Spawner's
`spawn [name]` creates a copy of its Target template at the spawner's position and rotation, `spawnfrom
<object> [name]` at that object's when exactly one has the name. The exporter ships every CAIHuman template
a Spawner targets as a template model (built only when spawned) and one spawn site per (spawner, place)
with the character's position there after MoveToFloor."""
import glob
import os
import types

import numpy as np

import dat85
import export_level
import export_models
import floor


def level(*objects):
    """A loaded level (dat85 form) of (class, props) objects."""
    return types.SimpleNamespace(objects=[{"class": c, "props": dict(p)} for c, p in objects], blind=[])


def test_every_spawner_of_a_character_template_is_a_spawn_site(extracted):
    # The research's count: 772 Spawners target a CAIHuman template in the 38 single-player levels.
    sites = 0
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        sites += len(export_level.spawn_sites(dat85.load(f)))
    assert sites == 772


def test_a_spawner_spawns_its_character_template_where_it_stands():
    w = level(("CAIHuman", {"Name": "cinjetTPLT", "Template": True}),
              ("CAIHuman", {"Name": "placed"}),
              ("AILightCycle", {"Name": "cycleTPLT", "Template": True}),
              ("Spawner", {"Name": "S1cinjetSP", "Target": "CinJetTplt"}),
              ("Spawner", {"Name": "sp2", "Target": "placed"}),      # not a template: nothing spawns
              ("Spawner", {"Name": "sp3", "Target": "cycleTPLT"}),   # not a character
              ("Spawner", {"Name": "sp4", "Target": "nobody"}))
    assert export_level.spawn_sites(w) == [{"spawner": 3, "at": 3, "template": 0}]


def test_spawnfrom_adds_a_site_at_its_object_when_one_has_the_name():
    w = level(("CAIHuman", {"Name": "tplt", "Template": True}),
              ("Spawner", {"Name": "sp", "Target": "tplt"}),
              ("Group", {"Name": "grp", "Object1": "sp"}),
              ("TeleportPoint", {"Name": "here"}),
              ("TeleportPoint", {"Name": "twice"}), ("TeleportPoint", {"Name": "twice"}),
              ("Trigger", {"Name": "t", "Command": "msg grp (spawnfrom here jet); msg sp (spawnfrom twice x); "
                                                 "msg sp (spawnfrom nowhere y)"}))
    # "twice" and "nowhere" aren't one object: the spawner's own place, already a site.
    assert export_level.spawn_sites(w) == [{"spawner": 1, "at": 1, "template": 0},
                                           {"spawner": 1, "at": 3, "template": 0}]


def human(name, template, **props):
    ps = [{"k": "ModelTemplate", "t": "s", "s": template, "v": []}]
    ps += [{"k": k, "t": "b", "s": "", "v": [1.0 if v else 0.0]} for k, v in props.items()]
    return {"cls": "CAIHuman", "name": name, "pos": [0, 500, 0], "rot": [0, 0, 0], "props": ps}


def test_spawned_templates_are_template_models_with_their_attachments(extracted):
    objects = [human("tplt", "IC_Regular", Template=True), human("unused", "IC_Regular", Template=True)]
    models, _ = export_level.model_instances(objects, export_models.Resolver(extracted),
                                             export_models.Styles(extracted), extracted, templates={0})
    assert {m["obj"] for m in models} == {0}
    assert models[0]["template"] == 1 and models[0]["parent"] == -1 and models[0]["anim"]
    assert len(models) == 14 and all(m.get("template") == 1 for m in models)   # IC_Regular's 13 attachments


def test_a_site_puts_the_character_on_the_floor_below_its_place(extracted):
    objects = [human("tplt", "IC_Regular", Template=True),
               {"cls": "Spawner", "name": "sp", "pos": [10, 300, 20], "rot": [0, 1.5, 0], "props": []}]
    models, _ = export_level.model_instances(objects, export_models.Resolver(extracted),
                                             export_models.Styles(extracted), extracted, templates={0})
    caster = floor.FloorCaster(np.array([[[-100, 50, -100], [-100, 50, 100], [100, 50, 0]]], np.float64))
    sites = export_level.place_sites([{"spawner": 1, "at": 1, "template": 0}], objects, models, caster,
                                     lambda o, dims: 0.25)
    half = models[0]["dims"][1]
    assert sites == [{"spawner": 1, "at": 1, "template": 0, "model": 0,
                      "pos": [10.0, 50 + half + 0.1, 20.0], "rot": [0.0, 1.5, 0.0], "sunAmount": 0.25}]


def test_a_template_without_a_drawn_model_still_has_its_site(extracted):
    objects = [human("tplt", "IC_Regular", Template=True, StartHidden=True),
               {"cls": "Spawner", "name": "sp", "pos": [10, 300, 20], "rot": [0, 0, 0], "props": []}]
    models, _ = export_level.model_instances(objects, export_models.Resolver(extracted),
                                             export_models.Styles(extracted), extracted, templates={0})
    assert models == []
    sites = export_level.place_sites([{"spawner": 1, "at": 1, "template": 0}], objects, models, None, None)
    assert sites[0]["model"] == -1 and sites[0]["pos"] == [10.0, 300.0, 20.0]


def test_level_json_carries_spawn_sites_and_template_models(extracted, tmp_path):
    import json
    name = "retailsingleplayer/m02-02"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] == export_level.FORMAT_VERSION == 27
    objects = meta["objects"]
    # Mercury is spawned (test_spawn_targets): her spawner's template is a template model at a site.
    sites = [s for s in meta["spawnSites"] if s["model"] >= 0]
    assert sites
    for s in sites:
        m = meta["models"][s["model"]]
        assert m["template"] == 1 and m["obj"] == s["template"] and m["parent"] == -1
        assert objects[s["spawner"]]["cls"] == "Spawner" and objects[s["template"]]["cls"] == "CAIHuman"
    assert not any(m.get("template") for m in meta["models"] if not any(
        p["k"] == "Template" and p["v"] == [1.0] for p in objects[m["obj"]]["props"]))
