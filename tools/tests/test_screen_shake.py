"""ScreenShake objects and the view's shake (TronViewer/.../ScreenShake.cs) compiled with .NET, with the level's
command manager. Rules: docs/research/screen-shake-iocam.md (branch research/screen-shake-iocam): ltjs
screenshake.cpp (Tron's object.lto the same), playermgr.cpp ShakeScreen / UpdateCameraShake /
UpdateCameraDisplacement (Tron's cshell.dll the same); worked by hand.

Driver lines (tab-separated):
  shake <name> <x y z> [k=v]...   a ScreenShake there: amount (x,y,z), num, freq, area, sound, radius
  player <x y z> | none           where the player object is (LT units), or no player
  run <command>                   a level command, run now
  tick <dt>                       a server frame: the clock, the command table, then the shakes' updates
  rand <a,b,...>                  the client's random numbers in [0, 1), in turn, over and over (default 0.5)
  view <dt>                       a client frame: "view <x y z>" the camera's displacement
  amount                          "amount <x y z>" the client's shake
The shakes print "pulse <time> <x y z>" for each shake the player's client gets and "sound <time> <sound>
<radius> <x y z>" for each sound they play.
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
        var cmds = new CommandMgr(() => 0.5);
        double[] rands = { 0.5 };
        int ri = 0;
        var view = new CameraShake(() => rands[ri++ % rands.Length]);
        LTVec? player = new LTVec(0, 0, 0);
        var shakes = new ScreenShakes(cmds)
        {
            PlayerPos = () => player,
            PlaySound = (pos, sound, radius) => Console.WriteLine($"sound {N(cmds.Time)} {sound} {N(radius)} {V(pos)}"),
        };
        shakes.ShakeScreen = v => { Console.WriteLine($"pulse {N(cmds.Time)} {V(v)}"); view.Add(v); };
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "shake":
                {
                    var p = new ScreenShakeProps();
                    foreach (var kv in a.Skip(3).Select(x => x.Split(new[] { '=' }, 2)))
                        switch (kv[0])
                        {
                            case "amount": p.Amount = Vec(kv[1]); break;
                            case "num": p.NumShakes = int.Parse(kv[1]); break;
                            case "freq": p.Frequency = F(kv[1]); break;
                            case "area": p.AreaOfEffect = F(kv[1]); break;
                            case "sound": p.ShakeSound = kv[1]; break;
                            case "radius": p.SoundRadius = F(kv[1]); break;
                        }
                    int id = cmds.Join(a[1], "ScreenShake");
                    cmds.Handle(id, shakes.Add(Vec(a[2]), p).OnMessage);
                    break;
                }
                case "player": player = a[1] == "none" ? (LTVec?)null : Vec(a[1]); break;
                case "run": cmds.Run(a[1]); break;
                case "tick":
                    cmds.BeginFrame(F(a[1]));
                    cmds.Update();
                    shakes.Update();
                    break;
                case "rand": rands = a[1].Split(',').Select(s => double.Parse(s, Inv)).ToArray(); ri = 0; break;
                case "view": Console.WriteLine("view " + V(view.Update(F(a[1])))); break;
                case "amount": Console.WriteLine("amount " + V(view.Amount)); break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "screen_shake", DRIVER, "ScreenShake.cs", "KeyframerMotion.cs", "Commands.cs")
    return lambda *lines: drive("\n".join(lines) + "\n").splitlines()


def tick(n, dt="0.125"):
    return ["tick\t" + dt] * n


def test_it_waits_for_on_and_then_pulses_once_on_the_next_frame(run):
    # NumShakes -1 (the default, "infinite"): --n is -2, not above 0, so nothing more is scheduled.
    out = run("shake\ts1\t0 0 0\tamount=0.6,0.6,0.6", *tick(2), "run\tmsg s1 on", *tick(12))
    assert out == ["pulse 0.375 0.6 0.6 0.6"]


def test_n_shakes_pulse_n_times_frequency_apart(run):
    out = run("shake\ts1\t0 0 0\tnum=3\tfreq=0.5", "run\tmsg s1 on", *tick(20))
    assert out == ["pulse 0.125 1 1 1", "pulse 0.625 1 1 1", "pulse 1.125 1 1 1"]


def test_off_cancels_the_next_pulse_and_keeps_the_count(run):
    # Pulse 1 at 0.125 leaves 3; OFF at 0.25; ON at 1 pulses at 1.125 (2 left), 1.625 (1 left), 2.125 (0: the last).
    out = run("shake\ts1\t0 0 0\tnum=4\tfreq=0.5", "run\tmsg s1 on", *tick(2), "run\tmsg s1 off", *tick(6),
              "run\tmsg s1 on", *tick(20))
    assert out == ["pulse 0.125 1 1 1", "pulse 1.125 1 1 1", "pulse 1.625 1 1 1", "pulse 2.125 1 1 1"]


def test_a_used_up_shake_pulses_once_per_on(run):
    out = run("shake\ts1\t0 0 0\tnum=2\tfreq=0.5", "run\tmsg s1 on", *tick(10), "run\tmsg s1 on", *tick(10),
              "run\tmsg s1 on", *tick(1))
    assert out == ["pulse 0.125 1 1 1", "pulse 0.625 1 1 1", "pulse 1.375 1 1 1", "pulse 2.625 1 1 1"]


def test_on_while_pending_pulses_on_the_next_frame_and_counts_on(run):
    # 4 shakes 1 s apart: 0.125 (3 left), ON at 0.5 -> 0.625 (2 left), then 1.625 (1 left), 2.625 (0: the last).
    out = run("shake\ts1\t0 0 0\tnum=4", "run\tmsg s1 on", *tick(4), "run\tmsg s1 on", *tick(30))
    assert out == ["pulse 0.125 1 1 1", "pulse 0.625 1 1 1", "pulse 1.625 1 1 1", "pulse 2.625 1 1 1"]


def test_only_a_player_within_the_area_of_effect_is_shaken_but_the_sound_always_plays(run):
    out = run("shake\tnear\t100 0 0\tarea=1000\tsound=screenshake_ones\tradius=150000",
              "shake\tfar\t2000 0 0\tarea=1000\tamount=2,2,1", "shake\tall\t9000 0 0\tamount=3,3,3",
              "player\t0 0 0", "run\tmsg near on; msg far on; msg all on", *tick(1),
              "player\tnone", "run\tmsg all on", *tick(1))
    assert out == ["sound 0.125 screenshake_ones 150000 100 0 0", "pulse 0.125 1 1 1", "pulse 0.125 3 3 3"]


def test_the_distance_is_measured_to_the_player_object_inclusive(run):
    out = run("shake\ts1\t0 0 1000\tarea=1000", "player\t0 0 0", "run\tmsg s1 on", *tick(1))
    assert out == ["pulse 0.125 1 1 1"]


def test_the_view_moves_by_random_times_the_shake_times_3_after_it_decays_2_a_second(run):
    # A 0.6 pulse; each frame of 0.05 s takes 0.1 off first. Random 0.75 -> 0.5, 0 -> -1.
    out = run("rand\t0.75,0,0.75", "shake\ts1\t0 0 0\tamount=0.6,0.6,0.2", "run\tmsg s1 on", *tick(1),
              "view\t0.05", "view\t0.05", "amount", "view\t0.05", "amount")
    assert out[1:] == ["view 0.75 -1.5 0.15", "view 0.6 -1.2 0", "amount 0.4 0.4 0", "view 0.45 -0.9 0",
                       "amount 0.3 0.3 0"]


def test_pulses_add_up_to_10_per_axis(run):
    out = run("shake\tbig\t0 0 0\tamount=3,6,1", "run\tmsg big on", *tick(1), "run\tmsg big on", *tick(1),
              "amount")
    assert out[-1] == "amount 6 10 2"


def test_a_move_under_a_tenth_of_a_unit_is_left_out_and_a_spent_shake_moves_nothing(run):
    # 0.06 after the decay: 0.5 x 0.06 x 3 = 0.09 on one axis, |d|^2 0.0081 < 0.01.
    out = run("rand\t0.75", "shake\ts1\t0 0 0\tamount=0.16,0,0", "run\tmsg s1 on", *tick(1),
              "view\t0.05", "amount", "view\t1", "amount", "view\t0.05")
    assert out[1:] == ["view 0 0 0", "amount 0.06 0 0", "view 0 0 0", "amount 0 0 0", "view 0 0 0"]
