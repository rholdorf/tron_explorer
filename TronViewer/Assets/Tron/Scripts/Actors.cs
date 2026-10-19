using System;
using System.Collections.Generic;
using System.Globalization;

// Characters as cutscene actors: what their messages do to them (docs/research/cutscene-actors.md on
// research/cutscene-actors). Plain C#, no Unity, so tools/tests/test_actors.py compiles it with .NET;
// LevelBuilder.Actors.cs gives each drawn character, placed or spawned, its Actor and draws what it does.
namespace Tron
{
    // A character's animations as its goal script plays them (CharacterAnimation; a fake in the tests).
    public interface IActorAnimation
    {
        // Plays its animation `name` (any case) from the start; false, and nothing changes, if it has none.
        bool Play(string name, bool loop);
        // The animation playing starts over at time 0, looping or once (SetModelLooping, ResetModelAnimation).
        void Restart(bool loop);
        bool Has(string name);
        // Played once and past its last key (MS_PLAYDONE).
        bool Done { get; }
    }

    // One character's AI as far as cutscenes reach it (ltjs ai.cpp, aigoalmgr.cpp, aigoalanimate.cpp,
    // aihumanstate.cpp CAIHumanStateAnimate, character.cpp, aihuman.cpp). Its messages (after the first-update
    // queue, Characters.cs; before GameBase's, which it falls through to):
    //   GOALSCRIPT <goal> [name=value...] [<goal> ...]: replaces the script (ClearGoalScript), started on the
    //     next update. A word without '=' is a goal (Animate, Goto: any case), the name=value words after it its
    //     parameters. An unknown goal stops the parse there: the steps before it stay, but nothing starts.
    //   TELEPORT <TeleportPoint> | <x,y,z>: moves it on its next update (CCharacter::UpdateTeleport) to the
    //     point's position and full rotation, then a MoveToFloor point drops it to the floor (FindFloorHeight:
    //     a cast from dims.y above to 10 dims.y below, standing at hit + dims.y). Anything but one
    //     TeleportPoint of that name does nothing. The animation and any turn go on.
    //   FACEOBJECT <object>: CAI::FacePos on the one object of that name (yaw only).
    //   HIDDEN 1/0: also hides / shows its attachments (HideCharacter), then GameBase's HIDDEN.
    //   ATTACH <position> <attachment>, DETACH <position>: CAttachments::Attach / Detach.
    //   TRACKLOOKAT / TRACKNONE: its head tracks the player's Head / stops.
    //   LISTENICON / SAYICON / ASKICON <true/false> [string id] (Tron, object.lto 0x101608db): one talk icon for all
    //     three: a true value (IsTrueChar) sets the character's talk-icon flag (character fx flag 0x20), any other
    //     clears it; the client shows AI_TALKICON on it while the flag is set (cshell.dll 0x10167d75). The type
    //     and string id are for the player talking to it.
    // The Animate goal (aigoals.txt [Goal4]: importance 100, DeleteWhenDone; aigoalanimate.cpp):
    //   - a new one starts with loop off; a script step finding one alive reuses it (AddGoal returns it):
    //     `anim=` and `loop=` (IsTrueChar: t, T, y, Y, 1) change it and restart the animation, a missing loop=
    //     keeps the old flag;
    //   - activating it enters state Animate (node tracking off: CAI::DisableNodeTracking);
    //   - while the state is initialized, a reset plays the animation (SetAnimation: the name, else DXBLoop,
    //     else the one playing starts over with the new flag);
    //   - played once, the state completes when the animation is done (CAIHumanStateAnimate::Update); the next
    //     update the goal unlocks at importance 0; the next the goal manager drops it: the script advances, the
    //     goal is deleted, state HumanIdle (its idle, looping), and the script's next step is added, active
    //     the update after (none left: the script is cleared).
    // Goto (AI movement) isn't run: a script step for it adds nothing and is counted for the level's report.
    // Per update (CAI::Update): teleport, goals, rotation (UpdatePosition), the state.
    public sealed class Actor
    {
        public const float RotationSpeedStatic = 0.5f;     // ai.cpp ROTATION_SPEED_STATIC: 180 degrees in 0.5 s
        public const float FacingThreshold = 0.999999f;    // c_fFacingThreshhold
        public const string MissingAnimation = "DXBLoop";

