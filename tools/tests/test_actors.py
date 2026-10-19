"""Characters as cutscene actors (TronViewer/.../Actors.cs over Commands.cs, Characters.cs and AnimTrack.cs),
compiled with .NET and driven line by line. Rules: docs/research/cutscene-actors.md (branch
research/cutscene-actors) from ltjs aigoalmgr.cpp (GOALSCRIPT, HandleGoalScript, UpdateGoals),
aigoalanimate.cpp, aihumanstate.cpp (CAIHumanStateAnimate), ai.cpp (FacePos, UpdatePosition, TRACKLOOKAT),
character.cpp (TELEPORT, HIDDEN, ATTACH), aihuman.cpp (HandleTeleport, FindFloorHeight). Expected values are
worked by hand from those rules.

Driver lines (tab-separated):
  character <name> <idle> <clips> <dims y>   a placed character at the origin facing +z, its animations
                                            "name:t0,t1,...:interp;..." (seconds), playing its idle
  point <name> <x,y,z> <yaw deg> <0/1>       a TeleportPoint, its MoveToFloor
  obj <name> <class> <x,y,z>                 any other object
  floor <y>                                  the world's floor height (none before this line)
  run <command>                              a command string, no sender
  frame <dt>                                 a frame: the characters' first updates, the actors' updates
                                            (frame time dt), then their animations advance dt
  pose <name>                                prints "pose <x> <y> <z> <yaw degrees>"
  icon <name>                                prints "icon <x> <y> <z>": where its talk icon is
The animations print "play <character> <clip> <loop>" and "restart <character> <loop>"; the actor's hooks
print "attachments <character> <shown>", "attach <character> <position> <name>", "detach <character>
<position>", "track <character> <on>", "talkicon <character> <on>"; its GameBase stand-in prints "base <character> <words>".
"""
import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Globalization;
using Tron;

sealed class FakeAnimation : IActorAnimation
{
    readonly string who;
    readonly AnimTrack track;
    readonly List<string> names = new List<string>();
    readonly List<string[]> texts = new List<string[]>();
    public Action<string> OnKey;
    public FakeAnimation(string who, string clips)
    {
        this.who = who;
        var infos = new List<AnimTrack.ClipInfo>();
        foreach (var c in clips.Split(';'))
        {
            var p = c.Split(':');
            names.Add(p[0]);
            // animation keys: "t=text|t=text", '~' standing for ';' in the text
            var keys = p.Length > 3 ? p[3].Split('|') : new string[0];
            texts.Add(Array.ConvertAll(keys, k => k.Substring(k.IndexOf('=') + 1).Replace('~', ';')));
            infos.Add(new AnimTrack.ClipInfo { Times = Array.ConvertAll(p[1].Split(','), F), Interp = F(p[2]),
                                               Keys = Array.ConvertAll(keys, k => F(k.Substring(0, k.IndexOf('=')))) });
        }
        track = new AnimTrack(infos);
    }
    void Flush()
    {
        foreach (var (clip, key) in track.Fired) OnKey?.Invoke(texts[clip][key]);
        track.Fired.Clear();
    }
    static float F(string s) => float.Parse(s, CultureInfo.InvariantCulture);
    int Find(string n) => names.FindIndex(x => string.Equals(x, n, StringComparison.OrdinalIgnoreCase));
    public bool Has(string n) => Find(n) >= 0;
    public bool Play(string n, bool loop)
    {
        int i = Find(n);
        if (i < 0) return false;
        track.Play(i, loop);
        Flush();
        if (Program.Verbose) Console.WriteLine("play\t" + who + "\t" + names[i] + "\t" + (loop ? 1 : 0));
        return true;
    }
    public void Restart(bool loop)
    {
        track.Restart(loop);
        Flush();
        Console.WriteLine("restart\t" + who + "\t" + (loop ? 1 : 0));
    }
    public bool Done => track.Done;
    public void Advance(float dt)
    {
        track.Advance(dt);
        Flush();
    }
}

