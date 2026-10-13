using System;

// Doors, switches and the sliding/rotating world models: the engine's ActiveWorldModel state machine
// (ltjs activeworldmodel.cpp, door.cpp; docs/research/triggers-doors.md). Plain C#, no Unity, so
// tools/tests/test_active_world_models.py compiles it with Mono. Positions and times in LT units and
// seconds; the host (ActiveWorldModelObject in the viewer) shows the pose, plays the sounds, runs the
// commands and answers whether the player is in the way.
namespace Tron
{
    public sealed class ActiveWorldModel
    {
        public enum State { Off, PowerOn, On, PowerOff, Pause }
        public enum Kind { Static = 0, Sliding = 1, Rotating = 2 }   // AWMType

        // A level object's properties as ReadProps sees them (missing ones read as false, 0, "", zero).
        public interface IProps
        {
            bool Bool(string key);
            float Num(string key);
            string Str(string key);
            LTVec Vec(string key);
        }

        // What the state machine needs from the world.
        public interface IHost
        {
            float Time { get; }                        // the server time, this frame's
            void PlaySound(string name, bool loop);    // from the object, 3D, SoundRadius
            void StopLoop();                           // kills the looping sound last started
            void Run(string command, int activator);   // through the command manager, the AWM as sender
            bool PlayerInside(LTVec pos, LTQuat rot);  // would the player intersect it at this pose?
            LTVec? PositionOf(int obj);                // an object's position (the player's live one)
        }

        public sealed class Settings
        {
            public Kind Type;
            public bool Door;
            public bool PlayerActivate, StartOn, TriggerOff, RemainOn, ForceMove, ForceMoveOn, ForceMoveOff,
                Locked, RotateAway, LoopSounds;
            public int Waveform;   // tools/waveform.py: 0 Linear, 1 Sine, 2 SlowOff, 3 SlowOn
            public string PowerOnSound = "", OnSound = "", PowerOffSound = "", OffSound = "", LockedSound = "";
            public string PowerOnCommand = "", OnCommand = "", PowerOffCommand = "", OffCommand = "", LockedCommand = "";
            public LTVec MoveDir, RotationAngles;   // MoveDir in the object's own frame; angles in degrees
            public float MoveDist, PowerOnTime, PowerOffTime, MoveDelay, OnWaitTime, OffWaitTime, SoundRadius;
            public string RotationPoint = "", DoorLink = "", ActivateType = "";

            static readonly string[] Waves = { "Linear", "Sine", "SlowOff", "SlowOn" };

