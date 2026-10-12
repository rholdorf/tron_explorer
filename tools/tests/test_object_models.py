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
