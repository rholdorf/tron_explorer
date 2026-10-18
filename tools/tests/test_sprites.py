"""The engine's sprite drawing (TronViewer/.../Sprites.cs SpriteMath) compiled with .NET. Rules: ltjs render_a
d3d/drawsprite.cpp (d3d_DrawSprite, d3d_DrawRotatableSprite), client/sprite.cpp spr_UpdateTracker and
game/clientshelldll lensflarefx.cpp, worked by hand. The camera sits at the origin looking down +z (right +x,
up +y) unless a line says otherwise.

Driver lines (tab-separated):
  corners <x y z> <w h> <scale> [rot=<yaw deg>] [glow] [bias]   the four corners, or "none"
  frame <seconds> <rate> <frames>                               the frame index
  flare <x y z> <minangle>                                      "shown alpha scale pos", min/max alpha 0/1,
                                                                scale 1/1.75, offset -8 along the object's z
"""
import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Globalization;
using System.Linq;
using Tron;
static class Driver
{
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    static float F(string s) => float.Parse(s, Inv);
    static string N(float v) => (Math.Abs(v) < 0.0005f ? 0f : v).ToString("0.###", Inv);
    static string V(LTVec v) => $"{N(v.x)} {N(v.y)} {N(v.z)}";
    static LTVec Vec(string s) { var p = s.Split(' ').Select(F).ToArray(); return new LTVec(p[0], p[1], p[2]); }
    static void Main()
    {
        LTVec cam = default, right = new LTVec(1, 0, 0), up = new LTVec(0, 1, 0), fwd = new LTVec(0, 0, 1);
        var c = new LTVec[4];
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "corners":
                {
                    var wh = a[2].Split(' ').Select(F).ToArray();
                    var s = new LTSprite { Pos = Vec(a[1]), ScaleX = F(a[3]), ScaleY = F(a[3]) };
                    foreach (var o in a.Skip(4))
                    {
                        if (o.StartsWith("rot=")) { s.Rotatable = true; s.Rot = LTQuat.FromEuler(0, F(o.Substring(4)) * (float)Math.PI / 180, 0); }
                        else if (o == "glow") s.Glow = true;
                        else if (o == "bias") s.ZBias = true;
                    }
                    Console.WriteLine(SpriteMath.Corners(s, wh[0], wh[1], cam, right, up, fwd, c) ? string.Join("|", c.Select(V)) : "none");
                    break;
                }
                case "frame":
                    Console.WriteLine(SpriteMath.Frame(double.Parse(a[1], Inv), int.Parse(a[2]), int.Parse(a[3])));
                    break;
                case "flare":
                {
                    bool on = SpriteMath.Flare(Vec(a[1]), new LTVec(0, 0, 1), cam, fwd, F(a[2]), 0, 1, 1, 1.75f, -8, out var p, out float al, out float sc);
                    Console.WriteLine($"{(on ? 1 : 0)} {N(al)} {N(sc)} {V(p)}");
                    break;
                }
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "sprites", DRIVER, "Sprites.cs", "KeyframerMotion.cs", "Commands.cs")
    return lambda *lines: drive("\n".join(lines) + "\n").splitlines()


def test_billboard_is_texture_size_times_scale_each_side(run):
    # 64 x 32 texels at scale 0.5: half-extents 32 across, 16 up, in the camera's axes.
    assert run("corners\t0 0 100\t64 32\t0.5") == ["-32 16 100|32 16 100|32 -16 100|-32 -16 100"]


def test_billboard_nearer_than_near_z_is_not_drawn(run):
    assert run("corners\t0 0 6.9\t8 8\t1", "corners\t0 0 7\t8 8\t1")[0] == "none"


def test_glow_sprite_grows_with_depth(run):
    # factor 0.1 + 1.9 x clamp((z - 10) / 490): 0.1 at 10, 1.05 at 255, 2 from 500.
    out = run("corners\t0 0 10\t10 10\t1\tglow", "corners\t0 0 255\t10 10\t1\tglow", "corners\t0 0 900\t10 10\t1\tglow")
    assert [o.split("|")[1].split()[0] for o in out] == ["1", "10.5", "20"]


def test_rotatable_lies_in_its_own_axes(run):
    # Yawed 90 degrees (forward +x): its right is -z, its up +y.
    (o,) = run("corners\t0 0 100\t10 10\t1\trot=90")
    assert o == "0 10 110|0 10 90|0 -10 90|0 -10 110"


def test_z_bias_pulls_twenty_units_closer_same_size_on_screen(run):
    # Billboard at z 100: corners at z 80, scaled by 1 - 20/100 about the view axis.
    (o,) = run("corners\t0 0 100\t10 10\t1\tbias")
    assert o == "-8 8 80|8 8 80|8 -8 80|-8 -8 80"
    # At z 20 the pull stops at NEARZ 7: bias = 7 - 20, scale 7/20.
    (o,) = run("corners\t0 0 20\t10 10\t1\tbias")
    assert o == "-3.5 3.5 7|3.5 3.5 7|3.5 -3.5 7|-3.5 -3.5 7"


def test_frames_count_whole_milliseconds_of_integer_periods(run):
    # 15 fps: 1000 / 15 = 66 ms frames, so frame 15 starts at 990 ms, not 1000.
    out = run("frame\t0.989\t15\t20", "frame\t0.990\t15\t20", "frame\t1.32\t15\t20", "frame\t5\t0\t20")
    assert out == ["14", "15", "0", "0"]


def test_flare_shows_within_min_angle_and_grows(run):
    # angle = cos x 90: straight ahead 90 (full: alpha 1, scale 1.75); cos 0.8 = 72 = 90 - 18, the edge.
    out = run("flare\t0 0 100\t18", "flare\t60 0 80\t18", "flare\t100 0 10\t18")
    assert out[0] == "1 1 1.75 0 0 92"
    assert out[1].split()[:3] == ["1", "0", "1"]
    assert out[2].split()[0] == "0"