            // ActiveWorldModel::ReadProps + PostReadProp; doors (SlidingDoor, RotatingDoor) then Door::ReadProps
            // over them, with their own names.
            public static Settings Read(string cls, IProps p)
            {
                bool door = cls != null && cls.EndsWith("Door", StringComparison.OrdinalIgnoreCase);
                var s = new Settings
                {
                    Type = (Kind)(int)p.Num("AWMType"), Door = door,
                    PlayerActivate = p.Bool("PlayerActivate"), StartOn = p.Bool("StartOn"),
                    TriggerOff = p.Bool("TriggerOff"), RemainOn = p.Bool("RemainOn"), ForceMove = p.Bool("ForceMove"),
                    ForceMoveOn = p.Bool("ForceMoveOn"), ForceMoveOff = p.Bool("ForceMoveOff"), Locked = p.Bool("Locked"),
                    RotateAway = p.Bool("RotateAway"), LoopSounds = p.Bool("LoopSounds"),
                    Waveform = Math.Max(0, Array.FindIndex(Waves, w => string.Equals(w, p.Str("Waveform"), StringComparison.OrdinalIgnoreCase))),
                    PowerOnSound = p.Str("PowerOnSound"), OnSound = p.Str("OnSound"), PowerOffSound = p.Str("PowerOffSound"),
                    OffSound = p.Str("OffSound"), LockedSound = p.Str("LockedSound"),
                    PowerOnCommand = p.Str("PowerOnCommand"), OnCommand = p.Str("OnCommand"),
                    PowerOffCommand = p.Str("PowerOffCommand"), OffCommand = p.Str("OffCommand"), LockedCommand = p.Str("LockedCommand"),
                    MoveDir = p.Vec("MoveDir"), MoveDist = p.Num("MoveDist"), PowerOnTime = p.Num("PowerOnTime"),
                    PowerOffTime = p.Num("PowerOffTime"), MoveDelay = p.Num("MoveDelay"), OnWaitTime = p.Num("OnWaitTime"),
                    OffWaitTime = p.Num("OffWaitTime"), RotationAngles = p.Vec("RotationAngles"),
                    RotationPoint = p.Str("RotationPoint"), SoundRadius = p.Num("SoundRadius"),
                };
                if (s.MoveDir.x * s.MoveDir.x + s.MoveDir.y * s.MoveDir.y + s.MoveDir.z * s.MoveDir.z < 0.0001f)
                    s.MoveDir = new LTVec(0, 1, 0);
                if (door)
                {
                    s.StartOn = p.Bool("StartOpen");
                    s.TriggerOff = p.Bool("TriggerClose");
                    s.RemainOn = p.Bool("RemainOpen");
                    s.RotateAway = p.Bool("OpenAway");
                    s.PowerOnSound = Or(p.Str("OpeningSound"), s.PowerOnSound);
                    s.OnSound = Or(p.Str("OpenSound"), s.OnSound);
                    s.PowerOffSound = Or(p.Str("ClosingSound"), s.PowerOffSound);
                    s.OffSound = Or(p.Str("ClosedSound"), s.OffSound);
                    s.OnCommand = Or(p.Str("OpenCommand"), s.OnCommand);
                    s.OffCommand = Or(p.Str("ClosedCommand"), s.OffCommand);
                    s.PowerOnCommand = Or(p.Str("OpeningCommand"), s.PowerOnCommand);
                    s.PowerOffCommand = Or(p.Str("ClosingCommand"), s.PowerOffCommand);
                    s.PowerOnTime = p.Num("OpeningTime");
                    s.PowerOffTime = p.Num("ClosingTime");
                    s.OnWaitTime = p.Num("OpenWaitTime");
                    s.OffWaitTime = p.Num("CloseWaitTime");
                    s.DoorLink = p.Str("DoorLink");
                }
                if (s.PlayerActivate) s.ActivateType = p.Str("ActivateType");
                if (s.PowerOffTime <= 0) s.PowerOffTime = s.PowerOnTime;
                return s;
            }

            static string Or(string a, string b) => string.IsNullOrEmpty(a) ? b : a;
        }

        const float NextFrame = 0.001f;   // UPDATE_NEXT_FRAME
        const float Never = float.PositiveInfinity;

        readonly Settings settings;
        readonly IHost host;
        readonly int self;
        readonly LTQuat initRot;
        readonly LTVec moveDir, initOnAngles, initRotDir, rotPtOffset;
        LTVec originalPos, offPos, onPos, pausePos, rotationPt;
        LTVec offAngles, onAngles, rotateDir;
        float pitch, yaw, roll;   // turned so far from the placed rotation (radians)
        float moveStartTm = -10, moveStopTm = -10, curTm, powerOnMultiplier = 1, nextUpdate = Never, frameTime;
        bool loopPlaying;
        State lastState;

        public State Current { get; private set; } = State.Off;
        public LTVec Pos { get; set; }   // the object's position; a keyframer may move it
        public LTQuat Rot => initRot * LTQuat.FromEuler(pitch, yaw, roll);
        public bool Locked { get; private set; }
        public int Activator { get; private set; } = -1;   // m_hActivateObj
        public ActiveWorldModel Link;                       // DoorLink, resolved by the host
        public int Player { get; set; }                     // the player's command-manager id
        public bool CanBeUsed => settings.PlayerActivate;   // the player's use drives it
        public bool IsDoor => settings.Door;
        public string DoorLink => settings.DoorLink;        // the name of the door it opens too ("" for none)
        public float SoundRadius => settings.SoundRadius;
        // The use prompt's state (ActivateTypeHandler): on while on or powering on.
        public bool PromptOn => Current == State.On || Current == State.PowerOn || (Current == State.Pause && (lastState == State.PowerOn));

