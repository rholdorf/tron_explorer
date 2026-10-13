"""Messages to the objects the viewer builds (ticket #33): the flags every object handles (GameBaseFlags.cs)
and the spinners' on / off state machine (SpinnerMotion.cs), compiled with Mono with the command manager
(Commands.cs) and driven frame by frame. Rules: docs/research/command-language.md "Per-class messages"
(ltjs gamebase.cpp, worldmodel.cpp, activeworldmodel.cpp, spinningworldmodel.cpp). Expected values are
worked by hand from those rules.

Driver lines (tab-separated):
  flags <name> <visible> <solid> <rayhit> <startHidden>
                      join an object with GameBaseFlags (0/1 each); prints "flags <name> <V> <S> <R>"
                      after each flag message and "removed <name>" on REMOVE
  spinner <name> <Key=value>...
                      join a spinner (SpinnerMotion.Settings fields; Final=x,y,z); its commands print
                      "cmd <name> <property>"
  frame <dt>          the pending-command table, then every spinner's update; prints
                      "spin <name> <state> <vx> <vy> <vz> <pitch> <yaw> <roll>"
  run <command>       run a command string with no sender
  report              print "unhandled <verb> <class> <word> <count>"
"""

import pytest

from conftest import mono_driver


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
        var spinners = new List<(string name, SpinnerMotion motion)>();
        Func<float, string> F = v => ((double)v).ToString("0.######", inv);
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "flags":
                {
                    string name = a[1];
                    int id = mgr.Join(name, "WorldModel");
                    var f = new GameBaseFlags(a[2] == "1", a[3] == "1", a[4] == "1", a[5] == "1");
                    f.Changed += () => Console.WriteLine("flags\t" + name + "\t" + (f.Visible ? 1 : 0) + "\t" + (f.Solid ? 1 : 0) + "\t" + (f.RayHit ? 1 : 0));
                    f.Remove += () => Console.WriteLine("removed\t" + name);
                    mgr.Handle(id, f.OnMessage);
                    break;
                }
                case "spinner":
                {
                    string name = a[1];
                    int id = mgr.Join(name, "SpinningWorldModel");
                    var s = new SpinnerMotion.Settings();
                    foreach (var kv in a.Skip(2))
                    {
                        var p = kv.Split('=');
                        var field = typeof(SpinnerMotion.Settings).GetField(p[0]);
                        if (field.FieldType == typeof(LTVec))
                        {
                            var v = p[1].Split(',').Select(x => float.Parse(x, inv)).ToArray();
                            field.SetValue(s, new LTVec(v[0], v[1], v[2]));
                        }
                        else if (field.FieldType == typeof(bool)) field.SetValue(s, p[1] == "1");
                        else if (field.FieldType == typeof(int)) field.SetValue(s, int.Parse(p[1]));
                        else field.SetValue(s, float.Parse(p[1], inv));
                    }
                    var m = new SpinnerMotion(s, prop => Console.WriteLine("cmd\t" + name + "\t" + prop));
                    mgr.Handle(id, m.OnMessage);
                    spinners.Add((name, m));
                    break;
                }
                case "frame":
                {
                    float dt = float.Parse(a[1], inv);
                    mgr.Update(dt);
                    foreach (var sp in spinners)
                    {
                        var name = sp.name;
                        var m = sp.motion;
                        m.Update(dt);
                        var v = m.Velocity;
                        Console.WriteLine(string.Join("\t", new[] { "spin", name, m.Current.ToString(), F(v.x), F(v.y), F(v.z), F(m.Pitch), F(m.Yaw), F(m.Roll) }));
                    }
                    break;
                }
                case "run":
                    mgr.Run(a[1]);
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
    run_driver = mono_driver(tmp_path_factory, "objectmessages", DRIVER, "Commands.cs", "GameBaseFlags.cs", "SpinnerMotion.cs", "KeyframerMotion.cs")

    def run(*lines):
        out = run_driver("\n".join(lines) + "\n")
        return [row.split("\t") for row in out.splitlines()]
    return run


def flags(rows):
    return [r[1:] for r in rows if r[0] == "flags"]


# ---- GameBase: VISIBLE, SOLID, HIDDEN, REMOVE ----

