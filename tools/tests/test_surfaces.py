"""Surface families (surfaces.py): what kind of surface a world triangle is, for the style baseline and
the bench glTF."""
import numpy as np
import pytest

import surfaces

UP, DOWN, SIDE = (0, 1, 0), (0, -1, 0), (1, 0, 0)


def test_up_facing_is_a_floor_interior_under_a_ceiling_exterior_under_the_sky():
    assert surfaces.family(UP, covered=True) == "floor-interior"
    assert surfaces.family(UP, covered=False) == "floor-exterior"


def test_down_facing_is_a_ceiling_and_the_rest_is_wall():
    assert surfaces.family(DOWN, covered=True) == "ceiling"
    assert surfaces.family(SIDE, covered=True) == "wall"


def test_slope_threshold_is_the_walkable_one():
    steep = (np.sin(np.radians(50)), np.cos(np.radians(50)), 0)    # normal.y ~0.64
    gentle = (np.sin(np.radians(40)), np.cos(np.radians(40)), 0)   # normal.y ~0.77
    assert surfaces.family(steep, covered=True) == "wall"
    assert surfaces.family(gentle, covered=True) == "floor-interior"
    assert surfaces.family((0, -0.77, 0.64), covered=True) == "ceiling"


def test_material_families_win_over_orientation():
    assert surfaces.family(UP, covered=True, blend="Translucent") == "glass"
    assert surfaces.family(SIDE, covered=True, blend="Additive") == "emissive"
    assert surfaces.family(UP, covered=False, blend="Additive") == "emissive"


def test_plain_world_models_classify_by_orientation():
    assert surfaces.family(SIDE, covered=True, blend="None") == "wall"


def test_degenerate_normal_is_unclassified():
    assert surfaces.family((0, 0, 0), covered=True) == "unclassified"


def test_families_are_the_six_plus_unclassified():
    assert surfaces.FAMILIES == ("floor-interior", "floor-exterior", "wall", "ceiling", "glass", "emissive",
                                 "unclassified")


# A 200 x 200 ceiling at y = 300 over x, z in [-100, 100], facing down; a sky patch beside it at y = 500.
CEIL = np.array([[[-100, 300, -100], [100, 300, 100], [100, 300, -100]],
                 [[-100, 300, -100], [-100, 300, 100], [100, 300, 100]]], np.float64)
SKY = CEIL + np.array([400, 200, 0])


def test_covered_when_the_first_thing_above_is_not_sky():
    c = surfaces.CoverCaster(CEIL, SKY)
    assert c.covered([0, 0, 0])
    assert not c.covered([400, 0, 0])      # sky above
    assert not c.covered([1000, 0, 0])     # nothing above at all
    assert not c.covered([0, 400, 0])      # the ceiling is below


def test_sky_below_a_ceiling_does_not_uncover_it():
    c = surfaces.CoverCaster(CEIL, CEIL + np.array([0, 100, 0]))
    assert c.covered([0, 0, 0])
    c = surfaces.CoverCaster(CEIL + np.array([0, 100, 0]), CEIL)
    assert not c.covered([0, 0, 0])