        // pos, pyr: the placed position and rotation (radians); rotationPoint: the RotationPoint object's
        // position, null for none. self, player: command-manager ids of the AWM and of the player.
        public ActiveWorldModel(Settings s, LTVec pos, LTVec pyr, LTVec? rotationPoint, int self, int player, IHost host)
        {
            settings = s;
            this.host = host;
            this.self = self;
            Player = player;
            Locked = s.Locked;
            Pos = originalPos = offPos = pos;
            initRot = LTQuat.FromEuler(pyr.x, pyr.y, pyr.z);
            if (s.Type == Kind.Sliding)
            {
                var d = initRot.Rotate(s.MoveDir);
                moveDir = d / d.Length();
            }
            else moveDir = s.MoveDir;
            onPos = offPos + moveDir * s.MoveDist;
            if (s.Type == Kind.Rotating)
            {
                const float rad = (float)(Math.PI / 180);
                onAngles = s.RotationAngles * rad;
                rotateDir = new LTVec(Dir(-onAngles.x), Dir(-onAngles.y), Dir(-onAngles.z));
                initOnAngles = onAngles;
                initRotDir = rotateDir;
            }
            rotationPt = rotationPoint ?? pos;
            rotPtOffset = originalPos - rotationPt;
        }

        // OnObjectCreated: the direction to turn an axis (off - on past one degree turns down, else up).
        static float Dir(float offset) => offset > (float)(Math.PI / 180) ? -1 : 1;

        // The end of OnObjectCreated, once every object exists: power on, or sit off silently.
        public void Start()
        {
            if (settings.StartOn) SetPowerOn();
            else SetOff(true);
        }

        // ---- Messages ----

        // OnTrigger (and Door::OnTrigger): true if it handled the message.
        public bool Handle(Message m)
        {
            if (m.Is("ACTIVATE")) Activate(m.Sender);
            else if (m.Is("TRIGGER")) HandleTriggerMsg();
            else if (m.Is("LOCK")) Locked = true;
            else if (m.Is("UNLOCK")) Locked = false;
            else if (m.Is("ON"))
            {
                if (Current == State.Off || Current == State.PowerOff) { Activator = m.Sender; HandleTriggerMsg(); }
            }
            else if (m.Is("OFF"))
            {
                if (Current == State.On || Current == State.PowerOn) { Activator = m.Sender; HandleTriggerMsg(); }
            }
            else if (m.Is("SETPOWERONMULTIPLIER"))
            {
                if (m.ArgCount > 0) powerOnMultiplier = CommandMgr.Atof(m.Arg(0));
            }
            else if (m.Is("PAUSE")) HandlePause();
            else if (m.Is("RESUME")) HandleResume();
            else if (settings.Door && m.Is("TRIGGERCLOSE")) TriggerClose();
            else return false;
            return true;
        }

        // ActiveWorldModel::Activate: the player's use. Only characters activate; the player needs
        // PlayerActivate. Tron's permission-set gate always passes: the viewer grants every set.
        public void Activate(int obj)
        {
            if (obj < 0 || obj != Player || !settings.PlayerActivate) return;
            Activator = obj;
            HandleTriggerMsg();
        }

        void HandleTriggerMsg()
        {
            if (settings.Door) HandleLinkTriggerMsg(true);
            else BaseTriggerMsg();
        }

        void BaseTriggerMsg()
        {
            if (Locked)
            {
                // No key controls anything in Tron: locked is locked.
                StartSound(settings.LockedSound, false);
                RunCommand(settings.LockedCommand);
                return;
            }
            float now = host.Time;
            switch (Current)
            {
                case State.Off:
                    if (now >= moveStopTm + settings.OffWaitTime) SetPowerOn();
                    break;
                case State.PowerOff:
                case State.PowerOn:
                    ChangeDir();
                    break;
                case State.On:
                    if (settings.TriggerOff)
                    {
                        if (now >= moveStopTm + settings.OnWaitTime) SetPowerOff();
                    }
                    else SetOn(true);   // re-arms the auto-off
                    break;
            }
        }

