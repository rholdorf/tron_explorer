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


def pools(meta, data):
    """level.bin's light group pools (they follow the light grid): vertex indices, vertex intensities,
    lightmap texels, grid samples."""
    p = meta["lightGroupPools"]
    sizes = [p["vertices"] * 4, p["vertices"], p["texels"], p["gridSamples"]]
    end = len(data)
    out = []
    for size, dtype in zip(reversed(sizes), (np.uint8, np.uint8, np.uint8, np.uint32)):
        out.append(np.frombuffer(data[end - size:end], dtype))
        end -= size
    return list(reversed(out)), end


def test_level_bin_has_the_light_grid_without_its_light_groups_then_the_groups(exported):
    meta, data, w = exported("retailsingleplayer/m05-01")
    g = meta["lightGrid"]
    assert g["dims"] == list(w.light_grid.dims) and g["cell"] == list(w.light_grid.cell)
    (vidx, vval, texels, samples), end = pools(meta, data)
    n = g["dims"][0] * g["dims"][1] * g["dims"][2] * 3
    grid = np.frombuffer(data[end - n:end], np.uint8).reshape(w.light_grid.data.shape)
    assert (grid == w.light_grid.data).all()
    # The grid groups added back at their DAT colour give the grid the game starts from.
    acc = grid.astype(np.float32)
    for lg in meta["lightGroups"]:
        if "grid" not in lg:
            continue
        b = lg["grid"]
        ex, ey, ez = b["ext"]
        s = samples[b["start"]:b["start"] + ex * ey * ez].reshape(ez, ey, ex).astype(np.float32)
        x, y, z = b["min"]
        acc[z:z + ez, y:y + ey, x:x + ex] += s[..., None] * np.array(lg["color"], np.float32)
    expect = modellight.with_light_groups(w.light_grid, w.grid_light_groups).data
    assert (np.minimum(acc, 255).astype(np.uint8) == expect).all()


def test_light_groups_name_what_they_light(exported):
    meta, data, _w = exported("retailsingleplayer/intro")
    groups = {g["name"]: g for g in meta["lightGroups"]}
    assert set(groups) == {"tron_lg", "lab_lg", "rez_lg"}
    (vidx, vval, texels, _samples), _end = pools(meta, data)
    nverts = (data.index(b"TRLV") == 0) and int.from_bytes(data[8:12], "little")
    assert len(vidx) == meta["lightGroupPools"]["vertices"] and (vidx < nverts).all() and (vval > 0).all()
    assert sum(g["vtxCount"] for g in groups.values()) == len(vidx)
    for g in groups.values():
        for p in g["patches"]:
            r = meta["lightmapRects"][p["lm"]]
            assert p["x"] + p["w"] <= r["w"] and p["y"] + p["h"] <= r["h"]
            assert p["start"] + p["w"] * p["h"] <= len(texels)
    lights = {l["name"]: l for l in meta["lights"]}
    assert lights["Light4"]["group"] == "rez_lg" and lights["Light4"]["color"] == pytest.approx([212.0, 372.0, 460.0], rel=0.01)


def test_models_carry_what_the_viewer_needs_to_light_them(exported):
    meta, _data, w = exported("retailsingleplayer/m02-04")
    assert len(meta["lights"]) == len(modellight.static_lights(w.objects, {}))
    assert meta["sun"]["color"] == pytest.approx([69.5, 77.0, 108.0])
    models = meta["models"]
    assert models and all(0.0 <= m["sunAmount"] <= 1.0 for m in models)
    assert any(m["sunAmount"] == 1.0 for m in models) and any(m["sunAmount"] == 0.0 for m in models)
    assert all(len(m["dims"]) == 3 and m["visRadius"] > 0 for m in models)


def test_a_level_without_a_sun_exports_a_black_one(exported):
    meta, _data, _w = exported("retailsingleplayer/m01-01")
    assert meta["sun"]["color"] == [0.0, 0.0, 0.0]
    assert all(m["sunAmount"] == 0.0 for m in meta["models"])
