using System;

namespace Tron
{
    // A spinner as the engine runs it (ltjs spinningworldmodel.cpp over activeworldmodel.cpp; tools/spinner.py):
    // its on / off state machine, the messages that drive it and the spin it gives its world model. Plain C#,
    // no Unity, so tools/tests/test_object_messages.py compiles it with Mono; Spinner.cs turns the world model.
    //
    // States (AWM_STATE_*): Off, PowerOn (spinning up), On (full speed), PowerOff (spinning down), Pause.
    // StartOn powers on at creation, else the spinner starts Off. One Update is one server frame.
    // - PowerOn (UpdatePowerOn): each axis' velocity grows by GetWaveformValue(final / PowerOnTime, p) x the
    //   frame time, p = (time - start) / PowerOnTime, until it reaches |final| (retail object.lto 0x1022ab60
    //   compares with |final| where ltjs uses final) or p > 1 (then final); then On, running OnCommand.
    // - PowerOff (UpdatePowerOff, ltjs): the velocity shrinks by GetWaveformValue(final / PowerOffTime, p) x
    //   the frame time until it is under MATH_EPSILON (a negative speed stops at once) or p > 1; then Off,
    //   running OffCommand.
    // - Every state but Off and Pause turns the angles by velocity x the time since the last turn
    //   (SpinningWorldModel::UpdateOn), so the first turn after a stop covers the whole stop at the new speed.
    //   A spinner blocked by an object stops unless ForceMove; that reacts to the player, so it isn't done.
    // Messages (ActiveWorldModel::OnTrigger): ON (from Off or PowerOff) and OFF (from On or PowerOn) both go
    // through HandleTriggerMsg, as TRIGGER does: Off powers on once OffWaitTime has passed since it stopped;
    // PowerOn / PowerOff turn back (ChangeDir, unless ForceMove / ForceMoveOn / ForceMoveOff); On powers off
    // only with TriggerOff (once OnWaitTime has passed), else it stays on. Locked: LockedCommand runs and
    // nothing moves (docs/research/triggers-doors.md: Locked blocks messages). LOCK / UNLOCK set it.
    // PAUSE (only while powering on or off) freezes the spinner; RESUME continues. PowerOnCommand and
    // PowerOffCommand run when the spin-up or spin-down starts. Sounds (PowerOnSound...) are left out.
    public sealed class SpinnerMotion
    {
        public enum State { On = 1, PowerOn, Off, PowerOff, Pause }

        public sealed class Settings
        {
            public LTVec Final;                     // rad/s per axis (pitch, yaw, roll)
            public float PowerOnTime = 1, PowerOffTime = 1, MoveDelay, OnWaitTime, OffWaitTime;
            public int Waveform;                    // 0 Linear, 1 Sine, 2 SlowOff, 3 SlowOn
            public bool StartOn, TriggerOff, Locked, ForceMove, ForceMoveOn, ForceMoveOff;
        }

        const float Epsilon = 1.192092896e-07f;   // MATH_EPSILON
        const float Circle = (float)(2 * Math.PI);

        readonly Settings s;
        readonly Action<string> runCommand;     // the spinner's command property to run ("OnCommand"...)
        float time, frameTime, moveStartTm, moveStopTm, lastTime;
        float vx, vy, vz;
        bool locked;
        State lastState;

        public State Current { get; private set; }
        public float Pitch { get; private set; }
        public float Yaw { get; private set; }
        public float Roll { get; private set; }
        public LTVec Velocity => new LTVec(vx, vy, vz);

        // runCommand: called with the name of the command property to run (PowerOnCommand, OnCommand,
        // PowerOffCommand, OffCommand, LockedCommand), in the order the engine runs them.
        public SpinnerMotion(Settings settings, Action<string> runCommand = null)
        {
            s = settings;
            this.runCommand = runCommand ?? (_ => { });
            locked = s.Locked;
            if (s.StartOn) SetPowerOn();
            else SetOff(true);
        }

        public void Update(float dt)
        {
            time += dt;
            frameTime = dt;
            switch (Current)
            {
                case State.On: UpdateOn(); break;
                case State.PowerOn: UpdatePowerOn(); break;
                case State.PowerOff: UpdatePowerOff(); break;
            }
        }

        public bool OnMessage(Message m)
        {
            if (m.Is("TRIGGER")) HandleTrigger();
            else if (m.Is("LOCK")) locked = true;
            else if (m.Is("UNLOCK")) locked = false;
            else if (m.Is("ON")) { if (Current == State.Off || Current == State.PowerOff) HandleTrigger(); }
            else if (m.Is("OFF")) { if (Current == State.On || Current == State.PowerOn) HandleTrigger(); }
            else if (m.Is("PAUSE"))
            {
                if (Current == State.PowerOn || Current == State.PowerOff)
                {
                    lastState = Current;
                    Current = State.Pause;
                }
            }
            else if (m.Is("RESUME")) { if (Current == State.Pause) Current = lastState; }
            else return false;
            return true;
        }

