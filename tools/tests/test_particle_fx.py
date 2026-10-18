"""The ParticleSystem effect (TronViewer/.../ParticleSystemFX.cs) compiled with .NET and driven frame by frame.
Rules: ltjs clientfxdll/particlesystemfx.cpp (Update, AddParticles, UpdateParticles) and
docs/research/clientfx-types.md on research/clientfx-types. Expected values are worked by hand from them.

Driver lines (tab-separated):
  rand <v,v,...>                  the random numbers in [0, 1) the manager hands out, in a cycle
  group <name> <phase>            a group; the keys after it are its keys
  ps <id> <start> <end> [k=v]...  a ParticleSystem key: ck, sk and rotadd as comma lists, any other k a
                                  type prop (a comma list is a vector, a number a number, else a string)
  floor                           the world is the plane y = 0 (normal up) for bounces and splats
  start <group> <loop> <x y z> [yaw]
                                  an instance at an object there (yaw in degrees)
  stop                            every instance shuts down smoothly
  frame <dt>                      the manager's update
  state                           "inst <group>" per instance, then "ps <id> <count>" per particle system and
                                  "p <life> <x y z> <vx vy vz> <r g b a> <size>" per particle
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
    static void Main()
    {
        double[] rand = { 0.5 };
        int next = 0;
        var mgr = new ClientFXMgr(() => rand[next++ % rand.Length]);
        mgr.Types["ParticleSystem"] = k => new FxParticleSystem(mgr);
        FxGroup g = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "rand":
                    rand = a[1].Split(',').Select(s => double.Parse(s, Inv)).ToArray();
                    next = 0;
                    break;
                case "group":
                    g = new FxGroup { Name = a[1], Phase = F(a[2]) };
                    mgr.Add(g);
                    break;
                case "ps":
                {
                    var k = new FxKey { Type = "ParticleSystem", Id = int.Parse(a[1]), Start = F(a[2]), End = F(a[3]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    k.Ck = new float[] { 0, 1, 1, 1, 0, 1, 1, 1, 1, 0 };
                    k.Sk = new float[] { 0, 1, 1, 1 };
                    foreach (var kv in a.Skip(4).Select(s => s.Split('=')))
                    {
                        var v = kv[1];
                        if (kv[0] == "ck") k.Ck = Fs(v);
                        else if (kv[0] == "sk") k.Sk = Fs(v);
                        else if (kv[0] == "rotadd") { var r = Fs(v); k.RotateAdd = new LTVec(r[0], r[1], r[2]); }
                        else if (v.Contains(',')) k.Nums[kv[0]] = Fs(v);
                        else if (float.TryParse(v, NumberStyles.Float, Inv, out var f)) k.Nums[kv[0]] = new[] { f };
                        else k.Strs[kv[0]] = v;
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "floor":
                    mgr.Intersect = (LTVec from, LTVec to, out LTVec point, out LTVec normal) =>
                    {
                        normal = new LTVec(0, 1, 0);
                        point = default;
                        if (from.y < 0 || to.y >= 0) return false;
                        point = LTVec.Lerp(from, to, from.y / (from.y - to.y));
                        return true;
                    };
                    break;
                case "start":
                {
                    float yaw = a.Length > 6 ? F(a[6]) * (float)Math.PI / 180 : 0;
                    var o = new Obj { Pos = new LTVec(F(a[3]), F(a[4]), F(a[5])), Rot = LTQuat.FromEuler(0, yaw, 0) };
                    mgr.Start(a[1], a[2] == "1", true, o);
                    break;
                }
                case "stop":
                    foreach (var inst in mgr.Instances.ToArray()) mgr.ShutDown(inst);
                    break;
                case "frame":
                    mgr.Update(F(a[1]), default);
                    break;
                case "state":
                    foreach (var inst in mgr.Instances)
                    {
                        Console.WriteLine($"inst\t{inst.Group.Name}");
                        foreach (var fx in inst.Effects.OfType<FxParticleSystem>())
                        {
                            Console.WriteLine($"ps\t{fx.Key.Id}\t{fx.Count}");
                            for (int i = 0; i < fx.Count; i++)
                            {
                                var p = fx.Particles[i];
                                Console.WriteLine($"p\t{N(p.Life)}\t{V(p.Pos)}\t{V(p.Vel)}\t{N(p.R)} {N(p.G)} {N(p.B)} {N(p.A)}\t{N(p.Size)}");
                            }
                        }
                    }
                    break;
            }
        }
    }
}
"""




