"""Head tracking (TronViewer/.../TrackedNodes.cs), compiled with .NET: ltjs game/shared trackednodecontrolfn.cpp
(FindLookDirectionLS, FindConstrainedVector, ConstrainToMaxAngularVel, SetupFinalTransform, SyncOrientation),
trackednodemgr.cpp (SetNodeConstraints) and trackednodecontext.cpp (the LookAt group going off looks back along
the animation and turns itself off once it looks there). Expected values are worked by hand.

Driver lines (tab-separated):
  node <axis x,y,z|-> <up x,y,z|-> <maxX deg> <maxY deg> <maxVel deg/s>   the node (its discomfort 0)
  on / off                                   the LookAt group on (the target is a point) / off
  update <target x,y,z> <dt>                 parent, bind and animated frames the identity at the origin;
                                             prints "frame <F as yaw pitch degrees> <U x y z> <enabled>"
"""
import math

import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Globalization;
using Tron;

static class Program
{
    static float F(string s) => float.Parse(s, CultureInfo.InvariantCulture);
    static LTVec? V(string s)
    {
        if (s == "-") return null;
        var a = s.Split(',');
        return new LTVec(F(a[0]), F(a[1]), F(a[2]));
    }
    static string N(double v) => Math.Round(v, 2).ToString("0.##", CultureInfo.InvariantCulture);

    static void Main()
    {
        TrackedNode node = null;
        var group = new LookAtGroup();
        float deg = (float)Math.PI / 180;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "node":
                    node = new TrackedNode("Head", V(a[1]), V(a[2]), 0, 0, F(a[3]) * deg, F(a[4]) * deg, F(a[5]) * deg);
                    group.Nodes.Add(node);
                    break;
                case "on": group.SetActive(true); break;
                case "off": group.SetActive(false); break;
                case "update":
                {
                    var frame = LTFrame.Identity;
                    node.Update(LTFrame.Identity, LTFrame.Identity, ref frame, V(a[1]).Value, F(a[2]));
                    var f = frame.F;
                    double yaw = Math.Atan2(f.x, f.z) * 180 / Math.PI, pitch = Math.Asin(Math.Max(-1, Math.Min(1, f.y))) * 180 / Math.PI;
                    Console.WriteLine("frame\t" + N(yaw) + "\t" + N(pitch) + "\t" + N(frame.U.x) + "\t" + N(frame.U.y) + "\t" + N(frame.U.z) + "\t" + (node.Enabled ? 1 : 0));
                    break;
                }
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    run_driver = cs_driver(tmp_path_factory, "tracked", DRIVER, "Commands.cs", "KeyframerMotion.cs", "TrackedNodes.cs")

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        return [tuple(x.split("\t")) for x in run_driver(text).splitlines()]
    return run


def at(yaw, pitch=0, d=100):
    y, p = math.radians(yaw), math.radians(pitch)
    return f"{d * math.sin(y) * math.cos(p):.5f},{d * math.sin(p):.5f},{d * math.cos(y) * math.cos(p):.5f}"


Z_NODE = ("node", "0,0,1", "0,1,0", 55, 45, 180)


def test_it_turns_to_the_target_within_its_reach(driver):
    out = driver([Z_NODE, ("on",), ("update", at(30), 1)])
    assert out == [("frame", "30", "0", "0", "1", "0", "1")]


def test_no_further_than_its_largest_angle(driver):
    out = driver([Z_NODE, ("on",), ("update", at(90), 1), ("update", at(0, 80), 1)])
    assert out == [("frame", "55", "0", "0", "1", "0", "1"), ("frame", "0", "45", "0", "0.71", "-0.71", "1")]


def test_no_faster_than_its_largest_speed(driver):
    out = driver([Z_NODE, ("on",), ("update", at(40), 0.1), ("update", at(40), 0.1), ("update", at(40), 0.1)])
    assert [o[1] for o in out] == ["18", "36", "40"]


def test_a_target_behind_looks_at_its_mirror_in_front(driver):
    out = driver([Z_NODE, ("on",), ("update", at(160), 1)])
    assert out[0][1:3] == ("20", "0")


def test_off_it_turns_back_to_the_animation_then_lets_go(driver):
    # The LookAt group going off: the node looks along the animation at its own speed, and turns itself off on
    # the update it first looks there (its auto-disable is only checked once, on the first update after).
    out = driver([Z_NODE, ("on",), ("update", at(30), 1), ("off",), ("update", at(30), 0.1)])
    assert out == [("frame", "30", "0", "0", "1", "0", "1"), ("frame", "12", "0", "0", "1", "0", "1")]
    out = driver([Z_NODE, ("on",), ("update", at(30), 1), ("off",), ("update", at(30), 1), ("update", at(30), 1)])
    assert out[1:] == [("frame", "0", "0", "0", "1", "0", "0"), ("frame", "0", "0", "0", "1", "0", "0")]


def test_a_node_whose_cone_axis_is_its_y_keeps_its_bind_pose_looking_along_it(driver):
    # SetNodeConstraints' defaults: axis +y, up -x (the head of Skeleton0's TrackingNodes0).
    out = driver([("node", "-", "-", 55, 45, 180), ("on",), ("update", "0,100,0", 1)])
    assert out == [("frame", "0", "0", "0", "1", "0", "1")]
    # 30 degrees from +y toward +z: its y axis follows.
    out = driver([("node", "-", "-", 55, 45, 180), ("on",), ("update", "0,86.6025,50", 1)])
    assert out[0][3:6] == ("0", "0.87", "0.5")
