"""The viewer's effect groups and SpecialFX objects (TronViewer/.../ClientFX.cs, SpecialFX.cs), compiled with
.NET and driven frame by frame. Rules: docs/research/clientfx-groups.md on research/clientfx-groups (ltjs
clientfxmgr.cpp UpdateAllActiveFX / UpdateInstanceInterval / ShutdownClientFX / ApplyEffectStartingOffset,
basefx.cpp, serverspecialfx.cpp). Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  group <name> <phase>            a group; the keys after it are its keys
  key <id> <start> <end> [k=v]... a key of type Probe (continual when it covers the phase); k: link, pos
                                  (UpdatePos), offset x,y,z, ck t,r,g,b,a,..., sk t,s,..., dist (1:
                                  DisableAtDist), smooth (0/1), maxoff, rand (0/1), step, drain (s a
                                  shutting-down effect takes to finish)
  sfx <name> <group> <loop> <smooth> <onetime> <x y z> [yaw]
                                  a SpecialFX object (yaw in degrees)
  msg <sfx> <words>               a message to it (prints "unhandled" if it doesn't take it)
  remove <sfx>                    its object leaves the level
  frame <dt> [<x y z>]            the manager's update with the camera there (default at the origin)
  state                           "inst <group> <elapsed> <suspended>" per instance, then
                                  "fx <id> <active><shutting><visible> <elapsed> <r g b a> <scale> <x y z>"
                                  per effect in update order
Probe effects print "term <id>" when they leave; OneTime objects print "removed <name>".
"""
import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Tron;
class Probe : FxEffect
{
    public float Drain, Drained;
    protected override void OnUpdate(float dt) { if (ShuttingDown) Drained += dt; else Drained = 0; }
    public override bool IsFinishedShuttingDown => Drained >= Drain - 1e-5f;
    public override void Term() => Console.WriteLine("term\t" + Key.Id);
}
static class Driver
{
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    static float F(string s) => float.Parse(s, Inv);
    static string N(float v) => (Math.Abs(v) < 0.0005f ? 0f : v).ToString("0.###", Inv);
    static float[] Fs(string s) => s.Split(',').Select(F).ToArray();
    static void Main()
    {
        var drains = new Dictionary<FxKey, float>();
        var mgr = new ClientFXMgr(() => 0.5);
        mgr.Types["Probe"] = k => new Probe { Drain = drains.TryGetValue(k, out var d) ? d : 0 };
        var objs = new Dictionary<string, SpecialFX>();
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
                case "key":
                {
                    var k = new FxKey { Type = "Probe", Id = int.Parse(a[1]), Start = F(a[2]), End = F(a[3]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    k.Ck = new float[] { 0, 1, 1, 1, 0, 1, 1, 1, 1, 0 };
                    k.Sk = new float[] { 0, 1, 1, 1 };
                    foreach (var kv in a.Skip(4).Select(s => s.Split('=')))
                    {
                        var v = kv[1];
                        switch (kv[0])
                        {
                            case "link": k.Link = int.Parse(v); break;
                            case "pos": k.UpdatePos = int.Parse(v); break;
                            case "offset": { var o = Fs(v); k.Offset = new LTVec(o[0], o[1], o[2]); break; }
                            case "ck": k.Ck = Fs(v); break;
                            case "sk": k.Sk = Fs(v); break;
                            case "dist": k.DisableAtDist = v == "1"; break;
                            case "smooth": k.SmoothShutDown = v == "1"; break;
                            case "maxoff": k.MaxStartOffset = F(v); break;
                            case "rand": k.RandomizeStartOffset = v == "1"; break;
                            case "step": k.StartOffsetInterval = F(v); break;
                            case "drain": drains[k] = F(v); break;
                        }
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "sfx":
                {
                    float yaw = a.Length > 9 ? F(a[9]) * (float)Math.PI / 180 : 0;
                    var name = a[1];
                    var o = new SpecialFX(mgr, a[2], a[3] == "1", a[4] == "1", a[5] == "1",
                        new LTVec(F(a[6]), F(a[7]), F(a[8])), LTQuat.FromEuler(0, yaw, 0));
                    o.RemoveObject = () => { Console.WriteLine("removed\t" + name); objs.Remove(name); };
                    objs[name] = o;
                    break;
                }
                case "msg":
                    if (!objs.TryGetValue(a[1], out var sfx) || !sfx.OnMessage(new Message(a[2].Split(' '), -1)))
                        Console.WriteLine("unhandled\t" + a[2]);
                    break;
                case "remove":
                    objs[a[1]].Remove();
                    objs.Remove(a[1]);
                    break;
                case "frame":
                    mgr.Update(F(a[1]), a.Length > 4 ? new LTVec(F(a[2]), F(a[3]), F(a[4])) : default);
                    break;
                case "state":
                    foreach (var inst in mgr.Instances)
                    {
                        Console.WriteLine($"inst\t{inst.Group.Name}\t{N(inst.Elapsed)}\t{(inst.Suspended ? 1 : 0)}");
                        foreach (var fx in inst.Effects)
                            Console.WriteLine($"fx\t{fx.Key.Id}\t{(fx.Active ? "A" : "-")}{(fx.ShuttingDown ? "S" : "-")}{(fx.Visible ? "V" : "-")}" +
                                $"\t{N(fx.Elapsed)}\t{N(fx.R)} {N(fx.G)} {N(fx.B)} {N(fx.A)}\t{N(fx.Scale)}\t{N(fx.Pos.x)} {N(fx.Pos.y)} {N(fx.Pos.z)}");
                    }
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "clientfx", DRIVER, "ClientFX.cs", "SpecialFX.cs", "Commands.cs",
                      "KeyframerMotion.cs")
    return lambda *lines: [l.split("\t") for l in drive("\n".join(lines) + "\n").splitlines()]


def fx(out):
    """{id: (flags, elapsed)} of the effects in the state lines."""
    return {r[1]: (r[2], r[3]) for r in out if r[0] == "fx"}


def test_a_loop_runs_its_keys_every_phase_and_off_ends_it(run):
    group = ["group\tg\t1", "key\t1\t0\t1", "key\t2\t0.25\t0.5", "sfx\to\tg\t1\t1\t0\t0\t0\t0"]
    out = run(*group, "msg\to\tON", "frame\t0.3", "state")
    assert out[0] == ["inst", "g", "0.3", "0"]
    assert fx(out) == {"1": ("A-V", "0.3"), "2": ("A-V", "0.05")}
    # key 2 ends at 0.5 and waits for its next start, hidden; key 1 is continual: its time wraps at 1.0
    out = run(*group, "msg\to\tON", "frame\t0.3", "frame\t0.3", "state", "frame\t0.5", "state")
    assert fx(out[:3]) == {"1": ("A-V", "0.6"), "2": ("---", "0.35")}
    assert out[3] == ["inst", "g", "0.1", "0"] and fx(out[3:]) == {"1": ("A-V", "0.1"), "2": ("---", "0.35")}
    # OFF: the inactive key goes, the active one finishes at once (nothing left to drain)
    out = run(*group, "msg\to\tON", "frame\t0.3", "frame\t0.3", "msg\to\tOFF", "state")
    assert out == [["term", "2"], ["term", "1"]]


def test_on_while_on_does_not_restart_and_trigger_toggles(run):
    group = ["group\tg\t1", "key\t1\t0\t1", "sfx\to\tg\t1\t1\t0\t0\t0\t0"]
    out = run(*group, "msg\to\tON", "frame\t0.4", "msg\to\tON", "frame\t0.1", "state")
    assert fx(out) == {"1": ("A-V", "0.5")}
    out = run(*group, "msg\to\tTRIGGER", "frame\t0.4", "msg\to\tTRIGGER", "state", "msg\to\tTRIGGER", "state")
    assert out == [["term", "1"], ["inst", "g", "0", "0"], ["fx", "1", "A-V", "0", "1 1 1 1", "1", "0 0 0"]]
    # TARGET turns it off; HIDDEN is GameBase's
    out = run(*group, "msg\to\tON", "msg\to\tTARGET", "msg\to\tHIDDEN 1", "state")
    assert out == [["term", "1"], ["unhandled", "HIDDEN 1"]]


def test_a_draining_effect_restarts_at_its_next_start(run):
    """Key 2 shuts down at 0.5 and drains for 1 s; at 1.25 (its start in the next phase) it is still
    draining: it runs up to there, then restarts from 0."""
    out = run("group\tg\t1", "key\t1\t0\t1", "key\t2\t0.25\t0.5\tdrain=1", "sfx\to\tg\t1\t1\t0\t0\t0\t0",
              "msg\to\tON", "frame\t0.3", "frame\t0.3", "state", "frame\t0.6", "state", "frame\t0.1", "state")
    assert fx(out[0:3])["2"] == ("ASV", "0.35")      # 0.25 of its run + 0.1 of drain
    assert fx(out[3:6])["2"] == ("ASV", "0.95")      # drained 0.7
    assert fx(out[6:9])["2"] == ("A-V", "0.05")      # restarted at 1.25, 0.05 into the new run


def test_colour_and_scale_follow_the_keys(run):
    """Lifespan 2 s, t = 0.25: halfway into neither key pair's end. Ck alpha is a transparency."""
    out = run("group\tg\t4", "key\t1\t0\t2\tck=0,1,0,0,0.5,1,0,1,0,0\tsk=0,1,1,3",
              "sfx\to\tg\t1\t1\t0\t0\t0\t0", "msg\to\tON", "frame\t0.5", "state")
    assert out[1][4:6] == ["0.75 0.25 0 0.625", "1.5"]


def test_a_loop_follows_its_object_and_a_linked_key_its_effect(run):
    """Object at (100, 0, 0) turned 90° (forward = +x). Key 1 Fixed, offset z 10: created at the object plus
    the offset in world axes, then the offset turns with the object. Key 2 Follow, linked to key 1, offset
    y 5: it updates before key 1 (reverse order), so it first sees key 1 where it was created."""
    keys = ["group\tg\t1", "key\t1\t0\t1\toffset=0,0,10", "key\t2\t0\t1\tlink=1\tpos=1\toffset=0,5,0"]
    out = run(*keys, "sfx\to\tg\t1\t1\t0\t100\t0\t0\t90", "msg\to\tON", "state", "frame\t0.1", "state")
    pos = {(i, r[1]): r[6] for i, r in enumerate(out) if r[0] == "fx"}
    assert pos == {(1, "2"): "100 5 10", (2, "1"): "110 0 0", (4, "2"): "110 5 0", (5, "1"): "110 0 0"}


def test_one_shots_overlap_stay_put_and_end(run):
    """Not Loop: every ON is another instance at the object, with no parent (the offset stays in world
    axes); each key runs once and the instance goes with its last effect, a continual key at the phase end."""
    group = ["group\tg\t1", "key\t1\t0\t0.5\toffset=0,0,10", "key\t2\t0\t1", "sfx\to\tg\t0\t1\t0\t100\t0\t0\t90"]
    out = run(*group, "msg\to\tON", "frame\t0.25", "msg\to\tON", "msg\to\tOFF", "frame\t0.1", "state")
    assert [r[2] for r in out if r[0] == "inst"] == ["0.35", "0.1"]
    assert {r[6] for r in out if r[0] == "fx" and r[1] == "1"} == {"100 0 10"}
    out = run(*group, "msg\to\tON", "frame\t0.6", "state", "frame\t0.5", "state")
    assert out == [["term", "1"], ["inst", "g", "0.6", "0"], ["fx", "2", "A-V", "0.6", "1 1 1 1", "1", "100 0 0"],
                   ["term", "2"]]


def test_one_time_removes_its_object_after_the_first_on(run):
    out = run("group\tg\t1", "key\t1\t0\t1", "sfx\to\tg\t0\t1\t1\t0\t0\t0", "msg\to\tON", "msg\to\tON",
              "frame\t0.5", "state")
    assert out == [["removed", "o"], ["unhandled", "ON"], ["inst", "g", "0.5", "0"],
                   ["fx", "1", "A-V", "0.5", "1 1 1 1", "1", "0 0 0"]]


def test_smooth_shutdown_drains_and_a_hard_one_cuts(run):
    keys = ["group\tg\t1", "key\t1\t0\t1\tdrain=0.3", "key\t2\t0\t1\tdrain=0.3\tsmooth=0"]
    out = run(*keys, "sfx\to\tg\t1\t1\t0\t0\t0\t0", "msg\to\tON", "frame\t0.2", "msg\to\tOFF", "state",
              "frame\t0.2", "state", "frame\t0.2")
    assert out[0] == ["term", "2"]                    # the key itself doesn't shut down smoothly
    assert fx(out[1:3]) == {"1": ("ASV", "0.2")} and fx(out[3:5]) == {"1": ("ASV", "0.4")}
    assert out[5:] == [["term", "1"]]
    out = run(*keys, "sfx\to\tg\t1\t0\t0\t0\t0\t0", "msg\to\tON", "frame\t0.2", "msg\to\tOFF", "state")
    assert sorted(out) == [["term", "1"], ["term", "2"]]
    # REMOVE shuts a loop down too
    out = run(*keys, "sfx\to\tg\t1\t0\t0\t0\t0\t0", "msg\to\tON", "remove\to", "state")
    assert sorted(out) == [["term", "1"], ["term", "2"]]


def test_a_start_offset_pre_ages_the_effect(run):
    out = run("group\tg\t30", "key\t1\t0\t30\tmaxoff=1.25", "key\t2\t0\t30\tmaxoff=20\trand=1\tstep=0.5",
              "sfx\to\tg\t1\t1\t0\t0\t0\t0", "msg\to\tON", "frame\t0.1", "state")
    assert fx(out) == {"1": ("A-V", "1.35"), "2": ("A-V", "10.1")}   # random 0.5 of 20


def test_an_instance_freezes_beyond_the_cull_distance_only_when_every_effect_allows(run):
    far = "frame\t0.5\t6001\t0\t0"
    out = run("group\tg\t1", "key\t1\t0\t1\tdist=1", "key\t2\t0.5\t1\tdist=1", "sfx\to\tg\t1\t1\t0\t0\t0\t0",
              "msg\to\tON", far, "state", "frame\t0.25", "state")
    assert out[0] == ["inst", "g", "0", "1"] and fx(out[:3]) == {"1": ("A--", "0"), "2": ("---", "0")}
    assert out[3] == ["inst", "g", "0.25", "0"] and fx(out[3:])["1"] == ("A-V", "0.25")
    out = run("group\tg\t1", "key\t1\t0\t1\tdist=1", "key\t2\t0.5\t1", "sfx\to\tg\t1\t1\t0\t0\t0\t0",
              "msg\to\tON", far, "state")
    assert out[0] == ["inst", "g", "0.5", "0"]
