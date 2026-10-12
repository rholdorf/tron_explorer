"""What export_level writes for model lighting: the light grid, the static lights, the sun."""
import json
import os

import numpy as np
import pytest

import export_level
import export_models
import modellight


@pytest.fixture(scope="module")
def exported(extracted, world, tmp_path_factory):
    def run(name):
        out = tmp_path_factory.mktemp("export")
        export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(out), name,
                            export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
        with open(out / "level.json") as f:
            meta = json.load(f)
        return meta, (out / "level.bin").read_bytes(), world(name)
    return run


def test_level_bin_ends_with_the_light_grid_with_light_groups_added(exported):
    meta, data, w = exported("retailsingleplayer/m05-01")
    g = meta["lightGrid"]
    assert g["dims"] == list(w.light_grid.dims) and g["cell"] == list(w.light_grid.cell)
    n = g["dims"][0] * g["dims"][1] * g["dims"][2] * 3
    tail = np.frombuffer(data[-n:], np.uint8).reshape(w.light_grid.data.shape)
    expect = modellight.with_light_groups(w.light_grid, w.grid_light_groups).data
    assert (tail == expect).all() and (expect != w.light_grid.data).any()


def test_models_carry_what_the_viewer_needs_to_light_them(exported):
    meta, _data, w = exported("retailsingleplayer/m02-04")
    assert len(meta["lights"]) == len(modellight.static_lights(w.objects, modellight.light_group_colors(w)))
    assert meta["sun"]["color"] == pytest.approx([69.5, 77.0, 108.0])
    models = meta["models"]
    assert models and all(0.0 <= m["sunAmount"] <= 1.0 for m in models)
    assert any(m["sunAmount"] == 1.0 for m in models) and any(m["sunAmount"] == 0.0 for m in models)
    assert all(len(m["dims"]) == 3 and m["visRadius"] > 0 for m in models)


def test_a_level_without_a_sun_exports_a_black_one(exported):
    meta, _data, _w = exported("retailsingleplayer/m01-01")
    assert meta["sun"]["color"] == [0.0, 0.0, 0.0]
    assert all(m["sunAmount"] == 0.0 for m in meta["models"])
