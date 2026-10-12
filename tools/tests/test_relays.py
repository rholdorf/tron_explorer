"""The viewer's triggers and relays (TronViewer/.../Relays.cs), compiled with Mono with the command manager
(Commands.cs) and driven frame by frame. Rules: docs/research/triggers-doors.md (trigger.cpp,
noplayertrigger.cpp) and docs/research/command-language.md (eventcounter.cpp with Tron's RESET,
commandobject.cpp, game/shared/timer.h). Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  obj <name> <class>              join an object that handles every message (prints "got")
  relay <name> <class> <x y z> <prop>...
                                  join a level object and hand it to Relays; a prop is "$Key=text" (a string)
                                  or "Key=1,2,3" (a number, bool or vector)
  player                          join the player ("player")
  frame <dt> [<x y z>]            one frame: timelines, the pending-command table, then triggers with the
                                  player's box centred at x y z (half-extents 24 53 24), or no player
  run <command>                   run a command string with no sender
  echo <text>                     print <text>
Handlers print "got <receiver> <sender> <message words joined by |>".
"""
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
                        if (p[0] == '$') strs[p.Substring(1, eq - 1)] = p.Substring(eq + 1);
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
                        relays.UpdateTriggers(player, c - h, c + h);
                    }
                    else relays.UpdateTriggers(-1, default(LTVec), default(LTVec));
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
