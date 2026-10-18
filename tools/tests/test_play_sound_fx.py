"""The PlaySound effect (TronViewer/.../PlaySoundFX.cs) compiled with .NET and driven frame by frame through the
effect manager. Rules: ltjs clientfxdll/playsoundfx.cpp (Update, SuspendedUpdate, Term, PlaySound) and
docs/research/clientfx-types.md on research/clientfx-types. Expected values are worked by hand from them.

Driver lines (tab-separated):
  group <name> <phase>                  a group; the keys after it are its keys
  sound <id> <start> <end> [k=v]...     a PlaySound key; offset as a comma list, follow=1 for UpdatePos
                                        Follow, dist=1 for DisableAtDist, file=<name>, any other k a number
  start <group> <loop> <x y z> [yaw]    an instance at an object there (yaw in degrees)
  move <x y z>                          the object moves
  stop                                  every instance shuts down smoothly
  frame <dt> [camera x y z]             the manager's update
The driver prints what the voices do: "play <id> <file> <pos> <loop> <local> <volume> <priority> <inner>
<outer> <pitch>", "move <id> <pos>", "kill <id>". A file named "missing" doesn't play.
"""
import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Globalization;
using System.Linq;
using Tron;
class Obj : IFxObject
{
    public LTVec Pos { get; set; }
    public LTQuat Rot { get; set; }
    public bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot) { pos = default; rot = default; return false; }
}
class Voice : IFxVoice
{
    public int Id;
    public void Move(LTVec p) => Console.WriteLine($"move\t{Id}\t{Driver.V(p)}");
    public void Kill() => Console.WriteLine($"kill\t{Id}");
}
static class Driver
{
    static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
    static float F(string s) => float.Parse(s, Inv);
    static string N(float v) => (Math.Abs(v) < 0.0005f ? 0f : v).ToString("0.###", Inv);
    public static string V(LTVec v) => $"{N(v.x)} {N(v.y)} {N(v.z)}";
    static LTVec Vec(string s) { var p = s.Split(' ', ',').Select(F).ToArray(); return new LTVec(p[0], p[1], p[2]); }
    static LTQuat Yaw(float deg) => LTQuat.FromEuler(0, deg * (float)Math.PI / 180, 0);
    static void Main()
    {
        var mgr = new ClientFXMgr(() => 0.5);
        mgr.Types["PlaySound"] = k => new FxSound((fx, pos) =>
        {
            if (fx.Sound == "missing") return null;
            Console.WriteLine($"play\t{fx.Key.Id}\t{fx.Sound}\t{V(pos)}\t{(fx.Loop ? 1 : 0)}\t{(fx.Local ? 1 : 0)}\t{fx.Volume}\t{fx.Priority}\t{N(fx.Inner)}\t{N(fx.Outer)}\t{N(fx.Pitch)}");
            return new Voice { Id = fx.Key.Id };
        });
        FxGroup g = null;
        Obj o = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "group":
                    g = new FxGroup { Name = a[1], Phase = F(a[2]) };
                    mgr.Add(g);
                    break;
                case "sound":
                {
                    var k = new FxKey { Type = "PlaySound", Id = int.Parse(a[1]), Start = F(a[2]), End = F(a[3]) };
                    k.Continual = k.End - k.Start >= g.Phase - 0.01f;
                    k.Strs["Sound"] = "s.wav";
                    foreach (var kv in a.Skip(4).Select(s => s.Split('=')))
                    {
                        if (kv[0] == "offset") k.Offset = Vec(kv[1]);
                        else if (kv[0] == "follow") k.UpdatePos = FxKey.Follow;
                        else if (kv[0] == "dist") k.DisableAtDist = true;
                        else if (kv[0] == "file") k.Strs["Sound"] = kv[1];
                        else k.Nums[kv[0]] = new[] { F(kv[1]) };
                    }
                    g.Keys = g.Keys.Concat(new[] { k }).ToArray();
                    break;
                }
                case "start":
                    o = new Obj { Pos = Vec(a[3]), Rot = Yaw(a.Length > 4 ? F(a[4]) : 0) };
                    mgr.Start(a[1], a[2] == "1", true, o);
                    break;
                case "move":
                    o.Pos = Vec(a[1]);
                    break;
                case "stop":
                    foreach (var inst in mgr.Instances.ToArray()) mgr.ShutDown(inst);
                    break;
                case "frame":
                    Console.WriteLine("frame");
                    mgr.Update(F(a[1]), a.Length > 2 ? Vec(a[2]) : default);
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "sounds", DRIVER, "ClientFX.cs", "PlaySoundFX.cs", "Commands.cs",
                      "KeyframerMotion.cs")

