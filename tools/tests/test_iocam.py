"""iocam: Tron's IO-node inset view (TronViewer/.../IOCam.cs) compiled with .NET, with the level's command
manager. Rules: docs/research/screen-shake-iocam.md (branch research/screen-shake-iocam): Tron's object.lto
CPlayerObj IOCAM handler, cshell.dll message 0xb4, the IO camera's rectangle and FOV (0x100a7200), its render
(0x100a74f0) and CHUDIOCamera (layout.txt [IONodeCam]); worked by hand.

Driver lines (tab-separated):
  obj <name> <class> [x y z] [pitch yaw roll]   a level object there (LT units, radians)
  remove <name>                  the first object of that name leaves the level
  run <command>                  a level command, run now
  cam                            "cam <on 0/1> <inset 0/1> <x y z> <qx qy qz qw> <target name or ->"
  fov <w> <h>                    "fov <fovX> <fovY>" in degrees, for a w x h pixel rectangle
  rect <w> <h>                   "rect <x> <y> <w> <h>": the inset on a w x h screen, top-left origin, pixels
  frame <dt>                     the HUD frame's update: "frame <visible 0/1> <piece 1 alpha> <static radius or ->"
  quads                          "q <x> <y> <w> <h> <u0> <v0> <u1> <v1>" per quad of piece 1 (640x480 units)
  rand <a,b,...>                 the HUD frame's random numbers in [0, 1), in turn (default 0.5)
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
        int player = cmds.Join("Player", "Player");
        var poses = new Dictionary<int, CameraPose>();
        var removed = new HashSet<int>();
        double[] rands = { 0.5 };
        int ri = 0;
        var cam = new IOCam(IOCamLayout.Default, () => rands[ri++ % rands.Length]);
        Func<string, int> find = name => cmds.Named(name).Where(i => !removed.Contains(i)).DefaultIfEmpty(-1).First();
        cam.Handle(cmds, player, name => { int i = find(name); return i >= 0 && poses.TryGetValue(i, out var p) ? p : (CameraPose?)null; },
                   find, id => !removed.Contains(id));
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "obj":
                {
                    int id = cmds.Join(a[1], a[2]);
                    var p = a.Length > 3 ? a[3].Split(' ').Select(F).ToArray() : new float[3];
                    var r = a.Length > 4 ? a[4].Split(' ').Select(F).ToArray() : new float[3];
                    poses[id] = new CameraPose(new LTVec(p[0], p[1], p[2]), LTQuat.FromEuler(r[0], r[1], r[2]));
                    break;
                }
                case "remove": removed.Add(find(a[1])); break;
                case "run": cmds.Run(a[1]); break;
                case "cam":
                {
                    var p = cam.Pose;
                    Console.WriteLine($"cam {(cam.On ? 1 : 0)} {(cam.ShowsInset ? 1 : 0)} {N(p.Pos.x)} {N(p.Pos.y)} {N(p.Pos.z)} " +
                                      $"{N(p.Rot.x)} {N(p.Rot.y)} {N(p.Rot.z)} {N(p.Rot.w)} {(cam.Target >= 0 ? cmds.Name(cam.Target) : "-")}");
                    break;
                }
                case "fov":
                {
                    var (fx, fy) = IOCam.Fov(cam.Layout, F(a[1]), F(a[2]));
                    Console.WriteLine($"fov {N(fx)} {N(fy)}");
                    break;
                }
                case "rect":
                {
                    var r = IOCam.ScreenRect(cam.Layout, F(a[1]), F(a[2]));
                    Console.WriteLine($"rect {N(r[0])} {N(r[1])} {N(r[2])} {N(r[3])}");
                    break;
                }
                case "frame":
                {
                    cam.Frame.Update(F(a[1]), cam.On);
                    var f = cam.Frame;
                    Console.WriteLine($"frame {(f.Visible ? 1 : 0)} {N(f.Alpha)} {(f.StaticShown ? N(f.StaticRadius) : "-")}");
                    break;
                }
                case "quads":
                    foreach (var q in IONodeFrame.Quads(cam.Layout.Center[0], cam.Layout.Center[1], cam.Layout.Piece1Radius))
                        Console.WriteLine("q " + string.Join(" ", q.Select(N)));
                    break;
                case "rand": rands = a[1].Split(',').Select(s => double.Parse(s, Inv)).ToArray(); ri = 0; break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "iocam", DRIVER, "IOCam.cs", "SceneCameras.cs", "GameBaseFlags.cs",
                      "KeyframerMotion.cs", "Commands.cs")
    return lambda *lines: drive("\n".join(lines) + "\n").splitlines()


STUDIO = ["obj\tIONodeActors00.ma3aCamPt\tBaseClass\t10 20 -32\t0 3.14159265 0", "obj\tma3aActor\tCAIHuman\t10 0 0"]


def test_on_places_the_camera_at_the_location_and_shows_the_inset_while_the_target_is_there(run):
    out = run(*STUDIO, "cam", "run\tmsg player (iocam on ionodeactors00.ma3acampt ma3aactor)", "cam",
              "remove\tma3aActor", "cam")
    assert out == ["cam 0 0 0 0 0 0 0 0 0 -",
                   "cam 1 1 10 20 -32 0 1 0 0 ma3aActor",
                   "cam 1 0 10 20 -32 0 1 0 0 ma3aActor"]


def test_a_location_that_names_nothing_ignores_the_message(run):
    out = run(*STUDIO, "run\tmsg player (iocam on ionodeactors00.ma3acampt ma3aactor)",
              "run\tmsg player (iocam on nowhere ma3aactor)", "cam")
    assert out == ["cam 1 1 10 20 -32 0 1 0 0 ma3aActor"]


def test_no_target_or_an_unknown_one_turns_it_on_without_the_inset(run):
    for msg in ("iocam on ionodeactors00.ma3acampt", "iocam on ionodeactors00.ma3acampt nobody"):
        out = run(*STUDIO, f"run\tmsg player ({msg})", "cam")
        assert out == ["cam 1 0 10 20 -32 0 1 0 0 -"]


def test_fewer_than_two_arguments_turn_it_off_whatever_the_word(run):
    for msg in ("iocam off", "iocam on", "iocam"):
        out = run(*STUDIO, "run\tmsg player (iocam on ionodeactors00.ma3acampt ma3aactor)", f"run\tmsg player ({msg})",
                  "cam")
        assert out == ["cam 0 0 10 20 -32 0 1 0 0 -"]


def test_the_word_after_iocam_is_never_read(run):
    out = run(*STUDIO, "run\tmsg player (iocam off ionodeactors00.ma3acampt ma3aactor)", "cam")
    assert out == ["cam 1 1 10 20 -32 0 1 0 0 ma3aActor"]


def test_the_fov_is_linear_in_the_rectangles_aspect(run):
    # The 137 x 173 rectangle (640x480 units): 70 x 137/173 x 0.75.
    assert run("fov\t137\t173") == ["fov 41.575 60"]


def test_the_rectangle_scales_from_640x480_per_axis(run):
    assert run("rect\t640\t480", "rect\t1920\t1080") == ["rect 252 105 137 173", "rect 756 236.25 411 389.25"]


def test_the_frame_shows_while_on_its_alpha_a_sine_from_the_middle(run):
    # Shown at t 0: alpha (0.27 + 0.36) / 2; a quarter period later the top, 0.36. The static waits 0.13 s
    # (random 0.5 of 0.01..0.25), then flickers at radius 256 (0.5 of 248..264).
    out = run(*STUDIO, "frame\t0.1", "run\tmsg player (iocam on ionodeactors00.ma3acampt)", "frame\t0.1", "frame\t0.1",
              "frame\t0.65", "run\tmsg player (iocam off)", "frame\t0.1")
    assert out == ["frame 0 0 -", "frame 1 0.315 -", "frame 1 0.324 -", "frame 1 0.36 256", "frame 0 0.36 -"]


def test_the_static_flickers_its_count_then_waits_again(run):
    # Random 0: waits 0.01, then 12 flickers of 0.04 s, then waits 0.01 again.
    out = run("rand\t0", *STUDIO, "run\tmsg player (iocam on ionodeactors00.ma3acampt)", "frame\t0",
              *["frame\t0.04"] * 14)
    shown = [o.split()[3] != "-" for o in out[1:]]
    assert shown == [True] * 12 + [False, True]


def test_the_frame_is_four_quads_mirrored_about_the_center(run):
    assert run("quads") == ["q 64 101 256 256 0 0 1 1", "q 320 101 256 256 1 0 0 1",
                            "q 64 357 256 256 0 1 1 0", "q 320 357 256 256 1 1 0 0"]
