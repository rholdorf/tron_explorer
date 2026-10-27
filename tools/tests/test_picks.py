"""Pick mode's plain cores (TronViewer/.../Picks.cs), compiled with .NET: a Pick as the JSON file seiri reads
(PickRecord), the suggested island of world triangles around a hit (PickIsland) and the box a Pick holds
(PickBox). Expected values are worked by hand. Vocabulary: GLOSSARY.md, Picking (#112).

Driver lines:
  record <kind> <level> <name> <time>        a new record
  id <key> <value>                           a string identity field; idn <key> <number> a number one
  hit <x> <y> <z>                            the hit point; box <minx> <miny> <minz> <maxx> <maxy> <maxz>
  json                                       prints the record's JSON
  file <existing name> ...                   prints its file name, given the names already in the folder
  dir <root> <arg> ...                       prints the Pick folder for that root and command line
  mesh <x y z> ... | <i j k> ...             positions, then triangles (one line each: "v x y z", "t i j k")
  island <seed> <maxExtent>                  prints the island's triangles, its box and whether it leaked
  corners <ax ay az> <bx by bz>              a box from two corners (min thickness 4)
  face <+1|-1>; push <amount>                cycle the selected face; push it out (negative pulls in)
  boxstate                                   prints "<face> min x y z max x y z"
"""
import json
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
    static float F(string s) => float.Parse(s, CultureInfo.InvariantCulture);
    static string G(float f) => f.ToString("0.###", CultureInfo.InvariantCulture);
    static void Main()
    {
        PickRecord r = null;
        PickBox b = null;
        var pos = new List<float>();
        var idx = new List<int>();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split(' ');
            switch (a[0])
            {
                case "record": r = new PickRecord(a[1], a[2], a[3].Replace('_', ' '), DateTime.Parse(a[4], CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal)); break;
                case "id": r.Id(a[1], string.Join(" ", a.Skip(2))); break;
                case "idn": r.Id(a[1], F(a[2])); break;
                case "hit": r.Hit = new LTVec(F(a[1]), F(a[2]), F(a[3])); break;
                case "box": r.Box = new PickBox(new LTVec(F(a[1]), F(a[2]), F(a[3])), new LTVec(F(a[4]), F(a[5]), F(a[6]))); break;
                case "json": Console.WriteLine(r.ToJson()); break;
                case "file": var have = new HashSet<string>(a.Skip(1)); Console.WriteLine(r.FileName(have.Contains)); break;
                case "dir": Console.WriteLine(PickRecord.PicksDir(a.Skip(2).ToArray(), a[1]) ?? "null"); break;
                case "v": pos.Add(F(a[1])); pos.Add(F(a[2])); pos.Add(F(a[3])); break;
                case "t": idx.Add(int.Parse(a[1])); idx.Add(int.Parse(a[2])); idx.Add(int.Parse(a[3])); break;
                case "island":
                    var isl = PickIsland.Grow(pos.ToArray(), idx.ToArray(), int.Parse(a[1]), F(a[2]));
                    Console.WriteLine(string.Join(",", isl.Triangles) + $" min {G(isl.Min.x)} {G(isl.Min.y)} {G(isl.Min.z)} max {G(isl.Max.x)} {G(isl.Max.y)} {G(isl.Max.z)} {(isl.Leaked ? "leaked" : "whole")}");
                    break;
                case "corners": b = PickBox.FromCorners(new LTVec(F(a[1]), F(a[2]), F(a[3])), new LTVec(F(a[4]), F(a[5]), F(a[6])), 4); break;
                case "face": b.NextFace(int.Parse(a[1])); break;
                case "push": b.Push(F(a[1])); break;
                case "boxstate": Console.WriteLine($"{PickBox.FaceNames[b.Face]} min {G(b.Min.x)} {G(b.Min.y)} {G(b.Min.z)} max {G(b.Max.x)} {G(b.Max.y)} {G(b.Max.z)}"); break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def drive(tmp_path_factory):
    return cs_driver(tmp_path_factory, "picks", DRIVER, "Picks.cs", "KeyframerMotion.cs", "Commands.cs")


def test_a_world_model_pick_names_its_level_kind_and_identity(drive):
    out = drive("record worldModel retailsingleplayer/m01-01 Door_A 2026-10-27T12:34:56Z\n"
                "id worldModel Door01\nid class RotatingDoor\nhit 10 -2.5 3000\njson\n")
    assert json.loads(out) == {
        "format": 1,
        "level": "retailsingleplayer/m01-01",
        "kind": "worldModel",
        "name": "Door A",
        "time": "2026-10-27T12:34:56Z",
        "identity": {"worldModel": "Door01", "class": "RotatingDoor"},
        "hit": [10, -2.5, 3000],
    }


def test_a_box_pick_holds_its_box_and_number_fields(drive):
    out = drive('record cut retailsingleplayer/m01-01 lobby 2026-10-27T12:00:00Z\n'
                'idn objectIndex 42\nid note say "hi"\\there\n'
                'box -10 0 20.25 30 128 64\njson\n')
    assert json.loads(out) == {
        "format": 1, "level": "retailsingleplayer/m01-01", "kind": "cut", "name": "lobby",
        "time": "2026-10-27T12:00:00Z",
        "identity": {"objectIndex": 42, "note": 'say "hi"\\there'},
        "box": {"min": [-10, 0, 20.25], "max": [30, 128, 64]},
    }


def test_file_name_is_level_and_name_numbered_past_the_ones_there(drive):
    lines = "record surface retailsingleplayer/m01-01 Wall/Panel:3 2026-10-27T12:00:00Z\n"
    assert drive(lines + "file\n") == "m01-01_wall-panel-3.json\n"
    assert drive(lines + "file m01-01_wall-panel-3.json m01-01_wall-panel-3-2.json\n") == "m01-01_wall-panel-3-3.json\n"


def test_picks_folder_is_seiri_requests_beside_the_repo_unless_given(drive):
    out = drive("dir /src/pg/tron_explorer -level m01-01\n"
                "dir /src/pg/tron_explorer -picks /tmp/my_picks -level m01-01\n"
                "dir /src/pg/tron_explorer -picks\n")
    assert out.splitlines() == [os.path.join("/src/pg", "seiri", "requests"), "/tmp/my_picks",
                                os.path.join("/src/pg", "seiri", "requests")]


# Three quads on y = 0: A (x 0..10) and B (x 10..20) meet along x = 10 through vertices of their own at the
# same positions (as the exporter splits them by UVs and lightmaps); C (x 100..110) touches nothing.
QUADS = "\n".join([
    "v 0 0 0", "v 10 0 0", "v 10 0 10", "v 0 0 10",          # A: 0-3
    "v 10 0 0", "v 20 0 0", "v 20 0 10", "v 10 0 10",        # B: 4-7
    "v 100 0 0", "v 110 0 0", "v 110 0 10", "v 100 0 10",    # C: 8-11
    "t 0 1 2", "t 0 2 3", "t 4 5 6", "t 4 6 7", "t 8 9 10", "t 8 10 11"]) + "\n"


def test_island_grows_through_shared_positions_not_just_shared_vertices(drive):
    assert drive(QUADS + "island 0 50\n") == "0,1,2,3 min 0 0 0 max 20 0 10 whole\n"
    assert drive(QUADS + "island 5 50\n") == "4,5 min 100 0 0 max 110 0 10 whole\n"


def test_island_wider_than_the_limit_has_leaked(drive):
    out = drive(QUADS + "island 0 15\n")
    assert out.endswith(" leaked\n")


def test_box_from_two_corners_in_any_order_is_at_least_min_thick(drive):
    assert drive("corners 10 0 20 0 0 0\nboxstate\n") == "+x min 0 -2 0 max 10 2 20\n"


def test_box_faces_cycle_both_ways(drive):
    out = drive("corners 0 0 0 10 10 10\nface 1\nboxstate\nface -1\nface -1\nboxstate\n")
    assert [l.split()[0] for l in out.splitlines()] == ["-x", "-z"]


def test_pushing_a_face_moves_it_out_and_pulling_stops_at_min_thickness(drive):
    out = drive("corners 0 0 0 10 0 20\nface 1\nface 1\npush 100\nboxstate\n"    # +y up 100
                "face 1\npush 3\nboxstate\n"                                       # -y down 3
                "face -1\npush -500\nboxstate\n")                                  # +y in, to 4 above -y
    assert out.splitlines() == ["+y min 0 -2 0 max 10 102 20",
                                "-y min 0 -5 0 max 10 102 20",
                                "+y min 0 -5 0 max 10 -1 20"]


def test_a_pick_without_a_name_is_named_for_its_kind(drive):
    assert drive("record surface retailsingleplayer/m01-01 _ 2026-10-27T12:00:00Z\nfile\n") == "m01-01_surface.json\n"