        static readonly HashSet<string> KnownGoals = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "Animate", "Goto" };

        sealed class Step
        {
            public string Goal;
            public readonly List<KeyValuePair<string, string>> Params = new List<KeyValuePair<string, string>>();
        }

        sealed class AnimateGoal
        {
            public string Anim;
            public bool Loop, ResetAnim = true, Scripted;
            public float Importance = 100;
        }

        enum StateStatus { None, Initialized, Complete }

        public readonly int Id;
        readonly CommandMgr commands;
        readonly IActorAnimation anim;   // null: it draws no character
        readonly string idle;
        readonly LTVec dims;

        // Where it stands (its object's position, LT units) and its rotation.
        public LTVec Pos;
        public LTQuat Rot;
        public bool Removed { get; private set; }
        public bool TrackingLookAt { get; private set; }
        public bool AttachmentsHidden { get; private set; }

        // The level around it, set by its builder:
        // the position of the object with that id (FaceObject), null if unknown;
        public Func<int, LTVec?> PositionOf;
        // the TeleportPoint with that id: its position, rotation and MoveToFloor, null if the object isn't one;
        public Func<int, (LTVec pos, LTQuat rot, bool moveToFloor)?> TeleportPointOf;
        // the first hit of the world going from one point straight down to another: its height, null for none;
        public Func<LTVec, LTVec, float?> CastDown;
        // after it moved or turned (teleport, a turn);
        public Action Moved;
        // its attachments shown / hidden (HIDDEN);
        public Action<bool> ShowAttachments;
        // CAttachments::Attach(position, attachment) / Detach(position);
        public Action<string, string> Attach;
        public Action<string> Detach;
        // its head starts / stops tracking the player's Head;
        public Action<bool> Track;
        // its talk icon (AI_TALKICON) shows / goes.
        public Action<bool> TalkIcon;
        public bool TalkIconOn { get; private set; }
        // Where the talk icon stands, following it: cshell.dll 0x10169720 creates AI_TALKICON at the object's
        // dims with 10.0f (0x101e9364) added to y, over its origin: on top of its box.
        public const float TalkIconHeight = 10;
        public LTVec TalkIconPos => new LTVec(Pos.x, Pos.y + dims.y + TalkIconHeight, Pos.z);

        readonly List<Step> script = new List<Step>();
        int scriptStep;
        bool queuedScript;
        AnimateGoal goal;
        bool goalCurrent;
        StateStatus status;
        bool stateLoop;   // the flag the state's animation plays with

        int teleportPoint = -1;
        LTVec? teleportPos;

        bool rotating;
        LTQuat startRot, targetRot;
        float rotationTime = -1, rotationTimer;

        internal Actor(int id, CommandMgr commands, IActorAnimation anim, string idle, LTVec pos, LTQuat rot, LTVec dims)
        {
            Id = id;
            this.commands = commands;
            this.anim = anim;
            this.idle = idle ?? "";
            this.dims = dims;
            Pos = pos;
            Rot = rot;
            targetRot = rot;   // CAI::InitialUpdate: the target rotation starts as the object's
        }

        // Its GameBase REMOVE: it takes no more messages and stops updating.
        public void Remove() => Removed = true;

        readonly List<string> keys = new List<string>();

        // An animation key its animation crossed (MID_MODELSTRINGKEY), run in the next command frame (RunKeys).
        public void AnimationKey(string text)
        {
            if (!Removed) keys.Add(text);
        }

