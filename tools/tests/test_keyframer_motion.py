"""The viewer's keyframer motion (TronViewer/.../KeyframerMotion.cs), compiled with Mono with the command
manager (Commands.cs) and run frame by frame against the engine's rules (ltjs keyframer.cpp;
docs/research/keyframer-paths.md on branch research/keyframer-paths; the messages:
docs/research/command-language.md "Per-class messages"). Expected values are worked by hand from those
rules.

One update is one server frame; the first only goes active (StartActive) and pauses (StartPaused). The
keyframer joins the command manager as "kf"; its keys' commands run there with it as sender and active
target. Scenario lines for the driver:
  kf <looping> <totalPathTime> <wave> <alignToPath> <ignoreOffsets>
  start <startActive> <startPaused>          (default: 1 0)
  base <baseKeyName>                         (default: k)
  key <time> <x> <y> <z> [<pitch> <yaw> <roll>]
  bez <prev x y z | -> <next x y z | ->      (on the last key)
  cmd <command text>                         (on the last key)
  target <x> <y> <z> [<pitch> <yaw> <roll>]
  cmd64 <base64>                             (on the last key) a command with any characters
  listen <name>                              an object that prints "got <name> <sender> <words joined by |>"
  reset                                      start a new scenario (a new command manager)
  quiet <dt> <frames>                        run without printing the frames, then "ok <active>"
  send <message text>                        a message to kf, now
  run <dt> <frames>                          -> per frame (the command table, then the keyframer):
                                                x y z qx qy qz qw active activations
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
using System.Linq;
using Tron;
static class Driver
{
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var keys = new List<KeyframerMotion.Key>();
        string[] kf = null;
        string baseKey = "k";
        bool startActive = true, startPaused = false;
        var targets = new List<float[]>();
        var mgr = new CommandMgr(() => 0.0);
        int id = mgr.Join("kf", "KeyFramer");
        KeyframerMotion m = null;
        Func<KeyframerMotion> build = () =>
        {
            if (m != null) return m;
            m = new KeyframerMotion(keys.ToArray(), kf[1] == "1", float.Parse(kf[2], inv), int.Parse(kf[3]), kf[4] == "1", kf[5] == "1")
            {
                BaseKeyName = baseKey, StartActive = startActive, StartPaused = startPaused,
                RunCommand = c => mgr.Run(c, id, id),
            };
            foreach (var t in targets) m.AddTarget(new LTVec(t[0], t[1], t[2]), LTQuat.FromEuler(t[3], t[4], t[5]));
            mgr.Handle(id, m.OnMessage);
            return m;
        };
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split(' ');
            Func<int, float> F = i => float.Parse(a[i], inv);
            string rest = line.IndexOf(' ') >= 0 ? line.Substring(line.IndexOf(' ') + 1) : "";
            switch (a[0])
            {
                case "kf": kf = a; break;
                case "start": startActive = a[1] == "1"; startPaused = a[2] == "1"; break;
                case "base": baseKey = a[1]; break;
                case "key":
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
                case "cmd": keys[keys.Count - 1].Command = rest; break;
                case "cmd64": keys[keys.Count - 1].Command = new string(Convert.FromBase64String(a[1]).Select(b => (char)b).ToArray()); break;
                case "reset":
                    keys = new List<KeyframerMotion.Key>();
                    targets.Clear();
                    baseKey = "k";
                    startActive = true;
                    startPaused = false;
                    mgr = new CommandMgr(() => 0.0);
                    id = mgr.Join("kf", "KeyFramer");
                    m = null;
                    break;
                case "quiet":
                    build();
                    for (int n = 0; n < int.Parse(a[2]); n++)
                    {
                        mgr.Update(F(1));
                        m.Update(F(1));
                    }
                    Console.WriteLine("ok " + (m.Active ? 1 : 0));
                    break;
                case "target": targets.Add(new[] { F(1), F(2), F(3), a.Length > 4 ? F(4) : 0, a.Length > 4 ? F(5) : 0, a.Length > 4 ? F(6) : 0 }); break;
                case "listen":
                {
                    int lid = mgr.Join(a[1], "Listener");
                    string name = a[1];
                    mgr.Handle(lid, msg =>
                    {
                        Console.WriteLine("got " + name + " " + (msg.Sender < 0 ? "-" : mgr.Name(msg.Sender)) + " " + string.Join("|", msg.Words));
                        return true;
                    });
                    break;
                }
                case "send": build(); mgr.Send(-1, "kf", rest); break;
                case "run":
                {
                    build();
                    for (int n = 0; n < int.Parse(a[2]); n++)
                    {
                        mgr.Update(F(1));
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
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    mcs, mono = shutil.which("mcs"), shutil.which("mono")
    if not mcs or not mono:
        pytest.skip("Mono (mcs, mono) not installed")
    d = tmp_path_factory.mktemp("keyframermotion")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs"),
                        os.path.join(SCRIPTS, "KeyframerMotion.cs"), os.path.join(SCRIPTS, "Commands.cs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def call(*lines):
        return subprocess.run([mono, exe], input="\n".join(lines) + "\n", capture_output=True, text=True,
                              check=True).stdout.splitlines()
    return call


@pytest.fixture(scope="module")
def run(driver):
    """The frames only: per frame x y z qx qy qz qw active activations."""
    return lambda *lines: [[float(x) for x in row.split()] for row in driver(*lines) if not row.startswith("got")]


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




# ---- Key commands: run through the command manager, the keyframer as sender and active target ----

def test_self_pause_then_a_delayed_resume(run):
    # m02-03's cubes, m08-01's platforms: key 0 sends "msg <self> PAUSE; delay .5 (msg <self> RESUME)".
    # The time still advances in the frame that pauses; the delay counts down in the command table, which
    # runs before the objects: queued in frame 2, it runs at the start of frame 4. (Frames of 0.125 s: the
    # command table clamps a frame to 0.2 s.)
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "cmd msg kf PAUSE; delay .25 (msg kf RESUME)", "key 1 100 0 0",
            "target 0 0 0", "run 0.125 5")
    assert xs(f) == pytest.approx([0, 0, 0, 12.5, 25])
    assert [row[7] for row in f] == [1, 0, 0, 1, 1]
    assert [row[8] for row in f] == [1, 1, 1, 2, 2]     # the ActiveSound restarts on RESUME


def test_forward_and_backward_from_the_ends_ping_pong(run):
    # m05-02's targets: key 0 "msg <self> forward", last key "msg <self> reverse".
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "cmd msg kf forward", "key 1 100 0 0", "cmd msg kf reverse",
            "target 0 0 0", "run 0.25 11")
    assert xs(f) == pytest.approx([0, 0, 25, 50, 75, 100, 75, 50, 25, 0, 25])


def test_goto_jumps_to_a_key_named_by_base_name_and_index_and_carries_on_from_it(run):
    # m08-01's Finders: the last key sends "msg <self> (Goto <base>02)". KeyFramer::FindKey: the base name
    # in any case, then "0", "01".."09", "10".. by key index.
    f = run("kf 0 0 0 0 0", "base Fkey", "key 0 0 0 0", "key 1 100 0 0", "key 2 200 0 0", "cmd msg kf (goto fKEY01)",
            "target 0 0 0", "run 0.5 8")
    assert xs(f) == pytest.approx([0, 0, 50, 100, 150, 100, 150, 100])
    assert all(row[7] == 1 for row in f)


def test_goto_a_key_that_isnt_there_does_nothing(run):
    f = run("kf 0 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "key 2 200 0 0", "cmd msg kf (goto k1)",
            "target 0 0 0", "run 0.5 6")
    assert xs(f) == pytest.approx([0, 0, 50, 100, 150, 150])


def test_off_stops_the_keyframer(run):
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "cmd msg kf off", "target 0 0 0", "run 0.25 8")
    assert [row[7] for row in f] == [1, 1, 1, 1, 1, 0, 0, 0]
    assert xs(f)[-1] == 75


def test_a_key_command_reaches_other_objects_with_the_keyframer_as_sender(driver):
    rows = driver("kf 1 0 0 0 0", "key 0 0 0 0", "cmd msg door (hidden 0)", "key 1 100 0 0", "target 0 0 0",
                  "listen door", "run 0.25 3")
    assert [r for r in rows if r.startswith("got")] == ["got door kf hidden|0"]


# ---- Messages from other objects ----

def test_a_keyframer_that_starts_inactive_waits_for_on_then_runs_from_the_first_key(run):
    f = run("kf 0 0 0 0 0", "start 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "run 0.25 3",
            "send on", "run 0.25 3")
    assert xs(f) == pytest.approx([0, 0, 0, 0, 25, 50])
    assert [row[7] for row in f] == [0, 0, 0, 1, 1, 1]


def test_on_while_active_does_nothing_and_on_after_off_starts_over(run):
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "run 0.25 3", "send on",
            "run 0.25 1", "send off", "run 0.25 1", "send on", "run 0.25 2")
    assert xs(f) == pytest.approx([0, 0, 25, 50, 50, 0, 25])


def test_a_keyframer_that_starts_paused_goes_on_with_resume_from_where_it_is(run):
    # KeyFramer::Update's first pass: GoActive (StartActive or StartPaused), then Pause.
    f = run("kf 0 0 0 0 0", "start 1 1", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "run 0.25 2",
            "send resume", "run 0.25 3")
    assert xs(f) == pytest.approx([0, 0, 0, 25, 50])
    assert [row[7] for row in f] == [0, 0, 1, 1, 1]


def test_on_before_the_first_update_only_makes_it_start_active(run):
    f = run("kf 0 0 0 0 0", "start 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "send on",
            "run 0.25 3")
    assert xs(f) == pytest.approx([0, 0, 25])
    assert [row[7] for row in f] == [1, 1, 1]


def test_pause_before_the_first_update_is_deferred_to_it(run):
    # Received before the first update, PAUSE waits for it (DeferCommand), after StartActive's GoActive.
    f = run("kf 0 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "send pause", "run 0.25 2",
            "send resume", "run 0.25 2")
    assert [row[7] for row in f] == [0, 0, 1, 1]
    assert xs(f) == pytest.approx([0, 0, 0, 25])


def test_moveto_travels_to_the_key_then_pauses_and_runs_its_command(driver, run):
    lines = ("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "key 2 200 0 0", "key 3 300 0 0", "target 0 0 0",
             "listen lift", "run 0.5 2", "send moveto k02 (msg lift arrived)", "run 0.5 5")
    f = run(*lines)
    assert xs(f) == pytest.approx([0, 0, 50, 100, 150, 150, 150])
    assert [row[7] for row in f] == [1, 1, 1, 1, 1, 0, 0]
    assert [r for r in driver(*lines) if r.startswith("got")] == ["got lift kf arrived"]


def test_moveto_a_key_behind_turns_back(run):
    # From between keys 1 and 2 going forward (time 1.5), key 0 lies behind: ToggleDir, travel back from
    # where the time is, and pause on reaching key 0, in the frame that processes it, before moving there.
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "key 2 200 0 0", "target 0 0 0", "run 0.5 4",
            "send moveto k0", "run 0.5 6")
    assert xs(f) == pytest.approx([0, 0, 50, 100, 150, 100, 50, 50, 50, 50])
    assert [row[7] for row in f][-1] == 0


def test_toggledir_turns_around_in_the_middle_of_a_segment(run):
    f = run("kf 1 0 0 0 0", "key 0 0 0 0", "key 1 100 0 0", "target 0 0 0", "run 0.25 3", "send toggledir",
            "run 0.25 2")
    assert xs(f) == pytest.approx([0, 0, 25, 50, 25])   # the time had reached 0.5 when it turned


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


def test_every_keyframer_in_the_levels_runs_its_path_and_key_commands(driver, world):
    # Every keyframer of the 38 single-player levels, started (ON for the ones that start inactive) and run
    # for 20 s of 0.05 s frames, its key commands going through the command manager: none throws.
    import base64
    import glob
    import keyframer
    from conftest import EXTRACTED
    root = os.path.join(EXTRACTED, "worlds")
    lines, n = [], 0
    for path in sorted(glob.glob(os.path.join(root, "retailsingleplayer", "*.dat"))):
        w = world(os.path.relpath(path, root)[:-4])
        for kf in keyframer.keyframers(w.objects, w.blind):
            n += 1
            lines += ["reset", "kf %d %r 0 %d %d" % (kf["looping"], kf["totalPathTime"], kf["alignToPath"],
                                                      kf["ignoreOffsets"]),
                      "start %d %d" % (kf["startActive"], kf["startPaused"]), "base " + kf["baseKeyName"]]
            for k in kf["keys"]:
                lines.append("key %r %r %r %r %r %r %r" % (k["time"], *k["pos"], *k["pyr"]))
                if k.get("bezPrev") or k.get("bezNext"):
                    lines.append("bez " + " ".join("%r %r %r" % tuple(c) if c else "-"
                                                   for c in (k.get("bezPrev"), k.get("bezNext"))))
                if k.get("command"):
                    lines.append("cmd64 " + base64.b64encode(k["command"].encode("latin-1")).decode())
            lines.append("target %r %r %r" % tuple(kf["keys"][0]["pos"]))
            if not kf["startActive"]:
                lines.append("send on")
            lines.append("quiet 0.05 400")
    rows = driver(*lines)
    assert len([r for r in rows if r.startswith("ok")]) == n == 2135