static class Program
{
    public static bool Verbose;
    static string V(LTVec v) => v.x.ToString("0.###", CultureInfo.InvariantCulture) + "\t" + v.y.ToString("0.###", CultureInfo.InvariantCulture) + "\t" + v.z.ToString("0.###", CultureInfo.InvariantCulture);
    static LTVec P(string s)
    {
        var a = s.Split(',');
        return new LTVec(float.Parse(a[0], CultureInfo.InvariantCulture), float.Parse(a[1], CultureInfo.InvariantCulture), float.Parse(a[2], CultureInfo.InvariantCulture));
    }
    static LTQuat Yaw(float deg) => LTQuat.FromEuler(0, deg * (float)Math.PI / 180, 0);

    static void Main()
    {
        var mgr = new CommandMgr(() => 0.0);
        int frame = 0;
        var characters = new Characters(mgr, () => frame);
        var actors = new Actors(mgr);
        var anims = new List<FakeAnimation>();
        var byName = new Dictionary<string, Actor>(StringComparer.OrdinalIgnoreCase);
        var positions = new Dictionary<int, LTVec>();
        var points = new Dictionary<int, (LTVec, LTQuat, bool)>();
        float? floor = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "character":
                {
                    string who = a[1];
                    int id = mgr.Join(who, "CAIHuman");
                    characters.Add(id, "");
                    var anim = new FakeAnimation(who, a[3]);
                    anim.Play(a[2], true);
                    anims.Add(anim);
                    var actor = actors.Add(id, anim, a[2], new LTVec(0, 0, 0), Yaw(0), new LTVec(10, float.Parse(a[4], CultureInfo.InvariantCulture), 10));
                    anim.OnKey = actor.AnimationKey;
                    actor.PositionOf =o => byName.TryGetValue(mgr.Name(o), out var other) && mgr.Class(o) == "CAIHuman" ? other.Pos : positions.TryGetValue(o, out var p) ? p : (LTVec?)null;
                    actor.TeleportPointOf = o => points.TryGetValue(o, out var tp) ? tp : ((LTVec, LTQuat, bool)?)null;
                    actor.CastDown = (from, to) => floor.HasValue && floor.Value <= from.y && floor.Value >= to.y ? floor : null;
                    actor.ShowAttachments = on => Console.WriteLine("attachments\t" + who + "\t" + (on ? 1 : 0));
                    actor.Attach = (pos, n) => Console.WriteLine("attach\t" + who + "\t" + pos + "\t" + n);
                    actor.Detach = pos => Console.WriteLine("detach\t" + who + "\t" + pos);
                    actor.Track = on => Console.WriteLine("track\t" + who + "\t" + (on ? 1 : 0));
                    actor.TalkIcon = on => Console.WriteLine("talkicon\t" + who + "\t" + (on ? 1 : 0));
                    mgr.Handle(id, m =>
                    {
                        Console.WriteLine("base\t" + who + "\t" + string.Join("|", m.Words));
                        if (m.Is("REMOVE")) actor.Remove();
                        return true;
                    });
                    byName[who] = actor;
                    break;
                }
                case "point":
                {
                    int id = mgr.Join(a[1], "TeleportPoint");
                    points[id] = (P(a[2]), Yaw(float.Parse(a[3], CultureInfo.InvariantCulture)), a[4] == "1");
                    positions[id] = P(a[2]);
                    break;
                }
                case "obj":
                {
                    int id = mgr.Join(a[1], a[2]);
                    positions[id] = P(a[3]);
                    string n = a[1];
                    mgr.Handle(id, m =>
                    {
                        Console.WriteLine("msg\t" + n + "\t" + (m.Sender >= 0 ? mgr.Name(m.Sender) : "-") + "\t" + string.Join("|", m.Words));
                        return true;
                    });
                    break;
                }
                case "floor":
                    floor = float.Parse(a[1], CultureInfo.InvariantCulture);
                    break;
                case "run":
                    mgr.Run(a[1]);
                    break;
                case "frame":
                {
                    Verbose = true;
                    float dt = float.Parse(a[1], CultureInfo.InvariantCulture);
                    frame++;
                    characters.Update();
                    actors.Update(dt);
                    actors.RunKeys();
                    foreach (var an in anims) an.Advance(dt);
                    Console.WriteLine("frame\t" + frame);
                    break;
                }
                case "pose":
                {
                    var act = byName[a[1]];
                    var f = act.Rot.Forward();
                    double yaw = Math.Atan2(f.x, f.z) * 180 / Math.PI;
                    Console.WriteLine("pose\t" + V(act.Pos) + "\t" + yaw.ToString("0.#", CultureInfo.InvariantCulture));
                    break;
                }
                case "icon":
                    Console.WriteLine("icon\t" + V(byName[a[1]].TalkIconPos));
                    break;
                case "report":
                    foreach (var u in mgr.Unhandled) Console.WriteLine("count\t" + u.Verb + "\t" + u.Class + "\t" + u.Word + "\t" + u.Count);
                    break;
            }
        }
    }
}
"""

# An idle (2 keys over 2 s), a 1-second animation, a single-key pose, and DXBLoop.
JET = ("character", "jet", "Idle", "Idle:0,2:0;Wave:0,1:0;Pose:0:0;Talk:0,3:0.2", 30)
JET_DXB = ("character", "jet", "Idle", "Idle:0,2:0;Wave:0,1:0;DXBLoop:0,1:0", 30)


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    run_driver = cs_driver(tmp_path_factory, "actors", DRIVER, "Commands.cs", "Characters.cs", "AnimTrack.cs",
                           "KeyframerMotion.cs", "Actors.cs")

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        return [tuple(x.split("\t")) for x in run_driver(text).splitlines()]
    return run


# The character's first two updates (Characters.cs): frame 1 runs Initial, frame 2 delivers what was queued.
START = [("frame", 0.1), ("frame", 0.1)]
STARTED = [("frame", "1"), ("frame", "2")]


def test_a_looping_animate_plays_on_the_update_it_arrives_and_keeps_looping(driver):
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Wave loop=1)"),
                  ("frame", 0.5), ("frame", 1.0), ("frame", 1.0)])
    assert out == [*STARTED, ("play", "jet", "Wave", "1"), ("frame", "3"), ("frame", "4"), ("frame", "5")]


def test_an_animate_queued_before_the_first_update_plays_on_the_second(driver):
    # CAI::PreUpdate sends the queue, then the same update's UpdateGoals starts the script.
    out = driver([JET, ("run", "msg jet (goalscript animate anim=Wave loop=true)"), *START])
    assert out == [("frame", "1"), ("play", "jet", "Wave", "1"), ("frame", "2")]


def test_a_once_animate_returns_to_the_idle_two_updates_after_it_ends(driver):
    # Frame 3 plays Wave (1 s). By frame 5 it has run 1.0 s (frames 3 and 4 advance 0.5 each): not yet past its
    # last key. Frame 6 sees it done (state complete), frame 7 the goal unlocks at importance 0, frame 8 the
    # goal manager drops it and the idle plays.
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Wave)"),
                  *[("frame", 0.5)] * 6])
    assert out == [*STARTED, ("play", "jet", "Wave", "0"), ("frame", "3"), ("frame", "4"), ("frame", "5"),
                   ("frame", "6"), ("frame", "7"), ("play", "jet", "Idle", "1"), ("frame", "8")]


def test_a_single_key_pose_is_done_at_once(driver):
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Pose loop=0)"),
                  ("frame", 0.1), ("frame", 0.1), ("frame", 0.1)])
    assert out == [*STARTED, ("play", "jet", "Pose", "0"), ("frame", "3"), ("frame", "4"),
                   ("play", "jet", "Idle", "1"), ("frame", "5")]


def test_a_later_animate_reuses_the_goal_and_keeps_its_loop_flag(driver):
    # AddGoal returns the Animate goal still alive: anim= changes, loop stays on, it plays at once.
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Wave loop=1)"), ("frame", 0.1),
                  ("run", "msg jet (goalscript animate anim=Talk)"), ("frame", 0.1), ("frame", 5)])
    assert out == [*STARTED, ("play", "jet", "Wave", "1"), ("frame", "3"), ("play", "jet", "Talk", "1"),
                   ("frame", "4"), ("frame", "5")]


def test_loop_given_again_replaces_the_flag(driver):
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Wave loop=1)"), ("frame", 0.1),
                  ("run", "msg jet (goalscript animate anim=Wave Loop=no)"), ("frame", 0.1)])
    assert out == [*STARTED, ("play", "jet", "Wave", "1"), ("frame", "3"), ("play", "jet", "Wave", "0"),
                   ("frame", "4")]


def test_only_the_last_goalscript_of_a_frame_stands(driver):
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Wave loop=1); "
                                       "msg jet (goalscript animate anim=Talk loop=1)"), ("frame", 0.1)])
    assert out == [*STARTED, ("play", "jet", "Talk", "1"), ("frame", "3")]


def test_a_two_step_script_starts_its_second_step_the_update_after_the_first_ends(driver):
    # Pose is done at frame 3; frame 4 unlocks, frame 5 drops it (idle) and adds step 2, active on frame 6.
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Pose animate anim=Wave)"),
                  *[("frame", 0.1)] * 4])
    assert out == [*STARTED, ("play", "jet", "Pose", "0"), ("frame", "3"), ("frame", "4"),
                   ("play", "jet", "Idle", "1"), ("frame", "5"), ("play", "jet", "Wave", "0"), ("frame", "6")]


def test_none_or_an_unknown_goal_changes_nothing_and_a_loop_goes_on(driver):
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=Wave loop=1)"), ("frame", 0.1),
                  ("run", "msg jet (goalscript none)"), ("frame", 0.1), ("run", "msg jet goalscript"),
                  ("frame", 3)])
    assert out == [*STARTED, ("play", "jet", "Wave", "1"), ("frame", "3"), ("frame", "4"), ("frame", "5")]


def test_a_missing_animation_plays_dxbloop_where_the_model_has_it(driver):
    out = driver([JET_DXB, *START, ("run", "msg jet (goalscript animate anim=Gen_IODefault Loop=true)"),
                  ("frame", 0.1)])
    assert out == [*STARTED, ("play", "jet", "DXBLoop", "1"), ("frame", "3")]


def test_a_missing_animation_without_dxbloop_restarts_the_one_playing(driver):
    out = driver([JET, *START, ("run", "msg jet (goalscript animate anim=m07jetrun loop=0)"), ("frame", 0.1)])
    assert out == [*STARTED, ("restart", "jet", "0"), ("frame", "3")]


def test_goto_is_not_run_and_is_counted(driver):
    out = driver([JET, *START, ("run", "msg jet (goalscript goto node=n1 movement=walk)"), ("frame", 0.1),
                  ("report",)])
    assert out == [*STARTED, ("frame", "3"), ("count", "MSG", "CAIHuman", "GOALSCRIPT GOTO", "1")]


def test_teleport_moves_it_on_its_next_update_and_drops_it_to_the_floor(driver):
    # MoveToFloor: the cast from dims.y (30) above the point to 10 dims.y below finds the floor at 90, so it
    # stands at 90 + 30. The point's rotation is taken whole.
    out = driver([JET, ("point", "tp1", "100,150,200", 90, 1), ("floor", 90), *START,
                  ("run", "msg jet (teleport tp1)"), ("pose", "jet"), ("frame", 0.1), ("pose", "jet")])
    assert out == [*STARTED, ("pose", "0", "0", "0", "0"), ("frame", "3"), ("pose", "100", "120", "200", "90")]


def test_teleport_without_move_to_floor_or_floor_in_reach_keeps_the_points_height(driver):
    out = driver([JET, ("point", "tp1", "100,150,200", 0, 0), ("point", "tp2", "0,1000,0", 0, 1), ("floor", 90),
                  *START, ("run", "msg jet (teleport tp1)"), ("frame", 0.1), ("pose", "jet"),
                  ("run", "msg jet (teleport tp2)"), ("frame", 0.1), ("pose", "jet")])
    assert out == [*STARTED, ("frame", "3"), ("pose", "100", "150", "200", "0"), ("frame", "4"),
                   ("pose", "0", "1000", "0", "0")]


def test_teleport_to_anything_but_one_teleport_point_does_nothing(driver):
    out = driver([JET, ("obj", "door", "Door", "50,0,0"), ("point", "twin", "1,2,3", 0, 0),
                  ("point", "twin", "4,5,6", 0, 0), *START,
                  ("run", "msg jet (teleport door); msg jet (teleport twin); msg jet (teleport nowhere)"),
                  ("frame", 0.1), ("pose", "jet")])
    assert out == [*STARTED, ("frame", "3"), ("pose", "0", "0", "0", "0")]


def test_an_animation_plays_on_through_a_teleport(driver):
    out = driver([JET, ("point", "tp1", "100,0,0", 0, 0), *START,
                  ("run", "msg jet (goalscript animate anim=Wave loop=1)"), ("frame", 0.1),
                  ("run", "msg jet (teleport tp1)"), ("frame", 0.1), ("pose", "jet")])
    assert out == [*STARTED, ("play", "jet", "Wave", "1"), ("frame", "3"), ("frame", "4"),
                   ("pose", "100", "0", "0", "0")]


def test_faceobject_turns_the_yaw_over_half_a_second_per_180_degrees_eased_by_sqrt(driver):
    # The player at +x from a character facing +z: 90 degrees, so 0.25 s. After 0.0625 s, sqrt(0.25) = half
    # way: 45 degrees; after 0.25 s, 90. The target's height doesn't tilt it.
    out = driver([JET, ("obj", "player", "Player", "500,300,0"), *START, ("run", "msg jet (faceobject player)"),
                  ("frame", 0.0625), ("pose", "jet"), ("frame", 0.1875), ("pose", "jet"), ("frame", 1),
                  ("pose", "jet")])
    assert out == [*STARTED, ("frame", "3"), ("pose", "0", "0", "0", "45"), ("frame", "4"),
                   ("pose", "0", "0", "0", "90"), ("frame", "5"), ("pose", "0", "0", "0", "90")]


def test_faceobject_ignores_an_object_within_a_unit_or_not_found(driver):
    out = driver([JET, ("obj", "near", "Point", "0.5,100,0.5"), *START,
                  ("run", "msg jet (faceobject near); msg jet (faceobject nobody)"), ("frame", 1),
                  ("pose", "jet")])
    assert out == [*STARTED, ("frame", "3"), ("pose", "0", "0", "0", "0")]


def test_faceobject_turns_toward_another_character(driver):
    out = driver([JET, ("character", "reg01", "Idle", "Idle:0,2:0", 30), *START,
                  ("point", "tp", "0,0,-100", 0, 0), ("run", "msg reg01 (teleport tp)"), ("frame", 0.1),
                  ("run", "msg jet (faceobject reg01)"), ("frame", 0.5), ("pose", "jet")])
    assert out[-1] == ("pose", "0", "0", "0", "180")


def test_hidden_hides_the_attachments_and_goes_on_to_gamebase_visible_does_not(driver):
    out = driver([JET, *START, ("run", "msg jet (hidden 1); msg jet (visible 1); msg jet (hidden 0)")])
    assert out == [*STARTED, ("attachments", "jet", "0"), ("base", "jet", "hidden|1"),
                   ("base", "jet", "visible|1"), ("attachments", "jet", "1"), ("base", "jet", "hidden|0")]


def test_attach_and_detach_name_a_position(driver):
    out = driver([JET, *START, ("run", "msg jet (detach RightHand); msg jet (attach RightHand ICRegularDisc)")])
    assert out == [*STARTED, ("detach", "jet", "RightHand"), ("attach", "jet", "RightHand", "ICRegularDisc")]


def test_tracklookat_until_tracknone_or_an_animate_starts(driver):
    # CAIHumanStateAnimate::Init calls DisableNodeTracking; HumanIdle doesn't.
    out = driver([JET, *START, ("run", "msg jet tracklookat"), ("run", "msg jet tracknone"),
                  ("run", "msg jet tracklookat"), ("run", "msg jet (goalscript animate anim=Wave loop=1)"),
                  ("frame", 0.1)])
    assert out == [*STARTED, ("track", "jet", "1"), ("track", "jet", "0"), ("track", "jet", "1"),
                   ("track", "jet", "0"), ("play", "jet", "Wave", "1"), ("frame", "3")]


def test_a_removed_character_takes_nothing_more(driver):
    out = driver([JET, *START, ("run", "msg jet remove"), ("run", "msg jet (goalscript animate anim=Wave)"),
                  ("frame", 0.1)])
    assert out == [*STARTED, ("base", "jet", "remove"), ("base", "jet", "goalscript|animate|anim=Wave"),
                   ("frame", "3")]


def test_messages_it_doesnt_act_on_reach_gamebase(driver):
    out = driver([JET, *START, ("run", "msg jet (talklock 1); msg jet armor_on")])
    assert out == [*STARTED, ("base", "jet", "talklock|1"), ("base", "jet", "armor_on")]


def test_the_three_talk_icons_are_one_icon_on_while_any_last_said_so(driver):
    # object.lto's LISTENICON / SAYICON / ASKICON handler: a true value sets the character's talk-icon flag
    # (character fx flag 0x20, which the client shows as AI_TALKICON) when it isn't set, anything else clears it;
    # the string id is kept for talking to it.
    out = driver([JET, *START, ("run", "msg jet (sayicon 1 12026); msg jet (listenicon true); msg jet (askicon 0); "
                                       "msg jet (askicon 0); msg jet (listenicon yes)")])
    assert out == [*STARTED, ("talkicon", "jet", "1"), ("talkicon", "jet", "0"), ("talkicon", "jet", "1")]


def test_the_talk_icon_stands_ten_units_above_the_box_and_follows(driver):
    # cshell.dll 0x10169720: the object's dims, y + 10.0f (0x101e9364), as AI_TALKICON's create offset (its key
    # has Offset 0,0,0 and follows): origin + (0, dims.y + 10, 0). JET's dims.y is 30.
    out = driver([JET, ("point", "spot", "100,5,-20", 90, 0), *START, ("icon", "jet"),
                  ("run", "msg jet (teleport spot)"), ("frame", 0.1), ("icon", "jet")])
    assert out == [*STARTED, ("icon", "0", "40", "0"), ("frame", "3"), ("icon", "100", "45", "-20")]


# A once animation with animation keys: a CMD key at 0.5 s and one at 0.5 s holding two statements.
KEYED = ("character", "jet", "Idle", "Idle:0,2:0;Examine:0,1:0:0.5=cmd msg door (on)|1=cmd msg door off~FOOTSTEP_KEY 1", 30)


def test_a_cmd_animation_key_runs_its_command_from_the_character_in_the_next_command_frame(driver):
    # CCharacter::HandleModelString: `CMD <command>` runs IsValidCmd + Process with the character as sender and
    # active target; other keys (FOOTSTEP_KEY) do nothing here. Frame 3 plays Examine; its time crosses 0.5 s
    # as the animations advance after frame 4's update, and the command runs in frame 5's command frame.
    out = driver([KEYED, ("obj", "door", "Door", "0,0,0"), *START,
                  ("run", "msg jet (goalscript animate anim=Examine)"), ("frame", 0.25), ("frame", 0.25),
                  ("frame", 0.5), ("frame", 0.5)])
    assert out == [*STARTED, ("play", "jet", "Examine", "0"), ("frame", "3"), ("frame", "4"),
                   ("msg", "door", "jet", "on"), ("frame", "5"), ("msg", "door", "jet", "off"), ("frame", "6")]


def test_a_removed_characters_keys_run_nothing(driver):
    out = driver([KEYED, ("obj", "door", "Door", "0,0,0"), *START,
                  ("run", "msg jet (goalscript animate anim=Examine)"), ("frame", 0.5), ("run", "msg jet remove"),
                  ("frame", 0.5)])
    assert ("msg", "door", "jet", "on") not in out


def test_attach_detach_on_and_off_animation_keys(driver):
    # HandleModelString: ATTACH with exactly a position and a name, DETACH with exactly a position (m01_jet's
    # `DETACH LeftLowerArm Jet_Disc` has one word too many: nothing), ON / OFF <object> send it ON / OFF.
    keyed = ("character", "jet", "Idle",
             "Idle:0,2:0;Examine:0,1:0:0=ATTACH LeftLowerArm Jet_Disc~DETACH LeftLowerArm Jet_Disc~DETACH RightHand"
             "|0.5=ON door~OFF door~ON nobody", 30)
    out = driver([keyed, ("obj", "door", "Door", "0,0,0"), *START,
                  ("run", "msg jet (goalscript animate anim=Examine)"), ("frame", 0.5), ("frame", 0.5)])
    assert out == [*STARTED, ("play", "jet", "Examine", "0"), ("attach", "jet", "LeftLowerArm", "Jet_Disc"),
                   ("detach", "jet", "RightHand"), ("frame", "3"), ("msg", "door", "jet", "ON"),
                   ("msg", "door", "jet", "OFF"), ("frame", "4")]
