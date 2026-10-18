"""The LTBBouncyChunk effect (TronViewer/.../BouncyChunkFX.cs) compiled with .NET and driven frame by frame
through the effect manager. Rules: ltjs clientfxdll/ltbbouncychunkfx.cpp (ParseProperties, Init, Update) and
docs/research/clientfx-types.md on research/clientfx-types. Expected values are worked by hand from them.

Driver lines (tab-separated):
  rand <v>                              the manager's random numbers are all v (in [0, 1))
  group <name> <phase>                  a group; the keys after it are its keys
  chunk <id> <start> <end> [k=v]...     an LTBBouncyChunk key; offset, sk, ChunkDir, Gravity as comma lists,
                                        any other k a number
  start <group> <loop> <x y z> [yaw]    an instance at an object there (yaw in degrees)
  frame <dt>                            the manager's update; the world is a floor at y = 0 facing up
  state                                 "c <id> <visible> <chunk pos> <velocity> <scale> <pos> <forward>"
                                        per chunk
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
    static LTVec Vec(string s) { var p = s.Split(' ', ',').Select(F).ToArray(); return new LTVec(p[0], p[1], p[2]); }
    static void Main()
    {
        double r = 0.5;
        var mgr = new ClientFXMgr(() => r);
        mgr.Types["LTBBouncyChunk"] = k => new FxChunk(mgr);
        mgr.Intersect = (LTVec from, LTVec to, out LTVec point, out LTVec normal) =>
        {
            point = normal = default;
            if (!(from.y >= 0 && to.y < 0)) return false;
            point = LTVec.Lerp(from, to, from.y / (from.y - to.y));
            normal = new LTVec(0, 1, 0);
            return true;
        };
        FxGroup g = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "rand":
                    r = double.Parse(a[1], Inv);
                    break;
                case "group":
                    g = new FxGroup { Name = a[1], Phase = F(a[2]) };
                    mgr.Add(g);
                    break;
                case "chunk":
                {
                    var k = new FxKey { Type = "LTBBouncyChunk", Id = int.Parse(a[1]), Start = F(a[2]), End = F(a[3]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    foreach (var kv in a.Skip(4).Select(s => s.Split('=')))
                    {
                        if (kv[0] == "offset") k.Offset = Vec(kv[1]);
                        else if (kv[0] == "sk") k.Sk = Fs(kv[1]);
                        else k.Nums[kv[0]] = Fs(kv[1]);
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "start":
                {
                    var o = new Obj { Pos = Vec(a[3]), Rot = LTQuat.FromEuler(0, (a.Length > 4 ? F(a[4]) : 0) * (float)Math.PI / 180, 0) };
                    mgr.Start(a[1], a[2] == "1", true, o);
                    break;
                }
                case "frame":
                    mgr.Update(F(a[1]), default);
                    break;
                case "state":
                    foreach (var inst in mgr.Instances)
                        foreach (var c in inst.Effects.OfType<FxChunk>())
                            Console.WriteLine($"c\t{c.Key.Id}\t{(c.Visible ? 1 : 0)}\t{V(c.ChunkPos)}\t{V(c.Velocity)}\t{N(c.Scale)}\t{V(c.Pos)}\t{V(c.ChunkRot.Forward())}");
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "chunks", DRIVER, "ClientFX.cs", "BouncyChunkFX.cs", "ModelFX.cs",
                      "Commands.cs", "KeyframerMotion.cs")

    def go(*lines):
        out = [l.split("\t") for l in drive("\n".join(lines) + "\n").splitlines()]
        return [dict(id=int(r[1]), visible=r[2] == "1", chunk=vec(r[3]), vel=vec(r[4]), scale=float(r[5]),
                     pos=vec(r[6]), fwd=vec(r[7])) for r in out if r[0] == "c"]
    return go


def vec(s):
    return tuple(float(x) for x in s.split())


def close(a, b, tol=1e-2):
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


STILL = "Amount=0"   # no gravity


def test_launch_tilts_by_whole_numbers_and_keeps_the_speed(run):
    # ChunkDir up: right = up x' (1,0,1)/sqrt2 = (-a, 0, a), up' = right x' o = (0, -1, 0) (LTVector::Cross is
    # b x this). rand() % 10 = 0: both tilts -5, so v = (5a, 850 + 5, -5a), renormalized to 850.
    (c,) = run("rand\t0", "group\tg\t1", f"chunk\t1\t0\t1\tChunkDir=0,1,0\tChunkSpeed=850\tChunkSpread=5\t{STILL}",
               "start\tg\t0\t0 0 0", "state")
    a = 5 / math.sqrt(2)
    n = math.sqrt(2 * a * a + 855 ** 2)
    assert close(c["vel"], (a * 850 / n, 855 * 850 / n, -a * 850 / n)), c
    # rand() % 10 = 5: no tilt.
    (c,) = run("rand\t0.5", "group\tg\t1", f"chunk\t1\t0\t1\tChunkDir=0,1,0\tChunkSpeed=850\tChunkSpread=5\t{STILL}",
               "start\tg\t0\t0 0 0", "state")
    assert close(c["vel"], (0, 850, 0)), c


def test_moves_then_gravity_adds(run):
    # Each update: pos += v dt, then v += normalize(Gravity) x Amount x dt.
    ms = run("group\tg\t5", "chunk\t1\t0\t5\tChunkDir=0,1,0\tChunkSpeed=100\tChunkSpread=0\tGravity=0,-2,0\tAmount=10",
             "start\tg\t0\t0 10 0", "frame\t1", "state", "frame\t1", "state")
    assert [(m["chunk"][1], m["vel"][1]) for m in ms] == [(110, 90), (200, 80)], ms


def test_bounces_off_the_world_at_seventy_percent(run):
    # From y 10 down at 100 for 0.5 s: through the floor, so it sits on the hit plus the normal (y 1) and
    # the velocity is reflected about the normal at 0.7 of its speed.
    (m,) = run("group\tg\t5", f"chunk\t1\t0\t5\tChunkDir=0,-1,0\tChunkSpeed=100\tChunkSpread=0\t{STILL}",
               "start\tg\t0\t0 10 0", "frame\t0.5", "state")
    assert close(m["chunk"], (0, 1, 0)) and close(m["vel"], (0, 70, 0)), m


def test_made_at_the_object_plus_the_offset_unrotated_with_its_rotation(run):
    (m,) = run("group\tg\t5", f"chunk\t1\t0\t5\tChunkSpread=0\tChunkSpeed=0\t{STILL}\toffset=0,0,10",
               "start\tg\t0\t5 0 0\t90", "state")
    assert close(m["chunk"], (5, 0, 10)) and close(m["fwd"], (1, 0, 0)), m


def test_shown_before_its_start_time_scaled_by_sk_at_zero(run):
    # The chunk is its own object, made visible: the effect is still hidden and inactive, the chunk stands.
    (m,) = run("group\tg\t5", f"chunk\t1\t1\t5\tChunkSpeed=100\tChunkSpread=0\t{STILL}\tsk=0,2,1,4",
               "start\tg\t0\t0 10 0", "frame\t0.5", "state")
    assert not m["visible"] and m["scale"] == 2 and close(m["chunk"], (0, 10, 0)), m


def test_what_links_to_it_follows_the_chunk(run):
    (m,) = run("group\tg\t5", f"chunk\t1\t0\t5\tChunkDir=1,0,0\tChunkSpeed=100\tChunkSpread=0\t{STILL}",
               "start\tg\t0\t0 10 0", "frame\t0.5", "state")
    assert close(m["pos"], m["chunk"]) and close(m["chunk"], (50, 10, 0)), m


def test_gone_when_its_key_ends(run):
    assert run("group\tg\t5", f"chunk\t1\t0\t1\tChunkSpread=0\t{STILL}", "start\tg\t0\t0 10 0", "frame\t1.1",
               "state") == []
