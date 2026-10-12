"""The DAT v85 light grid and world light groups (docs/research/light-grid.md §1)."""
import glob
import os

import numpy as np

import dat85

M01_01 = "retailsingleplayer/m01-01"


def test_m01_01_grid_covers_the_world_box(world):
    w = world(M01_01)
    g = w.light_grid
    assert g.base == w.ext_min
    assert g.cell == (1024.0, 1024.0, 1024.0)
    assert g.dims == (13, 17, 14)
    assert g.data.shape == (14, 17, 13, 3) and g.data.dtype == np.uint8
    assert g.data.max() == 255


def test_every_level_has_a_grid_over_its_world_box_and_light_groups_only_where_the_research_found_them(extracted):
    groups = {}
    for path in sorted(glob.glob(os.path.join(extracted, "worlds", "**", "*.dat"), recursive=True)):
        w = dat85.load(path)
        g = w.light_grid
        expect = tuple(int(np.floor((w.ext_max[i] - w.ext_min[i]) / g.cell[i])) + 1 for i in range(3))
        assert g.dims == expect, path
        if w.grid_light_groups:
            groups[os.path.basename(path)[:-4]] = len(w.grid_light_groups)
    assert groups == {"intro": 3, "m05-01": 2, "m05-04": 1, "m07-01cin": 3, "m08-01": 1}


def test_grid_light_group_covers_a_box_of_nodes(world):
    for lg in world("retailsingleplayer/m05-01").grid_light_groups:
        assert lg.name
        assert len(lg.color) == 3 and all(0 <= c <= 1 for c in lg.color)
        ex, ey, ez = lg.ext
        assert lg.samples.shape == (ez, ey, ex) and lg.samples.dtype == np.uint8
        assert lg.samples.any()
