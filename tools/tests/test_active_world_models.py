"""Doors, switches and sliding/rotating world models (TronViewer/.../ActiveWorldModel.cs), compiled with Mono
and driven line by line. Rules: docs/research/triggers-doors.md (ltjs activeworldmodel.cpp, door.cpp).
Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  new <name> <class> <x,y,z> <pitch,yaw,roll> [<rotation point x,y,z> | -] <prop>=<value>...
                         a new AWM (props: booleans 1/0, numbers, vectors x,y,z, strings)
  start <name>           the end of its creation (StartOn powers on)
  link <a> <b>           a's DoorLink is b
  tick <seconds>         one frame: the clock advances, then every AWM updates in creation order
  use <name>             the player's use
  msg <name> <sender> <word>...   a message (sender: player, - for none, or a number); prints "handled"
  block <0|1>            whether the player is in the way of any new pose
  player <x,y,z>         the player's position
  pose <name>            prints "pose <x> <y> <z> <qx> <qy> <qz> <qw> <state>"
Host events print as "sound <name> <file> <loop>", "stop <name>", "run <name> <command> <activator>".
The player's command-manager id is 1000.
"""
import math
import os
import shutil
import subprocess

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")
PLAYER = 1000

DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Tron;
class Props : ActiveWorldModel.IProps
{
    public readonly Dictionary<string, string> D = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    public bool Bool(string k) => D.TryGetValue(k, out var v) && v == "1";
    public float Num(string k) => D.TryGetValue(k, out var v) ? Driver.F(v) : 0;
    public string Str(string k) => D.TryGetValue(k, out var v) ? v : "";
    public LTVec Vec(string k) => D.TryGetValue(k, out var v) ? Driver.V(v) : new LTVec(0, 0, 0);
}
class Host : ActiveWorldModel.IHost
{
    public string Name;
    public float Time => Driver.Now;
    public void PlaySound(string name, bool loop) => Console.WriteLine("sound\t" + Name + "\t" + name + "\t" + loop);
    public void StopLoop() => Console.WriteLine("stop\t" + Name);
    public void Run(string command, int activator) => Console.WriteLine("run\t" + Name + "\t" + command + "\t" + activator);
    public bool PlayerInside(LTVec pos, LTQuat rot) => Driver.Blocked;
    public LTVec? PositionOf(int obj) => obj == 1000 ? Driver.Player : (LTVec?)null;
}
static class Driver
{
    public static float Now;
    public static bool Blocked;
    public static LTVec Player;
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    public static float F(string s) => float.Parse(s, Inv);
    public static LTVec V(string s) { var a = s.Split(','); return new LTVec(F(a[0]), F(a[1]), F(a[2])); }
    static string G(float v) => ((double)v).ToString("R", Inv);
    static void Main()
    {
        var awms = new Dictionary<string, ActiveWorldModel>();
        var order = new List<ActiveWorldModel>();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "new":
                {
                    var p = new Props();
                    foreach (var kv in a.Skip(6)) { int i = kv.IndexOf('='); p.D[kv.Substring(0, i)] = kv.Substring(i + 1); }
                    var s = ActiveWorldModel.Settings.Read(a[2], p);
                    var awm = new ActiveWorldModel(s, V(a[3]), V(a[4]), a[5] == "-" ? (LTVec?)null : V(a[5]), order.Count, 1000, new Host { Name = a[1] });
                    awms[a[1]] = awm;
                    order.Add(awm);
                    break;
                }
                case "start": awms[a[1]].Start(); break;
                case "link": awms[a[1]].Link = awms[a[2]]; break;
                case "tick":
                    Now += F(a[1]);
                    foreach (var w in order) w.Update(F(a[1]));
                    break;
                case "use": awms[a[1]].Activate(1000); break;
                case "msg":
                {
                    int sender = a[2] == "player" ? 1000 : a[2] == "-" ? -1 : int.Parse(a[2]);
                    Console.WriteLine("handled\t" + awms[a[1]].Handle(new Message(a.Skip(3).ToArray(), sender)));
                    break;
                }
                case "block": Blocked = a[1] == "1"; break;
                case "player": Player = V(a[1]); break;
                case "pose":
                {
                    var w = awms[a[1]];
                    var r = w.Rot;
                    Console.WriteLine(string.Join("\t", new[] { "pose", G(w.Pos.x), G(w.Pos.y), G(w.Pos.z), G(r.x), G(r.y), G(r.z), G(r.w), w.Current.ToString() }));
                    break;
                }
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    mcs, mono = shutil.which("mcs"), shutil.which("mono")
    if not mcs or not mono:
        pytest.skip("Mono (mcs, mono) not installed")
    d = tmp_path_factory.mktemp("awm")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs"),
                        *(os.path.join(SCRIPTS, f) for f in ("ActiveWorldModel.cs", "Commands.cs", "KeyframerMotion.cs"))],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def go(*lines):
        text = "".join("\t".join(str(x) for x in line) + "\n" for line in lines)
        out = subprocess.run([mono, exe], input=text, capture_output=True, text=True, check=True).stdout
        return [ln.split("\t") for ln in out.splitlines()]
    return go


def poses(out):
    return [(float(p[1]), float(p[2]), float(p[3]), p[8]) for p in out if p[0] == "pose"]


def events(out):
    return [p for p in out if p[0] != "pose"]


def close(a, b, eps=1e-3):
    return all(abs(x - y) < eps for x, y in zip(a, b))


# A lift: up 64 units in 1 s, Linear, used by the player, closes on its own after 2 s.
DOOR = ("new", "d", "SlidingDoor", "0,0,0", "0,0,0", "-", "AWMType=1", "PlayerActivate=1", "MoveDir=0,1,0",
        "MoveDist=64", "OpeningTime=1", "OpenWaitTime=2", "Waveform=Linear", "OpeningSound=snd\\open.wav",
        "OpenSound=snd\\opened.wav", "ClosingSound=snd\\close.wav", "ClosedSound=snd\\closed.wav",
        "OpeningCommand=msg a on", "OpenCommand=msg b on", "ClosingCommand=msg c on", "ClosedCommand=msg d on")


def door(*extra):
    return DOOR + extra


def ticks(n, dt=0.25, name="d"):
    out = []
    for _ in range(n):
        out += [("tick", dt), ("pose", name)]
    return out


def test_a_door_at_rest_does_nothing_until_used(run):
    out = run(door(), ("start", "d"), *ticks(2))
    assert events(out) == []
    assert poses(out) == [(0, 0, 0, "Off")] * 2


def test_using_a_door_slides_it_its_distance_over_its_opening_time(run):
    out = run(door(), ("start", "d"), ("use", "d"), *ticks(4))
    assert poses(out) == [(0, 16, 0, "PowerOn"), (0, 32, 0, "PowerOn"), (0, 48, 0, "PowerOn"), (0, 64, 0, "On")]


def test_each_state_plays_its_sound_and_runs_its_command_with_the_player_as_activator(run):
    out = run(door(), ("start", "d"), ("use", "d"), *ticks(4))
    assert events(out) == [["sound", "d", "snd\\open.wav", "False"], ["run", "d", "msg a on", str(PLAYER)],
                           ["sound", "d", "snd\\opened.wav", "False"], ["run", "d", "msg b on", str(PLAYER)]]


def test_a_door_that_neither_remains_open_nor_closes_on_use_closes_after_its_wait(run):
    # Open at t=1; closes on the first update past 1 + 2 s, then takes its opening time back down.
    out = run(door(), ("start", "d"), ("use", "d"), *ticks(17))
    p = poses(out)   # p[i] at t = (i + 1) / 4
    assert [x[3] for x in p[3:12]] == ["On"] * 9
    assert p[12] == (0, 64, 0, "PowerOff")   # t=3.25: UpdateOn turns it off; it moves from the next frame
    assert p[13] == (0, 48, 0, "PowerOff") and p[16] == (0, 0, 0, "Off")
    ev = events(out)
    assert ev[4:] == [["sound", "d", "snd\\close.wav", "False"], ["run", "d", "msg c on", str(PLAYER)],
                      ["sound", "d", "snd\\closed.wav", "False"], ["run", "d", "msg d on", str(PLAYER)]]


def test_using_an_open_auto_closing_door_again_restarts_its_wait(run):
    out = run(door(), ("start", "d"), ("use", "d"), *ticks(8), ("use", "d"), *ticks(9))
    p = poses(out)
    # re-armed at t=2 (no sound, no command): closes past t=4, not past t=3
    assert [x[3] for x in p[8:16]] == ["On"] * 8
    assert p[16] == (0, 64, 0, "PowerOff")
    assert len(events(out)) == 6


def test_a_trigger_close_door_stays_open_and_toggles_on_use(run):
    out = run(door("TriggerClose=1"), ("start", "d"), ("use", "d"), *ticks(20), ("use", "d"), *ticks(4))
    p = poses(out)
    assert p[19] == (0, 64, 0, "On")
    assert p[20:] == [(0, 48, 0, "PowerOff"), (0, 32, 0, "PowerOff"), (0, 16, 0, "PowerOff"), (0, 0, 0, "Off")]


def test_a_remain_open_door_opens_once_and_stays(run):
    out = run(door("RemainOpen=1"), ("start", "d"), ("use", "d"), *ticks(20), ("use", "d"), *ticks(4))
    assert all(p == (0, 64, 0, "On") for p in poses(out)[3:])
    assert len(events(out)) == 4


def test_closing_time_zero_closes_in_the_opening_time(run):
    out = run(door("TriggerClose=1", "OpenWaitTime=0", "OpeningTime=2", "ClosingTime=0"), ("start", "d"), ("use", "d"),
              *ticks(8), ("use", "d"), *ticks(8))
    p = poses(out)
    assert p[0][1] == 8 and p[7] == (0, 64, 0, "On")
    assert p[8][1] == 56 and p[15] == (0, 0, 0, "Off")


def test_the_sine_wave_starts_from_rest(run):
    out = run(door("Waveform=Sine"), ("start", "d"), ("use", "d"), *ticks(2))
    p = poses(out)
    # GetWaveformValue at 0% is 0; at 25%: pi/2 x 64 x sin(pi/4) per second, for 0.25 s
    assert p[0][1] == 0
    assert close([p[1][1]], [math.pi / 2 * 64 * math.sin(math.pi / 4) * 0.25])


def test_a_door_turns_its_move_direction_by_its_rotation(run):
    # MoveDir +Z in the door's frame, yawed 90 degrees: +Z becomes +X
    yawed = ("new", "d", "SlidingDoor", "0,0,0", f"0,{math.pi / 2},0", "-") + DOOR[6:] + ("MoveDir=0,0,1",)
    out = run(yawed, ("start", "d"), ("use", "d"), *ticks(1))
    assert close(poses(out)[0][:3], (16, 0, 0))


def test_a_locked_door_plays_its_locked_sound_and_command_and_stays_shut_until_unlocked(run):
    out = run(door("Locked=1", "LockedSound=snd\\lock.wav", "LockedCommand=msg nope trigger"), ("start", "d"),
              ("use", "d"), *ticks(2), ("msg", "d", "-", "UNLOCK"), ("use", "d"), *ticks(1))
    assert poses(out) == [(0, 0, 0, "Off"), (0, 0, 0, "Off"), (0, 16, 0, "PowerOn")]
    assert events(out)[:3] == [["sound", "d", "snd\\lock.wav", "False"], ["run", "d", "msg nope trigger", str(PLAYER)],
                               ["handled", "True"]]


def test_lock_also_stops_trigger_messages(run):
    out = run(door(), ("start", "d"), ("msg", "d", "-", "lock"), ("msg", "d", "-", "trigger"), *ticks(1))
    assert poses(out) == [(0, 0, 0, "Off")]


def test_a_trigger_message_works_like_use_and_the_commands_get_no_activator(run):
    out = run(door(), ("start", "d"), ("msg", "d", "5", "TRIGGER"), *ticks(1))
    assert poses(out) == [(0, 16, 0, "PowerOn")]
    assert ["run", "d", "msg a on", "-1"] in events(out)


def test_on_works_only_when_off_or_closing_and_off_only_when_on_or_opening(run):
    out = run(door("TriggerClose=1", "OpenWaitTime=0"), ("start", "d"), ("msg", "d", "-", "off"), *ticks(1),
              ("msg", "d", "7", "on"), *ticks(4), ("msg", "d", "-", "on"), *ticks(1), ("msg", "d", "-", "off"), *ticks(1))
    assert [p[3] for p in poses(out)] == ["Off", "PowerOn", "PowerOn", "PowerOn", "On", "On", "PowerOff"]
    assert ["run", "d", "msg a on", "7"] in events(out)


def test_using_a_door_while_it_opens_turns_it_back(run):
    out = run(door(), ("start", "d"), ("use", "d"), *ticks(2), ("use", "d"), *ticks(2))
    assert poses(out) == [(0, 16, 0, "PowerOn"), (0, 32, 0, "PowerOn"), (0, 16, 0, "PowerOff"), (0, 0, 0, "Off")]


def test_a_door_forced_to_open_ignores_use_until_it_is_open(run):
    out = run(door("ForceMoveOn=1"), ("start", "d"), ("use", "d"), *ticks(2), ("use", "d"), *ticks(2))
    assert [p[1] for p in poses(out)] == [16, 32, 48, 64]


def test_the_player_in_the_way_holds_the_door_where_it_is_and_its_clock_with_it(run):
    out = run(door(), ("start", "d"), ("use", "d"), *ticks(1), ("block", 1), *ticks(3), ("block", 0), *ticks(1))
    assert [p[1] for p in poses(out)] == [16, 16, 16, 16, 32]


def test_a_forced_door_moves_through_the_player(run):
    out = run(door("ForceMove=1"), ("start", "d"), ("block", 1), ("use", "d"), *ticks(2))
    assert [p[1] for p in poses(out)] == [16, 32]


def test_a_door_waits_its_move_delay_before_opening_and_twice_that_before_closing(run):
    out = run(door("MoveDelay=0.5", "TriggerClose=1", "OpenWaitTime=0"), ("start", "d"), ("use", "d"), *ticks(6),
              ("use", "d"), *ticks(5))
    p = [x[1] for x in poses(out)]
    assert p[:6] == [0, 16, 32, 48, 64, 64]          # starts at t=0.5
    assert p[6:] == [64, 64, 64, 48, 32]             # 2 x 0.5 s after the use


def test_a_door_that_starts_open_opens_at_load_with_its_sound_and_command(run):
    out = run(door("StartOpen=1"), ("start", "d"), *ticks(4))
    assert poses(out)[-1] == (0, 64, 0, "On")
    assert events(out)[:2] == [["sound", "d", "snd\\open.wav", "False"], ["run", "d", "msg a on", "-1"]]


def test_a_looping_sound_is_stopped_by_the_next_state_even_one_without_a_sound(run):
    out = run(door("LoopSounds=1", "OpenSound="), ("start", "d"), ("use", "d"), *ticks(4))
    assert events(out) == [["sound", "d", "snd\\open.wav", "True"], ["run", "d", "msg a on", str(PLAYER)],
                           ["stop", "d"], ["run", "d", "msg b on", str(PLAYER)]]


def test_a_door_that_starts_opening_opens_its_linked_door_too(run):
    out = run(door("TriggerClose=1"), ("new", "e") + door("TriggerClose=1", "OpeningCommand=msg e1 on")[2:],
              ("link", "d", "e"), ("start", "d"), ("start", "e"), ("use", "d"), *ticks(1), ("pose", "e"))
    assert [p[1] for p in poses(out)] == [16, 16]
    assert ["run", "e", "msg e1 on", str(PLAYER)] in events(out)


def test_a_switch_reads_the_generic_names(run):
    sw = ("new", "s", "SlidingSwitch", "0,0,0", "0,0,0", "-", "AWMType=1", "PlayerActivate=1", "MoveDist=0",
          "PowerOnTime=0", "TriggerOff=1", "PowerOnSound=snd\\click.wav", "OnCommand=msg lift trigger",
          "OffCommand=msg lift trigger")
    out = run(sw, ("start", "s"), ("use", "s"), *ticks(1, name="s"), ("use", "s"), *ticks(1, name="s"))
    assert [p[3] for p in poses(out)] == ["On", "Off"]
    assert events(out) == [["sound", "s", "snd\\click.wav", "False"], ["run", "s", "msg lift trigger", str(PLAYER)],
                           ["run", "s", "msg lift trigger", str(PLAYER)]]


def test_only_the_player_uses_and_only_with_player_activate(run):
    out = run(door("PlayerActivate=0"), ("start", "d"), ("use", "d"), ("msg", "d", "3", "ACTIVATE"), *ticks(1))
    assert poses(out) == [(0, 0, 0, "Off")]


def test_messages_it_does_not_know_are_left_for_other_handlers(run):
    out = run(door(), ("msg", "d", "-", "hidden", "1"), ("msg", "d", "-", "TRIGGERCLOSE"))
    assert events(out) == [["handled", "False"], ["handled", "True"]]


ROT = ("new", "r", "RotatingDoor", "100,0,0", "0,0,0", "0,0,0", "AWMType=2", "PlayerActivate=1",
       "RotationAngles=0,90,0", "OpeningTime=1", "TriggerClose=1", "Waveform=Linear")


def test_a_rotating_door_turns_about_its_rotation_point(run):
    out = run(ROT, ("start", "r"), ("use", "r"), *ticks(5, name="r"))
    p = [x for x in out if x[0] == "pose"]
    assert close([float(v) for v in p[1][1:8]], (100 * math.cos(math.pi / 4), 0, -100 * math.sin(math.pi / 4),
                                                 0, math.sin(math.pi / 8), 0, math.cos(math.pi / 8)))
    assert close([float(v) for v in p[3][1:8]], (0, 0, -100, 0, math.sin(math.pi / 4), 0, math.cos(math.pi / 4)))
    # it reaches the angle on the 4th frame and turns on in the next
    assert [x[8] for x in p] == ["PowerOn"] * 4 + ["On"]


def test_a_rotating_door_that_opens_away_swings_away_from_the_player(run):
    # A yaw of +1 rad would take the door to (54, 0, -84), -1 rad to (54, 0, 84): the player at (50, 0, -50)
    # is nearer the first, so it turns the other way.
    out = run(ROT + ("OpenAway=1",), ("player", "50,0,-50"), ("start", "r"), ("use", "r"), *ticks(5, name="r"))
    assert close(poses(out)[-1][:3], (0, 0, 100))
    out = run(ROT + ("OpenAway=1",), ("player", "50,0,50"), ("start", "r"), ("use", "r"), *ticks(5, name="r"))
    assert close(poses(out)[-1][:3], (0, 0, -100))


def test_a_rotating_door_the_player_used_is_not_held_by_a_player_it_turns_away_from(run):
    # The player on the -Z side; the door turns toward -Z (nearer the player: held) unless it opens away.
    out = run(ROT, ("player", "50,0,-50"), ("block", 1), ("start", "r"), ("use", "r"), *ticks(2, name="r"))
    assert close(poses(out)[-1][:3], (100, 0, 0))
    out = run(ROT, ("player", "50,0,60"), ("block", 1), ("start", "r"), ("use", "r"), *ticks(2, name="r"))
    assert close(poses(out)[-1][:3], (100 * math.cos(math.pi / 4), 0, -100 * math.sin(math.pi / 4)))


def test_a_toggling_door_cannot_be_closed_before_its_open_wait_time(run):
    out = run(door("TriggerClose=1"), ("start", "d"), ("use", "d"), *ticks(5), ("use", "d"), *ticks(8),
              ("use", "d"), *ticks(1))
    p = poses(out)
    assert all(x == (0, 64, 0, "On") for x in p[4:13])   # used at t=1.25: open since t=1, wait 2 s
    assert p[13] == (0, 48, 0, "PowerOff")               # used at t=3.25
