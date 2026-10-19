"""Scene cameras (TronViewer/.../SceneCameras.cs) compiled with .NET, with the level's command manager. Rules:
docs/research/scene-cameras.md (branch research/scene-cameras): ltjs objectdll camera.cpp (OnTrigger, TurnOn,
TurnOff, Update), clientshelldll camerafx.h (the FOV lerp), playermgr.cpp (UpdateAlternativeCamera: the first
live camera wins), interfacemgr.cpp (UpdateLetterBox) and playerobj.cpp (DoActivate: SKIP to every camera
that is on), checked against Tron's cshell.dll there; worked by hand.

Driver lines (tab-separated):
  cam <name> [k=v]...  a Camera at the origin, in level order: type, activeTime, oneTime, startActive, canSkip,
                       skipCleanupOnly, cleanup (its CleanupCommand), fov (x,y)
  point <name> <x y z> a CameraPoint there, turned 90 degrees (yaw)
  key <name>           an object of another class (a Key)
  log <name>           an object that prints "<name> <message>" for each message it gets
  run <command>        a level command, run now
  tick <dt>            a frame: the server clock, then the cameras
  skip                 the skip key (Space) during a scene
  state                "live <name or -> fov <x> <y> view <vertical> box <letterbox alpha> held <0/1>"
  pose <name>          "<x y z> <yaw degrees>" of a camera
The cameras print "removed <name>" when they leave the level.
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
    static string N(float v) => (Math.Abs(v) < 0.0005f ? 0f : v).ToString("0.###", Inv);
    static void Main()
    {
        var cmds = new CommandMgr(() => 0.5);
        var cams = new SceneCameras(() => cmds.Time);
        var points = new Dictionary<string, CameraPose>(StringComparer.OrdinalIgnoreCase);
        var poses = new Dictionary<string, CameraPose>(StringComparer.OrdinalIgnoreCase);
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "cam":
                {
                    var name = a[1];
                    var p = new SceneCamera.Props { ActiveTime = -1, OneTime = true, Type = 1, CanSkip = true, FovX = 90, FovY = 78 };
                    foreach (var kv in a.Skip(2).Select(x => x.Split(new[] { '=' }, 2)))
                        switch (kv[0])
                        {
                            case "type": p.Type = int.Parse(kv[1]); break;
                            case "activeTime": p.ActiveTime = F(kv[1]); break;
                            case "oneTime": p.OneTime = kv[1] == "1"; break;
                            case "startActive": p.StartActive = kv[1] == "1"; break;
                            case "canSkip": p.CanSkip = kv[1] == "1"; break;
                            case "skipCleanupOnly": p.OnSkipCleanupOnly = kv[1] == "1"; break;
                            case "cleanup": p.CleanupCommand = kv[1]; break;
                            case "fov": var f = kv[1].Split(','); p.FovX = F(f[0]); p.FovY = F(f[1]); break;
                        }
                    int id = cmds.Join(name, "Camera");
                    var flags = new GameBaseFlags(true, false, false);
                    cmds.Handle(id, flags.OnMessage);
                    poses[name] = new CameraPose(new LTVec(0, 0, 0), new LTQuat(0, 0, 0, 1));
                    var cam = cams.Add(name, p, flags);
                    cam.RunCommand = c => cmds.Run(c, id, id);
                    cam.RemoveObject = () => { Console.WriteLine("removed " + name); flags.OnMessage(new Message(new[] { "REMOVE" }, -1)); };
                    cam.FindPoint = n => points.TryGetValue(n, out var pose) ? pose : (CameraPose?)null;
                    cam.MoveTo = pose => poses[name] = pose;
                    cmds.Handle(id, cam.OnMessage);
                    cam.Start();
                    break;
                }
                case "point":
                {
                    cmds.Join(a[1], "CameraPoint");
                    var v = a[2].Split(' ').Select(F).ToArray();
                    points[a[1]] = new CameraPose(new LTVec(v[0], v[1], v[2]), LTQuat.FromEuler(0, (float)(Math.PI / 2), 0));
                    break;
                }
                case "key": cmds.Join(a[1], "Key"); break;
                case "log":
                {
                    var name = a[1];
                    int id = cmds.Join(name, "Trigger");
                    cmds.Handle(id, m => { Console.WriteLine(name + " " + m); return true; });
                    break;
                }
                case "run": cmds.Run(a[1]); break;
                case "tick":
                    cmds.BeginFrame(F(a[1]));
                    cams.Update(F(a[1]));
                    break;
                case "skip": cams.Skip(); break;
                case "state":
                {
                    var live = cams.Live;
                    Console.WriteLine($"live {(live == null ? "-" : live.Name)} fov {N(cams.FovX)} {N(cams.FovY)} " +
                                      $"view {N(SceneCameras.ViewFov(cams.FovX))} box {N(cams.LetterboxAlpha)} held {(cams.Held ? 1 : 0)}");
                    break;
                }
                case "pose":
                {
                    var p = poses[a[1]];
                    var f = p.Rot.Forward();
                    Console.WriteLine($"{N(p.Pos.x)} {N(p.Pos.y)} {N(p.Pos.z)} {N((float)(Math.Atan2(f.x, f.z) * 180 / Math.PI))}");
                    break;
                }
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "scenecameras", DRIVER, "SceneCameras.cs", "GameBaseFlags.cs",
                      "KeyframerMotion.cs", "Commands.cs")
    return lambda *lines: drive("\n".join(lines) + "\n").splitlines()


def live(out):
    return [o.split()[1] for o in out if o.startswith("live")]


def test_on_makes_it_live_and_off_gives_the_view_back(run):
    out = run("cam\tcam1\toneTime=0", "tick\t0.1", "state", "run\tmsg cam1 on", "tick\t0.1", "state",
              "run\tmsg cam1 off", "tick\t0.1", "state")
    assert live(out) == ["-", "cam1", "-"]
    assert [o.split()[-1] for o in out] == ["0", "1", "0"]   # the player is held while a camera is live


def test_start_active_is_on_from_the_level_start(run):
    assert live(run("cam\tcam1\tstartActive=1", "tick\t0.1", "state")) == ["cam1"]


def test_the_first_live_camera_in_level_order_wins(run):
    out = run("cam\ta\toneTime=0", "cam\tb\toneTime=0", "run\tmsg b on", "tick\t0.1", "state",
              "run\tmsg a on", "tick\t0.1", "state", "run\tmsg a off", "tick\t0.1", "state")
    assert live(out) == ["b", "a", "b"]


def test_moveto_cuts_to_a_camera_point_and_nothing_else(run):
    out = run("cam\tcam1", "point\tp1\t10 20 30", "key\tk1", "run\tmsg cam1 (moveto p1)", "pose\tcam1",
              "run\tmsg cam1 (moveto k1)", "run\tmsg cam1 (moveto nothing)", "run\tmsg cam1 moveto", "pose\tcam1")
    assert out == ["10 20 30 90", "10 20 30 90"]


def test_fov_snaps_without_a_time(run):
    out = run("cam\tcam1", "run\tmsg cam1 on", "tick\t0.1", "state", "run\tmsg cam1 (fov 70 60)", "tick\t0.1", "state")
    assert [o.split()[3:5] for o in out] == [["90", "78"], ["70", "60"]]


def test_a_timed_fov_lerps_from_the_previous_target(run):
    # fov 70 60; fov 47 40 2: snap, then zoom from 70/60 over 2 s of live frames.
    out = run("cam\tcam1", "run\tmsg cam1 on", "run\tmsg cam1 (fov 70 60)", "run\tmsg cam1 (fov 47 40 2)",
              "tick\t0.5", "state", "tick\t0.5", "state", "tick\t1", "state", "tick\t1", "state")
    assert [o.split()[3:5] for o in out] == [["64.25", "55"], ["58.5", "50"], ["47", "40"], ["47", "40"]]


def test_a_timed_fov_only_runs_while_the_camera_is_live(run):
    # Sent while off: the lerp starts when the camera goes live.
    out = run("cam\tcam1\toneTime=0", "run\tmsg cam1 (fov 50 40 1)", "tick\t5", "run\tmsg cam1 on", "tick\t0.5", "state")
    assert out[0].split()[3:5] == ["70", "59"]


def test_off_restores_the_normal_fov(run):
    out = run("cam\tcam1\toneTime=0\tfov=47,40", "run\tmsg cam1 on", "tick\t0.1", "state", "run\tmsg cam1 off", "tick\t0.1", "state")
    assert [o.split()[3:5] for o in out] == [["47", "40"], ["90", "78"]]


def test_the_view_keeps_the_horizontal_fov_of_a_4_3_screen(run):
    # Decided for the viewer: vertical = the vertical of FovX across 4:3, wider screens see more at the sides
    # (90 across 4:3 is the 73.74 down the viewer's player view already uses).
    out = run("cam\tcam1\toneTime=0\tfov=90,78", "cam\tcam2\toneTime=0\tfov=60,45", "run\tmsg cam1 on", "tick\t0.1", "state",
              "run\tmsg cam1 off", "run\tmsg cam2 on", "tick\t0.1", "state")
    assert [o.split()[6] for o in out] == ["73.74", "46.826"]


def test_type_1_letterboxes_fading_in_half_a_second_and_out_in_one(run):
    out = run("cam\tcam1\toneTime=0", "run\tmsg cam1 on", "tick\t0.25", "state", "tick\t0.25", "state", "tick\t1", "state",
              "run\tmsg cam1 off", "tick\t0.25", "state", "tick\t0.25", "state", "tick\t0.5", "state")
    assert [o.split()[8] for o in out] == ["0", "0.5", "1", "1", "0.75", "0.25"]


def test_types_0_and_2_have_no_letterbox(run):
    for t in ("0", "2"):
        out = run(f"cam\tcam1\ttype={t}", "run\tmsg cam1 on", "tick\t1", "state")
        assert out[0].split()[1] == "cam1" and out[0].split()[8] == "0"


def test_active_time_turns_it_off_and_on_restarts_the_timer(run):
    # Server frames are clamped to 0.2 s.
    out = run("cam\tcam1\toneTime=0\tactiveTime=0.3", "run\tmsg cam1 on", "tick\t0.2", "run\tmsg cam1 on",
              "tick\t0.2", "state", "tick\t0.2", "state")
    assert live(out) == ["cam1", "-"]


def test_turning_off_runs_the_cleanup_first_and_one_time_removes_it(run):
    out = run("log\tend", "cam\tcam1\tcleanup=msg end trigger", "run\tmsg cam1 on", "tick\t0.1", "run\tmsg cam1 off",
              "run\tmsg cam1 on", "tick\t0.1", "state")
    assert out == ["end trigger", "removed cam1", "live - fov 90 78 view 73.74 box 1 held 0"]


def test_off_while_off_still_runs_the_cleanup(run):
    out = run("log\tend", "cam\tcam1\toneTime=0\tcleanup=msg end trigger", "run\tmsg cam1 off")
    assert out == ["end trigger"]


def test_skip_turns_off_every_camera_that_is_on(run):
    out = run("log\tend", "cam\ta\tcleanup=msg end a", "cam\tb\tcleanup=msg end b", "cam\tc\tcleanup=msg end c",
              "run\tmsg a on", "run\tmsg b on", "tick\t0.1", "skip", "tick\t0.1", "state")
    assert out == ["end b", "removed b", "end a", "removed a", "live - fov 90 78 view 73.74 box 1 held 0"]


def test_skip_leaves_on_a_later_camera_an_earlier_cleanup_turned_on(run):
    # The server's object list is newest first, so the skip passes the later cameras before the earlier ones:
    # the intro's cam1, skipped, starts the titles' tcam through its cleanup, and tcam plays.
    out = run("cam	cam1	cleanup=msg tcam on", "cam	tcam", "run	msg cam1 on", "tick	0.1", "skip", "tick	0.1", "state")
    assert out == ["removed cam1", "live tcam fov 90 78 view 73.74 box 0.2 held 1"]


def test_skip_also_skips_an_earlier_camera_a_later_cleanup_turned_on(run):
    # m07-02: cam1 (object 916), skipped, turns on M07-02ANodeCam (584) through its cleanup in the same call;
    # the walk reaches ANodeCam after cam1 and skips it too, so the Alan scene is lost, in the game as well.
    out = run("cam\tanode\tcleanup=msg end anode", "cam\tcam1\tcleanup=msg anode on", "log\tend", "run\tmsg cam1 on",
              "tick\t0.1", "skip", "tick\t0.1", "state")
    assert out == ["removed cam1", "end anode", "removed anode", "live - fov 90 78 view 73.74 box 1 held 0"]


def test_can_skip_0_ignores_the_skip(run):
    out = run("cam\tcam1\tcanSkip=0", "run\tmsg cam1 on", "tick\t0.1", "skip", "tick\t0.1", "state")
    assert live(out) == ["cam1"]


def test_skip_cleanup_only_runs_the_cleanup_and_stays_on(run):
    out = run("log\tend", "cam\tcam1\tskipCleanupOnly=1\tcleanup=msg end trigger", "run\tmsg cam1 on", "tick\t0.1",
              "skip", "tick\t0.1", "state")
    assert out == ["end trigger", "live cam1 fov 90 78 view 73.74 box 0.2 held 1"]


def test_skip_does_nothing_without_a_live_camera(run):
    assert run("cam\tcam1", "skip", "tick\t0.1", "state") == ["live - fov 90 78 view 73.74 box 0 held 0"]


def test_a_removed_camera_takes_no_messages(run):
    out = run("cam\tcam1", "run\tmsg cam1 remove", "run\tmsg cam1 on", "tick\t0.1", "state")
    assert live(out) == ["-"]