        // CCharacter::HandleModelString for each statement of each key: `CMD <command>` rebuilds the command from
        // its words (one holding a space in parentheses) and runs it if valid (IsValidCmd, Process) with the
        // character as sender and active target; `ATTACH <position> <name>` and `DETACH <position>` (those word
        // counts only) as the messages; `ON` / `OFF <object>` send that to the one object of the name. Its other
        // keys (FOOTSTEP_KEY, BUTE_SOUND_KEY, DEATHFX...) do nothing here.
        internal void RunKeys()
        {
            if (Removed) keys.Clear();
            for (int i = 0; i < keys.Count; i++)
                foreach (var words in ConParse.Statements(keys[i]))
                {
                    if (words.Length == 0) continue;
                    bool Is(string k) => string.Equals(words[0], k, StringComparison.OrdinalIgnoreCase);
                    if (Is("ATTACH") && words.Length == 3) Attach?.Invoke(words[1], words[2]);
                    else if (Is("DETACH") && words.Length == 2) Detach?.Invoke(words[1]);
                    else if ((Is("ON") || Is("OFF")) && words.Length == 2)
                    {
                        int o = FindNamed(words[1]);
                        if (o >= 0) commands.SendTo(Id, o, Is("ON") ? "ON" : "OFF");
                    }
                    else if (Is("CMD") && words.Length >= 2)
                    {
                        var parts = new string[words.Length - 1];
                        for (int w = 1; w < words.Length; w++)
                            parts[w - 1] = words[w].IndexOf(' ') >= 0 ? "(" + words[w] + ")" : words[w];
                        commands.Run(string.Join(" ", parts), Id, Id);
                    }
                    if (Removed) break;
                }
            keys.Clear();
        }

        internal bool OnMessage(Message m)
        {
            if (Removed) return false;
            if (m.Is("GOALSCRIPT")) { GoalScript(m); return true; }
            if (m.Is("TELEPORT"))
            {
                var arg = m.Arg(0);
                if (IsVector(arg))
                {
                    teleportPos = ParseVector(arg);
                    teleportPoint = -1;
                    return true;
                }
                int point = FindNamed(arg);
                if (point >= 0 && TeleportPointOf?.Invoke(point) != null)
                {
                    teleportPoint = point;
                    teleportPos = null;
                }
                return true;
            }
            if (m.Is("FACEOBJECT"))
            {
                int o = FindNamed(m.Arg(0));
                var p = o >= 0 ? PositionOf?.Invoke(o) : null;
                if (p.HasValue) FacePos(p.Value);
                return true;
            }
            if (m.Is("HIDDEN"))
            {
                if (m.ArgCount >= 1)
                {
                    AttachmentsHidden = IsTrueChar(m.Arg(0));
                    ShowAttachments?.Invoke(!AttachmentsHidden);
                }
                return false;   // GameBase takes it too
            }
            if (m.Is("ATTACH")) { Attach?.Invoke(m.Arg(0), m.Arg(1)); return true; }
            if (m.Is("DETACH")) { Detach?.Invoke(m.Arg(0)); return true; }
            if (m.Is("LISTENICON") || m.Is("SAYICON") || m.Is("ASKICON"))
            {
                bool on = IsTrueChar(m.Arg(0));
                if (on != TalkIconOn)
                {
                    TalkIconOn = on;
                    TalkIcon?.Invoke(on);
                }
                return true;
            }
            if (m.Is("TRACKLOOKAT")) { SetTracking(true); return true; }
            if (m.Is("TRACKNONE")) { SetTracking(false); return true; }
            return false;
        }

        // CAIGoalMgr::HandleCommand GOALSCRIPT.
        void GoalScript(Message m)
        {
            script.Clear();
            scriptStep = 0;
            int i = 1;
            while (i < m.Words.Length)
            {
                var name = m.Words[i];
                if (!KnownGoals.Contains(name)) return;   // "Invalid goal type": not queued
                var step = new Step { Goal = name };
                while (++i < m.Words.Length && m.Words[i].IndexOf('=') >= 0)
                {
                    var w = m.Words[i];
                    int eq = w.IndexOf('=');
                    step.Params.Add(new KeyValuePair<string, string>(w.Substring(0, eq), w.Substring(eq + 1)));
                }
                script.Add(step);
            }
            queuedScript = true;
        }