    def go(*lines):
        # Events per frame: frames[i] is what the voices did during the i-th "frame" (0: at start).
        frames = [[]]
        for r in drive("\n".join(lines) + "\n").splitlines():
            if r == "frame":
                frames.append([])
            else:
                frames[-1].append(r.split("\t"))
        return frames
    return go


def kinds(frames):
    return [[e[0] for e in f if e[0] != "move"] for f in frames]


def test_plays_on_the_first_update_with_the_keys_props(run):
    (start, f1) = run("group\tg\t10",
                      "sound\t1\t0\t10\tLoop=1\tPlayLocal=1\tVolume=75\tPriority=3\tInnerRadius=100\t"
                      "OuterRadius=1500\tPitchShift=0.8",
                      "start\tg\t1\t5 0 0", "frame\t0.1")
    # Start's interval [0, 0] already updates the key once: that is its first update.
    assert start == [["play", "1", "s.wav", "5 0 0", "1", "1", "75", "3", "100", "1500", "0.8"]], start
    assert f1 == [], f1


def test_defaults_volume_100_pitch_1(run):
    (start,) = run("group\tg\t10", "sound\t1\t0\t10", "start\tg\t1\t0 0 0")
    assert start[0][6:] == ["100", "0", "0", "0", "1"], start


def test_starts_where_the_effect_was_created_offset_unrotated(run):
    # Init: m_vPos = create pos + offset (world axes); the sound starts there before the base update.
    (start,) = run("group\tg\t10", "sound\t1\t0\t10\toffset=0,0,10", "start\tg\t1\t5 0 0\t90")
    assert start[0][3] == "5 0 10", start


def test_follow_keeps_it_on_the_parent_without_offset(run):
    frames = run("group\tg\t10", "sound\t1\t0\t10\tfollow=1\toffset=0,0,10", "start\tg\t1\t5 0 0",
                 "move\t7 0 0", "frame\t0.1")
    assert ["move", "1", "7 0 0"] in frames[1], frames


def test_fixed_does_not_move(run):
    frames = run("group\tg\t10", "sound\t1\t0\t10", "start\tg\t1\t5 0 0", "move\t7 0 0", "frame\t0.1")
    assert frames[1] == [], frames


def test_killed_when_its_key_ends_and_played_again_next_phase(run):
    # A 1 s key in a 3 s looping group: killed at its end (t = 1.1) however long the wave, restarted when
    # the clock wraps (t = 3.1).
    frames = run("group\tg\t3", "sound\t1\t0\t1", "start\tg\t1\t0 0 0",
                 "frame\t0.5", "frame\t0.6", "frame\t1", "frame\t1", "frame\t0.5")
    assert kinds(frames) == [["play"], [], ["kill"], [], ["play"], []], frames


def test_continual_key_plays_on_unbroken(run):
    frames = run("group\tg\t2", "sound\t1\t0\t2\tLoop=1", "start\tg\t1\t0 0 0", *["frame\t1"] * 5)
    assert kinds(frames) == [["play"]] + [[]] * 5, frames


def test_one_shot_kills_at_its_end(run):
    frames = run("group\tg\t2", "sound\t1\t0\t2", "start\tg\t0\t0 0 0", "frame\t1", "frame\t1.5")
    assert kinds(frames) == [["play"], [], ["kill"]], frames


def test_shutdown_kills_at_once(run):
    frames = run("group\tg\t10", "sound\t1\t0\t10", "start\tg\t1\t0 0 0", "frame\t0.1", "stop", "frame\t0.1")
    assert kinds(frames) == [["play"], ["kill"], []], frames   # the stop lands in frame 1's output


def test_frozen_instance_kills_it_and_thawing_starts_it_again(run):
    far = "frame\t0.1\t10000 0 0"
    frames = run("group\tg\t10", "sound\t1\t0\t10\tdist=1", "start\tg\t1\t0 0 0", "frame\t0.1", far, far,
                 "frame\t0.1")
    assert kinds(frames) == [["play"], [], ["kill"], [], ["play"]], frames


def test_missing_file_is_not_tried_again(run):
    frames = run("group\tg\t3", "sound\t1\t0\t1\tfile=missing", "start\tg\t1\t0 0 0", *["frame\t1"] * 4)
    assert kinds(frames) == [[]] * 5, frames
