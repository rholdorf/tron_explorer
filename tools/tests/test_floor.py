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


@pytest.fixture(scope="module")
def m01_01(extracted, tmp_path_factory):
    import export_level
    import export_models
    rel = "retailsingleplayer/m01-01"
    out = tmp_path_factory.mktemp("m01-01")
    return export_level.export(f"{extracted}/worlds/{rel}.dat", str(out), rel, export_models.Resolver(extracted),
                               export_models.Styles(extracted), extracted)


def instance(meta, name):
    return next(m for m in meta["models"] if meta["objects"][m["obj"]]["name"] == name and m["parent"] < 0)


def test_level_characters_stand_on_the_floor_and_loop_their_idle(m01_01):
    z = instance(m01_01, "12073TP")                           # program, origin 80 above the floor
    assert m01_01["objects"][z["obj"]]["pos"][1] == 6120
    assert z["pos"][1] == pytest.approx(6092.1)                # floor 6040 + dims.y 52 + 0.1
    assert z["anim"] == "Gen_Idle01"


def test_attachments_take_their_character_position(m01_01):
    models = m01_01["models"]
    atts = [m for m in models if m["parent"] >= 0]
    assert atts
    for a in atts:
        assert a["pos"] == models[a["parent"]]["pos"] and a["anim"] == ""


def test_move_to_floor_off_leaves_the_character(m01_01):
    byte = instance(m01_01, "Byte")        # MoveToFloor False
    assert byte["pos"] == m01_01["objects"][byte["obj"]]["pos"]
    assert byte["anim"] == "Hover"


def test_prop_types_follow_their_type_move_to_floor(extracted):
    import export_level
    import export_models
    r = export_models.Resolver(extracted)

    def prop(t, mtf=True):
        return {"cls": "PropType", "props": [{"k": "Type", "t": "s", "s": t, "v": []},
                                             {"k": "MoveToFloor", "t": "b", "s": "", "v": [1.0 if mtf else 0.0]}]}
    assert export_level.moves_to_floor(prop("Tank"), r)
    assert not export_level.moves_to_floor(prop("m0502Forcefield"), r)   # level says True, type says 0
    assert not export_level.moves_to_floor({"cls": "ArchiveBin", "props": []}, r)


def test_world_model_objects_sit_at_their_world_models_centre(extracted):
    """The engine moves a brush object to its BSP's m_WorldTranslation (server_extradata.cpp); the intro's
    credit box tg1_01WM was placed in DEdit ~700 units from it, and its IgnoreOffsets keyframer's first key
    is that centre (#85)."""
    import os
    import dat85
    w = dat85.load(os.path.join(extracted, "worlds", "retailsingleplayer", "intro.dat"))
    by_name = {o["props"].get("Name"): o for o in w.objects}
    assert by_name["tg1_01WM"]["props"]["Pos"] == pytest.approx([-10405.25, -139130.06, -4214.63], abs=0.01)
    light = next(o for o in w.objects if o["class"] == "Light")
    light_pos = list(light["props"]["Pos"])
    floor.place_world_models(w)
    bsp = next(b for b in w.bsps if b.name == "tg1_01WM")
    assert by_name["tg1_01WM"]["props"]["Pos"] == pytest.approx(list(bsp.translation))
    assert by_name["tg1_01WM"]["props"]["Pos"] == pytest.approx([-10217.25, -138674.06, -3666.63], abs=0.01)
    assert list(light["props"]["Pos"]) == light_pos   # not a brush: stays where DEdit put it