@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "particles", DRIVER, "ClientFX.cs", "ParticleSystemFX.cs", "Commands.cs",
                      "KeyframerMotion.cs")
    return lambda *lines: [l.split("\t") for l in drive("\n".join(lines) + "\n").splitlines()]


def particles(out):
    return [r[1:] for r in out if r[0] == "p"]


BURST = ("ps\t1\t0\t1\tType=1\tParticlesPerEmission=3\tEmissionInterval=-1\tMinParticleLifeSpan=1\t"
         "MaxParticleLifeSpan=3\tMinRadius=0\tMaxRadius=0\tMinParticleVelocity=0,10,0\tMaxParticleVelocity=0,30,0\t"
         "GravityAcceleration=-10\tMoveParticlesWithSystem=0\tck=0,1,1,1,0,1,1,0,0,1\tsk=0,2,1,6")


def test_a_burst_ages_moves_and_takes_its_keys_over_each_life(run):
    """Interval -1: only the initial burst. Random 0.5: life 2, velocity (0, 20, 0), at the object. After
    0.5 s: t = 0.25, moved by the old velocity, then gravity. Ck alpha is a transparency."""
    out = run("group\tg\t1", BURST, "start\tg\t1\t100\t0\t0", "state", "frame\t0.5", "state")
    assert out[1] == ["ps", "1", "3"]
    assert particles(out[:5]) == [["2", "100 0 0", "0 20 0", "1 1 1 1", "2"]] * 3
    assert particles(out[5:]) == [["1.5", "100 10 0", "0 15 0", "1 0.75 0.75 0.75", "3"]] * 3
    # past their life they go; a continual key has no new initial frame, so no new burst
    out = run("group\tg\t1", BURST, "start\tg\t1\t100\t0\t0", "frame\t0.5", "frame\t0.6", "frame\t1", "state")
    assert out == [["inst", "g"], ["ps", "1", "0"]]


def test_emissions_catch_up_one_interval_at_a_time(run):
    """Interval 0.25, life 1. A 0.6 s frame: two emissions are due; after the first the particles move one
    interval, then everything the remaining 0.35 s."""
    key = ("ps\t1\t0\t1\tType=1\tParticlesPerEmission=1\tEmissionInterval=0.25\tMinParticleLifeSpan=1\t"
           "MaxParticleLifeSpan=1\tMaxRadius=0\tMinParticleVelocity=0,0,0\tMaxParticleVelocity=0,0,0\t"
           "GravityAcceleration=0")
    out = run("group\tg\t1", key, "start\tg\t1\t0\t0\t0", "frame\t0.6", "state")
    assert [p[0] for p in particles(out)] == ["0.4", "0.4", "0.65"]
    # a long frame is cut at each phase end: 1 s, 1 s, 0.4 s, four emissions in each whole phase
    out = run("group\tg\t1", key, "start\tg\t1\t0\t0\t0", "frame\t2.4", "state")
    assert [p[0] for p in particles(out)] == ["0.1", "0.35", "0.6"]


ROTATED = ("ps\t1\t0\t1\tType=1\tParticlesPerEmission=1\tEmissionInterval=-1\tMinRadius=10\tMaxRadius=10\t"
           "EmissionPlane=0,1,0\tMinParticleVelocity=0,0,10\tMaxParticleVelocity=0,0,10\tGravityAcceleration=0\t"
           "MinParticleLifeSpan=5\tMaxParticleLifeSpan=5")