        // Door::HandelLinkTriggerMsg: a door that starts opening triggers its linked door (one hop).
        void HandleLinkTriggerMsg(bool triggerLink)
        {
            BaseTriggerMsg();
            if (Locked) return;
            if (triggerLink && Current == State.PowerOn && Link != null) Link.TriggerLink(Activator);
        }

        void TriggerLink(int activator)
        {
            Activator = activator;
            if (Current == State.Off || Current == State.PowerOff) HandleLinkTriggerMsg(false);
        }

        void TriggerClose()
        {
            if ((Current == State.On || Current == State.PowerOn) && host.Time > moveStopTm + settings.OnWaitTime) SetPowerOff();
        }

        void HandlePause()
        {
            if (Current != State.PowerOn && Current != State.PowerOff) return;
            lastState = Current;
            Current = State.Pause;
            pausePos = Pos;
        }

        void HandleResume()
        {
            if (Current != State.Pause) return;
            Current = lastState;
            // Moved while paused (a keyframer): move the ends with it.
            var delta = pausePos - Pos;
            originalPos -= delta;
            offPos -= delta;
            onPos -= delta;
        }

        // ---- States ----

        void SetPowerOn()
        {
            if (Current == State.Off)
            {
                originalPos = offPos = Pos;
                onPos = offPos + moveDir * settings.MoveDist;
            }
            if (settings.Type == Kind.Rotating)
            {
                if (Current == State.Off) rotationPt = originalPos - rotPtOffset;
                if (settings.RotateAway && Activator >= 0 && host.PositionOf(Activator) is LTVec objPos)
                {
                    // Open away from the activator: whichever way ends farther from it (a one-radian turn
                    // each way; the roll's sign follows the yaw's, as in the engine).
                    float p0 = pitch, y0 = yaw, r0 = roll;
                    pitch = Sign(initOnAngles.x); yaw = Sign(initOnAngles.y); roll = initOnAngles.z == 0 ? 0 : Sign(initOnAngles.y);
                    var test1 = RotatedPos();
                    pitch = -Sign(initOnAngles.x); yaw = -Sign(initOnAngles.y); roll = initOnAngles.z == 0 ? 0 : -Sign(initOnAngles.y);
                    var test2 = RotatedPos();
                    pitch = p0; yaw = y0; roll = r0;
                    if (Dist2(test1, objPos) < Dist2(test2, objPos))
                    {
                        onAngles = -initOnAngles;
                        rotateDir = -initRotDir;
                    }
                    else
                    {
                        onAngles = initOnAngles;
                        rotateDir = initRotDir;
                    }
                }
            }
            StartSound(settings.PowerOnSound, settings.LoopSounds);
            nextUpdate = host.Time + NextFrame;
            Current = State.PowerOn;
            RunCommand(settings.PowerOnCommand);
            moveStartTm = host.Time + settings.MoveDelay;
            curTm = 0;
        }

        void SetOn(bool initialize = false)
        {
            nextUpdate = settings.TriggerOff || settings.RemainOn ? Never : host.Time + settings.OnWaitTime + NextFrame;
            Current = State.On;
            powerOnMultiplier = 1;
            if (initialize) return;
            StartSound(settings.OnSound, settings.LoopSounds);
            RunCommand(settings.OnCommand);
            moveStopTm = host.Time;
        }

        void SetPowerOff()
        {
            if (Current == State.On)
            {
                onPos = Pos;
                offPos = onPos - moveDir * settings.MoveDist;
            }
            StartSound(settings.PowerOffSound, settings.LoopSounds);
            nextUpdate = host.Time + NextFrame;
            Current = State.PowerOff;
            RunCommand(settings.PowerOffCommand);
            moveStartTm = host.Time + settings.MoveDelay;
            curTm = 0;
        }

        void SetOff(bool initialize = false)
        {
            nextUpdate = Never;
            Current = State.Off;
            if (initialize) return;
            if (settings.Type == Kind.Rotating)
            {
                onAngles = initOnAngles;
                rotateDir = initRotDir;
            }
            StartSound(settings.OffSound, settings.LoopSounds);
            RunCommand(settings.OffCommand);
            moveStopTm = host.Time;
        }