        // Once per AI update; frameTime: the server's frame time (s).
        public void Update(float frameTime)
        {
            if (Removed) return;
            UpdateTeleport();
            UpdateGoals();
            UpdatePosition(frameTime);
            // CAIHumanStateAnimate::Update: a once animation that is done completes the state.
            if (goal != null && goalCurrent && status == StateStatus.Initialized && !stateLoop && anim != null && anim.Done)
                status = StateStatus.Complete;
        }

        void UpdateGoals()
        {
            if (queuedScript) HandleGoalScript();
            if (goal != null && goalCurrent && goal.Importance <= 0)
            {
                // SetNextGoal(NULL): a scripted goal that ended advances the script; DeleteWhenDone; HumanIdle.
                if (goal.Scripted) scriptStep++;
                goal = null;
                goalCurrent = false;
                status = StateStatus.None;
                if (anim != null && idle.Length > 0) anim.Play(idle, true);
                if (script.Count > 0) HandleGoalScript();
                return;
            }
            if (goal != null && !goalCurrent)
            {
                // ActivateGoal: LockGoal, SetState(HumanAnimate); the state's Init turns node tracking off.
                goalCurrent = true;
                status = StateStatus.Initialized;
                SetTracking(false);
                rotating = false;
            }
            if (goal == null || !goalCurrent || goal.Importance <= 0) return;
            // CAIGoalAnimate::HandleStateAnimate.
            if (status == StateStatus.Initialized)
            {
                if (goal.ResetAnim)
                {
                    SetAnimation(goal.Anim, goal.Loop);
                    goal.ResetAnim = false;
                }
            }
            else if (status == StateStatus.Complete)
                goal.Importance = 0;
        }

        // CAIGoalMgr::HandleGoalScript: the step at the script's index (past the end: the script is cleared).
        void HandleGoalScript()
        {
            queuedScript = false;
            if (scriptStep >= script.Count)
            {
                script.Clear();
                scriptStep = 0;
                return;
            }
            var step = script[scriptStep];
            if (!string.Equals(step.Goal, "Animate", StringComparison.OrdinalIgnoreCase))
            {
                commands.Count("MSG", commands.Class(Id), "GOALSCRIPT " + step.Goal);
                return;
            }
            if (goal == null) goal = new AnimateGoal { Scripted = true };
            foreach (var p in step.Params)
            {
                if (string.Equals(p.Key, "ANIM", StringComparison.OrdinalIgnoreCase))
                {
                    goal.Anim = p.Value;
                    goal.ResetAnim = true;
                }
                else if (string.Equals(p.Key, "LOOP", StringComparison.OrdinalIgnoreCase))
                {
                    goal.Loop = IsTrueChar(p.Value);
                    goal.ResetAnim = true;
                }
            }
        }

        // CAIHumanStateAnimate::SetAnimation -> CAnimationContext::SetSpecial: the name, else DXBLoop, else the
        // animation playing starts over with the new flag.
        void SetAnimation(string name, bool loop)
        {
            stateLoop = loop;
            if (anim == null) return;
            if (anim.Has(name)) anim.Play(name, loop);
            else if (anim.Has(MissingAnimation)) anim.Play(MissingAnimation, loop);
            else anim.Restart(loop);
        }

        void UpdateTeleport()
        {
            if (teleportPos.HasValue)
            {
                Pos = teleportPos.Value;
                teleportPos = null;
                Moved?.Invoke();
                return;
            }
            if (teleportPoint < 0) return;
            var p = TeleportPointOf?.Invoke(teleportPoint);
            teleportPoint = -1;
            if (!p.HasValue) return;
            Pos = p.Value.pos;
            Rot = p.Value.rot;
            if (p.Value.moveToFloor)
            {
                // CAIHuman::FindFloorHeight.
                var from = new LTVec(Pos.x, Pos.y + dims.y, Pos.z);
                var to = new LTVec(Pos.x, Pos.y - 10 * dims.y, Pos.z);
                var hit = CastDown?.Invoke(from, to);
                if (hit.HasValue) Pos.y = hit.Value + dims.y;
            }
            Moved?.Invoke();
        }

