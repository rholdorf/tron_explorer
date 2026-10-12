"""The viewer's keyframer motion (TronViewer/.../KeyframerMotion.cs), compiled with Mono and run frame by
frame against the engine's rules (ltjs keyframer.cpp; docs/research/keyframer-paths.md on branch
research/keyframer-paths). Expected values are worked by hand from those rules.

One update is one server frame; the first only goes active. Scenario lines for the driver:
  kf <looping> <totalPathTime> <wave> <alignToPath> <ignoreOffsets>
  key <time> <x> <y> <z> [<pitch> <yaw> <roll>]
  bez <prev x y z | -> <next x y z | ->      (on the last key)
  cmd <VERB> <delay> <key>                    (on the last key)
  target <x> <y> <z> [<pitch> <yaw> <roll>]
  run <dt> <frames>                           -> one line per frame: x y z qx qy qz qw active activations
"""
import math
import os
import shutil
import subprocess

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")

DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Globalization;
using Tron;
static class Driver
{
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var keys = new List<KeyframerMotion.Key>();
        var cmds = new List<KeyframerMotion.Command>();
        string[] kf = null;
        var targets = new List<float[]>();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split(' ');
            Func<int, float> F = i => float.Parse(a[i], inv);
            switch (a[0])
            {
                case "kf": kf = a; break;
                case "key":
                    if (keys.Count > 0) keys[keys.Count - 1].Commands = cmds.ToArray();
                    cmds.Clear();
                    keys.Add(new KeyframerMotion.Key { Time = F(1), Pos = new LTVec(F(2), F(3), F(4)),
                        PYR = a.Length > 5 ? new LTVec(F(5), F(6), F(7)) : new LTVec() });
                    break;
                case "bez":
                {
                    var k = keys[keys.Count - 1];
                    int i = 1;
                    if (a[i] != "-") { k.HasPrev = true; k.BezPrev = new LTVec(F(i), F(i + 1), F(i + 2)); i += 3; } else i++;
                    if (a[i] != "-") { k.HasNext = true; k.BezNext = new LTVec(F(i), F(i + 1), F(i + 2)); }
                    break;
                }
                case "cmd": cmds.Add(new KeyframerMotion.Command { Verb = a[1], Delay = F(2), Key = (int)F(3) }); break;
                case "target": targets.Add(new[] { F(1), F(2), F(3), a.Length > 4 ? F(4) : 0, a.Length > 4 ? F(5) : 0, a.Length > 4 ? F(6) : 0 }); break;
                case "run":
                {
                    keys[keys.Count - 1].Commands = cmds.ToArray();
                    var m = new KeyframerMotion(keys.ToArray(), kf[1] == "1", float.Parse(kf[2], inv), int.Parse(kf[3]), kf[4] == "1", kf[5] == "1");
                    foreach (var t in targets) m.AddTarget(new LTVec(t[0], t[1], t[2]), LTQuat.FromEuler(t[3], t[4], t[5]));
                    for (int n = 0; n < int.Parse(a[2]); n++)
                    {
                        m.Update(F(1));
                        var t = m.Targets[0];
                        Console.WriteLine(string.Join(" ", new[] { t.Pos.x, t.Pos.y, t.Pos.z, t.Rot.x, t.Rot.y, t.Rot.z, t.Rot.w,
                            m.Active ? 1 : 0, m.Activations }.Select(v => ((double)v).ToString("R", inv))));
                    }
                    break;
                }
            }
        }
    }
}
""".replace("using Tron;", "using System.Linq;\nusing Tron;")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    mcs, mono = shutil.which("mcs"), shutil.which("mono")
    if not mcs or not mono:
        pytest.skip("Mono (mcs, mono) not installed")
    d = tmp_path_factory.mktemp("keyframermotion")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs"),
                        os.path.join(SCRIPTS, "KeyframerMotion.cs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def call(*lines):
        out = subprocess.run([mono, exe], input="\n".join(lines) + "\n", capture_output=True, text=True,
                             check=True).stdout
        return [[float(x) for x in row.split()] for row in out.splitlines()]
    return call


def xs(frames):
    return [f[0] for f in frames]


def test_time_mode_lerps_between_key_times_and_a_loop_jumps_back_to_the_first_key(run):
    # Frame 1 goes active. Frame 6 reaches the last key at t = 1: it wraps to key 0 with no segment to
    # move along, so the object stays put that frame and never shows at 100.
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "run 0.25 8")
    assert xs(f) == pytest.approx([0, 0, 25, 50, 75, 75, 25, 50])
    assert all(row[7] == 1 for row in f)


def test_a_path_that_doesnt_loop_stops_at_the_end(run):
    f = run("kf 0 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "run 0.25 8")
    assert xs(f) == pytest.approx([0, 0, 25, 50, 75, 75, 75, 75])
    assert [row[7] for row in f] == [1, 1, 1, 1, 1, 0, 0, 0]


def test_objects_keep_their_offset_from_the_first_key_unless_ignore_offsets(run):
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 10 5 0", "run 0.25 3")
    assert [row[:3] for row in f] == [[10, 5, 0], [10, 5, 0], [35, 5, 0]]
    f = run("kf 1 0 0 0 1", "key 0 0 0 0", "key 1 100 0 0", "target 10 5 0", "run 0.25 3")
    assert [row[:3] for row in f] == [[10, 5, 0], [0, 0, 0], [25, 0, 0]]


def test_a_first_key_time_is_a_start_delay(run):
    f = run("kf 1 0 0 0 0", "key 0.5 0 0 0", "key 1.5 100 0 0", "target 0 0 0", "run 0.25 5")
    assert xs(f) == pytest.approx([0, 0, 0, 0, 25])


def test_self_pause_then_a_delayed_resume(run):
    # m02-03's cubes, m08-01's platforms: key 0 sends "msg <self> PAUSE; delay .5 (msg <self> RESUME)".
    # The time still advances in the frame that pauses; the delay counts down after the keyframer's update.
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "cmd PAUSE 0 -1", "cmd RESUME 0.5 -1", "key 1 100 0 0",
            "target 0 0 0", "run 0.25 5")
    assert xs(f) == pytest.approx([0, 0, 0, 25, 50])
    assert [row[7] for row in f] == [1, 0, 1, 1, 1]
    assert [row[8] for row in f] == [1, 1, 2, 2, 2]     # the ActiveSound restarts on RESUME


def test_forward_and_backward_from_the_ends_ping_pong(run):
    # m05-02's targets: key 0 "msg <self> forward", last key "msg <self> reverse".
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "cmd FORWARD 0 -1", "key 1 100 0 0", "cmd BACKWARD 0 -1",
            "target 0 0 0", "run 0.25 11")
    assert xs(f) == pytest.approx([0, 0, 25, 50, 75, 100, 75, 50, 25, 0, 25])


def test_goto_jumps_to_a_key_and_carries_on_from_it(run):
    # m08-01's Finders: the last key sends "msg <self> (Goto <base>02)".
    f = run("kf 0 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "key 2 200 0 0", "cmd GOTO 0 1",
            "target 0 0 0", "run 0.5 8")
    assert xs(f) == pytest.approx([0, 0, 50, 100, 150, 100, 150, 100])
    assert all(row[7] == 1 for row in f)


def test_off_stops_the_keyframer(run):
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "cmd OFF 0 -1", "target 0 0 0", "run 0.25 8")
    assert [row[7] for row in f] == [1, 1, 1, 1, 1, 0, 0, 0]
    assert xs(f)[-1] == 75


def test_velocity_mode_moves_at_constant_speed_over_the_whole_path(run):
    # TotalPathTime 2 over 200 units: 100 units/s, 25 per 0.25 s frame, key times ignored. Reaching a key
    # snaps to it; the next frame starts the next segment. After the last key, a wrap frame stays put.
    f = run("kf 1 2 0 0 0", "key 0 0 0 0", "key 0 100 0 0", "key 0 100 100 0", "target 0 0 0", "run 0.25 11")
    assert [row[:2] for row in f] == [[0, 0], [25, 0], [50, 0], [75, 0], [100, 0], [100, 25], [100, 50],
                                      [100, 75], [100, 100], [100, 100], [25, 0]]


def test_sine_wave_speed(run):
    # Sine: speed = pi/2 * v * sin(pi * t / TotalPathTime). v = 200 / 2 = 100; frames of 0.5 s.
    f = run("kf 1 2 1 0 0", "key 0 0 0 0", "key 0 200 0 0", "target 0 0 0", "run 0.5 4")
    step = lambda t: math.pi / 2 * 100 * math.sin(math.pi * t / 2) * 0.5   # noqa: E731
    assert xs(f) == pytest.approx([0, step(0), step(0) + step(0.5), step(0) + step(0.5) + step(1.0)], abs=1e-3)


def test_a_segment_with_both_tangents_is_a_cubic_bezier(run):
    # B(0.5) = (p1 + 3 p2 + 3 p3 + p4) / 8 with p2 = key 0's next control, p3 = key 1's previous control.
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "bez - 0 100 0", "key 1 100 0 0", "bez 100 100 0 -",
            "target 0 0 0", "run 0.5 3")
    assert f[2][:3] == pytest.approx([50, 75, 0])


def test_rotation_slerps_between_the_keys(run):
    # Yaw 0 -> pi/2; halfway is yaw pi/4: (0, sin(pi/8), 0, cos(pi/8)).
    f = run("kf 1 0 0 0 0", "key 0 0 0 0 0 0 0", f"key 1 0 0 0 0 {math.pi / 2} 0", "target 0 0 0 0 0 0",
            "run 0.5 3")
    assert f[2][3:7] == pytest.approx([0, math.sin(math.pi / 8), 0, math.cos(math.pi / 8)], abs=1e-6)


def test_an_object_turned_away_from_the_keys_keeps_its_own_rotation(run):
    # The rotation offset (object - key 0, component-wise) is added back: on a translate-only path the
    # object keeps its rotation (yaw pi/2 here).
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", f"target 0 0 0 0 {math.pi / 2} 0", "run 0.25 3")
    assert f[2][3:7] == pytest.approx([0, math.sin(math.pi / 4), 0, math.cos(math.pi / 4)], abs=1e-6)


def test_align_to_path_faces_the_way_it_moves(run):
    # Moving along +x faces +x: yaw pi/2.
    f = run("kf 1 0 0 1 1", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "run 0.25 4")
    assert f[3][3:7] == pytest.approx([0, math.sin(math.pi / 4), 0, math.cos(math.pi / 4)], abs=1e-6)