        // ---- Update ----

        // One server frame: the host's Time already includes it.
        public void Update(float dt)
        {
            frameTime = dt;
            float now = host.Time;
            if (now < nextUpdate) return;
            nextUpdate = now + NextFrame;
            switch (Current)
            {
                case State.On: SetPowerOff(); break;   // UpdateOn: the auto-off
                case State.PowerOn: UpdatePowerOn(now); break;
                case State.PowerOff: UpdatePowerOff(now); break;
                case State.Off: nextUpdate = Never; break;
            }
        }

        void UpdatePowerOn(float now)
        {
            if (now < moveStartTm) return;
            float total = settings.PowerOnTime * powerOnMultiplier;
            float percent = total > 0.001f ? Clamp01(curTm / total) : 1;
            Step(onPos, offAngles, onAngles, rotateDir, total, percent, !settings.ForceMove && !settings.ForceMoveOn, SetOnDone);
        }

        // Power-off checks the delay against a start that already includes it: it waits twice MoveDelay.
        void UpdatePowerOff(float now)
        {
            if (now < moveStartTm + settings.MoveDelay) return;
            float total = settings.PowerOffTime;
            float percent = total > 0.001f ? Clamp01(curTm / total) : 1;
            Step(offPos, onAngles, offAngles, -rotateDir, total, percent, !settings.ForceMove && !settings.ForceMoveOff, SetOffDone);
        }

        void SetOnDone() => SetOn();
        void SetOffDone() => SetOff();

        // One frame of motion toward an end; arrival enters the next state. A step that would hit the
        // player isn't taken (the clock doesn't advance either): the door waits.
        void Step(LTVec finalPos, LTVec from, LTVec finalAngles, LTVec dir, float total, float percent, bool testCollision, Action arrive)
        {
            float p0 = pitch, y0 = yaw, r0 = roll;
            bool dx = CalcAngle(ref pitch, from.x, finalAngles.x, dir.x, total, percent);
            bool dy = CalcAngle(ref yaw, from.y, finalAngles.y, dir.y, total, percent);
            bool dz = CalcAngle(ref roll, from.z, finalAngles.z, dir.z, total, percent);
            if (!NewPos(finalPos, total, percent, testCollision, out var newPos))
            {
                pitch = p0; yaw = y0; roll = r0;
                return;
            }
            Pos = newPos;
            if ((settings.Type == Kind.Sliding && newPos == finalPos) || (settings.Type == Kind.Rotating && dx && dy && dz)) arrive();
            curTm += frameTime;
        }

        // CalcAngle: one frame's turn of an axis toward its target; true once it was already there.
        bool CalcAngle(ref float angle, float initial, float target, float dir, float total, float percent)
        {
            if (settings.Type != Kind.Rotating) return true;
            if (percent >= 1) { angle = target; return true; }
            float rate = target - initial;
            if (total > 0.001f) rate /= total;
            float amount = Wave(rate, percent) * frameTime;
            if (dir == 0) return true;
            if (dir > 0)
            {
                if (angle < target) { angle += amount; if (angle > target) angle = target; return false; }
            }
            else if (angle > target) { angle += amount; if (angle < target) angle = target; return false; }
            angle = target;
            return true;
        }

        // CalculateNewPosRot: the position for the current angles (rotating) or one frame along the way
        // (sliding); false if the new pose would hit the player.
        bool NewPos(LTVec finalPos, float total, float percent, bool testCollision, out LTVec pos)
        {
            if (settings.Type == Kind.Rotating) pos = RotatedPos();
            else if (settings.Type == Kind.Sliding)
            {
                var d = finalPos - Pos;
                float left = d.Length();
                float rate = total > 0.001f ? settings.MoveDist / total : settings.MoveDist;
                float move = Wave(rate, percent) * frameTime;
                pos = move >= left || percent >= 1 ? finalPos : Pos + d / left * move;
                if (settings.MoveDist == 0) return true;
            }
            else pos = Pos;
            return !testCollision || !HitsPlayer(pos, Rot, false);
        }

