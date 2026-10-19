"""A character's animation keys (TronViewer/.../AnimTrack.cs), compiled with .NET: a key fires when the
clip's time crosses it, the rule StateModel plays props' clips by too: the keys at times in (before, after]
each advance, the ones at 0 when the clip starts; a loop fires the rest of its lap, then from the top; none
while the clip blends in (its time held at 0), its keys at 0 once the blend is over. The engine's tracker fires
a character's keys as it passes them (CCharacter::HandleModelString, MID_MODELSTRINGKEY). Expected values are
worked by hand.

Scenario lines:
  clip <interp s> <key times s, comma> <animation key times s, comma>
  play <clip> <loop 0/1> / restart <loop 0/1>    -> "fired <clip>:<key>..." when any fired
  run <dt> <frames>                              -> per frame: "<time> fired ..." (fired empty when none)
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
    static string Fired(AnimTrack t)
    {
        var s = string.Join(" ", t.Fired.Select(f => f.clip + ":" + f.key));
        t.Fired.Clear();
        return s;
    }

    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var clips = new List<AnimTrack.ClipInfo>();
        AnimTrack t = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split(' ');
            float[] F(string s) => s == "-" ? new float[0] : s.Split(',').Select(x => float.Parse(x, inv)).ToArray();
            switch (a[0])
            {
                case "clip":
                    clips.Add(new AnimTrack.ClipInfo { Interp = float.Parse(a[1], inv), Times = F(a[2]), Keys = F(a[3]) });
                    break;
                case "play":
                    if (t == null) t = new AnimTrack(clips);
                    t.Play(int.Parse(a[1]), a[2] == "1");
                    if (t.Fired.Count > 0) Console.WriteLine("fired " + Fired(t));
                    break;
                case "restart":
                    t.Restart(a[1] == "1");
                    if (t.Fired.Count > 0) Console.WriteLine("fired " + Fired(t));
                    break;
                case "run":
                    for (int i = 0; i < int.Parse(a[2]); i++)
                    {
                        t.Advance(float.Parse(a[1], inv));
                        Console.WriteLine(string.Format(inv, "{0:0.00} fired {1}", t.Time, Fired(t)).TrimEnd());
                    }
                    break;
            }
        }
    }
}
"""

CLIPS = ["clip 0 0,1,2 0,0.5,2",    # 0: a cut; animation keys at 0, 0.5 and 2 s (its last key)
         "clip 0.25 0,1 0,0.75",    # 1: blends in over 250 ms; keys at 0 and 0.75 s
         "clip 0 0,1 -"]            # 2: no keys


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "animkeys", DRIVER, "AnimTrack.cs")
    return lambda *lines: drive("\n".join(CLIPS + list(lines)) + "\n").split("\n")[:-1]


def test_keys_fire_once_as_the_time_crosses_them_the_one_at_0_on_start(run):
    assert run("play 0 0", "run 0.25 10") == [
        "fired 0:0", "0.25 fired", "0.50 fired 0:1", "0.75 fired", "1.00 fired", "1.25 fired", "1.50 fired",
        "1.75 fired", "2.00 fired 0:2", "2.00 fired", "2.00 fired"]


def test_a_loop_fires_the_rest_of_its_lap_then_from_the_top(run):
    assert run("play 0 1", "run 0.5 5", "run 0.75 4") == [
        "fired 0:0", "0.50 fired 0:1", "1.00 fired", "1.50 fired", "2.00 fired 0:2", "0.50 fired 0:0 0:1",
        "1.25 fired", "2.00 fired 0:2", "0.75 fired 0:0 0:1", "1.50 fired"]


def test_a_frame_that_jumps_a_whole_lap_fires_the_rest_and_the_top_once(run):
    assert run("play 0 1", "run 0.25 1", "run 2.5 1") == ["fired 0:0", "0.25 fired", "0.75 fired 0:1 0:2 0:0 0:1"]


def test_none_fire_while_the_clip_blends_in_its_keys_at_0_when_it_starts(run):
    # The switch from clip 0 blends into clip 1 over 0.25 s; the time past the blend plays the clip.
    assert run("play 0 1", "run 0.25 1", "play 1 0", "run 0.1 2", "run 0.5 2") == [
        "fired 0:0", "0.25 fired", "0.00 fired", "0.00 fired", "0.45 fired 1:0", "0.95 fired 1:1"]


def test_restart_fires_the_keys_at_0_again(run):
    assert run("play 0 0", "run 1 1", "restart 0", "run 1 1") == [
        "fired 0:0", "1.00 fired 0:1", "fired 0:0", "1.00 fired 0:1"]


def test_a_clip_without_keys_fires_nothing(run):
    assert run("play 2 1", "run 0.6 3") == ["0.60 fired", "0.20 fired", "0.80 fired"]
