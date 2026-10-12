"""ArchiveBin draws as two models: the bin (glass) and the ArchiveBin_Frame template the game attaches
to its Frame socket (docs/research/archivebin-style.md)."""
import glob
import os

import pytest

import export_level
import export_models


@pytest.fixture(scope="module")
def tools(extracted):
    return export_models.Resolver(extracted), export_models.Styles(extracted)


def export(extracted, tools, tmp_path, rel):
    dat = os.path.join(extracted, "worlds", rel + ".dat")
    return export_level.export(dat, str(tmp_path / rel), rel, *tools, extracted)


def piece_styles(meta, model):
    return [meta["renderStyles"][p["style"]]["name"] for p in model["pieces"]]


def test_each_bin_gets_a_frame_model_at_its_transform(extracted, tools, tmp_path):
    meta = export(extracted, tools, tmp_path, "retailsingleplayer/m01-02")
    bins = [i for i, o in enumerate(meta["objects"]) if o["cls"] == "ArchiveBin"]
    assert bins
    for i in bins:
        files = sorted(m["file"] for m in meta["models"] if m["obj"] == i)
        assert files == ["props/models/archivebin.ltb", "props/models/archivebin_frame.ltb"]
        frame = next(m for m in meta["models"] if m["obj"] == i and m["file"].endswith("_frame.ltb"))
        assert frame["scale"] == [1, 1, 1]
        assert piece_styles(meta, frame) == ["rs/alpha_chrome.ltb"]


def test_bin_glass_draws_with_its_own_style(extracted, tools, tmp_path):
    meta = export(extracted, tools, tmp_path, "retailsingleplayer/m01-02")
    glass = next(m for m in meta["models"] if m["file"] == "props/models/archivebin.ltb")
    assert piece_styles(meta, glass) == ["props/rs/archivecube.ltb"] * 2


def test_style_piece_counts_across_all_levels(extracted, tools, tmp_path):
    counts = {}
    worlds = os.path.join(extracted, "worlds")
    for dat in sorted(glob.glob(os.path.join(worlds, "**", "*.dat"), recursive=True)):
        rel = os.path.relpath(dat, worlds)[:-4]
        meta = export(extracted, tools, tmp_path, rel)
        for m in meta["models"]:
            for name in piece_styles(meta, m):
                counts[name] = counts.get(name, 0) + 1
    assert counts.get("props/rs/archivecube.ltb") == 334
    assert counts.get("rs/alpha_chrome.ltb") == 167