        void HandleTrigger()
        {
            if (locked)
            {
                runCommand("LockedCommand");
                return;
            }
            switch (Current)
            {
                case State.Off:
                    if (time >= moveStopTm + s.OffWaitTime) SetPowerOn();
                    break;
                case State.PowerOff:
                case State.PowerOn:
                    ChangeDir();
                    break;
                case State.On:
                    if (!s.TriggerOff) SetOn(true);
                    else if (time >= moveStopTm + s.OnWaitTime) SetPowerOff();
                    break;
            }
        }

        void ChangeDir()
        {
            if (s.ForceMove) return;
            if (Current == State.PowerOn && s.ForceMoveOn) return;
            if (Current == State.PowerOff && s.ForceMoveOff) return;
            if (Current == State.PowerOff) SetPowerOn();
            else if (Current == State.PowerOn) SetPowerOff();
        }

        void SetPowerOn()
        {
            Current = State.PowerOn;
            runCommand("PowerOnCommand");
            moveStartTm = time + s.MoveDelay;
        }

        void SetOn(bool initialize)
        {
            Current = State.On;
            if (!initialize)
            {
                runCommand("OnCommand");
                moveStopTm = time;
            }
            lastTime = time;   // SpinningWorldModel::SetOn
        }

        void SetPowerOff()
        {
            Current = State.PowerOff;
            runCommand("PowerOffCommand");
            moveStartTm = time + s.MoveDelay;
        }

        void SetOff(bool initialize)
        {
            Current = State.Off;
            if (initialize) return;
            runCommand("OffCommand");
            moveStopTm = time;
        }

        void UpdateOn()
        {
            float dt = time - lastTime;
            if (vx != 0) Pitch = Wrap(Pitch + vx * dt);
            if (vy != 0) Yaw = Wrap(Yaw + vy * dt);
            if (vz != 0) Roll = Wrap(Roll + vz * dt);
            lastTime = time;
        }

        // Keep within 2 pi (the engine's: x > 2 pi takes 2 pi off, x < -2 pi adds it).
        static float Wrap(float a) => a > Circle ? a - Circle : a < -Circle ? a + Circle : a;

        void UpdatePowerOn()
        {
            float p = (time - moveStartTm) / s.PowerOnTime;
            bool doneX = PowerOn(ref vx, s.Final.x, p), doneY = PowerOn(ref vy, s.Final.y, p), doneZ = PowerOn(ref vz, s.Final.z, p);
            if (p > 1)
            {
                doneX = doneY = doneZ = true;
                vx = s.Final.x; vy = s.Final.y; vz = s.Final.z;
            }
            UpdateOn();
            if (doneX && doneY && doneZ) SetOn(false);
        }

        bool PowerOn(ref float v, float final, float p)
        {
            if (final == 0) return true;
            v += Wave(final / s.PowerOnTime, p) * frameTime;
            if (v < Math.Abs(final)) return false;
            v = final;
            return true;
        }

        void UpdatePowerOff()
        {
            float p = (time - moveStartTm) / s.PowerOffTime;
            bool done = false;
            if (p > 1)
            {
                done = true;
                vx = vy = vz = 0;
            }
            bool doneX = PowerOff(ref vx, s.Final.x, p), doneY = PowerOff(ref vy, s.Final.y, p), doneZ = PowerOff(ref vz, s.Final.z, p);
            UpdateOn();
            if (done || (doneX && doneY && doneZ)) SetOff(false);
        }

        bool PowerOff(ref float v, float final, float p)
        {
            if (final == 0) return true;
            v -= Wave(final / s.PowerOffTime, p) * frameTime;
            if (v >= Epsilon) return false;
            v = 0;
            return true;
        }

        // ActiveWorldModel::GetWaveformValue: the speed of change at fraction p of the move.
        float Wave(float rate, float p)
        {
            const float halfPi = (float)(Math.PI / 2);
            switch (s.Waveform)
            {
                case 1: return halfPi * rate * (float)Math.Sin(p * Math.PI);
                case 2: return halfPi * rate * (float)Math.Cos(p * halfPi) - rate * 0.001f;
                case 3: return halfPi * rate * (float)Math.Sin(p * halfPi) + rate * 0.001f;
                default: return rate;
            }
        }
    }
}
