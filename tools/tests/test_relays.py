"""The viewer's triggers and relays (TronViewer/.../Relays.cs), compiled with Mono with the command manager
(Commands.cs) and driven frame by frame. Rules: docs/research/triggers-doors.md (trigger.cpp,
noplayertrigger.cpp) and docs/research/command-language.md (eventcounter.cpp with Tron's RESET,
commandobject.cpp, game/shared/timer.h). Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  obj <name> <class>              join an object that handles every message (prints "got")
  relay <name> <class> <x y z> <prop>...
                                  join a level object and hand it to Relays; a prop is "$Key=text" (a string)
                                  or "Key=1,2,3" (a number, bool or vector); "$$Key=<base64>" for a string
                                  with control characters
  deaf <name> <class>             join an object that handles no message
  player                          join the player ("player")
  frame <dt> [<x y z>]            one frame: timelines, the pending-command table, then triggers with the
                                  player's box centred at x y z (half-extents 24 53 24), or no player
  run <command>                   run a command string with no sender
  echo <text>                     print <text>
Handlers print "got <receiver> <sender> <message words joined by |>".
"""
import base64
import glob
import os
import shutil
import subprocess

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")

DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Tron;
static class Driver
{
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var mgr = new CommandMgr(() => 0.0);
        var relays = new Relays(mgr);
        int player = -1;
        Func<int, string> name = id => id < 0 ? "-" : mgr.Name(id);
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "obj":
                {
                    int id = mgr.Join(a[1], a[2]);
                    mgr.Handle(id, m =>
                    {
                        Console.WriteLine("got\t" + mgr.Name(id) + "\t" + name(m.Sender) + "\t" + string.Join("|", m.Words));
                        return true;
                    });
                    break;
                }
                case "deaf":
                    mgr.Join(a[1], a[2]);
                    break;
                case "player":
                    player = mgr.Join("player", "Player");
                    break;
                case "relay":
                {
                    var strs = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    var nums = new Dictionary<string, float[]>(StringComparer.OrdinalIgnoreCase);
                    foreach (var p in a.Skip(4))
                    {
                        int eq = p.IndexOf('=');
                        if (p.StartsWith("$$")) strs[p.Substring(2, eq - 2)] = System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(p.Substring(eq + 1)));
                        else if (p[0] == '$') strs[p.Substring(1, eq - 1)] = p.Substring(eq + 1);
                        else nums[p.Substring(0, eq)] = p.Substring(eq + 1).Split(',').Select(v => float.Parse(v, inv)).ToArray();
                    }
                    var pos = a[3].Split(' ').Select(v => float.Parse(v, inv)).ToArray();
                    int id = mgr.Join(a[1], a[2]);
                    relays.Add(id, a[2], new LTVec(pos[0], pos[1], pos[2]), strs, nums);
                    break;
                }
                case "frame":
                {
                    float dt = float.Parse(a[1], inv);
                    relays.UpdateTimelines(dt);
                    mgr.Update(dt);
                    if (a.Length > 2)
                    {
                        var p = a[2].Split(' ').Select(v => float.Parse(v, inv)).ToArray();
                        var c = new LTVec(p[0], p[1], p[2]);
                        var h = new LTVec(24, 53, 24);
                        relays.UpdateObjects(player, c - h, c + h);
                    }
                    else relays.UpdateObjects(-1, default(LTVec), default(LTVec));
                    break;
                }
                case "run":
                    mgr.Run(a[1]);
                    break;
                case "echo":
                    Console.WriteLine(a[1]);
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    mcs, mono = shutil.which("mcs"), shutil.which("mono")
    if not mcs or not mono:
        pytest.skip("Mono (mcs, mono) not installed")
    d = tmp_path_factory.mktemp("relays")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs")] +
                       [os.path.join(SCRIPTS, f) for f in ("Commands.cs", "Relays.cs", "KeyframerMotion.cs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        out = subprocess.run([mono, exe], input=text, capture_output=True, text=True, check=True).stdout
        return [tuple(x.split("\t")) for x in out.splitlines()]
    return run


# A player-touch trigger at the origin, 16 units each way, that fires once (the editor's defaults where
# they matter: ActivationCount 1, NumberOfActivations 1, PlayerTriggerable 1).
def trigger(name="t", *props, cls="Trigger", pos="0 0 0"):
    return ("relay", name, cls, pos, "Dims=16,16,16", *props)


INSIDE, OUTSIDE = "0 40 0", "0 200 0"   # the player's box (half height 53) reaches the trigger at y 40


def test_the_player_walking_into_a_trigger_runs_its_commands_once(driver):
    out = driver([("obj", "a", "WorldModel"), ("player",),
                  trigger("t", "$Command1=msg a on", "$Command2=msg a (hidden 0)"),
                  ("frame", 0.1, OUTSIDE), ("echo", "in"), ("frame", 0.1, INSIDE), ("frame", 0.1, INSIDE),
                  ("frame", 0.1, OUTSIDE), ("frame", 0.1, INSIDE)])
    # The commands run with the toucher (the player) as the sender.
    assert out == [("in",), ("got", "a", "player", "on"), ("got", "a", "player", "hidden|0")]


def test_an_unlimited_trigger_fires_every_frame_the_player_is_inside_unless_trigger_delay_holds_it(driver):
    out = driver([("obj", "a", "WorldModel"), ("player",),
                  trigger("t", "$Command1=msg a on", "NumberOfActivations=0"),
                  trigger("d", "$Command1=msg a delayed", "NumberOfActivations=-1", "TriggerDelay=0.25", pos="0 0 0"),
                  ("frame", 0.1, INSIDE), ("echo", "1"), ("frame", 0.1, INSIDE), ("echo", "2"),
                  ("frame", 0.1, INSIDE), ("echo", "3"), ("frame", 0.1, INSIDE), ("echo", "4"),
                  ("frame", 0.1, INSIDE)])
    # With a TriggerDelay the touch at t=0.1 activates at the trigger's next update (t=0.2); the next touch
    # that counts is the first at or after 0.1 + 0.25.
    assert out == [("got", "a", "player", "on"), ("1",),
                   ("got", "a", "player", "on"), ("got", "a", "player", "delayed"), ("2",),
                   ("got", "a", "player", "on"), ("3",),
                   ("got", "a", "player", "on"), ("4",),
                   ("got", "a", "player", "on"), ("got", "a", "player", "delayed")]


def test_a_trigger_message_fires_it_and_lock_holds_both_touch_and_message(driver):
    out = driver([("obj", "a", "WorldModel"), ("player",),
                  trigger("t", "$Command1=msg a on", "NumberOfActivations=0", "PlayerTriggerable=0"),
                  ("relay", "s2", "Trigger", "0 0 0", "$Command1=msg t trigger", "PlayerTriggerable=0", "NumberOfActivations=0"),
                  ("run", "msg t trigger"), ("frame", 0.1, INSIDE), ("echo", "touch ignored"),
                  ("run", "msg t lock; msg t trigger"), ("echo", "locked"),
                  ("run", "msg t unlock"), ("echo", "unlock doesn't fire"), ("run", "msg s2 trigger")])
    assert out == [("got", "a", "-", "on"), ("touch ignored",), ("locked",), ("unlock doesn't fire",),
                   ("got", "a", "-", "on")]   # a chain keeps the first toucher as the sender


def test_send_delay_waits_and_the_trigger_ignores_touches_meanwhile(driver):
    out = driver([("obj", "a", "WorldModel"), ("player",),
                  trigger("t", "$Command1=msg a on", "NumberOfActivations=0", "SendDelay=0.25"),
                  ("frame", 0.1, INSIDE), ("echo", "1"), ("frame", 0.1, INSIDE), ("echo", "2"),
                  ("frame", 0.1, OUTSIDE), ("echo", "3"), ("frame", 0.1, OUTSIDE)])
    # Touched at 0.1: fires at the first update at or after 0.35 (0.4), even with the player gone.
    assert out == [("1",), ("2",), ("3",), ("got", "a", "player", "on")]


def test_activation_count_fires_every_nth_activation_up_to_number_of_activations(driver):
    out = driver([("obj", "a", "WorldModel"),
                  trigger("t", "$Command1=msg a on", "ActivationCount=2", "NumberOfActivations=2")] +
                 [x for i in range(6) for x in (("echo", str(i)), ("run", "msg t trigger"))])
    assert out == [("0",), ("1",), ("got", "a", "-", "on"), ("2",), ("3",), ("got", "a", "-", "on"), ("4",), ("5",)]


def test_a_no_player_trigger_waits_for_the_player_to_leave_its_box(driver):
    out = driver([("obj", "a", "WorldModel"), ("player",),
                  trigger("n", "$Command1=msg a on", "NumberOfActivations=0", cls="NoPlayerTrigger"),
                  ("frame", 0.1, INSIDE), ("echo", "touch does nothing"),
                  ("run", "msg n trigger; msg n trigger"), ("frame", 0.1, INSIDE), ("frame", 0.1, INSIDE),
                  ("echo", "left"), ("frame", 0.05, OUTSIDE), ("echo", "next poll"), ("frame", 0.05, OUTSIDE)])
    # Polls every 0.1 s from the message (t=0.1): 0.2 and 0.3 find the player inside, 0.4 doesn't.
    assert out == [("touch does nothing",), ("left",), ("next poll",), ("got", "a", "-", "on")]


def test_an_exit_trigger_runs_its_commands_on_trigger_only(driver):
    out = driver([("obj", "a", "WorldModel"), ("player",),
                  trigger("x", "$Command1=msg a on", cls="ExitTrigger"),
                  ("frame", 0.1, INSIDE), ("echo", "touch does nothing"), ("run", "msg x trigger")])
    assert out == [("touch does nothing",), ("got", "a", "-", "on")]


def counter(name="c", *props):
    return ("relay", name, "EventCounter", "0 0 0", *props)


def test_an_event_counter_runs_the_commands_of_the_values_it_steps_onto(driver):
    out = driver([("obj", "a", "WorldModel"),
                  counter("c", "Event1Value=1", "$Event1IncToValCmd=msg a one", "Event2Value=3",
                          "$Event2IncToValCmd=msg a three", "$Event2DecToValCmd=msg a down3",
                          "Event3Value=1", "$Event3DecToValCmd=msg a down1", "Event4Value=-1"),
                  ("run", "msg c inc"), ("echo", "+2"), ("run", "msg c (increment 2)"),
                  ("echo", "dec"), ("run", "msg c (dec 5)"), ("echo", "floor"), ("run", "msg c decrement")])
    # Each step counts by one and runs every event whose value is the new count; it stops at 0.
    assert out == [("got", "a", "c", "one"), ("+2",), ("got", "a", "c", "three"),
                   ("dec",), ("got", "a", "c", "down1"), ("floor",)]


def test_a_locked_event_counter_ignores_steps_and_reset_goes_back_to_the_starting_value_silently(driver):
    out = driver([("obj", "a", "WorldModel"),
                  counter("c", "StartingValue=1", "Event1Value=2", "$Event1IncToValCmd=msg a two",
                          "Event2Value=1", "$Event2DecToValCmd=msg a back"),
                  ("run", "msg c lock; msg c inc"), ("echo", "unlocked"), ("run", "msg c unlock; msg c inc"),
                  ("echo", "reset"), ("run", "msg c reset"), ("echo", "inc"), ("run", "msg c inc")])
    assert out == [("unlocked",), ("got", "a", "c", "two"), ("reset",), ("inc",), ("got", "a", "c", "two")]


def command_object(name="co", *props):
    return ("relay", name, "CommandObject", "0 0 0", *props)


TIMELINE = ("$EventT0E0=0|msg a e0", "$EventT0E1=500|msg a e2", "$EventT1E0=250|msg a e1",
            "$FinishedCommand=msg a done")


def frames(n, dt=0.125):
    return [x for i in range(n) for x in (("frame", dt), ("echo", f"f{i + 1}"))]


def test_a_command_object_runs_its_events_on_time_then_its_finished_command(driver):
    out = driver([("obj", "a", "WorldModel"), command_object("co", *TIMELINE, "NumberOfActivations=-1"),
                  ("run", "msg co on")] + frames(4) + [("run", "msg co start")] + frames(1))
    # Each frame's lite update sees the frame's time: started at 0, the event at 0 runs at 0.125. The
    # sender (and active target) is the command object. At the end the events are re-armed.
    assert out == [("got", "a", "co", "e0"), ("f1",), ("got", "a", "co", "e1"), ("f2",), ("f3",),
                   ("got", "a", "co", "e2"), ("got", "a", "co", "done"), ("f4",),
                   ("got", "a", "co", "e0"), ("f1",)]


def test_on_doesnt_restart_a_running_timeline_and_off_stops_it_without_rearming(driver):
    out = driver([("obj", "a", "WorldModel"), command_object("co", *TIMELINE),
                  ("run", "msg co on")] + frames(1) + [("run", "msg co on")] + frames(1) +
                 [("run", "msg co off; msg co on")] + frames(4))
    # Restarted at 0.25 with e0 and e1 already run: e2 waits for 0.5 s from the restart.
    assert out == [("got", "a", "co", "e0"), ("f1",), ("got", "a", "co", "e1"), ("f1",),
                   ("f1",), ("f2",), ("f3",), ("got", "a", "co", "e2"), ("got", "a", "co", "done"), ("f4",)]


def test_pause_freezes_the_timeline_and_resume_continues_it(driver):
    out = driver([("obj", "a", "WorldModel"), command_object("co", *TIMELINE),
                  ("run", "msg co on")] + frames(1) + [("run", "msg co pause")] + frames(2) +
                 [("run", "msg co resume")] + frames(3))
    # Paused at 0.125 for 0.25 s: e1 (0.25) runs at 0.5 and e2 (0.5) at 0.75.
    assert out == [("got", "a", "co", "e0"), ("f1",), ("f1",), ("f2",),
                   ("got", "a", "co", "e1"), ("f1",), ("f2",), ("got", "a", "co", "e2"), ("got", "a", "co", "done"),
                   ("f3",)]


def test_a_command_object_is_removed_after_number_of_activations_and_ignores_on_while_locked(driver):
    out = driver([("obj", "a", "WorldModel"), command_object("co", "$EventT0E0=0|msg a e0", "NumberOfActivations=1",
                                                             "Locked=1"),
                  ("run", "msg co on")] + frames(1) + [("run", "msg co unlock; msg co on")] + frames(2) +
                 [("run", "msg co on")] + frames(1))
    assert out == [("f1",), ("got", "a", "co", "e0"), ("f1",), ("f2",), ("f1",)]


def test_an_events_delay_0_runs_in_the_same_frame_the_command_table_ticks_after_the_timelines(driver):
    out = driver([("obj", "a", "WorldModel"), command_object("co", "$EventT0E0=0|delay 0 (msg a later)"),
                  ("run", "msg co on")] + frames(1))
    assert out == [("got", "a", "co", "later"), ("f1",)]


def test_every_relay_in_the_levels_builds_and_fires(driver, extracted):
    """Every object of the 38 single-player levels joins (relays with their props); then every trigger gets
    TRIGGER, every command object ON and every counter INC, and the timelines run for 60 s: nothing throws
    or recurses for ever."""
    import dat85
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        w = dat85.load(f)
        lines, fire = [("player",)], []
        for o in w.objects:
            p, cls = o["props"], o["class"]
            name = p.get("Name", "")
            if cls not in ("Trigger", "NoPlayerTrigger", "ExitTrigger", "EventCounter", "CommandObject"):
                lines.append(("deaf", name, cls))
                continue
            props = []
            for k, v in p.items():
                if isinstance(v, str):
                    props.append(f"$${k}=" + base64.b64encode(v.encode()).decode())
                elif isinstance(v, (bool, int, float)):
                    props.append(f"{k}={float(v)}")
                elif isinstance(v, list) and len(v) >= 3 and k != "Rotation":
                    props.append(f"{k}=" + ",".join(str(float(x)) for x in v))
            lines.append(("relay", name, cls, " ".join(str(float(x)) for x in p.get("Pos", [0, 0, 0])), *props))
            word = {"EventCounter": "inc", "CommandObject": "on"}.get(cls, "trigger")
            if name and "\t" not in name:
                fire.append(("run", f"msg ({name}) {word}"))
        lines += fire + [("frame", 0.1, "0 0 0")] * 600 + [("echo", "end")]
        out = driver(lines)
        assert out[-1] == ("end",), f


def test_a_startup_command_runs_once_at_its_first_update_as_its_own_sender(driver):
    out = driver([("obj", "a", "WorldModel"),
                  ("relay", "s", "StartupCommand", "0 0 0", "$Command=msg a now;delay 0.1 (msg a later)"),
                  ("echo", "loaded")] + frames(3, 0.1))
    # startupcommand.cpp: Command runs at the object's first MID_UPDATE (the objects' update, after the
    # pending-command table), sender and active target itself, and the object is removed. Its delay starts
    # counting at the next frame's table tick.
    assert out == [("loaded",), ("got", "a", "s", "now"), ("f1",), ("got", "a", "s", "later"), ("f2",), ("f3",)]
