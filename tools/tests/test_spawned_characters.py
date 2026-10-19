"""Spawners and characters in the viewer (TronViewer/.../Characters.cs over Commands.cs), compiled with .NET
and driven line by line. Rules: ltjs spawner.cpp (Spawner::OnTrigger, SpawnObjectTemplate), ai.cpp (CAI's
first update: Initial, the queued messages), serverutilities.cpp (SendMixedTriggerMsgToObject,
ParseTriggerMsg). Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  obj <name> <class>                     join an object that handles every message
  character <name> <Initial>             a placed character (joined, then Characters.Add)
  spawner <name> <InitialCommand>        join a Spawner
  site <spawner> <at> <template Initial> a spawn site of that spawner at object <at> (index = order added)
  run <command>                          run a command string, no sender
  frame                                  the next frame: the characters update
Handlers print "got <receiver id>:<name> <sender name> <words joined by |>"; building a spawned character
prints "built <id>:<name> <site>"; it then handles every message.
"""
import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Collections.Generic;
using Tron;
static class Driver
{
    static void Main()
    {
        var mgr = new CommandMgr(() => 0.0);
        int frame = 0;
        var characters = new Characters(mgr, () => frame);
        var ids = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        Func<int, string> name = id => id < 0 ? "-" : mgr.Name(id);
        Action<int> echo = id => mgr.Handle(id, m =>
        {
            Console.WriteLine("got\t" + id + ":" + mgr.Name(id) + "\t" + name(m.Sender) + "\t" + string.Join("|", m.Words));
            return true;
        });
        var spawners = new Spawners(mgr, characters, (id, site) =>
        {
            Console.WriteLine("built\t" + id + ":" + mgr.Name(id) + "\t" + site);
            echo(id);
        });
        int sites = 0;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "obj":
                    ids[a[1]] = mgr.Join(a[1], a[2]);
                    echo(ids[a[1]]);
                    break;
                case "character":
                    ids[a[1]] = mgr.Join(a[1], "CAIHuman");
                    characters.Add(ids[a[1]], a[2]);
                    echo(ids[a[1]]);
                    break;
                case "spawner":
                    ids[a[1]] = mgr.Join(a[1], "Spawner");
                    spawners.AddSpawner(ids[a[1]], a[2]);
                    break;
                case "site":
                    spawners.AddSite(sites++, ids[a[1]], ids[a[2]], a[3]);
                    break;
                case "run":
                    mgr.Run(a[1]);
                    break;
                case "frame":
                    frame++;
                    characters.Update();
                    Console.WriteLine("frame\t" + frame);
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    run_driver = cs_driver(tmp_path_factory, "characters", DRIVER, "Commands.cs", "Characters.cs")

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        return [tuple(x.split("\t")) for x in run_driver(text).splitlines()]
    return run


def test_spawn_creates_the_named_character_at_the_spawners_site(driver):
    out = driver([("spawner", "S1cinjetSP", ""), ("site", "S1cinjetSP", "S1cinjetSP", ""),
                  ("run", "msg S1cinjetSP (spawn cinjet)")])
    assert out == [("built", "1:cinjet", "0")]


def test_a_spawned_character_takes_messages_by_its_name_once_it_has_updated_twice(driver):
    # CAI::OnTrigger queues every message until its first update ends; its second update (PreUpdate) sends
    # the queue to itself as one mixed message, the AI the sender.
    out = driver([("spawner", "sp", ""), ("site", "sp", "sp", ""),
                  ("run", "msg sp (spawn jet)"), ("run", "msg JET (hidden 1)"),
                  ("frame",), ("frame",), ("run", "msg jet (remove)")])
    assert out == [("built", "1:jet", "0"), ("frame", "1"),
                   ("got", "1:jet", "jet", "hidden|1"), ("frame", "2"),
                   ("got", "1:jet", "-", "remove")]


def test_the_spawners_initial_command_runs_at_once_with_the_spawn_as_active_target(driver):
    # Spawner::OnTrigger: Process(InitialCommand, spawner, spawned); `msg <CAIHuman> (...)` names no object,
    # so it goes to the active target's name. The AI queues it like any message before its first update.
    out = driver([("obj", "counter", "Counter"),
                  ("spawner", "sp", "msg <CAIHuman> (goal_guard node=n1); msg counter (increment 1)"),
                  ("site", "sp", "sp", ""), ("run", "msg sp (spawn guard)"), ("frame",), ("frame",)])
    assert out == [("built", "2:guard", "0"), ("got", "0:counter", "sp", "increment|1"), ("frame", "1"),
                   ("got", "2:guard", "guard", "goal_guard|node=n1"), ("frame", "2")]


def test_initial_runs_on_the_first_update_its_commands_at_once_its_messages_queued(driver):
    # CAI::Update sends Initial to itself (SendMixedTriggerMsgToObject: split on ';' outside parentheses and
    # quotes, a part that is a command runs as one); its messages still meet the first-update queue,
    # after what was queued before.
    out = driver([("obj", "door", "Door"), ("spawner", "sp", "msg <CAIHuman> (talklock 1)"),
                  ("site", "sp", "sp", "goalscript animate anim=Gen_IODefault Loop=true; msg door (on)"),
                  ("run", "msg sp (spawn actor)"), ("frame",), ("frame",), ("frame",)])
    assert out == [("built", "2:actor", "0"),
                   ("got", "0:door", "actor", "on"), ("frame", "1"),
                   ("got", "2:actor", "actor", "talklock|1"),
                   ("got", "2:actor", "actor", "goalscript|animate|anim=Gen_IODefault|Loop=true"), ("frame", "2"),
                   ("frame", "3")]


def test_a_message_between_the_first_and_second_update_is_not_queued(driver):
    out = driver([("spawner", "sp", ""), ("site", "sp", "sp", "hidden 1"),
                  ("run", "msg sp (spawn a)"), ("frame",), ("run", "msg a (visible 1)"), ("frame",)])
    assert out == [("built", "1:a", "0"), ("frame", "1"), ("got", "1:a", "-", "visible|1"),
                   ("got", "1:a", "a", "hidden|1"), ("frame", "2")]


def test_placed_characters_run_initial_and_queue_the_same_way(driver):
    out = driver([("character", "Alan", "goalscript animate anim=Talk loop=1"), ("run", "msg alan (hidden 1)"),
                  ("frame",), ("frame",)])
    assert out == [("frame", "1"), ("got", "0:Alan", "Alan", "hidden|1"),
                   ("got", "0:Alan", "Alan", "goalscript|animate|anim=Talk|loop=1"), ("frame", "2")]


def test_each_spawn_is_a_new_character_and_a_message_reaches_all_of_that_name(driver):
    out = driver([("spawner", "sp", ""), ("site", "sp", "sp", ""),
                  ("run", "msg sp (spawn twin); msg sp (spawn twin)"), ("frame",), ("frame",),
                  ("run", "msg twin (remove)")])
    assert out == [("built", "1:twin", "0"), ("built", "2:twin", "0"), ("frame", "1"), ("frame", "2"),
                   ("got", "1:twin", "-", "remove"), ("got", "2:twin", "-", "remove")]


def test_spawn_without_a_name_makes_a_nameless_character_no_msg_reaches(driver):
    # SpawnObjectTemplate renames the copy to the message's name, "" when there's none.
    out = driver([("spawner", "sp", "msg <CAIHuman> (hidden 1)"), ("site", "sp", "sp", "visible 1"),
                  ("run", "msg sp spawn"), ("frame",), ("frame",)])
    assert out == [("built", "1:", "0"), ("frame", "1"), ("got", "1:", "", "visible|1"), ("frame", "2")]


def test_spawnfrom_uses_the_site_at_the_one_object_with_that_name(driver):
    out = driver([("obj", "here", "TeleportPoint"), ("obj", "twice", "Point"), ("obj", "twice", "Point"),
                  ("spawner", "sp", ""), ("site", "sp", "sp", ""), ("site", "sp", "here", ""),
                  ("run", "msg sp (spawnfrom here a); msg sp (spawnfrom twice b); msg sp (spawnfrom nowhere c)")])
    assert [o for o in out if o[0] == "built"] == [("built", "4:a", "1"), ("built", "5:b", "0"),
                                                    ("built", "6:c", "0")]


def test_spawners_take_their_other_messages_without_creating_anything(driver):
    # Spawner::OnTrigger handles every message itself (no GameBase): `default` with no DefaultSpawn, or a
    # message read as a class to create, makes nothing here.
    out = driver([("spawner", "sp", ""), ("site", "sp", "sp", ""), ("run", "msg sp default; msg sp remove"),
                  ("run", "msg sp (spawn a)")])
    assert out == [("built", "1:a", "0")]
