"""Light groups while the level runs (TronViewer/.../LightGroups.cs, #89), compiled with .NET. Rules: ltjs
lightgroup.cpp (StartOn / StartColor, ON / OFF / TOGGLE / COLOR, UpdateClients after each message),
clientde_impl.cpp SetLightGroupColor (no change within 0.0001 does nothing) and CD3D_RenderBlock's sum.

Driver lines (tab-separated):
  group <name> <r g b>          a group at its DAT colour (0-1)
  object <name> <on> <r g b>    a LightGroup object (StartColor 0-255); prints the changes it makes
  msg <object#> <words...>      a message to the n-th object; prints "handled" or "not", then the changes
  add <value> <color> <int>     LightGroups.Add
Each change prints "changed <name> <r g b>".
"""
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
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    static float F(string s) => float.Parse(s, Inv);
    static string N(float v) => v.ToString("0.###", Inv);
    static void Main()
    {
        var groups = new LightGroups();
        groups.Changed += i => Console.WriteLine($"changed {groups[i].Name} {N(groups[i].Color.x)} {N(groups[i].Color.y)} {N(groups[i].Color.z)}");
        var objects = new List<LightGroupObject>();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "group": groups.Add(a[1], new LTVec(F(a[2]), F(a[3]), F(a[4]))); break;
                case "object": objects.Add(groups.AddObject(a[1], a[2] == "1", new LTVec(F(a[3]), F(a[4]), F(a[5])))); break;
                case "msg":
                    bool h = objects[int.Parse(a[1])].OnMessage(new Message(a.Skip(2).ToArray(), -1));
                    Console.WriteLine(h ? "handled" : "not");
                    break;
                case "add": Console.WriteLine(LightGroups.Add(byte.Parse(a[1]), F(a[2]), byte.Parse(a[3]))); break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "lightgroups", DRIVER, "LightGroups.cs", "Commands.cs", "KeyframerMotion.cs")
    return lambda *lines: drive("\n".join("\t".join(str(x) for x in l) for l in lines) + "\n").split("\n")[:-1]


def test_an_object_sets_its_group_at_its_first_update(run):
    out = run(("group", "lab_lg", 0.828, 0.863, 1), ("group", "tron_lg", 0.9, 0.96, 1),
              ("object", "lab_lg", 1, 255, 255, 255), ("object", "tron_lg", 0, 255, 255, 255))
    # StartColor replaces the DAT colour; one that starts off goes black.
    assert out == ["changed lab_lg 1 1 1", "changed tron_lg 0 0 0"]


def test_on_off_toggle_and_color(run):
    out = run(("group", "rez_lg", 0.46, 0.81, 1), ("object", "REZ_LG", 0, 255, 128, 0),
              ("msg", 0, "on"), ("msg", 0, "ON"), ("msg", 0, "toggle"), ("msg", 0, "TOGGLE"),
              ("msg", 0, "color", 51), ("msg", 0, "color", -1, 255, 0), ("msg", 0, "color", 1, 2),
              ("msg", 0, "hidden", 1))
    assert out == ["changed rez_lg 0 0 0",
                   "changed rez_lg 1 0.502 0", "handled",
                   "handled",                                   # already on: nothing changes
                   "changed rez_lg 0 0 0", "handled",
                   "changed rez_lg 1 0.502 0", "handled",
                   "changed rez_lg 0.2 0.2 0.2", "handled",
                   "changed rez_lg 0.2 1 0", "handled",         # a negative channel keeps its value
                   "handled",                                   # two values: the colour stays
                   "not"]


def test_an_object_without_a_group_changes_nothing(run):
    assert run(("object", "nothing", 1, 255, 255, 255), ("msg", 0, "off")) == ["handled"]


def test_add_truncates_and_clamps(run):
    assert run(("add", 10, 0.5, 3), ("add", 10, 0.46, 255), ("add", 200, 1, 100), ("add", 0, 0, 255)) == \
        ["11", "127", "255", "0"]
