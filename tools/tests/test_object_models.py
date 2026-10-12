"""Models that the game's object code (object.lto) creates without a level property or attribute file
naming them (docs/research/object-lto-models.md)."""
import os

import pytest

import export_level
import export_models


@pytest.fixture(scope="module")
def tools(extracted):
    return export_models.Resolver(extracted), export_models.Styles(extracted)


def export(extracted, tools, tmp_path, rel):
    dat = os.path.join(extracted, "worlds", "retailsingleplayer", rel + ".dat")
    return export_level.export(dat, str(tmp_path / rel), rel, *tools, extracted)


def models_of(meta, cls):
    return [m for m in meta["models"] if meta["objects"][m["obj"]]["cls"] == cls]


def test_io_node_shows_its_template_with_the_off_skin(extracted, tools, tmp_path):
    meta = export(extracted, tools, tmp_path, "m01-01")
    [node] = models_of(meta, "IONode")
    assert node["file"] == "props/models/ionode.ltb"
    assert node["skins"] == ["props/skins/ionode_off.dtx", "props/skins/ionodeface.dtx",
                             "props/skins/ionodering1.dtx", "props/skins/ionodering2.dtx"]
    assert node["styles"] == ["chars/rs/jet_rs.ltb", "rs/alpha_additive_wglow.ltb"]
    assert node["parent"] == -1


def test_optimizer_shows_its_template_with_the_on_skins(extracted, tools, tmp_path):
    meta = export(extracted, tools, tmp_path, "m01-02")
    [opt] = models_of(meta, "Optimizer")
    assert opt["file"] == "props/models/optimizer.ltb"
    assert opt["skins"] == ["props/skins/optimizer_1.dtx", "props/skins/optimizer_2.dtx", "tex/chrome.dtx"]
    assert opt["styles"] == ["chars/rs/jet_rs.ltb"]


def prop(obj, key):
    return next((q["s"] for q in obj["props"] if q["k"] == key), "")


BERRIES = {"Subroutine": "SubroutineBerry", "Permission Set": "PSetBerry", "Email": "DocumentBerry",
           "Custom": "DocumentBerry", "Primitive": "DocumentBerry", "Procedural": "DocumentBerry"}
BERRY_SKIN = {"SubroutineBerry": "props/skins/archive_cubeinternal.dtx",
              "PSetBerry": "props/skins/archive_cubeinternal_blue.dtx",
              "DocumentBerry": "props/skins/archive_cubeinternal_green.dtx"}


def test_each_bin_item_is_a_berry_at_a_bin_socket(extracted, tools, tmp_path):
    meta = export(extracted, tools, tmp_path, "m01-02")
    checked = 0
    for b, m in enumerate(meta["models"]):
        o = meta["objects"][m["obj"]]
        if o["cls"] != "ArchiveBin" or m["file"] != "props/models/archivebin.ltb":
            continue
        items = [prop(o, f"Type{k}") for k in range(1, 7)]
        items = [BERRIES[t] for t in items if t and t != "<none>"]
        berries = [x for x in meta["models"] if x["parent"] == b]
        assert [x["skins"][0] for x in berries] == [BERRY_SKIN[t] for t in items]
        assert all(x["file"] == "props/models/archiveobject.ltb" and x["skinned"] == 0 for x in berries)
        assert [x["socket"] for x in berries] == [f"Socket{k}" for k in range(1, len(items) + 1)]
        checked += len(items)
    assert checked > 0


def test_tron_turret_sits_at_its_parents_socket(extracted, tools, tmp_path):
    meta = export(extracted, tools, tmp_path, "m05-02")
    turrets = models_of(meta, "TronTurret")
    assert len(turrets) == 4
    for t in turrets:
        parent = meta["models"][t["parent"]]
        assert meta["objects"][parent["obj"]]["name"] == prop(meta["objects"][t["obj"]], "Parent")
        assert parent["file"] == "props/models/tankbody.ltb"
        assert t["socket"] == "TurretSocket"
        assert t["file"] == "props/models/tankturret.ltb"
        assert t["skins"][0] == "props/skins/tank1.dtx"
        assert t["styles"] == ["props/rs/tank1.ltb", "chars/rs/jet_rs.ltb"]


def test_every_turret_in_the_single_player_levels_has_its_tank(extracted, tools, tmp_path):
    turrets = [t for rel in ("m05-02", "m05-03") for t in models_of(export(extracted, tools, tmp_path, rel),
                                                                   "TronTurret")]
    assert len(turrets) == 14
    assert all(t["parent"] >= 0 for t in turrets)