        // CAI::FacePos(pos, ROTATION_SPEED_STATIC).
        void FacePos(LTVec target)
        {
            var dir = target - Pos;
            dir.y = 0;
            if (dir.x * dir.x + dir.z * dir.z < 1) return;
            dir = dir / dir.Length();
            var tf = targetRot.Forward();
            var f = Rot.Forward();
            float dpTarget = Dot(dir, tf), dpForward = Dot(dir, f);
            if (rotating && Math.Abs(dpTarget) > FacingThreshold) return;
            rotating = true;
            startRot = Rot;
            targetRot = LTQuat.FromForwardUp(dir, new LTVec(0, 1, 0));
            if (dpForward >= FacingThreshold) return;
            if (dpForward < -1) dpForward = -1;
            rotationTime = (float)(Math.Acos(dpForward) / Math.PI) * RotationSpeedStatic;
            rotationTimer = 0;
        }

        // CAI::UpdatePosition: the turn, eased by sqrt (CAIHuman::GetRotationInterpolation).
        void UpdatePosition(float frameTime)
        {
            if (rotationTimer < rotationTime)
            {
                rotationTimer = Math.Min(rotationTime, rotationTimer + frameTime);
                Rot = LTQuat.Slerp(startRot, targetRot, (float)Math.Sqrt(rotationTimer / rotationTime));
                Moved?.Invoke();
            }
            else rotating = false;
        }

        void SetTracking(bool on)
        {
            if (TrackingLookAt == on) return;
            TrackingLookAt = on;
            Track?.Invoke(on);
        }

        // FindNamedObject: the one object with the name (none or several: -1).
        int FindNamed(string name)
        {
            var ids = commands.Named(name);
            return ids.Count == 1 ? ids[0] : -1;
        }

        static float Dot(LTVec a, LTVec b) => a.x * b.x + a.y * b.y + a.z * b.z;

        // IsTrueChar: the value's first character is t, T, y, Y or 1.
        public static bool IsTrueChar(string v) => !string.IsNullOrEmpty(v) && "tTyY1".IndexOf(v[0]) >= 0;

        // IsVector: no letters (an empty word isn't one here).
        static bool IsVector(string s)
        {
            if (string.IsNullOrEmpty(s)) return false;
            foreach (var c in s)
                if (char.IsLetter(c)) return false;
            return true;
        }

        static LTVec ParseVector(string s)
        {
            var p = s.Split(',');
            float F(int i) => i < p.Length && float.TryParse(p[i], NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v : 0;
            return new LTVec(F(0), F(1), F(2));
        }
    }

    // The level's actors: each joins after its first-update queue and before its GameBase handler, and
    // updates once per frame after Characters.
    public sealed class Actors
    {
        readonly CommandMgr commands;
        readonly List<Actor> all = new List<Actor>();

        public Actors(CommandMgr commands) { this.commands = commands; }

        public IReadOnlyList<Actor> All => all;

        // Character `id`, drawn with `anim` (null: nothing drawn), whose idle is `idle`, standing at pos / rot,
        // its model's dims (half-extents, LT units).
        public Actor Add(int id, IActorAnimation anim, string idle, LTVec pos, LTQuat rot, LTVec dims)
        {
            var a = new Actor(id, commands, anim, idle, pos, rot, dims);
            commands.Handle(id, a.OnMessage);
            all.Add(a);
            return a;
        }

        public void Update(float frameTime)
        {
            foreach (var a in all) a.Update(frameTime);
        }

        // The animation keys the animations crossed since the last command frame, after the actors' updates.
        public void RunKeys()
        {
            for (int i = 0; i < all.Count; i++) all[i].RunKeys();
        }
    }
}
