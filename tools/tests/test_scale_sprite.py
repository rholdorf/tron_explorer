"""The ScaleSprite object (TronViewer/.../ScaleSprite.cs) compiled with .NET. Rules: ltjs objectdll
scalesprite.cpp (ReadProp, OnTrigger, SetDamaged, SetDestroyed), gamebase.cpp through GameBaseFlags,
render_a drawsprite.cpp d3d_GetSpriteColor and clientshelldll lensflarefx.cpp, worked by hand.

Driver lines (tab-separated):
  make [k=v]...    a ScaleSprite at the origin facing +z: startOn, color (r,g,b 0-255), light (r,g,b), flare (1:
                   CreateSprite with MinAngle 18, alpha 0-1, scale 1-1.75, offset -8), damaged, destroyed
  msg <words>      a message: its own handler, then GameBase's ("unhandled" if neither takes it)
  cam <x y z>      the camera there looking down +z; the sprite updates
  state            "s <shown> <file> <r g b a> <blend> <rotatable>" and, with a flare, "f <shown> <scale> <pos>"
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
    static LTVec Vec(string s) { var p = s.Split(' ', ',').Select(F).ToArray(); return new LTVec(p[0], p[1], p[2]); }
    static void Main()
    {
        ScaleSprite s = null;
        GameBaseFlags flags = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "make":
                {
                    var p = new ScaleSprite.Props { File = "on.spr", ScaleX = 1, ScaleY = 1, Alpha = 1, Color = new LTVec(255, 255, 255),
                        Additive = true, Rotatable = true, Glow = true, ZBias = true, StartOn = true };
                    var light = default(LTVec);
                    foreach (var kv in a.Skip(1).Select(x => x.Split('=')))
                        switch (kv[0])
                        {
                            case "startOn": p.StartOn = kv[1] == "1"; break;
                            case "color": p.Color = Vec(kv[1]); break;
                            case "light": light = Vec(kv[1]); break;
                            case "damaged": p.Damaged = kv[1]; break;
                            case "destroyed": p.Destroyed = kv[1]; break;
                            case "flare":
                                p.CreateSprite = true; p.FlareFile = "flare.spr"; p.FlareAdditive = true; p.MinAngle = 18;
                                p.MinAlpha = 0; p.MaxAlpha = 1; p.MinScale = 1; p.MaxScale = 1.75f; p.Offset = -8;
                                break;
                        }
                    flags = new GameBaseFlags(p.StartOn, false, false);
                    s = new ScaleSprite(p, new LTVec(0, 0, 100), new LTQuat(0, 0, 0, 1), light, flags);
                    s.RemoveObject = () => flags.OnMessage(new Message(new[] { "REMOVE" }, -1));
                    break;
                }
                case "msg":
                {
                    var m = new Message(a[1].Split(' '), -1);
                    if (!s.OnMessage(m) && !flags.OnMessage(m)) Console.WriteLine("unhandled");
                    break;
                }
                case "cam":
                    s.Update(new LTVec(0, 0, 100), new LTQuat(0, 0, 0, 1), Vec(a[1]), new LTVec(0, 0, 1));
                    break;
                case "state":
                {
                    var t = s.Sprite;
                    Console.WriteLine($"s {(t.Shown ? 1 : 0)} {t.File} {N(t.R)} {N(t.G)} {N(t.B)} {N(t.A)} {t.Blend} {(t.Rotatable ? 1 : 0)}");
                    if (s.Flare != null) Console.WriteLine($"f {(s.Flare.Shown ? 1 : 0)} {N(s.Flare.ScaleX)} {V(s.Flare.Pos)}");
                    break;
                }
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "scalesprite", DRIVER, "ScaleSprite.cs", "Sprites.cs", "GameBaseFlags.cs",
                      "KeyframerMotion.cs", "Commands.cs")
    return lambda *lines: drive("\n".join(lines) + "\n").splitlines()


def test_start_on_shows_it_and_its_props_draw(run):
    assert run("make", "state") == ["s 1 on.spr 1 1 1 1 1 1"]
    assert run("make\tstartOn=0", "state") == ["s 0 on.spr 1 1 1 1 1 1"]


def test_on_and_off_and_hidden_share_the_visible_flag(run):
    out = run("make\tstartOn=0", "msg\tON", "state", "msg\tHIDDEN 1", "state", "msg\tON", "state", "msg\tOFF",
              "msg\tHIDDEN 0", "state")
    # HIDDEN 0 restores what the object had at its first GameBase message (HIDDEN 1, when ON had shown it).
    assert [o.split()[1] for o in out] == ["1", "0", "1", "1"]


def test_light_adds_to_its_colour_clamped(run):
    # d3d_GetSpriteColor without FLAG_NOLIGHT: colour + light table, clamped to 255.
    (o,) = run("make\tcolor=64,128,255\tlight=64,200,10", "state")
    assert o.split()[3:6] == [str(round(128 / 255, 3)), "1", "1"]


def test_damage_swaps_and_destroy_swaps_or_removes(run):
    out = run("make\tdamaged=dmg.spr", "msg\tDAMAGE", "state", "msg\tDESTROY", "state")
    assert [o.split()[:3] for o in out] == [["s", "1", "dmg.spr"], ["s", "0", "dmg.spr"]]   # no destroyed file: removed
    out = run("make\tdestroyed=gone.spr", "msg\tDAMAGE", "state", "msg\tDESTROY", "state")
    assert [o.split()[2] for o in out] == ["on.spr", "gone.spr"]   # no damaged file: DAMAGE does nothing


def test_removed_takes_every_message_and_shows_nothing(run):
    out = run("make", "msg\tREMOVE", "msg\tON", "state")
    assert out == ["s 0 on.spr 1 1 1 1 1 1"]


def test_other_words_are_not_its_own(run):
    assert run("make", "msg\tTOGGLE") == ["unhandled"]


def test_flare_shows_when_looked_at_and_hides_with_the_object(run):
    out = run("make\tflare=1", "cam\t0 0 0", "state", "cam\t100 0 90", "state", "msg\tOFF", "cam\t0 0 0", "state")
    assert out[1] == "f 1 1.75 0 0 92"   # straight ahead: full scale, 8 units behind the object's forward
    assert out[3].split()[1] == "0"      # off to the side
    assert out[5].split()[1] == "0"      # the object is off
