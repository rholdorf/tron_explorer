"""The style baseline (baseline.py) on real levels."""
import pytest

import baseline


@pytest.fixture(scope="module")
def m01(world):
    return baseline.LevelMeasure(world("retailsingleplayer/m01-01"), "m01-01").result()


def test_m01_01_is_an_interior_of_rooms_and_corridors(m01):
    assert m01["kind"] == "interior"
    assert 2500 < m01["reachableArea"] < 3500
    assert m01["graph"]["rooms"] > 10 and m01["graph"]["corridors"] > 10
    assert all(r["area"] > 0 and r["width"] > 0 for r in m01["rooms"])


def test_most_reachable_floor_lies_in_ai_volumes(m01):
    assert m01["aiVolumeShare"] > 0.6


def test_surfaces_near_the_floor_are_mostly_walls_floors_and_ceilings(m01):
    s = m01["surfaceArea"]
    assert s["wall"] > s["emissive"] > s["glass"]
    assert s["floor-interior"] > s["floor-exterior"]
    assert s["unclassified"] == 0


def test_doors_thinner_than_a_cell_still_cut_the_floor(world):
    w = world("retailsingleplayer/m04-01")
    g = baseline.FloorGrid(w)
    assert len(baseline._components(g.door_cells(w), g.adj)) >= 10


def test_elevators_and_displays_are_not_doors(world):
    w = world("retailsingleplayer/m01-01")
    assert baseline.FloorGrid(w).door_cells(w) == set()
