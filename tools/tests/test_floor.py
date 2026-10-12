"""MoveToFloor (floor.py) and its use in the level export."""
import numpy as np
import pytest

import floor

# Two floor triangles covering x, z in [-100, 100] at y = 0.
FLAT = np.array([[[-100, 0, -100], [100, 0, -100], [100, 0, 100]],
                 [[-100, 0, -100], [100, 0, 100], [-100, 0, 100]]], np.float64)


def test_drops_to_floor_plus_dims_plus_a_tenth():
    c = floor.FloorCaster(FLAT)
    assert floor.move_to_floor([10, 200, 10], 48, c) == pytest.approx([10, 48.1, 10])


def test_moves_only_when_the_gap_exceeds_dims_y():
    c = floor.FloorCaster(FLAT)
    assert floor.move_to_floor([10, 48, 10], 48, c) == [10, 48, 10]     # gap == dims.y: stays
    assert floor.move_to_floor([10, 20, 10], 48, c) == [10, 20, 10]     # sunk into the floor: never up


def test_no_floor_within_the_cast_leaves_the_object():
    c = floor.FloorCaster(FLAT)
    assert floor.move_to_floor([500, 200, 0], 48, c) == [500, 200, 0]   # nothing below
    assert floor.move_to_floor([0, 20000, 0], 48, c) == [0, 20000, 0]   # floor beyond 10000
    assert floor.move_to_floor([0, -10, 0], 48, c) == [0, -10, 0]       # floor above


def test_nearest_floor_below_wins():
    upper = FLAT + np.array([0, 300, 0])
    c = floor.FloorCaster(np.concatenate([FLAT, upper]))
    assert floor.move_to_floor([0, 500, 0], 50, c)[1] == pytest.approx(350.1)
    assert floor.move_to_floor([0, 200, 0], 50, c)[1] == pytest.approx(50.1)


def test_sloped_floor_height_is_interpolated():
    ramp = np.array([[[0, 0, 0], [100, 100, 0], [0, 0, 100]]], np.float64)
    assert floor.FloorCaster(ramp).floor_below([50, 500, 10]) == pytest.approx(50)


def test_world_floors_face_up(world):
    # m05-02's tanks rest on the floor already (dims.y 43, origin 43 above it): they don't move.
    w = world("retailsingleplayer/m05-02")
    c = floor.FloorCaster.from_world(w)
    tank = next(o for o in w.objects if o["props"].get("Name") == "Tank01.Body")
    assert c.floor_below(tank["props"]["Pos"]) == pytest.approx(0)
    assert floor.move_to_floor(tank["props"]["Pos"], 43, c) == tank["props"]["Pos"]
