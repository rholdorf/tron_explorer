"""The SpriteSystem effect (TronViewer/.../SpriteSystemFX.cs) compiled with .NET and driven frame by frame. Rules:
ltjs clientfxdll/spritesystemfx.cpp (ParseProperties, Init, Update, AddSprites, UpdateSprites, Render,
SetupParticle), worked by hand.

Driver lines (tab-separated):
  rand <a,b,...>                  the manager's random numbers, in turn, over and over (default 0.5)
  group <name> <phase>            a group; the keys after it are its keys
  key <id> <start> <end> [k=v]... a SpriteSystem key: ck, sk, rotateadd as comma lists, updatepos, s:<text> a
                                  string, any other value a number. Its sprite file is 16 x 32 texels, 3 frames of 100 ms.
  start <group> <loop> <x y z>    an instance at an object there
  move <x y z>                    the object moves
  frame <dt>                      the manager's update
  stop                            every instance shuts down smoothly
  render                          "m <blend> <count>" per effect, then "q <x y z> <rgba> <u v> <frame>" per vertex,
                                  the camera at the origin looking down +z (right +x, up +y)
"""
import math

import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Collections.Generic;
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
        var file = new FxSpriteSystem.SpriteFile { Frames = 3, LengthMs = 300, Width = 16, Height = 32 };
        mgr.Types["SpriteSystem"] = k => new FxSpriteSystem(mgr, f => file);
        FxGroup g = null;
        Obj obj = null;
        var cam = new PrimCamera { Right = new LTVec(1, 0, 0), Up = new LTVec(0, 1, 0), Forward = new LTVec(0, 0, 1) };
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
                    var k = new FxKey { Type = "SpriteSystem", Id = int.Parse(a[1]), Start = F(a[2]), End = F(a[3]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    k.Strs["Sprite"] = "fx/spr/x.spr";
                    foreach (var kv in a.Skip(4).Select(s => s.Split(new[] { '=' }, 2)))
                    {
                        var v = kv[1];
                        if (kv[0] == "ck") k.Ck = Fs(v);
                        else if (kv[0] == "sk") k.Sk = Fs(v);
                        else if (kv[0] == "updatepos") k.UpdatePos = int.Parse(v);
                        else if (kv[0] == "rotateadd") { var r = Fs(v); k.RotateAdd = new LTVec(r[0], r[1], r[2]); }
                        else if (v.StartsWith("s:")) k.Strs[kv[0]] = v.Substring(2);
                        else k.Nums[kv[0]] = Fs(v);
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "start":
                    obj = new Obj { Pos = Vec(a[3]) };
                    mgr.Start(a[1], a[2] == "1", true, obj);
                    break;
                case "move":
                    obj.Pos = Vec(a[1]);
                    break;
                case "frame":
                    mgr.Update(F(a[1]), default);
                    break;
                case "stop":
                    foreach (var inst in mgr.Instances.ToArray()) mgr.ShutDown(inst);
                    break;
                case "render":
                    foreach (var inst in mgr.Instances)
                        foreach (var s in inst.Effects.OfType<FxSpriteSystem>())
                        {
                            Console.WriteLine($"m\t{s.BlendMode}\t{s.Count}");
                            if (!s.Visible) continue;
                            var q = new List<PrimVert>();
                            s.Render(cam, q);
                            for (int i = 0; i < q.Count; i++)
                                Console.WriteLine($"q\t{V(q[i].Pos)}\t{q[i].Color:x8}\t{N(q[i].U)} {N(q[i].V)}\t{s.QuadFrame(i / 4)}");
                        }
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "sprite_system", DRIVER, "ClientFX.cs", "DrawPrimFX.cs", "SpriteSystemFX.cs",
                       "Commands.cs", "KeyframerMotion.cs")

    def go(*lines):
        out = {"m": [], "q": []}
        for l in drive("\n".join(lines) + "\n").splitlines():
            r = l.split("\t")
            if r[0] == "m":
                out["m"].append((int(r[1]), int(r[2])))
            else:
                out["q"].append(dict(pos=vec(r[1]), rgba=r[2], uv=vec(r[3]), frame=int(r[4])))
        return out
    return go


def vec(s):
    return tuple(float(x) for x in s.split())


def close(a, b, tol=1e-3):
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


def centres(q):
    return [tuple(sum(v["pos"][i] for v in q[n:n + 4]) / 4 for i in range(3)) for n in range(0, len(q), 4)]


# Sprites made where the effect is, still, unturned, living 2 s.
STILL = "MinRadius=0\tMaxRadius=0\tMinSpriteVelocity=0,0,0\tMaxSpriteVelocity=0,0,0\tGravityAcceleration=0\t" \
        "MinSpriteRotation=0,0,0\tMaxSpriteRotation=0,0,0\tMinSpriteLifespan=2\tMaxSpriteLifespan=2"
KEY = "key\t1\t0\t10\t" + STILL + "\tSpritesPerEmission=3\tEmissionInterval=1"


def test_a_burst_on_the_first_frame_and_one_every_interval(run):
    out = run("group\tg\t20", KEY, "start\tg\t0\t0 0 100", "render", "frame\t0.5", "render", "frame\t0.6", "render")
    assert [c for _, c in out["m"]] == [3, 3, 6], out["m"]


def test_sprites_die_at_the_end_of_their_life_and_a_shut_down_system_waits_for_them(run):
    key = KEY.replace("EmissionInterval=1", "EmissionInterval=0")
    out = run("group\tg\t20", key, "start\tg\t1\t0 0 100", "frame\t1", "stop", "render", "frame\t0.5", "render",
              "frame\t0.6", "render")
    assert [c for _, c in out["m"]] == [3, 3], out["m"]


def test_a_sprite_is_a_camera_quad_stretched_by_the_texture_and_the_key(run):
    # Sk 2, StretchU 0.5, StretchV 40, 16 x 32 texels: half-width 2 x 0.5 = 1, half-height 2 x 2 x 40 = 160.
    key = KEY.replace("SpritesPerEmission=3", "SpritesPerEmission=1") + "\tsk=0,2,1,2\tStretchU=0.5\tStretchV=40"
    out = run("group\tg\t20", key, "start\tg\t0\t0 0 100", "render")
    assert [(v["pos"], v["uv"]) for v in out["q"]] == [
        ((-1, 160, 100), (0, 0)), ((1, 160, 100), (1, 0)), ((1, -160, 100), (1, 1)), ((-1, -160, 100), (0, 1))]


def test_ck_and_sk_run_over_each_sprites_own_life(run):
    # Half of a 2 s life: colour 0.5 and alpha 1 - 0.5 -> 127 each; scale 1 -> 3 at half is 2: half-width 2,
    # half-height 2 x 32 / 16 = 4.
    key = KEY.replace("SpritesPerEmission=3", "SpritesPerEmission=1") + \
        "\tck=0,1,0.5,0,0,1,0,0.5,1,1\tsk=0,1,1,3"
    out = run("group\tg\t20", key, "start\tg\t0\t0 0 100", "frame\t1", "render")
    first = [v for v in out["q"]][:4]
    assert {v["rgba"] for v in first} == {"7f7f7f7f"}, first
    assert close(first[1]["pos"], (2, 4, 100)), first


def test_additive_or_normal_blend(run):
    out = run("group\tg\t20", KEY + "\tAType=1", KEY.replace("key\t1", "key\t2"), "start\tg\t0\t0 0 100", "render")
    assert sorted(b for b, _ in out["m"]) == [3, 7], out["m"]


def test_sprites_behind_the_camera_are_not_drawn(run):
    out = run("group\tg\t20", KEY, "start\tg\t0\t0 0 -10", "render")
    assert out["m"][0][1] == 3 and out["q"] == [], out


def test_sprites_move_then_gain_gravity_per_second(run):
    key = KEY.replace("GravityAcceleration=0", "GravityAcceleration=20").replace("SpritesPerEmission=3",
                                                                                 "SpritesPerEmission=1")
    out = run("group\tg\t20", key, "start\tg\t0\t0 0 100", "frame\t0.9", "frame\t0.5", "render")
    # 0.9 s: still (velocity was 0), then 18; 0.5 s more: 9 up. The second burst, made in that update, is moved
    # by its velocity then, 0.
    ys = sorted(c[1] for c in centres(out["q"]))
    assert close(ys, [0, 9]), ys


def test_a_cylinder_places_sprites_within_min_radius_of_the_axis_up_to_max_radius_along_it(run):
    # Plane (0, 1, 0): perpendiculars (0, 0, -1) and (-1, 0, 0). Random 0.75, 0.5 -> (0, 0, -0.5) normalised,
    # times Rand(0, 60) = 30, plus the plane times Rand(0, 200) = 100. Eleven draws per sprite.
    key = KEY.replace("MinRadius=0\tMaxRadius=0", "MinRadius=60\tMaxRadius=200").replace(
        "SpritesPerEmission=3", "SpritesPerEmission=1") + "\tEmissionType=4"
    out = run("rand\t0.75,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5", "group\tg\t20", key, "start\tg\t0\t0 0 100",
              "render")
    assert close(centres(out["q"])[0], (0, 100, 70)), centres(out["q"])


def test_sprites_stay_where_they_were_made(run):
    # Following its object, the effect moves; its sprites don't.
    out = run("group\tg\t20", KEY.replace("SpritesPerEmission=3", "SpritesPerEmission=1") + "\tupdatepos=1",
              "start\tg\t0\t0 0 100",
              "move\t50 0 100", "frame\t1", "render")
    xs = sorted(c[0] for c in centres(out["q"]))
    assert close(xs, [0, 50]), xs


def test_frames_run_over_the_sprite_files_length(run):
    # SpriteDefault: 3 frames / (300 ms / 3) = 0.03 "length"; frame = (int)(3 x age / 0.03) % 3. ParticleLife:
    # the length is the sprite's life (2 s): at 1 s, (int)(3 x 1 / 2) = 1.
    key = KEY.replace("SpritesPerEmission=3", "SpritesPerEmission=1").replace("EmissionInterval=1",
                                                                              "EmissionInterval=0")
    life = run("group\tg\t20", key + "\tAnimationLength=1", "start\tg\t0\t0 0 100", "frame\t1", "render")
    assert life["q"][0]["frame"] == 1, life["q"]
    dflt = run("group\tg\t20", key, "start\tg\t0\t0 0 100", "frame\t0.015", "render")
    assert dflt["q"][0]["frame"] == 1, dflt["q"]
