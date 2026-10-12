"""Model lighting: light grid sampling, static lights, the sun (docs/research/light-grid.md §2)."""
import math

import numpy as np
import pytest

import dat85
import modellight


def grid(nodes, dims=(2, 2, 2), cell=10.0):
    """A synthetic grid; nodes = {(x, y, z): (r, g, b)}, everything else black."""
    g = dat85.LightGrid()
    g.base, g.cell, g.dims = (0.0, 0.0, 0.0), (cell, cell, cell), dims
    g.data = np.zeros((dims[2], dims[1], dims[0], 3), np.uint8)
    for (x, y, z), c in nodes.items():
        g.data[z, y, x] = c
    return g


def test_sample_interpolates_between_nodes():
    g = grid({(1, 0, 0): (200, 100, 40)})
    assert modellight.sample_grid(g, (2.5, 0, 0)) == (50, 25, 10)
    assert modellight.sample_grid(g, (5, 0, 0)) == (100, 50, 20)


def test_ltjs_order_mirrors_the_y_lerp_inside_a_cell():
    g = grid({(0, 1, 0): (200, 200, 200)})
    assert modellight.sample_grid(g, (0, 2.5, 0)) == (50, 50, 50)
    assert modellight.sample_grid(g, (0, 2.5, 0), ltjs_order=True) == (150, 150, 150)


def light_group(color, mn, samples):
    lg = dat85.GridLightGroup()
    lg.name, lg.color, lg.min = "g", color, mn
    lg.samples = np.array(samples, np.uint8)
    lg.ext = lg.samples.shape[::-1]
    return lg


def test_lit_light_groups_add_color_times_sample_to_their_nodes():
    g = grid({(1, 0, 0): (10, 10, 250)})
    groups = [light_group((0.5, 1.0, 1.0), (1, 0, 0), [[[100], [40]]]),   # nodes (1,0,0), (1,1,0)
              light_group((1.0, 0.0, 1.0), (0, 0, 0), [[[200]]])]         # a channel off: skipped
    out = modellight.with_light_groups(g, groups)
    assert out.data[0, 0, 1].tolist() == [60, 110, 255]
    assert out.data[0, 1, 1].tolist() == [20, 40, 40]
    assert out.data[0, 0, 0].tolist() == [0, 0, 0]
    assert g.data[0, 0, 1].tolist() == [10, 10, 250]


def test_past_the_last_node_the_sample_is_that_node():
    g = grid({(1, 1, 1): (90, 90, 90)})
    assert modellight.sample_grid(g, (15, 25, 18)) == (90, 90, 90)


def light(cls, name, **props):
    return {"class": cls, "props": {"Name": name, "Pos": [0.0, 0.0, 0.0], "LightRadius": 100.0, **props}}


def test_static_lights_are_the_object_lights_that_light_objects_slowly():
    objs = [
        light("Light", "fast_default"),                                   # FastLightObjects defaults on
        light("Light", "slow", FastLightObjects=False, LightColor=[100.0, 50.0, 10.0], BrightScale=2.0,
              ObjectBrightScale=0.5, Attenuation="Quartic"),
        light("DirLight", "inherits_slow", InnerColor=[10.0, 20.0, 30.0], FOV=90.0,
              Rotation=[0.0, math.pi / 2, 0.0, 0.0], Attenuation="Linear"),
        light("ObjectLight", "no_objects", LightObjects=False),
        light("Light", "grouped", LightColor=[200.0, 200.0, 200.0], LightGroup="lg"),
        light("Light", "fast", FastLightObjects=True),
        light("Light", "inherits_fast"),
        light("Prop", "not_a_light", FastLightObjects=False),
        light("Light", "slow_again", FastLightObjects=False, Pos=[1.0, 2.0, 3.0], LightColor=[1.0, 2.0, 3.0]),
    ]
    lights = modellight.static_lights(objs, {"lg": (0.5, 0.25, 1.0)})
    assert [lt["name"] for lt in lights] == ["slow", "inherits_slow", "grouped", "slow_again"]
    slow, spot, grouped, last = lights
    assert slow["color"] == [100.0, 50.0, 10.0] and slow["cosFov"] == -1 and slow["att"] == "Quartic"
    assert spot["att"] == "Linear" and spot["color"] == [10.0, 20.0, 30.0]
    assert spot["cosFov"] == pytest.approx(math.cos(math.radians(45)))
    assert spot["dir"] == pytest.approx([1.0, 0.0, 0.0], abs=1e-6)
    assert grouped["color"] == [100.0, 50.0, 200.0]
    assert last["pos"] == [1.0, 2.0, 3.0] and last["radius"] == 100.0


