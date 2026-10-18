"""The CamJitter, DynaLight and Null effects (TronViewer/.../CamJitterFX.cs, DynaLightFX.cs, NullFX.cs) compiled
with .NET and driven frame by frame. Rules: ltjs clientfxdll/camjitterfx.cpp, dynalightfx.cpp, nullfx.cpp and
render_a setupmodel.cpp (the dynamic light as a D3D point light), renderlight.cpp GetLightSample, 3d_ops.cpp
d3d_CalcLightAdd. Expected values are worked by hand from them.

Driver lines (tab-separated):
  rand <a,b,...>                  the manager's random numbers, in turn, over and over (default 0.5)
  group <name> <phase>            a group; the keys after it are its keys
  key <type> <id> <start> <end> [k=v]...
                                  a key: ck, sk, offset as comma lists, updatepos, link, any other value a number
  start <group> <loop> <x y z>    an instance at an object there
  wall <x>                        the world: a wall at x = <x> facing -x
  frame <dt> <x y z>              the manager's update, the camera there
  stop                            every instance shuts down smoothly
  state                           "o <x y z>" the camera offset; "l <x y z> <r g b> <radius>" per light;
                                  "n <x y z>" per null
  sample <light> <radius> <rgb> <at>       "s <rgb>": FxDynaLight.Sample
  spriteadd <light> <radius> <rgb> <at>    "s <rgb>": FxDynaLight.SpriteAdd
"""
import math