def test_hidden_clears_visible_solid_and_rayhit_and_hidden_0_restores_what_the_object_had(driver):
    rows = driver("flags\twm\t1\t1\t1\t0", "run\tmsg wm (hidden 1)", "run\tmsg wm (hidden 0)")
    assert flags(rows) == [["wm", "0", "0", "0"], ["wm", "1", "1", "1"]]


def test_hidden_0_restores_the_flags_of_the_first_message_not_more(driver):
    # A non-solid world model (Solid FALSE) shown again by HIDDEN 0 stays non-solid.
    rows = driver("flags\twm\t1\t0\t1\t0", "run\tmsg wm (hidden 1)", "run\tmsg wm (hidden 0)")
    assert flags(rows) == [["wm", "0", "0", "0"], ["wm", "1", "0", "1"]]


def test_start_hidden_is_a_hidden_1_at_creation_so_hidden_0_shows_it(driver):
    # WorldModel::OnObjectCreated sends itself "Hidden 1": the original flags are the props'.
    rows = driver("flags\twm\t1\t1\t1\t1", "run\tmsg wm (hidden 0)")
    assert flags(rows) == [["wm", "1", "1", "1"]]


def test_visible_and_solid_set_one_flag_solid_1_brings_back_rayhit_solid_0_drops_it(driver):
    rows = driver("flags\twm\t1\t1\t1\t0", "run\tmsg wm (visible 0)", "run\tmsg wm (VISIBLE TRUE)",
                  "run\tmsg wm (solid 0)", "run\tmsg wm (solid 1)")
    assert flags(rows) == [["wm", "0", "1", "1"], ["wm", "1", "1", "1"], ["wm", "1", "0", "0"], ["wm", "1", "1", "1"]]


def test_a_flag_message_without_a_0_or_1_changes_nothing_but_is_handled(driver):
    rows = driver("flags\twm\t1\t1\t1\t0", "run\tmsg wm visible", "run\tmsg wm (hidden yes)", "report")
    assert flags(rows) == []
    assert [r for r in rows if r[0] == "unhandled"] == []


def test_remove_takes_the_object_out_and_it_then_ignores_everything(driver):
    rows = driver("flags\twm\t1\t1\t1\t0", "run\tmsg wm remove", "run\tmsg wm (hidden 1)", "run\tmsg wm remove",
                  "report")
    assert rows == [["removed", "wm"]]


def test_other_words_fall_through_to_the_report(driver):
    rows = driver("flags\twm\t1\t1\t1\t0", "run\tmsg wm (attach thing)", "report")
    assert rows == [["unhandled", "MSG", "WorldModel", "ATTACH", "1"]]


# ---- Spinners ----

def spins(rows):
    return [r[2:] for r in rows if r[0] == "spin"]


def test_a_spinner_that_starts_on_spins_up_linearly_over_power_on_time(driver):
    # Final yaw speed 2 rad/s over PowerOnTime 1 s, frames of 0.25 s: v = 0.5, 1, 1.5, 2 (then On).
    rows = driver("spinner\ts\tFinal=0,2,0\tPowerOnTime=1\tStartOn=1", *["frame\t0.25"] * 5)
    s = spins(rows)
    assert [float(r[2]) for r in s] == pytest.approx([0.5, 1, 1.5, 2, 2])
    assert [r[0] for r in s] == ["PowerOn", "PowerOn", "PowerOn", "On", "On"]
    # yaw += v x 0.25 each frame
    assert [float(r[5]) for r in s] == pytest.approx([0.125, 0.375, 0.75, 1.25, 1.75])


def test_a_spinner_that_starts_off_waits_for_on(driver):
    rows = driver("spinner\ts\tFinal=0,2,0\tPowerOnTime=1", "frame\t0.25", "run\tmsg s on", "frame\t0.25",
                  "frame\t0.25")
    s = spins(rows)
    assert [r[0] for r in s] == ["Off", "PowerOn", "PowerOn"]
    assert [float(r[2]) for r in s] == pytest.approx([0, 0.5, 1])


