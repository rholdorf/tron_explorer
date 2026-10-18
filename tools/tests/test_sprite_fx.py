"""The Sprite effect (TronViewer/.../SpriteFX.cs) compiled with .NET and driven frame by frame.
Rules: ltjs clientfxdll/spritefx.cpp (ParseProperties, Init, Update), basefx.h SetVisible (FLAG_VISIBLE only),
drawsprite.cpp d3d_GetSpriteColor and docs/research/clientfx-types.md on research/clientfx-types. Expected
values are worked by hand from them.

Driver lines (tab-separated):
  group <name> <phase>                  a group; the keys after it are its keys
  sprite <id> <start> <end> [k=v]...    a Sprite key (additive, ZBias, CameraFacing unless set); rotadd,
                                        offset, ck, sk as comma lists, any other k a number or a vector
  start <group> <loop> <x y z> [yaw]    an instance at an object there (yaw in degrees)
  cam <yaw>                             the camera's rotation (degrees)
  stop                                  every instance shuts down smoothly
  frame <dt>                            the manager's update, then a draw (a restarted sprite's Born is set)
  state                                 "s <id> <shown> <pos> <forward> <up> <scale> <r g b a> <blend>
                                        <rotatable> <zbias> <fog> <restarted>" per sprite; the light grid is
                                        (51, 102, 0) everywhere
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
    public LTQuat Rot { get; set; }
    public bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot) { pos = default; rot = default; return false; }
}
static class Driver
{
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    static float F(string s) => float.Parse(s, Inv);
    static string N(float v) => (Math.Abs(v) < 0.0005f ? 0f : v).ToString("0.###", Inv);
    static string V(LTVec v) => $"{N(v.x)} {N(v.y)} {N(v.z)}";
    static float[] Fs(string s) => s.Split(',').Select(F).ToArray();
    static LTQuat Yaw(float deg) => LTQuat.FromEuler(0, deg * (float)Math.PI / 180, 0);
    static void Main()
    {
        var mgr = new ClientFXMgr(() => 0.5);
        mgr.Types["Sprite"] = k => new FxSprite(mgr, p => new LTVec(51, 102, 0));
        FxGroup g = null;
        var restarted = new System.Collections.Generic.HashSet<FxSprite>();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "group":
                    g = new FxGroup { Name = a[1], Phase = F(a[2]) };
                    mgr.Add(g);
                    break;
                case "sprite":
                {
                    var k = new FxKey { Type = "Sprite", Id = int.Parse(a[1]), Start = F(a[2]), End = F(a[3]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    k.Strs["Sprite"] = "fx/spr/sphereadd.spr";
                    k.Nums["BlendMode"] = new[] { 1f };
                    k.Nums["DisableLight"] = new[] { 1f };
                    k.Nums["ZBias"] = new[] { 1f };
                    foreach (var kv in a.Skip(4).Select(s => s.Split('=')))
                    {
                        var v = kv[1];
                        if (kv[0] == "ck") k.Ck = Fs(v);
                        else if (kv[0] == "sk") k.Sk = Fs(v);
                        else if (kv[0] == "rotadd") { var r = Fs(v); k.RotateAdd = new LTVec(r[0], r[1], r[2]); }
                        else if (kv[0] == "offset") { var r = Fs(v); k.Offset = new LTVec(r[0], r[1], r[2]); }
                        else k.Nums[kv[0]] = Fs(v);
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "start":
                {
                    var p = a[3].Split(' ').Select(F).ToArray();
                    var o = new Obj { Pos = new LTVec(p[0], p[1], p[2]), Rot = Yaw(a.Length > 4 ? F(a[4]) : 0) };
                    mgr.Start(a[1], a[2] == "1", true, o);
                    break;
                }
                case "cam":
                    mgr.CameraRot = Yaw(F(a[1]));
                    break;
                case "stop":
                    foreach (var inst in mgr.Instances.ToArray()) mgr.ShutDown(inst);
                    break;
                case "frame":
                    mgr.Update(F(a[1]), default);
                    restarted.Clear();
                    foreach (var inst in mgr.Instances)
                        foreach (var sp in inst.Effects.OfType<FxSprite>())
                            if (double.IsNaN(sp.Sprite.Born)) { restarted.Add(sp); sp.Sprite.Born = 0; }
                    break;
                case "state":
                    foreach (var inst in mgr.Instances)
                        foreach (var sp in inst.Effects.OfType<FxSprite>())
                        {
                            var s = sp.Sprite;
                            Console.WriteLine($"s\t{sp.Key.Id}\t{(s.Shown ? 1 : 0)}\t{V(s.Pos)}\t{V(s.Rot.Forward())}\t{V(s.Rot.Up())}\t{N(s.ScaleX)}\t{N(s.R)} {N(s.G)} {N(s.B)} {N(s.A)}\t{s.Blend}\t{(s.Rotatable ? 1 : 0)}\t{(s.ZBias ? 1 : 0)}\t{(s.Fog ? 1 : 0)}\t{(restarted.Contains(sp) ? 1 : 0)}");
                        }
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "sprites", DRIVER, "ClientFX.cs", "SpriteFX.cs", "Sprites.cs",
                       "Commands.cs", "KeyframerMotion.cs")

    def go(*lines):
        out = [l.split("\t") for l in drive("\n".join(lines) + "\n").splitlines()]
        return [dict(id=int(r[1]), shown=r[2] == "1", pos=vec(r[3]), fwd=vec(r[4]), up=vec(r[5]),
                     scale=float(r[6]), rgba=vec(r[7]), blend=int(r[8]), rotatable=r[9] == "1",
                     zbias=r[10] == "1", fog=r[11] == "1", restarted=r[12] == "1") for r in out if r[0] == "s"]
    return go


def vec(s):
    return tuple(float(x) for x in s.split())


def close(a, b, tol=1e-3):
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


def test_camera_facing_is_a_fogged_additive_billboard(run):
    (s,) = run("group\tg\t10", "sprite\t1\t0\t10", "start\tg\t1\t0 0 0", "frame\t0.1", "state")
    assert s["shown"] and not s["rotatable"] and s["zbias"] and s["fog"] and s["blend"] == 1, s


def test_ck_colours_it_and_sk_sizes_it(run):
    # Halfway through the key: Ck from (1, 0, 0, a 0) to (0, 1, 0, a 1), Sk from 1 to 3. Unlit (NOLIGHT).
    (s,) = run("group\tg\t10", "sprite\t1\t0\t10\tck=0,1,0,0,0,1,0,1,0,1\tsk=0,1,1,3", "start\tg\t1\t0 0 0",
               "frame\t5", "state")
    assert close(s["rgba"], (0.5, 0.5, 0, 0.5)) and math.isclose(s["scale"], 2, abs_tol=1e-3), s


@pytest.mark.parametrize("facing, normal, yaw, fwd", [
    (2, "0,0,1", 90, (1, 0, 0)),     # ParentAlign: the parent's rotation
    (2, "1,0,0", 0, (1, 0, 0)),      # turned to Normal
    (2, "1,0,0", 90, (0, 0, -1)),
    (1, "1,0,0", 90, (1, 0, 0)),     # AlongNormal: the base gives the parent's rotation
])
def test_facings_other_than_the_camera_are_rotatable(run, facing, normal, yaw, fwd):
    (s,) = run("group\tg\t10", f"sprite\t1\t0\t10\tFacing={facing}\tNormal={normal}", f"start\tg\t1\t0 0 0\t{yaw}",
               "frame\t0.1", "state")
    assert s["rotatable"] and close(s["fwd"], fwd), s


def test_offset_turns_with_the_parent(run):
    (s,) = run("group\tg\t10", "sprite\t1\t0\t10\toffset=0,0,10", "start\tg\t1\t5 0 0\t90", "frame\t0.1", "state")
    assert close(s["pos"], (15, 0, 0)), s


def test_rotate_add_spins_a_camera_facing_sprite_on_the_camera(run):
    # Ring192Derez: CameraFacing, RotateAdd z 90 deg/s. Rotatable, the camera's rotation then the spin about
    # its forward: after 1 s the up axis has turned a quarter.
    (s,) = run("group\tg\t10", "sprite\t1\t0\t10\trotadd=0,0,90", "cam\t90", "start\tg\t1\t0 0 0", "frame\t0.5",
               "frame\t0.5", "state")
    assert s["rotatable"] and close(s["fwd"], (1, 0, 0)), s
    assert close([abs(x) for x in s["up"]], (0, 0, 1)), s


def test_rotate_add_with_parent_align_spins_on_the_parent_turned_to_normal(run):
    # Energy_Field: ParentAlign, Normal (1, 0, 0), RotateAdd x 180 deg/s: parent x spin x normal. After 1 s,
    # a half turn about x: the normal (forward) stays on x, its up flips.
    (s,) = run("group\tg\t10", "sprite\t1\t0\t10\tFacing=2\tNormal=1,0,0\trotadd=180,0,0", "start\tg\t1\t0 0 0",
               "frame\t0.5", "frame\t0.5", "state")
    assert close(s["fwd"], (1, 0, 0)), s
    assert close(s["up"], (0, -1, 0)), s


def test_a_sprite_that_takes_light_adds_the_grid(run):
    # BlendMode None, DisableLight off: colour (0.5, 0.5, 0.5) x 255 + (51, 102, 0), clamped, / 255.
    (s,) = run("group\tg\t10", "sprite\t1\t0\t10\tBlendMode=0\tDisableLight=0\tck=0,0.5,0.5,0.5,0,1,0.5,0.5,0.5,0",
               "start\tg\t1\t0 0 0", "frame\t0.1", "state")
    assert s["blend"] == 0 and close(s["rgba"], (0.7, 0.9, 0.5, 1)), s


def test_frames_start_over_on_each_initial_frame(run):
    rows = run("group\tg\t2", "sprite\t1\t0.5\t1", "start\tg\t1\t0 0 0", "frame\t0.6", "state", "frame\t0.1",
               "state", "frame\t1.9", "state")
    assert [r["restarted"] for r in rows] == [True, False, True], rows


def test_shutting_down_hides_it_at_once(run):
    rows = run("group\tg\t10", "sprite\t1\t0\t10", "start\tg\t1\t0 0 0", "frame\t0.1", "stop", "frame\t0.1",
               "state")
    assert rows == [], rows


def test_a_loop_that_starts_it_again_only_sets_it_visible(run):
    # A key from 0.5 to 1 in a 2 s loop: hidden from 1 (every flag cleared), shown at 2.5 again with only
    # FLAG_VISIBLE: lit by the grid (no FLAG_NOLIGHT), unbiased, a billboard. Additive stays (Flags2).
    rows = run("group\tg\t2", "sprite\t1\t0.5\t1\tFacing=2\tck=0,0.2,0.2,0.2,0,1,0.2,0.2,0.2,0",
               "start\tg\t1\t0 0 0", "frame\t0.6", "state", "frame\t0.6", "state", "frame\t1.4", "state")
    first, gone, again = rows
    assert first["shown"] and first["rotatable"] and first["zbias"] and close(first["rgba"], (0.2, 0.2, 0.2, 1))
    assert not gone["shown"]
    assert again["shown"] and not again["rotatable"] and not again["zbias"] and again["blend"] == 1
    assert close(again["rgba"], (0.4, 0.6, 0.2, 1)), again