import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Globalization;
using System.Linq;
using Tron;
class Obj : IFxObject
{
    public LTVec Pos { get; set; }
    public LTQuat Rot { get; set; } = new LTQuat(0, 0, 0, 1);
    public bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot)
    {
        pos = default;
        rot = Rot;
        return false;
    }
}
static class Driver
{
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    static float F(string s) => float.Parse(s, Inv);
    static string N(float v) => (Math.Abs(v) < 0.0005f ? 0f : v).ToString("0.###", Inv);
    static string V(LTVec v) => $"{N(v.x)} {N(v.y)} {N(v.z)}";
    static float[] Fs(string s) => s.Split(',').Select(F).ToArray();
    static LTVec Vec(string s) { var p = s.Split(' ', ',').Select(F).ToArray(); return new LTVec(p[0], p[1], p[2]); }
    static void Main()
    {
        double[] rands = { 0.5 };
        int ri = 0;
        var mgr = new ClientFXMgr(() => rands[ri++ % rands.Length]);
        mgr.Types["CamJitter"] = k => new FxCamJitter(mgr);
        mgr.Types["DynaLight"] = k => new FxDynaLight(mgr);
        mgr.Types["Null"] = k => new FxNull(mgr);
        FxGroup g = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "rand":
                    rands = a[1].Split(',').Select(s => double.Parse(s, Inv)).ToArray();
                    ri = 0;
                    break;
                case "group":
                    g = new FxGroup { Name = a[1], Phase = F(a[2]) };
                    mgr.Add(g);
                    break;
                case "key":
                {
                    var k = new FxKey { Type = a[1], Id = int.Parse(a[2]), Start = F(a[3]), End = F(a[4]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    foreach (var kv in a.Skip(5).Select(s => s.Split(new[] { '=' }, 2)))
                    {
                        var v = kv[1];
                        if (kv[0] == "ck") k.Ck = Fs(v);
                        else if (kv[0] == "sk") k.Sk = Fs(v);
                        else if (kv[0] == "offset") { var r = Fs(v); k.Offset = new LTVec(r[0], r[1], r[2]); }
                        else if (kv[0] == "updatepos") k.UpdatePos = int.Parse(v);
                        else if (kv[0] == "link") k.Link = int.Parse(v);
                        else k.Nums[kv[0]] = Fs(v);
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "start":
                    mgr.Start(a[1], a[2] == "1", true, new Obj { Pos = Vec(a[3]) });
                    break;
                case "wall":
                {
                    float x = F(a[1]);
                    mgr.Intersect = (LTVec from, LTVec to, out LTVec p, out LTVec n) =>
                    {
                        p = default;
                        n = new LTVec(-1, 0, 0);
                        if (!(from.x < x && to.x >= x)) return false;
                        p = LTVec.Lerp(from, to, (x - from.x) / (to.x - from.x));
                        return true;
                    };
                    break;
                }
                case "frame":
                    mgr.Update(F(a[1]), Vec(a[2]));
                    break;
                case "stop":
                    foreach (var inst in mgr.Instances.ToArray()) mgr.ShutDown(inst);
                    break;
                case "state":
                    Console.WriteLine("o\t" + V(mgr.CameraOffset));
                    foreach (var inst in mgr.Instances)
                        foreach (var fx in inst.Effects)
                        {
                            if (fx is FxDynaLight l) Console.WriteLine($"l\t{V(l.Pos)}\t{V(l.Color)}\t{N(l.Radius)}");
                            if (fx is FxNull n) Console.WriteLine($"n\t{V(n.Pos)}");
                        }
                    break;
                case "sample":
                    Console.WriteLine("s\t" + V(FxDynaLight.Sample(Vec(a[1]), F(a[2]), Vec(a[3]), Vec(a[4]))));
                    break;
                case "spriteadd":
                    Console.WriteLine("s\t" + V(FxDynaLight.SpriteAdd(Vec(a[1]), F(a[2]), Vec(a[3]), Vec(a[4]))));
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "camera_light", DRIVER, "ClientFX.cs", "CamJitterFX.cs", "DynaLightFX.cs",
                       "NullFX.cs", "Commands.cs", "KeyframerMotion.cs")

    def go(*lines):
        out = {"o": [], "l": [], "n": [], "s": []}
        for l in drive("\n".join(lines) + "\n").splitlines():
            r = l.split("\t")
            if r[0] == "l":
                out["l"].append(dict(pos=vec(r[1]), rgb=vec(r[2]), radius=float(r[3])))
            else:
                out[r[0]].append(vec(r[1]))
        return out
    return go


def vec(s):
    return tuple(float(x) for x in s.split())


def close(a, b, tol=1e-3):
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


# Random 0.75, 0.25, 0.5 -> -1..1 as 0.5, -0.5, 0 on x, y, z.
JITTER = ("rand\t0.75,0.25,0.5", "group\tg\t10")
SHAKE = "key\tCamJitter\t1\t0\t1\tsk=0,10,1,10\tInnerRadius=500\tOuterRadius=600"


def test_jitter_within_the_inner_radius_moves_the_camera_by_its_scale(run):
    out = run(*JITTER, SHAKE, "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 100", "state")
    assert close(out["o"][-1], (5, -5, 0)), out


def test_jitter_falls_off_by_squared_distance_to_the_outer_radius(run):
    # 550 units: 1 - (302500 - 250000) / (360000 - 250000) = 0.5227.
    out = run(*JITTER, SHAKE, "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 550", "state")
    assert close(out["o"][-1], (2.614, -2.614, 0)), out


def test_no_jitter_beyond_the_outer_radius(run):
    out = run(*JITTER, SHAKE, "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 700", "state")
    assert close(out["o"][-1], (0, 0, 0)), out


def test_jitters_of_one_update_add_up_and_the_next_update_starts_again(run):
    out = run(*JITTER, SHAKE, SHAKE.replace("\t1\t0\t1", "\t2\t0\t1"), "start\tg\t0\t0 0 0",
              "frame\t0.1\t0 0 100", "state", "frame\t0\t0 0 100", "state")
    assert close(out["o"][0], (10, -10, 0)), out
    assert close(out["o"][1], (10, -10, 0)), out


def test_a_jitter_shutting_down_shakes_no_more(run):
    # The update that reaches the key's end still shakes; the one after it doesn't.
    out = run(*JITTER, SHAKE, "start\tg\t0\t0 0 0", "frame\t1.5\t0 0 100", "state", "frame\t0.1\t0 0 100", "state")
    assert close(out["o"][0], (5, -5, 0)), out
    assert close(out["o"][1], (0, 0, 0)), out


LIGHT = "key\tDynaLight\t1\t0\t1\tck=0,0.5,0.25,1,0.5,1,0.5,0.25,1,0.5\tsk=0,150,1,150"


def test_a_light_is_its_colour_times_its_alpha_in_bytes_with_its_scale_as_radius(run):
    # (0.5, 0.25, 1) x (1 - 0.5), truncated to bytes: 63, 31, 127.
    out = run("group\tg\t10", LIGHT + "\toffset=0,10,0", "start\tg\t0\t5 0 0", "frame\t0.1\t0 0 0", "state")
    (l,) = out["l"]
    assert l == dict(pos=(5, 10, 0), rgb=(63, 31, 127), radius=150), l


def test_flicker_scales_the_colour_by_0_3_to_0_49(run):
    # Random 0.5: 0.3 + 0.095 = 0.395 -> 0.0988, 0.0494, 0.1975 -> 25, 12, 50.
    out = run("group\tg\t10", LIGHT + "\tFlicker=200", "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 0", "state")
    assert out["l"][0]["rgb"] == (25, 12, 50), out


def test_a_light_shutting_down_has_no_radius(run):
    out = run("group\tg\t10", LIGHT.replace("\t0\t1\t", "\t0\t10\t"), "start\tg\t1\t0 0 0", "frame\t0.1\t0 0 0",
              "stop", "frame\t0.1\t0 0 0", "state")
    assert out["l"] == [] or out["l"][0]["radius"] == 0, out


def test_a_model_gets_a_d3d_point_light(run):
    # 1 / (1 + 19 x 50^2 / 100^2) = 0.1739; nothing at the radius.
    out = run("sample\t0 0 0\t100\t200 100 50\t50 0 0", "sample\t0 0 0\t100\t200 100 50\t0 100 0")
    assert close(out["s"][0], (34.783, 17.391, 8.696)), out
    assert out["s"][1] == (0, 0, 0), out


def test_a_lit_sprite_gets_2c_minus_255_by_linear_falloff_toned_down(run):
    # 0.7 x (1 - 50 / 100) = 0.35: (400 - 255, 200 - 255, 100 - 255) x 0.35. A dim light darkens.
    out = run("spriteadd\t0 0 0\t100\t200 100 50\t0 0 50", "spriteadd\t0 0 0\t100\t200 100 50\t0 0 100")
    assert close(out["s"][0], (50.75, -19.25, -54.25)), out
    assert out["s"][1] == (0, 0, 0), out


NULL = "key\tNull\t1\t0\t10\tMinVelocity=0,0,0\tMaxVelocity=20,0,0\tGravityAcceleration=0"


def test_a_null_moves_by_its_velocity_from_where_it_was_made(run):
    # Random 0.5: velocity (10, 0, 0). The offset isn't where it starts.
    out = run("group\tg\t10", NULL + "\toffset=0,50,0", "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 0", "state")
    assert close(out["n"][0], (1, 0, 0)), out


def test_null_gravity_is_per_update_not_per_second(run):
    # Velocity (0, 0, 0); each update (the start's included) adds -500 to y after the move.
    key = NULL.replace("MaxVelocity=20,0,0", "MaxVelocity=0,0,0").replace("Acceleration=0", "Acceleration=-500")
    one = run("group\tg\t10", key, "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 0", "state")
    two = run("group\tg\t10", key, "start\tg\t0\t0 0 0", "frame\t0.05\t0 0 0", "frame\t0.05\t0 0 0", "state")
    assert close(one["n"][0], (0, -50, 0)), one
    assert close(two["n"][0], (0, -75, 0)), two


def test_a_bouncing_null_turns_off_the_wall_at_three_quarters_speed(run):
    # Velocity (100, 0, 0) heads through the wall at x = 5: reflected to (-75, 0, 0) before the move.
    key = NULL.replace("MaxVelocity=20,0,0", "MaxVelocity=200,0,0") + "\tBounce=1"
    out = run("wall\t5", "group\tg\t10", key, "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 0", "state")
    assert close(out["n"][0], (-7.5, 0, 0)), out


def test_what_is_linked_to_a_null_follows_it(run):
    # The light updates before the null it follows (the game's update order): a frame behind.
    out = run("group\tg\t10", NULL, LIGHT.replace("\t1\t0\t1\t", "\t2\t0\t10\t") + "\tlink=1\tupdatepos=1",
              "start\tg\t0\t0 0 0", "frame\t0.1\t0 0 0", "frame\t0.1\t0 0 0", "state")
    assert close(out["n"][0], (2, 0, 0)), out
    assert close(out["l"][0]["pos"], (1, 0, 0)), out
