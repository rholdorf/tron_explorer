"""Dialogues and subtitles (TronViewer/.../Dialogues.cs) compiled with .NET, with the level's command manager.
Rules: docs/research/dialogue.md (branch research/dialogue): ltjs dialogue.cpp (HandleOn, Update,
NotifySpeakers, UpdateDialogue, StartDialogue, HandleOff), character.cpp (PlayDialogue, PlayDialogSound),
characterfx.cpp (PlayLipSyncSound) and hudsubtitles.cpp (Show, Update, Render), with Tron's changes from its
object.lto and cshell.dll there; worked by hand.

Driver lines (tab-separated):
  obj <name> <class> [radius] [cinematic]  a level object (Player, CAIHuman, Speaker, or any other class)
                                          with its voice's radius and IsCinematicAI
  log <name>             an object that prints "<time> <name> <message>" for each message it gets
  dlg <name> [k=v]...    a Dialogue: start, finished, cleanup (commands), remove (RemoveWhenComplete, 1)
  line <id> <speaker> <delay> <duration> [command]   the last dialogue's next line (duration 0: no voice file)
  str <id> <text>        a game string
  at <name> <x y z>      an object's place (LT units); the listener is "listener"
  scene <0/1>            a scene camera is live or not
  run <command>          a level command, run now
  tick <dt>              a frame: the server clock, the command table, then the dialogues and the subtitles
  sub                    "sub <id or -> <text>|<visible 0/1> <cinematic layout 0/1>"
  subs <0/1>             the subtitles toggle
  show <id> <text> [duration]  a subtitle shown directly (no duration: none), the player's
  top <lines> <height>   "top <y>": where the subtitle's text starts in the play box (y 380, 3 lines of 16)
The dialogues print "voice <time> <speaker> <id> <2d | 3d radius>" when a voice starts, "kill <time>
<speaker>" when one is cut, and "removed <time> <name>" when a dialogue leaves the level.
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
        var info = new Dictionary<int, (float radius, bool cinematic)>();
        var places = new Dictionary<string, LTVec>(StringComparer.OrdinalIgnoreCase);
        var strings = new Dictionary<int, string>();
        bool scene = false;
        var subtitles = new Subtitles();
        var dialogues = new Dialogues(cmds, subtitles,
            id => info.TryGetValue(id, out var i) ? i : (1000f, false),
            () => scene, id => strings.TryGetValue(id, out var t) ? t : null);
        dialogues.SpeakerPos = id => places.TryGetValue(cmds.Name(id), out var p) ? p : new LTVec(0, 0, 0);
        dialogues.ListenerPos = () => places.TryGetValue("listener", out var p) ? p : new LTVec(0, 0, 0);
        dialogues.PlayVoice = v => Console.WriteLine($"voice {N(cmds.Time)} {cmds.Name(v.Speaker)} {v.Id} {(v.Local ? "2d" : "3d " + N(v.Radius))}");
        dialogues.KillVoice = id => Console.WriteLine($"kill {N(cmds.Time)} {cmds.Name(id)}");
        DialogueProps last = null;
        var lines = new List<DialogueLine>();
        Action flush = () => { };
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            if (a[0] != "line") flush();
            switch (a[0])
            {
                case "obj":
                {
                    int id = cmds.Join(a[1], a[2]);
                    info[id] = (a.Length > 3 ? F(a[3]) : 1000f, a.Length > 4 && a[4] == "1");
                    break;
                }
                case "log":
                {
                    var name = a[1];
                    int id = cmds.Join(name, "Trigger");
                    cmds.Handle(id, m => { Console.WriteLine($"{N(cmds.Time)} {name} {m}"); return true; });
                    break;
                }
                case "dlg":
                {
                    var name = a[1];
                    var p = new DialogueProps { RemoveWhenComplete = true };
                    foreach (var kv in a.Skip(2).Select(x => x.Split(new[] { '=' }, 2)))
                        switch (kv[0])
                        {
                            case "start": p.StartCommand = kv[1]; break;
                            case "finished": p.FinishedCommand = kv[1]; break;
                            case "cleanup": p.CleanUpCommand = kv[1]; break;
                            case "remove": p.RemoveWhenComplete = kv[1] == "1"; break;
                        }
                    int id = cmds.Join(name, "Dialogue");
                    var flags = new GameBaseFlags(true, false, false);
                    cmds.Handle(id, flags.OnMessage);
                    flags.Remove += () => Console.WriteLine($"removed {N(cmds.Time)} {name}");
                    lines = new List<DialogueLine>();
                    var ls = lines;
                    flush = () => { p.Lines = ls.ToArray(); var d = dialogues.Add(id, p, flags); cmds.Handle(id, d.OnMessage); flush = () => { }; };
                    break;
                }
                case "line":
                    lines.Add(new DialogueLine { Id = int.Parse(a[1]), Speaker = a[2], Delay = F(a[3]), Duration = F(a[4]),
                                                 Voice = F(a[4]) > 0 ? $"voice/{a[1]}.wav" : "", Command = a.Length > 5 ? a[5] : "" });
                    break;
                case "str": strings[int.Parse(a[1])] = a[2]; break;
                case "at": { var v = a[2].Split(' ').Select(F).ToArray(); places[a[1]] = new LTVec(v[0], v[1], v[2]); break; }
                case "scene": scene = a[1] == "1"; break;
                case "run": cmds.Run(a[1]); break;
                case "tick":
                    cmds.BeginFrame(F(a[1]));
                    cmds.Update();
                    dialogues.Update(F(a[1]));
                    break;
                case "show": subtitles.Show(int.Parse(a[1]), a[2], new LTVec(0, 0, 0), 0, a.Length > 3 ? F(a[3]) : -1, null, new LTVec(0, 0, 0), false); break;
                case "top": Console.WriteLine("top " + N(subtitles.TextTop(int.Parse(a[1]), F(a[2]), 380, 3, 16))); break;
                case "subs": subtitles.Enabled = a[1] == "1"; break;
                case "sub":
                {
                    bool vis = subtitles.Draws(dialogues.ListenerPos(), scene);
                    Console.WriteLine($"sub {(subtitles.Visible ? subtitles.Id.ToString() : "-")} {subtitles.Text}|{(vis ? 1 : 0)} {(subtitles.Cinematic ? 1 : 0)}");
                    break;
                }
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    drive = cs_driver(tmp_path_factory, "dialogues", DRIVER, "Dialogues.cs", "GameBaseFlags.cs",
                      "KeyframerMotion.cs", "Commands.cs")
    return lambda *lines: drive("\n".join(lines) + "\n").splitlines()


def tick(n, dt="0.125"):
    return ["tick\t" + dt] * n


def test_lines_play_in_turn_each_after_its_delay_once_the_last_voice_ends(run):
    # Frames of 0.125 s. ON at 0: line 1 waits Delay1 0.25, its voice lasts 0.375 (to 0.625); line 2 starts
    # 0.5 s after the update that saw that voice end.
    out = run("obj\tplayer\tPlayer", "obj\tbob\tCAIHuman\t1500", "dlg\td1",
              "line\t10001\tplayer\t0.25\t0.375", "line\t10002\tbob\t0.5\t1",
              "run\tmsg d1 on", *tick(30))
    assert out[:2] == ["voice 0.25 player 10001 2d", "voice 1.125 bob 10002 3d 1500"]


def test_start_runs_before_line_1_after_its_delay_and_finish_then_cleanup_after_the_last_voice(run):
    out = run("log\tev", "obj\tplayer\tPlayer", "dlg\td1\tstart=msg ev start\tfinished=msg ev finished\tcleanup=msg ev cleanup",
              "line\t10001\tplayer\t0.25\t0.25\tmsg ev line1", "line\t10002\tplayer\t0\t0.25\tmsg ev line2",
              "run\tmsg d1 on", *tick(10))
    assert out == ["0.25 ev start", "0.25 ev line1", "voice 0.25 player 10001 2d",
                   "0.5 ev line2", "voice 0.5 player 10002 2d",
                   "0.75 ev finished", "0.75 ev cleanup", "removed 0.75 d1"]


def test_00000_is_a_silent_step_that_waits_its_delay_and_runs_its_command(run):
    out = run("log\tev", "obj\tplayer\tPlayer", "dlg\td1",
              "line\t0\tplayer\t0.25\t0\tmsg ev cue", "line\t10002\tplayer\t0\t0.25",
              "run\tmsg d1 on", *tick(6))
    # The step starts at 0.25 and ends on the next update; line 2 follows in that update.
    assert out[:3] == ["0.25 ev cue", "voice 0.375 player 10002 2d", "removed 0.625 d1"]


def test_a_cut_line_plays_nothing_and_ends_at_once(run):
    out = run("obj\tplayer\tPlayer", "obj\tcrown\tCAIHuman", "dlg\td1", "line\t10013\tcrown\t0\t0",
              "line\t10002\tplayer\t0\t0.25", "run\tmsg d1 on", *tick(6))
    assert out[:2] == ["voice 0.25 player 10002 2d", "removed 0.5 d1"]


def test_off_cuts_the_voice_and_cleans_up_without_the_finished_command(run):
    out = run("log\tev", "obj\tbob\tCAIHuman", "dlg\td1\tfinished=msg ev finished\tcleanup=msg ev cleanup",
              "line\t10001\tbob\t0\t5", "run\tmsg d1 on", *tick(2), "run\tmsg d1 off", "run\tmsg d1 on", *tick(2))
    assert out == ["voice 0.125 bob 10001 3d 1000", "kill 0.25 bob", "0.25 ev cleanup", "removed 0.25 d1"]


def test_off_while_off_still_runs_the_cleanup(run):
    out = run("log\tev", "dlg\td1\tremove=0\tcleanup=msg ev cleanup", "line\t10001\tplayer\t0\t5", "run\tmsg d1 off")
    assert out == ["0 ev cleanup"]


def test_kept_when_complete_it_plays_again_from_line_1_on_the_next_on(run):
    out = run("obj\tplayer\tPlayer", "dlg\td1\tremove=0", "line\t10001\tplayer\t0\t0.25",
              "line\t10002\tplayer\t0\t0.25", "run\tmsg d1 on", *tick(5), "run\tmsg d1 on", *tick(2))
    assert [o.split()[3] for o in out if o.startswith("voice")] == ["10001", "10002", "10001"]


def test_a_speaker_not_there_yet_turns_it_off_silently_until_the_next_on(run):
    # Tron's NotifySpeakers: no command runs and the dialogue stays; once the character is spawned an ON plays it.
    out = run("log\tev", "dlg\td1\tcleanup=msg ev cleanup\tfinished=msg ev finished", "line\t10001\tcinjet\t0\t0.25",
              "run\tmsg d1 on", *tick(3), "obj\tcinjet\tCAIHuman", *tick(2), "run\tmsg d1 on", *tick(4))
    assert out == ["voice 0.75 cinjet 10001 3d 1000", "1 ev finished", "1 ev cleanup", "removed 1 d1"]


def test_a_speaker_named_twice_or_not_a_character_fails_the_line_and_finishes(run):
    for objs in (["obj\tbob\tCAIHuman", "obj\tbob\tCAIHuman"], ["obj\tbob\tKey"]):
        out = run("log\tev", *objs, "dlg\td1\tfinished=msg ev finished\tcleanup=msg ev cleanup",
                  "line\t10001\tbob\t0\t1\tmsg ev line1", "line\t10002\tbob\t0\t1", "run\tmsg d1 on", *tick(3))
        assert out == ["0.125 ev line1", "0.125 ev finished", "0.125 ev cleanup", "removed 0.125 d1"]


def test_speaker_names_match_in_any_case(run):
    out = run("obj\tplayer\tPlayer", "dlg\td1", "line\t10001\tPLAYER\t0\t0.25", "run\tmsg d1 on", *tick(1))
    assert out == ["voice 0.125 player 10001 2d"]


def test_a_new_line_cuts_what_the_speaker_was_saying(run):
    out = run("obj\tbob\tSpeaker\t30000", "dlg\td1", "line\t10001\tbob\t0\t5", "dlg\td2", "line\t10002\tbob\t0\t1",
              "run\tmsg d1 on", *tick(2), "run\tmsg d2 on", *tick(1))
    assert out == ["voice 0.125 bob 10001 3d 30000", "kill 0.375 bob", "voice 0.375 bob 10002 3d 30000"]


def test_while_a_scene_camera_is_on_only_the_player_and_cinematic_ais_are_heard(run):
    # Heard client-local at radius 10000; any other speaker's line ends silently on the next update.
    out = run("obj\tplayer\tPlayer", "obj\tbob\tCAIHuman\t1500\t0", "obj\tcin\tCAIHuman\t1500\t1",
              "obj\tspk\tSpeaker\t30000\t1", "scene\t1", "dlg\td1", "line\t10001\tbob\t0\t1", "line\t10002\tspk\t0\t1",
              "line\t10003\tcin\t0\t0.25", "line\t10004\tplayer\t0\t0.25", "run\tmsg d1 on", *tick(8))
    assert out == ["voice 0.375 cin 10003 2d", "voice 0.625 player 10004 2d", "removed 0.875 d1"]


def test_a_removed_dialogue_takes_no_on(run):
    out = run("obj\tplayer\tPlayer", "dlg\td1", "line\t10001\tplayer\t0\t0.25", "run\tmsg d1 remove",
              "run\tmsg d1 on", *tick(3))
    assert out == ["removed 0 d1"]


def test_a_voice_is_subtitled_with_its_string_until_it_ends(run):
    out = run("obj\tplayer\tPlayer", "str\t10001\tHello, program.", "dlg\td1", "line\t10001\tplayer\t0\t0.25",
              "line\t10002\tplayer\t0\t0.25", "run\tmsg d1 on", "tick\t0.125", "sub", *tick(2), "sub")
    assert [o for o in out if o.startswith("sub")] == ["sub 10001 Hello, program.|1 0", "sub - |0 0"]


def test_a_line_with_no_string_or_no_voice_shows_nothing(run):
    out = run("obj\tplayer\tPlayer", "str\t10013\tcut", "dlg\td1", "line\t10001\tplayer\t0\t0.25",
              "line\t10013\tplayer\t0\t0", "run\tmsg d1 on", "tick\t0.125", "sub", *tick(2), "sub")
    assert [o for o in out if o.startswith("sub")] == ["sub - |0 0", "sub - |0 0"]


def test_off_takes_the_subtitle_down_with_the_voice(run):
    out = run("obj\tplayer\tPlayer", "str\t10001\tHi", "dlg\td1", "line\t10001\tplayer\t0\t5",
              "run\tmsg d1 on", "tick\t0.125", "run\tmsg d1 off", "sub")
    assert out[-1] == "sub - |0 0"


def test_an_ai_is_subtitled_only_within_77_percent_of_its_radius(run):
    # Checked when it starts and each frame, from where it spoke.
    out = run("obj\tbob\tCAIHuman\t1000", "obj\tamy\tCAIHuman\t1000", "str\t10001\tnear", "str\t10002\tfar",
              "at\tbob\t0 0 0.5", "at\tamy\t0 0 800", "at\tlistener\t0 0 0",
              "dlg\td1", "line\t10001\tbob\t0\t1", "line\t10002\tamy\t0\t1", "run\tmsg d1 on",
              "tick\t0.125", "sub", "at\tlistener\t0 0 -900", "tick\t0.125", "sub", *tick(8), "sub")
    assert [o for o in out if o.startswith("sub")] == ["sub 10001 near|1 0", "sub 10001 near|0 0", "sub - |0 0"]


def test_under_a_scene_camera_every_subtitle_shows_in_the_scene_layout(run):
    out = run("obj\tcin\tCAIHuman\t1000\t1", "str\t10001\tscene", "at\tcin\t0 0 5000", "scene\t1",
              "dlg\td1", "line\t10001\tcin\t0\t1", "run\tmsg d1 on", "tick\t0.125", "sub")
    assert out[-1] == "sub 10001 scene|1 1"


def test_a_new_subtitle_replaces_the_one_up_unless_it_is_in_the_quiet_band(run):
    out = run("obj\tbob\tSpeaker\t1000", "obj\tamy\tSpeaker\t1000", "obj\tjoe\tSpeaker\t1000",
              "str\t10001\tfirst", "str\t20500\tchatter", "str\t20900\tkept", "dlg\td1", "line\t10001\tbob\t0\t5",
              "dlg\td2", "line\t20500\tamy\t0\t1", "dlg\td3", "line\t20900\tjoe\t0\t1",
              "run\tmsg d1 on", "tick\t0.125", "run\tmsg d2 on", "tick\t0.125", "sub", "run\tmsg d3 on", "tick\t0.125", "sub")
    assert [o for o in out if o.startswith("sub")] == ["sub 10001 first|1 0", "sub 20900 kept|1 0"]
    assert "voice 0.25 amy 20500 3d 1000" in out   # its voice still plays


def test_subtitles_off_hides_them_and_stops_their_clock(run):
    # Subtitles 0: CHUDSubtitles' Update and Render do nothing, so its time runs on only once they're back on.
    out = run("obj\tbob\tSpeaker\t1000", "str\t10001\tHi", "dlg\td1", "line\t10001\tbob\t0\t5",
              "dlg\td2\tremove=0", "run\tmsg d1 on", "tick\t0.125", "subs\t0", "sub", "subs\t1", "sub")
    assert [o for o in out if o.startswith("sub")] == ["sub 10001 Hi|0 0", "sub 10001 Hi|1 0"]


def test_a_subtitle_without_a_duration_lasts_0_04_s_a_character(run):
    out = run("show\t10001\t0123456789", "tick\t0.125", "tick\t0.125", "tick\t0.125", "sub", "tick\t0.125", "sub")
    assert out == ["sub 10001 0123456789|1 0", "sub - |0 0"]


def test_a_subtitle_that_fits_sits_on_the_bottom_of_its_three_line_box(run):
    # The box is 2 + 3 x 16 tall: one line of 16 starts 34 below its top, three of 48 start 2 below.
    assert run("show\t1\tx\t4", "top\t1\t16", "top\t3\t48") == ["top 414", "top 382"]


def test_a_longer_subtitle_scrolls_up_after_three_line_times_until_its_last_line_shows(run):
    # 5 lines over 6 s: T = 1 s a line; it starts top-aligned, waits 3 s, then moves 16 a second, at most
    # 80 + 2 - 50 = 32.
    out = run("show\t1\tx\t6", "top\t5\t80", *(["tick\t0.125"] * 28), "top\t5\t80",
              *(["tick\t0.125"] * 8), "top\t5\t80", *(["tick\t0.125"] * 8), "top\t5\t80")
    assert out == ["top 380", "top 372", "top 356", "top 348"]
