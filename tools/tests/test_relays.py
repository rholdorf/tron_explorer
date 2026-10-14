"""The viewer's triggers and relays (TronViewer/.../Relays.cs), compiled with .NET with the command manager
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
  group <name> <member>...        join a Group passing its messages on to its members
  player [hear]                   join the player ("player"); with "hear" it prints what it gets
  start <command>                 the start point's command, for the player's first update
  frame <dt> [<x y z>]            one frame: timelines, the pending-command table, then triggers with the
                                  player's box centred at x y z (half-extents 24 53 24), or no player
  run <command>                   run a command string with no sender
  echo <text>                     print <text>
  report                          print "unhandled <verb> <class> <word> <count>" per row of the report
Handlers print "got <receiver> <sender> <message words joined by |>".
"""
import base64
import glob
import os

import pytest

from conftest import cs_driver


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
                case "group":
                    mgr.JoinGroup(a[1], a.Skip(2));
                    break;
                case "player":
                {
                    int id = player = mgr.Join("player", "Player");
                    if (a.Length > 1 && a[1] == "hear")
                        mgr.Handle(id, m =>
                        {
                            Console.WriteLine("got\tplayer\t" + name(m.Sender) + "\t" + string.Join("|", m.Words));
                            return true;
                        });
                    break;
                }
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
                    mgr.BeginFrame(dt);
                    relays.UpdateTimelines();
                    mgr.Update();
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
                case "start":
                    relays.StartCommand = a[1];
                    break;
                case "$$start":
                    relays.StartCommand = System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(a[1]));
                    break;
                case "run":
                    mgr.Run(a[1]);
                    break;
                case "echo":
                    Console.WriteLine(a[1]);
                    break;
                case "report":
                    foreach (var u in mgr.Unhandled)
                        Console.WriteLine("unhandled\t" + u.Verb + "\t" + u.Class + "\t" + u.Word + "\t" + u.Count);
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    run_driver = cs_driver(tmp_path_factory, "relays", DRIVER, "Commands.cs", "Relays.cs", "KeyframerMotion.cs")

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        out = run_driver(text)
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


def test_an_exit_trigger_counts_the_level_switch_it_skips_after_running_its_commands(driver):
    # The 39 ExitTriggers all have ExitMission FALSE: a level switch. Once per activation, not per message.
    out = driver([("obj", "a", "WorldModel"),
                  trigger("x", "$Command1=msg a on", cls="ExitTrigger"),
                  ("run", "msg x trigger"), ("run", "msg x trigger"), ("report",)])
    assert out == [("got", "a", "-", "on"), ("unhandled", "EXIT", "ExitTrigger", "LEVEL", "1")]


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


def test_the_start_points_command_runs_at_the_players_first_update_after_the_level_objects(driver):
    out = driver([("obj", "a", "WorldModel"),
                  ("relay", "s", "StartupCommand", "0 0 0", "$Command=msg a startup"),
                  trigger("t", "$Command1=msg a touched"), ("player",), ("start", "msg a start;delay 0.1 (msg a later)"),
                  ("frame", 0.1), ("echo", "spawned"), ("frame", 0.1, INSIDE), ("echo", "f2"),
                  ("frame", 0.1, INSIDE), ("echo", "f3"), ("frame", 0.1, INSIDE)])
    # CPlayerObj::Update: SendStartLevelCommand on the player's first update, once, sender and active target
    # the player. The player is created after the level's objects, so it updates after them.
    assert out == [("got", "a", "s", "startup"), ("spawned",), ("got", "a", "player", "touched"),
                   ("got", "a", "player", "start"), ("f2",), ("got", "a", "player", "later"), ("f3",)]


def test_m10_04s_startup_command_declares_a_variable_and_a_when_that_are_reported_and_triggers_trigger0(driver):
    command = "Int BitCounter 0;When (BitCounter == 4) Then (MSG BitsReleased Trigger;msg trigger0 trigger"
    out = driver([("obj", "trigger0", "Trigger"), ("obj", "BitsReleased", "Trigger"),
                  ("relay", "StartupCommand0", "StartupCommand", "0 0 0", "$Command=" + command)] + frames(1) +
                 [("report",)])
    # ';' splits inside the parentheses: INT and WHEN (counted, the viewer has no variables), a MSG with four
    # words (skipped), then "msg trigger0 trigger", the level's opening sequence.
    assert out == [("got", "trigger0", "StartupCommand0", "trigger"), ("f1",),
                   ("unhandled", "INT", "", "", "1"), ("unhandled", "WHEN", "", "", "1")]