def test_in_the_level_the_velocity_turns_with_the_system_and_the_offset_does_not(run):
    """Random 0.75: the point is (perp1 + perp2) / 2 normalized, x 10; perps of up are (0, 0, -1) and
    (-1, 0, 0). The object faces +x (yaw 90): the velocity turns, the spawn offset stays in world axes."""
    out = run("rand\t0.75", "group\tg\t1", ROTATED + "\tMoveParticlesWithSystem=0", "start\tg\t1\t100\t0\t0\t90",
              "state")
    assert particles(out) == [["5", "92.929 0 -7.071", "10 0 0", "1 1 1 1", "1"]]
    # moving with the system: both stay in its space
    out = run("rand\t0.75", "group\tg\t1", ROTATED + "\tMoveParticlesWithSystem=1", "start\tg\t1\t100\t0\t0\t90",
              "state")
    assert particles(out) == [["5", "-7.071 0 -7.071", "0 0 10", "1 1 1 1", "1"]]


def test_swarm_turns_particles_about_the_system_in_radians(run):
    """RotateAdd (0, pi/2, 0) per second, in the system's space: a still particle at x 10 is at z -10 a
    second later."""
    key = ("ps\t1\t0\t2\tType=1\tParticlesPerEmission=1\tEmissionInterval=-1\tMinRadius=10\tMaxRadius=10\t"
           "EmissionPlane=0,0,1\tMinParticleVelocity=0,0,0\tMaxParticleVelocity=0,0,0\tGravityAcceleration=0\t"
           f"MinParticleLifeSpan=5\tMaxParticleLifeSpan=5\trotadd=0,{math.pi / 2},0")
    out = run("rand\t0,0.5,0.5", "group\tg\t2", key, "start\tg\t1\t0\t0\t0", "state", "frame\t1", "state")
    first, second = particles(out)
    assert first[1] == "10 0 0" and second[1] == "0 0 -10"


def test_a_shutting_down_system_emits_no_more_and_ends_with_its_last_particle(run):
    key = ("ps\t1\t0\t1\tType=1\tParticlesPerEmission=1\tEmissionInterval=0.1\tMinParticleLifeSpan=0.5\t"
           "MaxParticleLifeSpan=0.5\tMaxRadius=0\tGravityAcceleration=0")
    out = run("group\tg\t1", key, "start\tg\t1\t0\t0\t0", "frame\t0.25", "stop", "state", "frame\t0.2", "state",
              "frame\t0.2", "state")
    assert out[1] == ["ps", "1", "3"]
    assert [p[0] for p in particles(out[:5])] == ["0.25", "0.25", "0.35"]
    assert [r[:2] for r in out[5:]] == [["inst", "g"], ["ps", "1"], ["p", "0.05"], ["p", "0.05"], ["p", "0.15"]]
    assert len(out) == 10      # the instance went with its last particle


def test_bounce_reflects_off_the_world_and_splat_starts_a_group_there(run):
    """Falling at 10/s from y 3: after 0.2 s at y 1, the next step's segment crosses the floor. A bounce
    reflects the velocity and keeps 0.75 of it; a splat starts its group at the hit point and the particle
    goes (KillOnSplat)."""
    key = ("ps\t1\t0\t1\tType=0\tParticlesPerEmission=1\tEmissionInterval=-1\tMinRadius=0\tMaxRadius=0\t"
           "MinParticleVelocity=0,-10,0\tMaxParticleVelocity=0,-10,0\tGravityAcceleration=0\t"
           "MinParticleLifeSpan=5\tMaxParticleLifeSpan=5\tMoveParticlesWithSystem=0")
    out = run("floor", "group\tg\t1", key + "\tPercentToBounce=100", "start\tg\t1\t0\t3\t0", "frame\t0.2", "state")
    assert particles(out) == [["4.8", "0 1 0", "0 7.5 0", "1 1 1 1", "1"]]
    out = run("floor", "group\ts\t1", "ps\t9\t0\t1\tParticlesPerEmission=0", "group\tg\t1", key + "\tSplatEffect=s\tSplatPercent=100", "start\tg\t1\t0\t3\t0",
              "frame\t0.2", "state")
    assert out == [["inst", "g"], ["ps", "1", "0"], ["inst", "s"], ["ps", "9", "0"]]
