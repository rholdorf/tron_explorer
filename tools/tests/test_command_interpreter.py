"""The viewer's command interpreter (TronViewer/.../Commands.cs), compiled with Mono and driven line by line.
Rules: docs/research/command-language.md (ltjs commandmgr.cpp, serverutilities.cpp, gamebase.cpp,
group.cpp). Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  obj <name> <class>             join an object that handles every message (prints "got")
  deaf <name> <class>            join an object that handles none
  relay <name> <class> <command> join an object that handles every message by running <command> (itself
                                 the sender and active target), like a trigger's commands
  group <name> <member>...       join a Group
  run <sender> <command>         run a command string (sender "" for none); prints "ran True|False"
  runat <sender> <target> <command>  the same with an active target
  tick <seconds>                 one frame of the pending-command table
  rand <value>...                the next values (0-1) the random source returns
  echo <text>                    print <text>
  report                         print the unhandled counts: "unhandled <verb> <class> <word> <count>"
  tokens <base64>                print the statements of a string: "tok <base64>", statements joined by
                                 \\x1e and words by \\x1f
Handlers print "got <receiver> <sender> <message words joined by |>".
"""
import base64
import os
import shutil
import subprocess

import pytest

import commands

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")

DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Tron;
static class Driver
{
    static void Main()
    {
        var randoms = new Queue<double>();
        var mgr = new CommandMgr(() => randoms.Count > 0 ? randoms.Dequeue() : 0.0);
        var ids = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        Func<int, string> name = id => id < 0 ? "-" : mgr.Name(id);
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "obj":
                case "deaf":
                case "relay":
                {
                    int id = mgr.Join(a[1], a[2]);
                    ids[a[1]] = id;
                    if (a[0] == "deaf") break;
                    string cmd = a[0] == "relay" ? a[3] : null;
                    mgr.Handle(id, m =>
                    {
                        Console.WriteLine("got\t" + mgr.Name(id) + "\t" + name(m.Sender) + "\t" + string.Join("|", m.Words));
                        if (cmd != null) mgr.Run(cmd, id, id);
                        return true;
                    });
                    break;
                }
                case "group":
                    ids[a[1]] = mgr.JoinGroup(a[1], a.Skip(2));
                    break;
                case "run":
                    Console.WriteLine("ran\t" + mgr.Run(a[2], a[1] == "" ? -1 : ids[a[1]]));
                    break;
                case "runat":
                    Console.WriteLine("ran\t" + mgr.Run(a[3], a[1] == "" ? -1 : ids[a[1]], ids[a[2]]));
                    break;
                case "tick":
                    mgr.Update(float.Parse(a[1], System.Globalization.CultureInfo.InvariantCulture));
                    break;
                case "rand":
                    foreach (var v in a.Skip(1)) randoms.Enqueue(double.Parse(v, System.Globalization.CultureInfo.InvariantCulture));
                    break;
                case "echo":
                    Console.WriteLine(a[1]);
                    break;
                case "report":
                    foreach (var u in mgr.Unhandled)
                        Console.WriteLine("unhandled\t" + u.Verb + "\t" + u.Class + "\t" + u.Word + "\t" + u.Count);
                    break;
                case "tokens":
                {
                    var text = Encoding.UTF8.GetString(Convert.FromBase64String(a[1]));
                    var s = string.Join("\x1e", ConParse.Statements(text).Select(st => string.Join("\x1f", st)));
                    Console.WriteLine("tok\t" + Convert.ToBase64String(Encoding.UTF8.GetBytes(s)));
                    break;
                }
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
    d = tmp_path_factory.mktemp("commands")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs"),
                        os.path.join(SCRIPTS, "Commands.cs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        out = subprocess.run([mono, exe], input=text, capture_output=True, text=True, check=True).stdout
        return [tuple(x.split("\t")) for x in out.splitlines()]
    return run


def got(out):
    """The deliveries and echoes, in order (not the "ran" results)."""
    return [o for o in out if o[0] != "ran"]


def test_the_viewer_tokenizes_every_level_string_like_the_exporter(driver, corpus):
    texts = sorted({t for _, _, _, t in corpus})
    out = driver([("tokens", base64.b64encode(t.encode()).decode()) for t in texts])
    assert len(out) == len(texts)
    for t, (_, b64) in zip(texts, out):
        s = base64.b64decode(b64).decode()
        assert [w.split("\x1f") if w else [] for w in s.split("\x1e")] == commands.statements(t), t


def test_msg_reaches_every_object_with_that_name_in_any_case_right_away(driver):
    out = driver([("obj", "Door1", "SlidingDoor"), ("obj", "door1", "WorldModel"), ("obj", "lamp", "Prop"),
                  ("run", "", "msg DOOR1 (hidden 1); msg lamp on")])
    assert got(out) == [("got", "Door1", "-", "hidden|1"), ("got", "door1", "-", "hidden|1"),
                        ("got", "lamp", "-", "on")]


def test_the_receiver_splits_a_message_into_statements(driver):
    # Only through an escaped ';': a plain one would end the msg statement itself.
    out = driver([("obj", "a", "WorldModel"), ("run", "", "msg a (hidden 0%;solid 1)")])
    assert got(out) == [("got", "a", "-", "hidden|0"), ("got", "a", "-", "solid|1")]


def test_a_string_whose_first_statement_isnt_a_command_never_runs(driver):
    out = driver([("obj", "a", "WorldModel"), ("run", "", "*msg a on; msg a off")])
    assert out == [("ran", "False")]


def test_a_statement_with_the_wrong_word_count_is_skipped_and_the_rest_runs(driver):
    out = driver([("obj", "a", "WorldModel"), ("run", "", "msg a on; msg a on now; popcornkf off; msg a off")])
    assert got(out) == [("got", "a", "-", "on"), ("got", "a", "-", "off")]


def test_msg_is_synchronous_a_relay_runs_its_commands_before_the_next_statement(driver):
    out = driver([("obj", "a", "WorldModel"), ("obj", "b", "WorldModel"),
                  ("relay", "t", "Trigger", "msg a on"),
                  ("run", "", "msg t trigger; msg b on")])
    assert got(out) == [("got", "t", "-", "trigger"), ("got", "a", "t", "on"), ("got", "b", "-", "on")]


def test_the_sender_is_passed_on(driver):
    out = driver([("obj", "a", "WorldModel"), ("obj", "s", "Trigger"), ("run", "s", "msg a on")])
    assert got(out) == [("got", "a", "s", "on")]


def test_a_class_prefix_on_the_target_is_ignored(driver):
    out = driver([("obj", "a", "WorldModel"), ("run", "", "msg <WorldModel>a on")])
    assert got(out) == [("got", "a", "-", "on")]


def test_an_empty_target_name_is_the_active_target(driver):
    out = driver([("obj", "spawned", "CAIHuman"), ("runat", "", "spawned", "msg <CAIHuman> (hidden 1)")])
    assert got(out) == [("got", "spawned", "-", "hidden|1")]


def test_delay_runs_at_the_first_tick_its_time_is_used_up(driver):
    out = driver([("obj", "a", "WorldModel"), ("run", "", "delay 0.25 (msg a on)"),
                  ("tick", 0.1), ("echo", "1"), ("tick", 0.1), ("echo", "2"), ("tick", 0.1), ("echo", "3"),
                  ("run", "", "delay 0 (msg a off)"), ("echo", "4"), ("tick", 0.1)])
    assert got(out) == [("1",), ("2",), ("got", "a", "-", "on"), ("3",), ("4",), ("got", "a", "-", "off")]


def test_a_delayed_command_keeps_its_sender(driver):
    out = driver([("obj", "a", "WorldModel"), ("obj", "s", "Trigger"), ("run", "s", "delay 0 (msg a on)"),
                  ("tick", 0.1)])
    assert got(out) == [("got", "a", "s", "on")]


def test_frame_time_is_clamped_to_a_fifth_of_a_second(driver):
    out = driver([("obj", "a", "WorldModel"), ("run", "", "delay 0.25 (msg a on)"),
                  ("tick", 1.0), ("echo", "1"), ("tick", 0.1)])
    assert got(out) == [("1",), ("got", "a", "-", "on")]


def test_loopid_repeats_until_aborted_and_a_failed_abort_drops_the_rest(driver):
    out = driver([("obj", "a", "WorldModel"), ("rand", 0, 0),
                  ("run", "", "loopid L1 0.1 0.3 (msg a on)"),
                  ("tick", 0.1), ("tick", 0.1), ("echo", "x"),
                  ("run", "", "abort l1; msg a off"), ("tick", 0.2),
                  ("run", "", "abort l1; msg a off")])
    # Each re-arm draws min + (max - min) * random: random 0 -> 0.1 s.
    assert got(out) == [("got", "a", "-", "on"), ("got", "a", "-", "on"), ("x",), ("got", "a", "-", "off")]
    assert out[-1] == ("ran", "False")


def test_rand_picks_one_command(driver):
    out = driver([("obj", "a", "WorldModel"), ("rand", 0.5, 0.1, 0.9),
                  ("run", "", "rand3 (msg a one) (msg a two) (msg a three)"),
                  ("run", "", "rand 0.5 (msg a yes) (msg a no)"),
                  ("run", "", "rand 0.5 (msg a yes) (msg a no)")])
    assert got(out) == [("got", "a", "-", "two"), ("got", "a", "-", "yes"), ("got", "a", "-", "no")]


def test_a_full_pending_table_runs_the_command_now_and_drops_the_rest(driver):
    lines = [("obj", "a", "WorldModel")] + [("run", "", "delay 10 (msg a later)")] * 100
    out = driver(lines + [("run", "", "delay 10 (msg a now); msg a after")])
    assert got(out) == [("got", "a", "-", "now")]
    assert out[-1] == ("ran", "False")


def test_a_group_passes_each_message_on_to_its_members_as_the_sender(driver):
    out = driver([("obj", "a", "WorldModel"), ("obj", "b", "SoundFX"), ("group", "grp", "a", "b"),
                  ("run", "", "msg grp (moveto k01 (msg x on))")])
    # The group rebuilds the message from its words: the parentheses are lost.
    assert got(out) == [("got", "a", "grp", "moveto|k01|msg|x|on"), ("got", "b", "grp", "moveto|k01|msg|x|on")]


def test_a_command_object_is_reached_only_when_no_regular_object_has_its_name(driver):
    out = driver([("obj", "co", "CommandObject"), ("obj", "co", "Trigger"), ("obj", "co2", "CommandObject"),
                  ("run", "", "msg co on; msg co2 on")])
    assert got(out) == [("got", "co", "-", "on"), ("got", "co2", "-", "on")]
    assert driver([("obj", "co", "CommandObject"), ("run", "", "msg co on")])[0] == ("got", "co", "-", "on")


def test_a_message_that_is_a_command_runs_as_one(driver):
    out = driver([("obj", "a", "WorldModel"), ("obj", "player", "Player"), ("run", "", "msg player (msg a on)")])
    assert got(out) == [("got", "a", "-", "on")]


def test_messages_and_commands_nobody_handles_are_counted_by_verb_class_and_word(driver):
    out = driver([("deaf", "fx", "SpecialFX"), ("deaf", "fx2", "SpecialFX"), ("obj", "a", "WorldModel"),
                  ("run", "", "msg fx on; msg FX2 (ON); msg fx2 off; msg ghost hidden; msg a on"),
                  ("run", "", "int x 0; msg a off"), ("run", "", "msg player (add inner 1)"),
                  ("report",)])
    assert sorted(o[1:] for o in out if o[0] == "unhandled") == sorted([
        ("MSG", "SpecialFX", "ON", "2"), ("MSG", "SpecialFX", "OFF", "1"), ("MSG", "(no object)", "HIDDEN", "1"),
        ("INT", "", "", "1"), ("ADD", "", "", "1")])
