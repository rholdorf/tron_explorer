using System;
using System.Collections.Generic;

// ScreenShake objects and the view's shake (docs/research/screen-shake-iocam.md on research/screen-shake-iocam).
// Plain C#, no Unity, so tools/tests/test_screen_shake.py compiles it with .NET; LevelBuilder.ScreenShake.cs joins
// the level's objects and CameraJitter puts the shake on the view.
namespace Tron
{
    // A ScreenShake's props (BEGIN_CLASS defaults).
    public sealed class ScreenShakeProps
    {
        public LTVec Amount = new LTVec(1, 1, 1);
        public int NumShakes = -1;
        public float Frequency = 1;
        public float AreaOfEffect = ScreenShakes.EntireLevel;
        public string ShakeSound = "";
        public float SoundRadius = 500;
    }

    // The level's ScreenShake objects (ltjs screenshake.cpp; Tron's object.lto the same): server timers that send
    // shake pulses to the player's client. Idle at load (no StartOn). ON: an update on the next frame, even with
    // one pending; OFF: no next update (the count stays). Each update counts NumShakes down first and schedules
    // another Frequency seconds later only while it is still above 0 (so -1, "infinite", and any count used up
    // give one pulse per ON), plays ShakeSound at the object, and sends Amount to the player when the player
    // object is within AreaOfEffect (-1: anywhere). Anything else goes to GameBase.
    public sealed class ScreenShakes
    {
        public const float EntireLevel = -1;        // c_fENTIRE_LEVEL
        public const float NextFrame = 0.001f;      // UPDATE_NEXT_FRAME as Tron sets it

        readonly CommandMgr commands;
        readonly List<ScreenShake> shakes = new List<ScreenShake>();

        // Where the player object is (LT units), null when there is none.
        public Func<LTVec?> PlayerPos;
        // PlaySoundFromPos(pos, sound, radius): a soundbute name or a file, 3D at the object.
        public Action<LTVec, string, float> PlaySound;
        // MID_SHAKE_SCREEN to the player's client (CameraShake.Add).
        public Action<LTVec> ShakeScreen;

        public ScreenShakes(CommandMgr commands) => this.commands = commands;

        // A ScreenShake at `pos`; give it its messages with Commands.Handle(id, shake.OnMessage). Its GameBase
        // handler takes none of its words (ON, OFF), so either may come first (LevelBuilder joins the flags first,
        // as LevelBuilder.Messages.cs does).
        public ScreenShake Add(LTVec pos, ScreenShakeProps props)
        {
            var s = new ScreenShake(this, pos, props);
            shakes.Add(s);
            return s;
        }

        internal float Now => commands.Time;

        // Each server frame, after the command table: the shakes whose update time came.
        public void Update()
        {
            float now = Now;
            foreach (var s in shakes) s.Update(now);
        }

        internal void Pulse(ScreenShake s)
        {
            var p = s.Props;
            if (!string.IsNullOrEmpty(p.ShakeSound)) PlaySound?.Invoke(s.Pos, p.ShakeSound, p.SoundRadius);
            var player = PlayerPos?.Invoke();
            if (player == null) return;
            if (p.AreaOfEffect == EntireLevel || LTVec.Dist(player.Value, s.Pos) <= p.AreaOfEffect) ShakeScreen?.Invoke(p.Amount);
        }
    }

    public sealed class ScreenShake
    {
        readonly ScreenShakes owner;
        internal readonly LTVec Pos;
        internal readonly ScreenShakeProps Props;
        int left;
        float next = float.NaN;   // the next update's time; NaN: none (UPDATE_NEVER)

        internal ScreenShake(ScreenShakes owner, LTVec pos, ScreenShakeProps props)
        {
            this.owner = owner;
            Pos = pos;
            Props = props;
            left = props.NumShakes;
        }

        public bool OnMessage(Message m)
        {
            if (m.Is("ON")) next = owner.Now + ScreenShakes.NextFrame;
            else if (m.Is("OFF")) next = float.NaN;
            else return false;
            return true;
        }

        internal void Update(float now)
        {
            if (!(now >= next)) return;
            next = --left > 0 ? now + Props.Frequency : float.NaN;
            owner.Pulse(this);
        }
    }

    // The client's screen shake (ltjs playermgr.cpp; Tron's cshell.dll the same): pulses add up, each axis clamped
    // at 10; every frame each axis drops by twice the frame time (not below 0) and, while any is above 0, the
    // camera's position moves by random(-1, 1) x axis x 3 on each world axis (LT units), a new random each frame,
    // unless that move is under 0.1 units. The camera is put back each frame (CameraJitter), so moves don't build up.
    public sealed class CameraShake
    {
        public const float MaxShake = 10, Decay = 2, Scale = 3, MinMove2 = 0.01f;

        readonly Func<double> random;
        public LTVec Amount { get; private set; }

        // random: uniform in [0, 1) (GetRandom); System.Random when null.
        public CameraShake(Func<double> random = null)
        {
            if (random == null)
            {
                var r = new Random();
                random = r.NextDouble;
            }
            this.random = random;
        }

        // ShakeScreen: a pulse.
        public void Add(LTVec v)
        {
            var s = Amount + v;
            Amount = new LTVec(Math.Min(s.x, MaxShake), Math.Min(s.y, MaxShake), Math.Min(s.z, MaxShake));
        }

        // UpdateCameraShake then UpdateCameraDisplacement: this frame's move of the view (LT units, world axes).
        public LTVec Update(float frameTime)
        {
            float d = frameTime * Decay;
            var s = Amount;
            Amount = s = new LTVec(Math.Max(0, s.x - d), Math.Max(0, s.y - d), Math.Max(0, s.z - d));
            if (s.x <= 0 && s.y <= 0 && s.z <= 0) return default;
            var move = new LTVec(Rand() * s.x * Scale, Rand() * s.y * Scale, Rand() * s.z * Scale);
            return move.x * move.x + move.y * move.y + move.z * move.z < MinMove2 ? default : move;
        }

        float Rand() => (float)(random() * 2 - 1);
    }
}
