"""remaster: the remaster-mode switch (TronViewer/.../Remaster.cs) compiled with .NET: -remaster [ids], F2's toggle,
and the techniques' hooks (#96, #103).

Driver lines: "args <arg> ..." builds the switch from a command line; "register <id>" adds a hook that prints
"<id> <on 0/1>" when called; "toggle"; "apply"; "state" prints "<on 0/1> <set, comma-separated> | <unknown>".
"""
import pytest

from conftest import cs_driver

DRIVER = r"""
using System;
using System.Linq;
using Tron;
static class Driver
{
    static void Main()
    {
        Remaster r = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split(' ');
            switch (a[0])
            {
                case "args": r = Remaster.FromArgs(a.Skip(1).ToList()); break;
                case "register": var id = a[1]; r.Register(id, on => Console.WriteLine($"{id} {(on ? 1 : 0)}")); break;
                case "toggle": r.Toggle(); break;
                case "apply": r.Apply(); break;
                case "state":
                    Console.WriteLine($"{(r.On ? 1 : 0)} {string.Join(",", Remaster.Ids.Where(r.Set.Contains))} | {string.Join(",", r.Unknown)}");
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    return cs_driver(tmp_path_factory, "remaster", DRIVER, "Remaster.cs")


def test_faithful_without_the_flag(drive):
    assert drive("args -level m01-01\nstate\n") == "0 hd,aniso,aa,glow,ssao | \n"


def test_flag_alone_is_every_technique(drive):
    assert drive("args -remaster\nstate\nargs -remaster -level m01-01\nstate\n") == \
        "1 hd,aniso,aa,glow,ssao | \n1 hd,aniso,aa,glow,ssao | \n"


def test_list_is_the_set_unknown_ids_reported(drive):
    assert drive("args -level x -remaster AA,ssao,,bloom\nstate\n") == "1 aa,ssao | bloom\n"


def test_hooks_follow_the_toggle_and_stay_off_outside_the_set(drive):
    out = drive("args -remaster aa\nregister aa\nregister glow\ntoggle\ntoggle\napply\n")
    assert out == "aa 1\nglow 0\naa 0\nglow 0\naa 1\nglow 0\naa 1\nglow 0\n"


def test_apply_runs_in_technique_order(drive):
    out = drive("args -remaster\nregister ssao\nregister aniso\nregister hd\napply\n")
    assert out.splitlines()[3:] == ["hd 1", "aniso 1", "ssao 1"]
