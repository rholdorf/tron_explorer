"""A character's animation track (TronViewer/.../AnimTrack.cs), compiled with .NET and run against the engine's
tracker rules (ltjs engine/runtime/model/src/animtracker.cpp: trk_SetCurAnim, trk_ScanToKeyFrame,
trk_IsStopped; docs/research/cutscene-actors.md on branch research/cutscene-actors). Expected values are
worked by hand from those rules.

Scenario lines for the driver:
  clip <interp s> <key time s>...     a clip (index in order of declaration)
  play <clip> <loop 0/1>              Play(clip, loop): a switch blends when something played before
  run <dt> <frames>                   -> per frame: clip time done blending [fromClip fromKey weight]
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
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var clips = new List<AnimTrack.ClipInfo>();
        AnimTrack t = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split(' ');
            switch (a[0])
            {
                case "clip":
                    clips.Add(new AnimTrack.ClipInfo { Interp = float.Parse(a[1], inv),
                        Times = a.Skip(2).Select(x => float.Parse(x, inv)).ToArray() });
                    break;
                case "play":
                    if (t == null) t = new AnimTrack(clips);
                    t.Play(int.Parse(a[1]), a[2] == "1");
                    break;
                case "run":
                    for (int i = 0; i < int.Parse(a[2]); i++)
                    {
                        t.Advance(float.Parse(a[1], inv));
                        var s = string.Format(inv, "{0} {1:0.000} {2} {3}", t.Clip, t.Time, t.Done ? 1 : 0, t.Blending ? 1 : 0);
                        if (t.Blending) s += string.Format(inv, " {0} {1} {2:0.00}", t.FromClip, t.FromKey, t.Weight);
                        Console.WriteLine(s);
                    }
                    break;
            }
        }
    }
}
"""

CLIPS = ["clip 0 0 1 2",          # 0: a cut, keys at 0, 1, 2 s
         "clip 0.25 0 0.5 1",     # 1: blends in over 250 ms
         "clip 0 0"]              # 2: one key (a pose)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "animtrack", DRIVER, "AnimTrack.cs")
    return lambda *lines: drive("\n".join(CLIPS + list(lines)) + "\n").split("\n")[:-1]


def test_looping_clip_wraps_past_its_last_key(run):
    # trk_ScanToKeyFrame: at exactly the last key's time it stays (t <= keyTime); past it, t %= endTime.
    assert run("play 0 1", "run 0.5 5") == ["0 0.500 0 0", "0 1.000 0 0", "0 1.500 0 0", "0 2.000 0 0",
                                            "0 0.500 0 0"]


def test_once_clip_holds_its_last_key_and_is_done_past_it(run):
    # Not looping: time clamps at endTime + 1 ms; trk_IsStopped once it passes endTime.
    assert run("play 0 0", "run 0.5 6")[3:] == ["0 2.000 0 0", "0 2.001 1 0", "0 2.001 1 0"]


def test_one_key_clip_played_once_is_done_at_once(run):
    assert run("play 2 0", "run 0.1 1") == ["2 0.000 1 0"]


def test_switch_blends_from_the_old_clip_s_next_key_over_the_new_clip_s_interp(run):
    # trk_SetCurAnim with a transition: Prev = the old clip at its current key (the next one at 0.5 s:
    # key 1); the new clip's time stays at 0 while the weight goes interpMS / m_InterpolationMS; past the
    # end the extra time plays the clip.
    assert run("play 0 1", "run 0.5 1", "play 1 0", "run 0.1 3") == [
        "0 0.500 0 0", "1 0.000 0 1 0 1 0.40", "1 0.000 0 1 0 1 0.80", "1 0.050 0 0"]


def test_switch_to_a_clip_without_interp_cuts(run):
    assert run("play 1 1", "run 0.3 1", "play 0 1", "run 0.1 1") == ["1 0.300 0 0", "0 0.100 0 0"]


def test_first_clip_never_blends(run):
    # No valid tracker before: no transition.
    assert run("play 1 1", "run 0.1 1") == ["1 0.100 0 0"]


def test_switch_during_a_blend_blends_from_the_new_clip_s_first_key(run):
    # Prev = Cur, which is the blending clip at key 0.
    assert run("play 0 1", "run 0.5 1", "play 1 1", "run 0.1 1", "play 1 0", "run 0.1 1")[-1] == \
        "1 0.000 0 1 1 0 0.40"


def test_played_again_restarts(run):
    assert run("play 0 1", "run 0.5 3", "play 0 1", "run 0.25 1")[-1] == "0 0.250 0 0"
