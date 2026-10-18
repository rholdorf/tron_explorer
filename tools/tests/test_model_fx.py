"""The LTBModel effect (TronViewer/.../ModelFX.cs) compiled with .NET and driven frame by frame.
Rules: ltjs clientfxdll/ltbmodelfx.cpp (Init, Update, IsFinishedShuttingDown), the engine's anim tracker
(animtracker.cpp: no looping, stopped past the last key) and docs/research/clientfx-types.md on
research/clientfx-types. Expected values are worked by hand from them.

Driver lines (tab-separated):
  group <name> <phase>                  a group; the keys after it are its keys
  model <id> <start> <end> <clip> [k=v]...
                                        an LTBModel key whose model's clip lasts <clip> s (-1: no clip); rotadd,
                                        offset, ck, sk as comma lists, any other k a number or a vector
  start <group> <loop> <x y z> [yaw]    an instance at an object there (yaw in degrees)
  cam <yaw>                             the camera's rotation (degrees)
  stop                                  every instance shuts down smoothly
  frame <dt>                            the manager's update
  state                                 "m <id> <visible> <pos> <forward> <up> <scale> <a> <anim time>" per model
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
        var clips = new System.Collections.Generic.Dictionary<FxKey, float>();
        mgr.Types["LTBModel"] = k => new FxModel(mgr, clips[k]);
        FxGroup g = null;
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
                case "model":
                {
                    var k = new FxKey { Type = "LTBModel", Id = int.Parse(a[1]), Start = F(a[2]), End = F(a[3]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    k.Nums["Facing"] = new[] { 2f };
                    clips[k] = F(a[4]);
                    foreach (var kv in a.Skip(5).Select(s => s.Split('=')))
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
                    break;
                case "state":
                    foreach (var inst in mgr.Instances)
                        foreach (var m in inst.Effects.OfType<FxModel>())
                            Console.WriteLine($"m\t{m.Key.Id}\t{(m.Visible ? 1 : 0)}\t{V(m.Pos)}\t{V(m.Rot.Forward())}\t{V(m.Rot.Up())}\t{N(m.Scale)}\t{N(m.A)}\t{N(m.AnimTime)}");
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "models", DRIVER, "ClientFX.cs", "ModelFX.cs", "Commands.cs",
                       "KeyframerMotion.cs")

    def go(*lines):
        out = [l.split("\t") for l in drive("\n".join(lines) + "\n").splitlines()]
        return [dict(id=int(r[1]), visible=r[2] == "1", pos=vec(r[3]), fwd=vec(r[4]), up=vec(r[5]),
                     scale=float(r[6]), a=float(r[7]), anim=float(r[8])) for r in out if r[0] == "m"]
    return go


def vec(s):
    return tuple(float(x) for x in s.split())


def close(a, b, tol=1e-3):
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


@pytest.mark.parametrize("normal, yaw, fwd", [
    ("0,0,1", 0, (0, 0, 1)),
    ("0,0,1", 90, (1, 0, 0)),     # the parent's rotation
    ("1,0,0", 0, (1, 0, 0)),      # turned to Normal
    ("0,1,0", 90, (0, 1, 0)),
])
def test_parent_align_faces_the_parent_turned_to_normal(run, normal, yaw, fwd):
    (m,) = run("group\tg\t10", f"model\t1\t0\t10\t-1\tNormal={normal}", f"start\tg\t1\t0 0 0\t{yaw}",
               "frame\t0.1", "state")
    assert close(m["fwd"], fwd), m


def test_offset_turns_with_the_object(run):
    # Init: m_vPos = create pos + rotation x offset; the base then keeps it in the parent's axes.
    (m,) = run("group\tg\t10", "model\t1\t0\t10\t-1\toffset=0,0,10", "start\tg\t1\t5 0 0\t90", "frame\t0.1", "state")
    assert close(m["pos"], (15, 0, 0)), m


def test_camera_facing_faces_the_camera(run):
    (m,) = run("group\tg\t10", "model\t1\t0\t10\t-1\tFacing=0", "cam\t-90", "start\tg\t1\t0 0 0\t90",
               "frame\t0.1", "state")
    assert close(m["fwd"], (-1, 0, 0)), m


def test_along_normal_with_a_parent_loses_the_normal(run):
    # Init turns it to Normal; the base update then sets the parent's rotation (ltjs as written).
    (m,) = run("group\tg\t10", "model\t1\t0\t10\t-1\tFacing=1\tNormal=1,0,0", "start\tg\t1\t0 0 0",
               "frame\t0.1", "state")
    assert close(m["fwd"], (0, 0, 1)), m


def test_rotate_add_spins_in_degrees_per_second(run):
    # 90 degrees a second about up, on the parent's rotation: after 1 s the forward is the parent's right.
    (m,) = run("group\tg\t10", "model\t1\t0\t10\t-1\trotadd=0,90,0", "start\tg\t1\t0 0 0",
               "frame\t0.5", "frame\t0.5", "state")
    assert close(m["fwd"], (1, 0, 0)) and close(m["up"], (0, 1, 0)), m


def test_ck_alpha_and_sk_scale(run):
    # Ck a is a transparency (drawn 1 - a), Sk a uniform scale, both over the key's life.
    (m,) = run("group\tg\t10", "model\t1\t0\t10\t-1\tck=0,1,1,1,0,1,1,1,1,1\tsk=0,1,1,3",
               "start\tg\t1\t0 0 0", "frame\t5", "state")
    assert close((m["a"], m["scale"]), (0.5, 2)), m


def test_clip_plays_once_then_restarts(run):
    # The tracker runs after the effect's update and stops at the end; the next update restarts it.
    lines = ["group\tg\t10", "model\t1\t0\t10\t1", "start\tg\t1\t0 0 0"]
    for _ in range(4):
        lines += ["frame\t0.4", "state"]
    times = [m["anim"] for m in run(*lines)]
    assert close(times, (0.4, 0.8, 1.0, 0.4)), times


def test_override_ani_length_stretches_the_clip(run):
    # rate = clip length / AniLength (the key's lifespan when 0).
    (a,) = run("group\tg\t10", "model\t1\t0\t10\t1\tOverrideAniLength=1\tAniLength=2", "start\tg\t1\t0 0 0",
               "frame\t1", "state")
    (b,) = run("group\tg\t10", "model\t1\t0\t4\t1\tOverrideAniLength=1", "start\tg\t1\t0 0 0", "frame\t1", "state")
    assert close((a["anim"], b["anim"]), (0.5, 0.25)), (a, b)


def test_sync_to_key_scrubs_the_clip_with_the_key(run):
    # Before the base update: time = (key time / lifespan wrapped) x (length - 1 ms), whole ms; then the
    # tracker runs on by the frame.
    ms = run("group\tg\t2", "model\t1\t0\t2\t1\tSyncToKey=1", "start\tg\t1\t0 0 0",
             "frame\t0.5", "state", "frame\t0.5", "state")
    assert close([m["anim"] for m in ms], (0.5, 0.249 + 0.5)), ms


def test_smooth_shutdown_waits_for_the_clip(run):
    lines = ["group\tg\t10", "model\t1\t0\t10\t1", "start\tg\t1\t0 0 0", "frame\t0.4", "stop"]
    for _ in range(3):
        lines += ["frame\t0.4", "state"]
    ms = run(*lines)
    assert [m["anim"] for m in ms] == [0.8, 1.0], ms   # gone on the frame after the clip ends


def test_sync_to_key_shuts_down_at_once(run):
    assert run("group\tg\t10", "model\t1\t0\t10\t1\tSyncToKey=1", "start\tg\t1\t0 0 0", "frame\t0.4", "stop",
               "state") == []