def test_off_spins_down_over_power_off_time_with_trigger_off_then_runs_off_command(driver):
    rows = driver("spinner\ts\tFinal=0,2,0\tPowerOnTime=0.5\tPowerOffTime=1\tStartOn=1\tTriggerOff=1",
                  "frame\t0.25", "frame\t0.25", "run\tmsg s off", *["frame\t0.25"] * 4)
    s = spins(rows)
    assert [float(r[2]) for r in s] == pytest.approx([1, 2, 1.5, 1, 0.5, 0])
    assert [r[0] for r in s] == ["PowerOn", "On", "PowerOff", "PowerOff", "PowerOff", "Off"]
    assert [r[1:] for r in rows if r[0] == "cmd"] == [["s", "PowerOnCommand"], ["s", "OnCommand"],
                                                      ["s", "PowerOffCommand"], ["s", "OffCommand"]]


def test_without_trigger_off_off_leaves_a_spinner_on(driver):
    # HandleTriggerMsg in the On state without TriggerOff only re-arms the on timers (SetOn(TRUE)).
    rows = driver("spinner\ts\tFinal=0,2,0\tPowerOnTime=0.25\tStartOn=1", "frame\t0.25", "run\tmsg s off",
                  "frame\t0.25")
    assert [r[0] for r in spins(rows)] == ["On", "On"]


def test_on_while_spinning_down_turns_back_and_spins_up_from_the_speed_it_had(driver):
    rows = driver("spinner\ts\tFinal=0,2,0\tPowerOnTime=1\tPowerOffTime=1\tTriggerOff=1\tStartOn=1",
                  *["frame\t0.25"] * 4, "run\tmsg s off", "frame\t0.25", "run\tmsg s on", "frame\t0.25")
    s = spins(rows)
    assert [r[0] for r in s[-2:]] == ["PowerOff", "On"]   # 1.5 + 0.5 reaches the final speed at once
    assert [float(r[2]) for r in s[-2:]] == pytest.approx([1.5, 2])


def test_a_locked_spinner_runs_its_locked_command_and_doesnt_move_until_unlocked(driver):
    rows = driver("spinner\ts\tFinal=0,2,0", "run\tmsg s lock", "run\tmsg s on", "frame\t0.25",
                  "run\tmsg s unlock", "run\tmsg s on", "frame\t0.25")
    assert [r[1:] for r in rows if r[0] == "cmd"] == [["s", "LockedCommand"], ["s", "PowerOnCommand"]]
    assert [r[0] for r in spins(rows)] == ["Off", "PowerOn"]


def test_off_wait_time_holds_a_new_power_on_after_a_stop(driver):
    rows = driver("spinner\ts\tFinal=0,2,0\tPowerOnTime=0.25\tPowerOffTime=0.25\tTriggerOff=1\tOffWaitTime=1\tStartOn=1",
                  "frame\t0.25", "run\tmsg s off", "frame\t0.25", "run\tmsg s on", "frame\t0.25",
                  *["frame\t0.25"] * 3, "run\tmsg s on", "frame\t0.25")
    assert [r[0] for r in spins(rows)] == ["On", "Off", "Off", "Off", "Off", "Off", "On"]


def test_pause_freezes_a_spin_up_and_resume_continues_it(driver):
    rows = driver("spinner\ts\tFinal=0,2,0\tPowerOnTime=1\tStartOn=1", "frame\t0.25", "run\tmsg s pause",
                  "frame\t0.25", "run\tmsg s resume", "frame\t0.25")
    s = spins(rows)
    assert [r[0] for r in s] == ["PowerOn", "Pause", "PowerOn"]
    assert float(s[1][5]) == pytest.approx(0.125)   # yaw held while paused


def test_a_negative_speed_spins_up_until_power_on_time_is_over(driver):
    # Retail UpdatePowerOn stops an axis at v >= |final|: a negative one ramps the whole PowerOnTime.
    rows = driver("spinner\ts\tFinal=0,-2,0\tPowerOnTime=0.5\tStartOn=1", *["frame\t0.25"] * 3)
    s = spins(rows)
    assert [float(r[2]) for r in s] == pytest.approx([-1, -2, -2])
    assert [r[0] for r in s] == ["PowerOn", "PowerOn", "On"]