def level_lines(w, receivers=(), hear_player=False):
    """Driver lines joining every object of a loaded level as the viewer does: groups with their
    Object1..50, relays and startup commands with their props, objects of the classes in `receivers`
    printing what they get and the rest taking nothing; then the player with the start point's command.
    Returns (lines, the start point's position as "x y z")."""
    lines, start = [], None
    for o in w.objects:
        p, cls = o["props"], o["class"]
        name = p.get("Name", "")
        if cls == "Group":
            lines.append(("group", name, *[p.get(f"Object{i}", "") or "" for i in range(1, 51)]))
        elif cls in ("Trigger", "NoPlayerTrigger", "ExitTrigger", "EventCounter", "CommandObject", "StartupCommand",
                     "IONode"):
            props = []
            for k, v in p.items():
                if isinstance(v, str):
                    props.append(f"$${k}=" + base64.b64encode(v.encode()).decode())
                elif isinstance(v, (bool, int, float)):
                    props.append(f"{k}={float(v)}")
                elif isinstance(v, list) and len(v) >= 3 and k != "Rotation":
                    props.append(f"{k}=" + ",".join(str(float(x)) for x in v))
            lines.append(("relay", name, cls, " ".join(str(float(x)) for x in p.get("Pos", [0, 0, 0])), *props))
        else:
            lines.append(("obj" if cls in receivers else "deaf", name, cls))
        if cls == "GameStartPoint" and p.get("GameType") == "Single" and start is None:
            start = p
    lines.append(("player", "hear") if hear_player else ("player",))
    if start is not None and start.get("Command"):
        lines.append(("$$start", base64.b64encode(start["Command"].encode()).decode()))
    pos = " ".join(str(float(x)) for x in (start or {}).get("Pos", [0, 0, 0]))
    return lines, pos


def test_every_levels_load_commands_run_headless(driver, extracted):
    """The 38 single-player levels as loaded: startup commands and the start point's command, then 30 s of
    frames with the player standing at the start point. Nothing throws or recurses for ever, and the levels
    the living-level map flagged start what their startup commands start (keyframers, and m07-02's floaters,
    sliding doors that loop on their ClosedCommand)."""
    import dat85
    movers = ("KeyFramer", "SlidingDoor", "RotatingDoor", "SpinningWorldModel")
    started = {}
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        name = os.path.basename(f)[:-4]
        lines, pos = level_lines(dat85.load(f), receivers=movers)
        out = driver(lines + [("frame", 0.1, pos)] * 300 + [("echo", "end")])
        assert out[-1] == ("end",), name
        started[name] = {(g[1].lower(), g[3].lower()) for g in out if g[0] == "got"}
    assert {("dsdtkf", "on"), ("dsdmkf", "on"), ("dsdbkf", "on")} <= started["m02-01"]   # through startupcmdgroup
    assert {("flybykf", "on"), ("slidingdoor2", "trigger"), ("slidingdoor18", "trigger")} <= started["m04-01"]
    assert ("shuttlekf01", "on") in started["m10-02"]
    assert {(f"floater0{i}", "trigger") for i in range(1, 5)} <= started["m07-02"]   # through startupgrp


# ---- IONode (Tron-only; object.lto 0x10022960 OnTrigger, 0x10022ff0 its activation) ----

def test_cineactivate_runs_an_io_nodes_trigger_command_at_once_as_its_sender(driver):
    out = driver([("obj", "a", "WorldModel"), ("obj", "player", "Player"),
                  ("relay", "node", "IONode", "0 0 0", "$TriggerCommand=msg a trigger;msg player (fadein .5)"),
                  ("run", "msg node cineactivate"), ("echo", "again"), ("run", "msg node CINEACTIVATE"), ("report",)])
    # The activation runs TriggerCommand right away (IsValidCmd, then Process with the node as sender and no
    # active target), every time: the node has no once-only gate. (A message to the player has the player as
    # its sender.)
    assert out == [("got", "a", "node", "trigger"), ("got", "player", "player", "fadein|.5"), ("again",),
                   ("got", "a", "node", "trigger"), ("got", "player", "player", "fadein|.5")]


def test_cinedeactivate_is_taken_and_an_io_node_with_no_trigger_command_does_nothing(driver):
    out = driver([("relay", "node", "IONode", "0 0 0", "$TriggerCommand="),
                  ("run", "msg node cineactivate"), ("run", "msg node cinedeactivate"), ("report",)])
    # CINEDEACTIVATE only moves the node's look to its closing state (no commands); an empty TriggerCommand
    # runs nothing. Neither is reported.
    assert out == []


def test_m10_04s_intro_fades_out_then_its_io_node_fades_back_in(driver, extracted):
    """m10-04 (ticket #38): the intro cutscene's keyframer triggers Fade2TR, which fades out and half a second
    later triggers masterstartup; that cineactivates IONodeM10-04A, whose TriggerCommand fades back in."""
    import dat85
    lines, pos = level_lines(dat85.load(os.path.join(extracted, "worlds", "retailsingleplayer", "m10-04.dat")),
                             hear_player=True)
    out = driver(lines + [("frame", 0.1, pos)] * 5 + [("run", "msg Fade2TR trigger")] +
                 [("frame", 0.1, pos)] * 10)
    fades = [g[3] for g in out if g[0] == "got" and g[1] == "player" and g[3].lower().startswith("fade")]
    assert fades == ["fadeout|.3", "fadein|.5"]
