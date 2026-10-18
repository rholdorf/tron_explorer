"""The DrawPrim effects (TronViewer/.../LightningFX.cs, PolyTrailFX.cs, DrawPrimFX.cs) compiled with .NET and
driven frame by frame. Rules: ltjs clientfxdll/lightningfx.cpp (Init, EmitBolts, PreRender, Render) and
polytubefx.cpp (Init, Update, CalcCurWidth, Render), LTVector::Norm, and docs/research/clientfx-types.md on
research/clientfx-types. Expected values are worked by hand from them.

Driver lines (tab-separated):
  rand <a,b,...>                      the manager's random numbers, in turn, over and over (default 0.5)
  group <name> <phase>                a group; the keys after it are its keys
  key <type> <id> <start> <end> [k=v]...
                                      a LightningFX or PolyTrail key; ck, sk, offset as comma lists, updatepos,
                                      s:<text> a string, any other value a number
  start <group> <loop> <x y z>        an instance at an object there
  node <name> <x y z>                 the object has that node (sockets: socket <name> <x y z>)
  move <x y z>                        the object moves
  stop                                every instance shuts down smoothly
  frame <dt>                          the manager's update
  bolts                               "b <points>" per active bolt, points "x y z|..."
  trail                               "t <width> <points>" per trail, points "x y z age u rgba|..."
  render                              "q <x y z> <rgba> <u v>" per vertex, the camera at the origin looking
                                      down +z (right +x, up +y)
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
    public Dictionary<(string, bool), LTVec> At = new Dictionary<(string, bool), LTVec>();
    public bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot)
    {
        rot = Rot;
        return At.TryGetValue((name, socket), out pos);
    }
}
static class Driver
{
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    static float F(string s) => float.Parse(s, Inv);
    static string N(float v) => (Math.Abs(v) < 0.0005f ? 0f : v).ToString("0.###", Inv);
    static string V(LTVec v) => $"{N(v.x)} {N(v.y)} {N(v.z)}";
    static float[] Fs(string s) => s.Split(',').Select(F).ToArray();
    static LTVec Vec(string s) { var p = s.Split(' ').Select(F).ToArray(); return new LTVec(p[0], p[1], p[2]); }
    static void Main()
    {
        double[] rands = { 0.5 };
        int ri = 0;
        var mgr = new ClientFXMgr(() => rands[ri++ % rands.Length]);
        mgr.Types["LightningFX"] = k => new FxLightning(mgr);
        mgr.Types["PolyTrail"] = k => new FxPolyTrail();
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
                    var k = new FxKey { Type = a[1], Id = int.Parse(a[2]), Start = F(a[3]), End = F(a[4]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    foreach (var kv in a.Skip(5).Select(s => s.Split(new[] { '=' }, 2)))
                    {
                        var v = kv[1];
                        if (kv[0] == "ck") k.Ck = Fs(v);
                        else if (kv[0] == "sk") k.Sk = Fs(v);
                        else if (kv[0] == "offset") { var r = Fs(v); k.Offset = new LTVec(r[0], r[1], r[2]); }
                        else if (kv[0] == "updatepos") k.UpdatePos = int.Parse(v);
                        else if (v.StartsWith("s:")) k.Strs[kv[0]] = v.Substring(2);
                        else k.Nums[kv[0]] = Fs(v);
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "node":
                case "socket":
                    obj.At[(a[1], a[0] == "socket")] = Vec(a[2]);
                    break;
                case "start":
                    obj = new Obj { Pos = Vec(a[3]) };
                    mgr.Start(a[1], a[2] == "1", true, obj);
                    break;
                case "move":
                    obj.Pos = Vec(a[1]);
                    break;
                case "stop":
                    foreach (var inst in mgr.Instances.ToArray()) mgr.ShutDown(inst);
                    break;
                case "frame":
                    mgr.Update(F(a[1]), default);
                    break;
                case "bolts":
                    foreach (var inst in mgr.Instances)
                        foreach (var l in inst.Effects.OfType<FxLightning>())
                            foreach (var p in l.ActivePaths)
                                Console.WriteLine("b\t" + string.Join("|", p.Select(V)));
                    break;
                case "trail":
                    foreach (var inst in mgr.Instances)
                        foreach (var t in inst.Effects.OfType<FxPolyTrail>())
                            Console.WriteLine($"t\t{N(t.Width)}\t" + string.Join("|", t.Points.Select(p => $"{V(p.pos)} {N(p.elapsed)} {N(p.u)} {p.color:x8}")));
                    break;
                case "render":
                {
                    var q = new List<PrimVert>();
                    foreach (var inst in mgr.Instances)
                        foreach (var d in inst.Effects.OfType<FxDrawPrim>())
                            if (d.Visible) d.Render(cam, q);
                    foreach (var v in q) Console.WriteLine($"q\t{V(v.Pos)}\t{v.Color:x8}\t{N(v.U)} {N(v.V)}");
                    break;
                }
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "drawprim", DRIVER, "ClientFX.cs", "DrawPrimFX.cs", "LightningFX.cs",
                       "PolyTrailFX.cs", "Commands.cs", "KeyframerMotion.cs")

    def go(*lines):
        out = {"b": [], "t": [], "q": []}
        for l in drive("\n".join(lines) + "\n").splitlines():
            r = l.split("\t")
            if r[0] == "b":
                out["b"].append([vec(p) for p in r[1].split("|")])
            elif r[0] == "t":
                pts = [p.split(" ") for p in r[2].split("|")] if r[2] else []
                out["t"].append(dict(width=float(r[1]), pts=[dict(pos=tuple(map(float, p[:3])), age=float(p[3]),
                                                                    u=float(p[4]), rgba=p[5]) for p in pts]))
            elif r[0] == "q":
                out["q"].append(dict(pos=vec(r[1]), rgba=r[2], uv=vec(r[3])))
        return out
    return go


def vec(s):
    return tuple(float(x) for x in s.split())


def close(a, b, tol=1e-3):
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


BOLT = "key\tLightningFX\t1\t0\t10\tMinNumBolts=1\tMaxNumBolts=1\tMinSegmentsPerBolt=6\tMaxSegmentsPerBolt=6\t" \
       "MinBoltWidth=2\tMaxBoltWidth=2\tMinLifetime=1\tMaxLifetime=1\tPulse=0\tMinPerturb=0\tMaxPerturb=0"


def test_a_bolt_runs_to_an_attractor_of_its_parent(run):
    # Random 0.5: no sideways push. 6 points stepping a sixth of the way, the last on the node.
    out = run("group\tg\t10", BOLT + "\tNodeAttractors=s:Head;joint3", "start\tg\t1\t0 0 0", "node\tjoint3\t60 0 0",
              "frame\t0.1", "bolts")
    (b,) = out["b"]
    assert [p[0] for p in b] == [0, 10, 20, 30, 40, 60], b


def test_bolt_count_width_and_life_come_from_their_ranges(run):
    # MinNumBolts 2, MaxNumBolts 4 at random 0.5: 2 + (int)(0.5 x 3) = 3 bolts; they live 1 s.
    key = BOLT.replace("MinNumBolts=1\tMaxNumBolts=1", "MinNumBolts=2\tMaxNumBolts=4") + "\tMinDelay=5\tMaxDelay=5"
    out = run("group\tg\t10", key + "\tSocketAttractors=s:tip", "start\tg\t1\t0 0 0", "socket\ttip\t0 30 0",
              "frame\t0.1", "bolts", "frame\t1", "bolts")
    assert len(out["b"]) == 3, out["b"]


def test_a_bolt_to_its_own_place_draws_nothing(run):
    # CHAR_HogEnergySuck in a level: its attractors are a character's nodes, so the bolt ends where it starts.
    out = run("group\tg\t10", BOLT + "\tNodeAttractors=s:Right_Hand", "start\tg\t1\t5 5 100", "frame\t0.1", "render")
    assert out["q"] == [], out["q"]


def test_omni_radius_ends_the_bolt_at_a_random_point(run):
    # No attractors: direction (2r - 1) per axis from 0.75 0.5 0.5 -> (0.5, 0, 0), normalised (1, 0, 0), times
    # Rand(-32, 32) at 0.75 = 16. The draws before: the bolt's points (Init), bolt count, width, life.
    key = BOLT + "\tOmniDirectionalRadius=32"
    out = run("rand\t0.5,0.5,0.5,0.5,0.75,0.5,0.5,0.75", "group\tg\t10", key, "start\tg\t1\t0 0 0", "frame\t0.1",
              "bolts")
    (b,) = out["b"]
    assert close(b[-1], (16, 0, 0)), b


def test_a_bolt_is_a_camera_facing_strip_of_its_width(run):
    # Along x at depth 100, a sixth of the way per point: each bisector is (dy, -dx) scaled to 2, so the quads span y -2..2; UVs 0..1 per
    # segment; Ck halfway (0.1 s of 1 s) from white to red, alpha 1 - 0.
    key = BOLT + "\tck=0,1,1,1,0,1,1,0,0,0"
    out = run("group\tg\t10", key + "\tNodeAttractors=s:n", "start\tg\t1\t0 0 100", "node\tn\t60 0 100",
              "frame\t0.5", "render")
    q = out["q"]
    assert len(q) == 5 * 4, q
    assert close(q[0]["pos"], (0, -2, 100)) and close(q[1]["pos"], (10, -2, 100)), q[:4]
    assert close(q[2]["pos"], (10, 2, 100)) and close(q[3]["pos"], (0, 2, 100)), q[:4]
    assert [v["uv"] for v in q[:4]] == [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert q[0]["rgba"] == "ff7f7fff", q[0]


def test_sk_scales_a_bolts_width(run):
    key = BOLT + "\tsk=0,1,1,3"
    out = run("group\tg\t10", key + "\tNodeAttractors=s:n", "start\tg\t1\t0 0 100", "node\tn\t50 0 100",
              "frame\t0.5", "render")
    assert close(out["q"][0]["pos"], (0, -4, 100)), out["q"][0]


def test_pulse_jitters_the_inner_points_only(run):
    # Random 1: every pulse push is +Pulse on each axis (the last draw of a push sets each), the ends stay.
    key = BOLT.replace("Pulse=0", "Pulse=2")
    out = run("group\tg\t10", key + "\tNodeAttractors=s:n", "start\tg\t1\t0 0 0", "node\tn\t60 0 0", "frame\t0.1",
              "rand\t0.999999", "frame\t0.1", "bolts")
    (b,) = out["b"]
    assert close(b[0], (0, 0, 0)) and close(b[-1], (60, 0, 0)), b
    assert close(b[1], (12, 2, 2), tol=1e-2), b


def test_lightning_goes_at_once_when_shut_down(run):
    out = run("group\tg\t10", BOLT + "\tNodeAttractors=s:n", "start\tg\t1\t0 0 0", "node\tn\t60 0 0", "frame\t0.1",
              "stop", "frame\t0.1", "bolts")
    assert out["b"] == []


TRAIL = "key\tPolyTrail\t1\t0\t10\tupdatepos=1\tSectionInterval=0.1\tTrailLen=50\tSectionLifespan=1\tTrailWidth=10"


def test_a_trail_starts_where_its_instance_started_and_its_last_point_follows(run):
    out = run("group\tg\t10", TRAIL, "start\tg\t1\t0 0 0", "frame\t0.05", "move\t20 0 0", "frame\t0.03", "trail")
    (t,) = out["t"]
    assert [p["pos"] for p in t["pts"]] == [(0, 0, 0), (20, 0, 0)], t
    # U: the second point was added at 0 (distance 0 then), so it stays 0 as the point moves.
    assert [p["u"] for p in t["pts"]] == [0, 0], t


def test_points_come_every_interval_and_age_out(run):
    lines = ["group\tg\t10", TRAIL, "start\tg\t1\t0 0 0", "frame\t0.01"]
    for i in range(1, 6):
        lines += [f"move\t{i * 10} 0 0", "frame\t0.11"]
    lines.append("trail")
    (t,) = run(*lines)["t"]
    assert len(t["pts"]) == 7, t
    # The third point was added at x 10 with the second at 0: U 10 / TrailWidth 10.
    assert t["pts"][2]["u"] == 1, t


def test_old_points_go_but_never_the_last(run):
    out = run("group\tg\t10", TRAIL.replace("SectionLifespan=1", "SectionLifespan=0.25"), "start\tg\t1\t0 0 0",
              "frame\t0.01", "move\t10 0 0", "frame\t0.3", "trail")
    (t,) = out["t"]
    # The third point came at 10 with this frame; the two at 0 are 0.31 s old and go.
    assert [p["pos"] for p in t["pts"]] == [(10, 0, 0)], t


def test_ck_runs_over_each_points_life(run):
    key = TRAIL + "\tck=0,1,1,1,0,1,0,0,0,1"
    (t,) = run("group\tg\t10", key, "start\tg\t1\t0 0 0", "frame\t0.5", "trail")["t"]
    # Both points 0.5 s old: halfway from white to black, alpha 1 - 0.5.
    assert {p["rgba"] for p in t["pts"]} == {"7f7f7f7f"}, t


def test_big_to_small_narrows_with_more_points(run):
    key = TRAIL.replace("TrailLen=50", "TrailLen=10") + "\tWidthStyle=3"
    lines = ["group\tg\t10", key, "start\tg\t1\t0 0 0", "frame\t0.01"]
    for i in range(1, 4):
        lines += [f"move\t{i * 10} 0 0", "frame\t0.11"]
    lines.append("trail")
    (t,) = run(*lines)["t"]
    # 5 points: 10 x (10 - 3) / 10.
    assert len(t["pts"]) == 5 and t["width"] == 7, t


def test_uadd_scrolls_u(run):
    # The second point comes at the start, the third with the frame (0.25 s > the interval).
    (t,) = run("group\tg\t10", TRAIL + "\tUAdd=2", "start\tg\t1\t0 0 0", "frame\t0.25", "trail")["t"]
    assert [p["u"] for p in t["pts"]] == [0.5, 0.5, 0.5], t


def test_a_shut_down_trail_stays_until_its_points_age_out(run):
    out = run("group\tg\t10", TRAIL, "start\tg\t1\t0 0 0", "frame\t0.01", "move\t10 0 0", "frame\t0.2", "stop",
              "move\t50 0 0", "frame\t0.5", "trail", "frame\t0.6", "trail", "frame\t0.1", "trail")
    first = out["t"][0]
    assert first["pts"][-1]["pos"] == (10, 0, 0), first   # the last point stops following
    assert len(out["t"]) == 2 and len(out["t"][1]["pts"]) == 1, out["t"]


def test_a_trail_is_a_camera_facing_ribbon(run):
    out = run("group\tg\t10", TRAIL, "start\tg\t1\t0 0 100", "frame\t0.01", "move\t0 30 100", "frame\t0.01",
              "render")
    q = out["q"]
    # Along y: bisector (dy, -dx) = (+, 0) scaled to 10.
    assert close(q[0]["pos"], (10, 0, 100)) and close(q[3]["pos"], (-10, 0, 100)), q
    assert close(q[1]["uv"], (0, 0)), q