        // The position when turned by (pitch, yaw, roll) about the rotation point, in the placed frame.
        LTVec RotatedPos()
        {
            var turn = initRot * LTQuat.FromEuler(pitch, yaw, roll) * initRot.Conjugate();
            return turn.Rotate(rotPtOffset) + rotationPt;
        }

        // TestObjectCollision against the player only (no test object), or against the activator.
        // Rotating: a player it would turn away from (the activator's case) doesn't count.
        bool HitsPlayer(LTVec pos, LTQuat rot, bool activatorOnly)
        {
            if (activatorOnly && Activator != Player) return false;
            if (!host.PlayerInside(pos, rot)) return false;
            if (settings.Type != Kind.Rotating) return true;
            if (!activatorOnly && Activator != Player) return true;
            var p = host.PositionOf(Player) ?? pos;
            return !(Dist2(p, Pos) <= Dist2(p, pos));
        }

        // ChangeDir: reverse, unless forced to finish or reversing would hit the activator.
        void ChangeDir()
        {
            if (settings.ForceMove) return;
            if (Current == State.PowerOn && settings.ForceMoveOn) return;
            if (Current == State.PowerOff && settings.ForceMoveOff) return;
            if (Activator >= 0 && TestPose(out var pos, out var rot) && HitsPlayer(pos, rot, true)) return;
            if (Current == State.PowerOff) SetPowerOn();
            else if (Current == State.PowerOn) SetPowerOff();
        }

        // GetTestPosRot: a step back the other way, at 10% of its move.
        bool TestPose(out LTVec pos, out LTQuat rot)
        {
            float p0 = pitch, y0 = yaw, r0 = roll;
            LTVec final;
            float time;
            if (Current == State.PowerOn)
            {
                final = offPos;
                time = settings.PowerOffTime;
                CalcAngle(ref pitch, pitch, offAngles.x, -rotateDir.x, time, 0.1f);
                CalcAngle(ref yaw, yaw, offAngles.y, -rotateDir.y, time, 0.1f);
                CalcAngle(ref roll, roll, offAngles.z, -rotateDir.z, time, 0.1f);
            }
            else if (Current == State.PowerOff)
            {
                final = onPos;
                time = settings.PowerOnTime;
                CalcAngle(ref pitch, pitch, onAngles.x, rotateDir.x, time, 0.1f);
                CalcAngle(ref yaw, yaw, onAngles.y, rotateDir.y, time, 0.1f);
                CalcAngle(ref roll, roll, onAngles.z, rotateDir.z, time, 0.1f);
            }
            else
            {
                pos = Pos;
                rot = Rot;
                return false;
            }
            NewPos(final, time, 0.1f, false, out pos);
            rot = Rot;
            pitch = p0; yaw = y0; roll = r0;
            return true;
        }

        // GetWaveformValue: the speed at `percent` of a move whose average speed is `rate`.
        float Wave(float rate, float percent)
        {
            const float halfPi = (float)(Math.PI / 2);
            switch (settings.Waveform)
            {
                case 1: return halfPi * rate * (float)Math.Sin(percent * Math.PI);
                case 2: return halfPi * rate * (float)Math.Cos(percent * halfPi) - rate * 0.001f;
                case 3: return halfPi * rate * (float)Math.Sin(percent * halfPi) + rate * 0.001f;
                default: return rate;
            }
        }

        // ---- Sounds and commands ----

        // StartSound: stops the looping sound it started last (a one-shot plays out), then plays this one.
        void StartSound(string name, bool loop)
        {
            if (loopPlaying) host.StopLoop();
            loopPlaying = false;
            if (string.IsNullOrEmpty(name)) return;
            host.PlaySound(name, loop);
            loopPlaying = loop;
        }

        void RunCommand(string command)
        {
            if (!string.IsNullOrEmpty(command)) host.Run(command, Activator);
        }

        static float Sign(float v) => v == 0 ? 0 : v > 0 ? 1 : -1;
        static float Dist2(LTVec a, LTVec b) { var d = a - b; return d.x * d.x + d.y * d.y + d.z * d.z; }
        static float Clamp01(float v) => v < 0 ? 0 : v > 1 ? 1 : v;
    }
}
