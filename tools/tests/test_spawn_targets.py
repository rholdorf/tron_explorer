"""msg targets that name no object: the ones a Spawner would create apart from the dead ones
(docs/research/no-object-targets.md). The viewer joins every level object but templates, which the game
never creates (GameBase::ReadProp), and counts a target with no object as `(spawned <class>)` when it is
one of the level's spawn names (the exporter's commands.spawn_names, in level.json), else `(no object)`.
"""
import collections
import glob
import os
import types

import commands
import dat85


def classify(w):
    """Each executed msg target of a level the way the viewer reports it: "object", "player", "active",
    "(spawned <class>)" or "(no object)"."""
    live = {o["props"].get("Name", "").lower() for o in w.objects if not o["props"].get("Template")}
    spawned = {s["name"].lower(): s["cls"] for s in commands.spawn_names(w)}
    out = collections.Counter()
    for _, prop, text in commands.level_commands(w):
        for words in commands.executed(prop, text):
            if words[0].upper() != "MSG":
                continue
            name = commands.target_name(words[1]).lower()
            out["active" if not name else "player" if name in commands.PLAYER_NAMES else "object" if name in live
                else f"(spawned {spawned[name]})" if name in spawned else "(no object)"] += 1
    return out


def test_spawned_targets_are_reported_apart_from_dead_ones(extracted):
    total = collections.Counter()
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        total += classify(dat85.load(f))
    assert sum(total.values()) == 27830
    # 464 names only a spawn gives, 355 more that templates had before they stopped joining.
    assert {k: v for k, v in total.items() if k.startswith("(spawned")} == {
        "(spawned CAIHuman)": 737, "(spawned AILightCycle)": 53, "(spawned SpecialFX)": 18,
        "(spawned PatchRoutine)": 6, "(spawned CThorne)": 5}
    # 936 dead in the game, and the template that no spawn uses.
    assert total["(no object)"] == 937


def level(*objects):
    return types.SimpleNamespace(objects=[{"class": c, "props": p} for c, p in objects], blind=[])


def test_a_spawn_name_comes_from_spawn_or_spawnfrom_to_a_spawner_directly_or_through_a_group():
    w = level(("CAIHuman", {"Name": "Guard", "Template": True}),
              ("AILightCycle", {"Name": "Cycle", "Template": True}),
              ("Spawner", {"Name": "sp1", "Target": "Guard"}),
              ("Spawner", {"Name": "sp2", "Target": "Cycle"}),
              ("Group", {"Name": "grp", "Object1": "sp2"}),
              ("Trigger", {"Name": "t", "Command": "msg sp1 (spawn Alan); msg grp (spawnfrom t Rinzler); "
                                                 "msg sp1 spawn; msg t (spawn Nobody)"}))
    assert commands.spawn_names(w) == [{"name": "Alan", "cls": "CAIHuman"}, {"name": "Rinzler", "cls": "AILightCycle"}]


def test_m02_02s_mercury_is_a_spawned_caihuman(world):
    names = {s["name"]: s["cls"] for s in commands.spawn_names(world("retailsingleplayer/m02-02"))}
    assert names["Mercury"] == "CAIHuman"


def test_level_json_carries_its_spawn_names(extracted, tmp_path):
    import json
    import export_level
    import export_models
    name = "retailsingleplayer/m10-03"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] == export_level.FORMAT_VERSION == 22
    assert meta["spawns"] == commands.spawn_names(dat85.load(os.path.join(extracted, "worlds", name + ".dat")))
    assert meta["spawns"]