def point(pos, color, radius=100.0, att="Quartic", to_ambient=0.0, direction=(0.0, 0.0, 1.0), cos_fov=-1.0):
    return {"name": "", "cls": "Light", "pos": list(pos), "dir": list(direction), "color": list(color),
            "radius": radius, "cosFov": cos_fov, "att": att, "attCoefs": [1.0, 0.0, 0.0], "toAmbient": to_ambient}


GREY = grid({(x, y, z): (20, 30, 40) for x in (0, 1) for y in (0, 1) for z in (0, 1)})


def lit(lights, pos=(5.0, 5.0, 5.0), dims=(10.0, 10.0, 10.0), vis_radius=200.0, **kw):
    return modellight.model_lighting(GREY, pos, dims, vis_radius, lights, **kw)


def test_without_lights_a_model_gets_the_grid_as_ambient():
    assert lit([]) == {"ambient": (20, 30, 40), "lights": []}


def test_a_quartic_point_light_becomes_a_directional_light_sampled_at_the_model():
    out = lit([point((55.0, 5.0, 5.0), (200.0, 100.0, 0.0))])     # 50 units away, radius 100
    assert out["ambient"] == (20, 30, 40)
    [lt] = out["lights"]
    assert lt["color"] == pytest.approx([112.5, 56.25, 0.0])         # (1 - 0.25)^2
    assert lt["dir"] == pytest.approx([-1.0, 0.0, 0.0])               # from the light toward the model


def test_lights_beyond_the_fourth_strongest_fold_into_ambient():
    lights = [point((5.0 + 10 * k, 5.0, 5.0), (100.0, 100.0, 100.0)) for k in range(1, 6)]  # 10..50 away
    out = lit(lights)
    assert len(out["lights"]) == 4
    assert [lt["color"][0] for lt in out["lights"]] == pytest.approx([98.01, 92.16, 82.81, 70.56])
    assert out["ambient"] == (20 + 56, 30 + 56, 40 + 56)                # the 50-unit light: 56.25


def test_convert_to_ambient_splits_a_light():
    out = lit([point((55.0, 5.0, 5.0), (200.0, 200.0, 200.0), to_ambient=0.25)])
    assert out["lights"][0]["color"] == pytest.approx([84.375] * 3)    # 112.5 * 0.75
    assert out["ambient"] == (20 + 28, 30 + 28, 40 + 28)


def test_ambient_clamps_at_255():
    out = lit([point((5.0, 5.0, 5.0 + 10 * k), (250.0, 250.0, 250.0)) for k in range(1, 7)])
    assert out["ambient"] == (255, 255, 255)


def test_lights_whose_box_misses_the_model_box_are_not_considered():
    out = lit([point((400.0, 5.0, 5.0), (200.0, 200.0, 200.0), radius=150.0)], vis_radius=200.0)
    assert out["lights"] == []


def test_a_spot_takes_the_brightest_sample_over_the_model_box():
    # Pointing down +x from x=-45, 15 degree half-angle.
    cos_fov = math.cos(math.radians(15))
    spot = point((-45.0, 0.0, 0.0), (100.0, 100.0, 100.0), radius=1000.0, direction=(1.0, 0.0, 0.0), cos_fov=cos_fov)
    out = modellight.model_lighting(GREY, (5.0, 30.0, 0.0), (1.0, 1.0, 1.0), 2000.0, [spot])
    assert out["lights"] == []     # center and corners all outside the cone: nothing to draw
    # The center (16.2 degrees off the axis) is outside; corner (6, 13.5, +-1) is inside (14.9 degrees).
    out = modellight.model_lighting(GREY, (5.0, 14.5, 0.0), (1.0, 1.0, 1.0), 2000.0, [spot])
    [lt] = out["lights"]
    d2 = 51.0 ** 2 + 13.5 ** 2 + 1.0
    expect = 100.0 * (1 - d2 / 1e6) ** 2 * (51.0 / math.sqrt(d2) - cos_fov) / (1 - cos_fov)
    assert lt["color"] == pytest.approx([expect] * 3, rel=1e-4)


def test_a_narrow_spot_lights_models_as_a_directional_light():
    # Retail Lithtech.exe StaticLightCB (0x54f2cb): cos(FOV/2) > 0.98 -> SetupDirLight(dir, color). The
    # levels' far GlobalLightHigh/Medium/Low (FOV 5) light every model in reach this way.
    far = point((80000.0, 0.0, 0.0), (159.0, 120.0, 90.0), radius=200000.0, direction=(0.0, -1.0, 0.0),
                cos_fov=math.cos(math.radians(2.5)))
    out = lit([far])
    assert out["lights"] == [{"dir": [0.0, -1.0, 0.0], "color": pytest.approx([159.0, 120.0, 90.0])}]
    assert out["ambient"] == (20, 30, 40)
    # Out of the light's box (pos +- radius): not considered.
    assert lit([dict(far, radius=1000.0)])["lights"] == []


def test_m01_01_program_is_lit_by_the_three_global_lights_where_the_grid_is_black(world):
    w = world("retailsingleplayer/m01-01")
    program = next(o for o in w.objects if o["props"].get("Name") == "12073TP")
    pos = program["props"]["Pos"]
    lights = modellight.static_lights(w.objects, modellight.light_group_colors(w))
    out = modellight.model_lighting(w.light_grid, pos, (24.0, 53.0, 24.0), 128.0, lights)
    assert out["ambient"] == (0, 0, 0)
    assert sorted(lt["color"][0] for lt in out["lights"]) == pytest.approx([116.0, 138.0, 159.0])
    globals_ = sorted(lt["dir"] for lt in lights if lt["name"].startswith("GlobalLight"))
    assert sorted(lt["dir"] for lt in out["lights"]) == globals_


def test_a_spot_just_wider_than_the_directional_cutoff_stays_a_spot():
    spot = point((80000.0, 0.0, 0.0), (159.0, 120.0, 90.0), radius=200000.0, direction=(0.0, -1.0, 0.0),
                 cos_fov=0.979)
    assert lit([spot])["lights"] == []


def test_the_sun_is_a_directional_light_scaled_by_how_much_sky_the_model_sees():
    sun = {"dir": [0.0, -1.0, 0.0], "color": [100.0, 80.0, 60.0], "toAmbient": 0.0}
    out = lit([], sun=sun, sun_amount=0.5)
    assert out["lights"] == [{"dir": [0.0, -1.0, 0.0], "color": pytest.approx([50.0, 40.0, 30.0])}]


def quad(x0, x1, y, z0, z1):
    a, b, c, d = (x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)
    return [(a, b, c), (a, c, d)]


def sky_with_roof():
    """Sky over everything at y=1000; an opaque roof at y=500 over z in [30, 1000]."""
    tris = quad(-1000, 1000, 1000, -1000, 1000) + quad(-1000, 1000, 500, 30, 1000)
    return modellight.SkyCaster(np.array(tris, np.float32), np.array([True, True, False, False]))


def test_sun_amount_is_whether_rays_toward_the_sun_reach_the_sky():
    sky, down = sky_with_roof(), (0.0, -1.0, 0.0)
    assert sky.sun_amount((0.0, 0.0, -500.0), down, right=(1.0, 0.0, 0.0), radius=100.0) == 1.0
    assert sky.sun_amount((0.0, 0.0, 500.0), down, right=(1.0, 0.0, 0.0), radius=100.0) == 0.0
    assert sky.sun_amount((0.0, 600.0, 500.0), down, right=(1.0, 0.0, 0.0), radius=100.0) == 1.0


def test_sun_amount_bisects_a_model_half_in_shadow():
    # Rays from z = -100 .. 100 (sun direction x right * radius); lit below z = 30, i.e. 65%.
    # GetDirLightAmount bisects down to a 0.05 step: lit, shadow, lit, shadow, shadow -> 0.65625.
    amount = sky_with_roof().sun_amount((0.0, 0.0, 0.0), (0.0, -1.0, 0.0), right=(1.0, 0.0, 0.0), radius=100.0)
    assert amount == 0.65625


def test_the_sun_is_the_static_sun_light_unless_its_object_brightness_is_zero(world):
    sun = modellight.sun_light(world("retailsingleplayer/m02-04").objects)
    assert sun["color"] == pytest.approx([69.5, 77.0, 108.0])
    p, y = 0.8691740036010742, 0.7836530208587646
    assert sun["dir"] == pytest.approx([math.cos(p) * math.sin(y), -math.sin(p), math.cos(p) * math.cos(y)])
    assert sun["dir"][1] < 0                                   # shining down
    assert modellight.sun_light(world("retailmultiplayer/deathmatch/dm-03").objects) is None
    assert modellight.sun_light(world("retailsingleplayer/m01-01").objects) is None


def test_retail_levels_have_232_static_object_lights(extracted):
    import glob
    import os
    from collections import Counter
    count = Counter()
    for path in glob.glob(os.path.join(extracted, "worlds", "**", "*.dat"), recursive=True):
        w = dat85.load(path)
        for lt in modellight.static_lights(w.objects, modellight.light_group_colors(w)):
            count[lt["cls"]] += 1
            assert lt["att"] == "Quartic"
    assert count == {"DirLight": 205, "Light": 20, "ObjectLight": 7}
