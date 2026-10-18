using System;
using System.Collections.Generic;

namespace Tron
{
    // A keyframer's path as the engine runs it (ltjs keyframer.cpp, docs/research/keyframer-paths.md):
    // a port of KeyFramer's Update / ProcessCurrentKey / CalcCurPos / UpdateObjects and OnTrigger, in
    // LithTech units and LithTech quaternions. Plain C# (System only), so it compiles outside Unity and
    // tools/tests/test_keyframer_motion.py checks it with Mono; Keyframer.cs applies the targets' poses to
    // their GameObjects.
    //
    // One Update is one server frame. The first one only goes active if StartActive or StartPaused
    // (CreateKeyList + GoActive, nothing moves), pauses if StartPaused, then handles the messages that
    // came before it (DeferCommand). Then: process every key reached (time mode: key time <= current time;
    // velocity mode: the current position is exactly on the key), wrap to the first key at the end of the
    // list (a non-looping path then stops), move the targets, advance the time. Processing a key runs its
    // command (RunCommand, through the level's command manager with the keyframer as sender and active
    // target), which can message the keyframer itself (PAUSE, GOTO...) right away or after a delay.
    //
    // Messages (OnMessage, KeyFramer::OnTrigger): ON (from the first key; before the first update it only
    // sets StartActive), OFF, PAUSE / RESUME (OFF isn't a pause: RESUME won't restart it, ON will),
    // FORWARD, BACKWARD / REVERSE, TOGGLEDIR, GOTO <key>, MOVETO <key> [<command>] (travel to the key, then
    // pause and run the command). PAUSE, GOTO and MOVETO before the first update wait for it. Key names:
    // BaseKeyName (any case) then "0", "01".."09", "10".. by index. TARGET / CLEARTARGET / TARGETOFFSET
    // (turn the targets to face an object) aren't handled.
    public sealed class KeyframerMotion
    {
        public sealed class Key
        {
            public LTVec Pos, PYR, BezPrev, BezNext;
            public bool HasPrev, HasNext;      // BEZPREV_KEY, BEZNEXT_KEY
            public float Time;                 // running sum of the time stamps (m_fRealTime)
            public string Command = "";        // run when the key is reached
            internal LTQuat Rot;
            internal float DistToLast;
        }

        // A controlled object: its pose, read by the viewer after each Update.
        public sealed class Target
        {
            public LTVec Pos;
            public LTQuat Rot;
            internal LTVec Offset;
            internal LTQuat RotOffset;
        }

        readonly Key[] keys;
        readonly bool looping, alignToPath, ignoreOffsets, useVelocity;
        readonly float totalPathTime, endTime;
        readonly int wave;
        float velocity, totalDistance;
        public readonly List<Target> Targets = new List<Target>();

        public string BaseKeyName = "";
        public bool StartActive, StartPaused;
        // Runs a key's (or MOVETO's) command string; set by whoever joins the keyframer to the level.
        public Action<string> RunCommand = _ => { };

        int curKey = -1, pos1 = -1, pos2 = -1;   // indices into keys, -1 = none
        int destKey = -1;                        // MOVETO's destination
        string destCommand;
        float curTime, keyPercent, frameTime;
        LTVec curPos;
        bool forward = true, paused, finished, firstUpdate = true;
        readonly List<Message> deferred = new List<Message>();

        public bool Active { get; private set; }
        // Bumped by each GoActive: the ActiveSound (re)starts from the beginning then, and stops when
        // Active turns false (GoInActive: PAUSE, OFF, the end of a non-looping path).
        public int Activations { get; private set; }

        // wave: 0 Linear, 1 Sine, 2 SlowOff, 3 SlowOn. totalPathTime > 0: velocity mode.
        public KeyframerMotion(Key[] keys, bool looping, float totalPathTime, int wave, bool alignToPath, bool ignoreOffsets)
        {
            this.keys = keys;
            this.looping = looping;
            this.totalPathTime = totalPathTime;
            this.wave = wave;
            this.alignToPath = alignToPath;
            this.ignoreOffsets = ignoreOffsets;
            useVelocity = totalPathTime > 0;
            foreach (var k in keys) k.Rot = LTQuat.FromEuler(k.PYR.x, k.PYR.y, k.PYR.z);
            endTime = keys.Length > 0 ? keys[keys.Length - 1].Time : 0;
            if (useVelocity) CalculateVelocityInfo();
        }

        // CreateKeyList: each object keeps its offset from the first key; its rotation offset is a
        // component-wise quaternion difference ("no geometric meaning", but that's what the engine adds back).
        public Target AddTarget(LTVec pos, LTQuat rot)
        {
            var t = new Target { Pos = pos, Rot = rot };
            if (keys.Length > 0)
            {
                t.Offset = pos - keys[0].Pos;
                t.RotOffset = LTQuat.Sub(rot, keys[0].Rot);
            }
            Targets.Add(t);
            return t;
        }

        public void Update(float dt)
        {
            frameTime = dt;
            if (firstUpdate)
            {
                firstUpdate = false;
                if (StartActive || StartPaused) GoActive(true);
                if (StartPaused) Pause();
                var messages = deferred.ToArray();
                deferred.Clear();
                foreach (var m in messages) OnMessage(m);
                return;
            }
            if (!Active) return;

            while (curKey >= 0 && Active)
            {
                var k = keys[curKey];
                if (useVelocity) { if (!(curPos == k.Pos)) break; }
                else if (forward ? k.Time > curTime : k.Time < curTime) break;
                ProcessCurrentKey();
            }

            if (curKey < 0)
            {
                curKey = forward ? 0 : keys.Length - 1;
                curTime = forward ? 0 : endTime;
                curPos = keys[curKey].Pos;
                if (!looping) finished = true;
            }

            if (Active) UpdateObjects();
            if (finished) GoInActive();
            curTime += forward ? dt : -dt;
        }

        void GoActive(bool reset)
        {
            if (Active || keys.Length == 0 || Targets.Count == 0) return;
            finished = false;
            Active = true;
            if (reset)
            {
                curTime = forward ? 0 : endTime;
                curKey = forward ? 0 : keys.Length - 1;
                curPos = keys[curKey].Pos;
            }
            Activations++;
        }

        void GoInActive() => Active = false;

        void ProcessCurrentKey()
        {
            if (curKey < 0) return;
            int old = curKey;
            if (forward) { pos1 = old; pos2 = Next(old); }
            else { pos2 = old; pos1 = old - 1; }
            curKey = forward ? Next(old) : old - 1;
            if (!string.IsNullOrEmpty(keys[old].Command)) RunCommand(keys[old].Command);
            if (destKey >= 0 && old == destKey) ReachedDestination();
        }

        int Next(int i) => i + 1 < keys.Length ? i + 1 : -1;

        // KeyFramer::OnTrigger: true if the message is one of the keyframer's.
        public bool OnMessage(Message m)
        {
            if (m.Is("ON"))
            {
                paused = false;
                if (firstUpdate) StartActive = true;
                else GoActive(true);
            }
            else if (m.Is("OFF")) GoInActive();
            else if (m.Is("PAUSE")) { if (firstUpdate) deferred.Add(m); else Pause(); }
            else if (m.Is("RESUME")) Resume();
            else if (m.Is("FORWARD")) Forward();
            else if (m.Is("BACKWARD") || m.Is("REVERSE")) Backward();
            else if (m.Is("TOGGLEDIR")) ToggleDir();
            else if (m.Is("GOTO"))
            {
                if (firstUpdate) deferred.Add(m);
                else if (m.ArgCount > 0)
                {
                    int key = FindKey(m.Arg(0), -1, out _);
                    if (key >= 0) GoToKey(key);
                }
            }
            else if (m.Is("MOVETO")) { if (firstUpdate) deferred.Add(m); else MoveToKey(m); }
            else return false;
            return true;
        }

        void Pause()
        {
            if (!Active || paused) return;
            paused = true;
            GoInActive();
        }

        void ToggleDir()
        {
            if (forward) Backward();
            else Forward();
        }

        // KeyFramer::FindKey: the key a name stands for, or -1. atOrBefore: whether key `test` comes at or
        // before it in the list.
        int FindKey(string name, int test, out bool atOrBefore)
        {
            atOrBefore = false;
            if (string.IsNullOrEmpty(BaseKeyName) || name.Length <= BaseKeyName.Length ||
                !name.StartsWith(BaseKeyName, StringComparison.OrdinalIgnoreCase))
                return -1;
            var ext = name.Substring(BaseKeyName.Length);
            if (ext.Length > 10) return -1;
            for (int i = 0; i < keys.Length; i++)
            {
                if (i == test) atOrBefore = true;
                if (ext == (i > 0 && i < 10 ? "0" + i : i.ToString())) return i;
            }
            return -1;
        }

        // KeyFramer::MoveToKey: travel to a key (turning around if it lies behind), then ReachedDestination.
        void MoveToKey(Message m)
        {
            if (m.ArgCount < 1) return;
            if (m.ArgCount > 1) destCommand = m.Arg(1);
            int cur = forward ? pos1 : pos2;
            destKey = FindKey(m.Arg(0), cur, out bool atOrBefore);
            if (destKey < 0) return;
            Resume();
            if (destKey == cur)
            {
                if (curPos == keys[cur].Pos) ProcessCurrentKey();
                else ToggleDir();
            }
            else if (atOrBefore ? !forward : forward)
                ToggleDir();
        }

        void ReachedDestination()
        {
            Pause();
            if (destCommand == null) return;
            var cmd = destCommand;
            destCommand = null;
            RunCommand(cmd);
        }

        void Resume()
        {
            if (!paused) return;
            paused = false;
            GoActive(false);
        }

        void Forward()
        {
            if (!forward && keyPercent > 0.99f) keyPercent = 0;
            forward = true;
            curKey = pos2;
        }

        void Backward()
        {
            if (forward && keyPercent < 0.01f) keyPercent = 1;
            forward = false;
            curKey = pos1;
        }

        void GoToKey(int key)
        {
            Resume();
            curKey = key;
            curTime = keys[key].Time;
            curPos = keys[key].Pos;
            ProcessCurrentKey();
            if (pos1 < 0) pos1 = pos2;
            else if (pos2 < 0) pos2 = pos1;
            UpdateObjects();
        }

        void CalculateVelocityInfo()
        {
            totalDistance = 0;
            for (int i = 0; i + 1 < keys.Length; i++)
            {
                totalDistance += IsBezier(i, i + 1)
                    ? Bezier.SubSegmentLength(keys[i].Pos, keys[i].BezNext, keys[i + 1].BezPrev, keys[i + 1].Pos, 0, 1)
                    : LTVec.Dist(keys[i].Pos, keys[i + 1].Pos);
                keys[i + 1].DistToLast = totalDistance;
            }
            velocity = totalDistance / totalPathTime;
            foreach (var k in keys) k.DistToLast = totalDistance - k.DistToLast;
        }

        bool IsBezier(int a, int b) => keys[a].HasNext && keys[b].HasPrev;

        public static float WaveSpeed(float speed, float percent, int wave)
        {
            switch (wave)
            {
                case 1: return (float)(Math.PI / 2) * speed * (float)Math.Sin(percent * Math.PI);
                case 2: return (float)(Math.PI / 2) * speed * (float)Math.Cos(percent * Math.PI / 2);
                case 3: return (float)(Math.PI / 2) * speed * (float)Math.Sin(percent * Math.PI / 2) + speed * 0.003f;
                default: return speed;
            }
        }

        bool CalcCurPos(out bool atKey)
        {
            atKey = false;
            Key k1 = keys[pos1], k2 = keys[pos2];
            bool bezier = IsBezier(pos1, pos2);
            if (useVelocity)
            {
                if (!(velocity > 0 && totalDistance > 0)) return false;
                float pathPercent = Clamp01(curTime / totalPathTime);
                float moveDist = WaveSpeed(velocity, pathPercent, wave) * frameTime;
                float movePercent;
                if (bezier)
                {
                    float between = Math.Abs(k1.DistToLast - k2.DistToLast);
                    movePercent = between <= Epsilon ? 1 : moveDist / between;
                    // "TODO: Find a better, more correct, algorithm": rescale by the chord length covered.
                    float seg = Bezier.SubSegmentLength(k1.Pos, k1.BezNext, k2.BezPrev, k2.Pos, keyPercent, keyPercent + movePercent);
                    if (seg > 0 && moveDist > 0) movePercent /= seg / moveDist;
                }
                else
                {
                    float between = LTVec.Dist(k2.Pos, k1.Pos);
                    movePercent = between <= Epsilon ? 1 : moveDist / between;
                }
                if (forward)
                {
                    keyPercent += movePercent;
                    if (keyPercent >= 1 || pathPercent >= 1) atKey = true;
                }
                else
                {
                    keyPercent -= movePercent;
                    if (keyPercent <= Epsilon || pathPercent <= Epsilon) atKey = true;
                }
                if (atKey)
                {
                    curPos = forward ? k2.Pos : k1.Pos;
                    keyPercent = forward ? Clamp01(-(1 - keyPercent)) : Clamp01(keyPercent - 1);
                }
                else
                    curPos = bezier ? Bezier.Evaluate(k1.Pos, k1.BezNext, k2.BezPrev, k2.Pos, keyPercent)
                                    : LTVec.Lerp(k1.Pos, k2.Pos, keyPercent);
                return true;
            }

            if (!(curTime >= k1.Time && curTime <= k2.Time)) return false;
            float range = k2.Time - k1.Time;
            if (-0.001f <= range && range < 0.001f) range = 0;
            keyPercent = range != 0 ? (curTime - k1.Time) / range : 0;
            curPos = bezier ? Bezier.Evaluate(k1.Pos, k1.BezNext, k2.BezPrev, k2.Pos, keyPercent)
                            : LTVec.Lerp(k1.Pos, k2.Pos, keyPercent);
            return true;
        }

        const float Epsilon = 1.192092896e-07f;   // MATH_EPSILON (FLT_EPSILON)

        static float Clamp01(float v) => v < 0 ? 0 : v > 1 ? 1 : v;

        void UpdateObjects()
        {
            if (pos1 < 0 || pos2 < 0) return;
            if (!CalcCurPos(out bool atKey)) return;
            Key k1 = keys[pos1], k2 = keys[pos2];
            var rotNew = atKey ? (forward ? k2.Rot : k1.Rot) : LTQuat.Slerp(k1.Rot, k2.Rot, keyPercent);
            foreach (var t in Targets)
            {
                var old = t.Pos;
                var pos = curPos;
                if (!ignoreOffsets) pos += t.Offset;
                t.Pos = pos;
                var rot = rotNew;
                if (alignToPath)
                {
                    var dir = pos - old;
                    // The engine normalizes a zero move too (NaN); the viewer keeps the last rotation.
                    if (dir.Length() < 1e-6f) continue;
                    dir = dir / dir.Length();
                    if (!forward) dir = -dir;
                    rot = LTQuat.FromForwardUp(dir, new LTVec(0, 1, 0));
                    var pyr = LTVec.Lerp(k1.PYR, k2.PYR, keyPercent);
                    LTVec right = rot.Right(), fwd = rot.Forward();
                    rot = LTQuat.AxisAngle(right, pyr.x) * rot;
                    rot = LTQuat.AxisAngle(fwd, pyr.z) * rot;
                }
                if (!ignoreOffsets) rot = LTQuat.Add(rot, t.RotOffset);
                t.Rot = rot;
            }
        }
    }

    public struct LTVec
    {
        public float x, y, z;
        public LTVec(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
        public static LTVec operator +(LTVec a, LTVec b) => new LTVec(a.x + b.x, a.y + b.y, a.z + b.z);
        public static LTVec operator -(LTVec a, LTVec b) => new LTVec(a.x - b.x, a.y - b.y, a.z - b.z);
        public static LTVec operator -(LTVec a) => new LTVec(-a.x, -a.y, -a.z);
        public static LTVec operator *(LTVec a, float s) => new LTVec(a.x * s, a.y * s, a.z * s);
        public static LTVec operator /(LTVec a, float s) => new LTVec(a.x / s, a.y / s, a.z / s);
        public static bool operator ==(LTVec a, LTVec b) => a.x == b.x && a.y == b.y && a.z == b.z;
        public static bool operator !=(LTVec a, LTVec b) => !(a == b);
        public override bool Equals(object o) => o is LTVec v && v == this;
        public override int GetHashCode() => x.GetHashCode() ^ y.GetHashCode() ^ z.GetHashCode();
        public float Length() => (float)Math.Sqrt(x * x + y * y + z * z);
        public static float Dist(LTVec a, LTVec b) => (a - b).Length();
        public static LTVec Lerp(LTVec a, LTVec b, float t) => a + (b - a) * t;
        // LTVector::Cross is b x this.
        public LTVec Cross(LTVec b) => new LTVec(b.y * z - b.z * y, b.z * x - b.x * z, b.x * y - b.y * x);
    }

    // LTRotation: x, y, z, w with the same meaning as Unity's Quaternion (both left-handed, Y up).
    public struct LTQuat
    {
        public float x, y, z, w;
        public LTQuat(float x, float y, float z, float w) { this.x = x; this.y = y; this.z = z; this.w = w; }

        // LTRotation(pitch, yaw, roll): the rotation matrix, then quat_ConvertFromMatrix (its signs
        // matter: rotation offsets are added component-wise).
        public static LTQuat FromEuler(float pitch, float yaw, float roll)
        {
            double yc = Math.Cos(yaw), ys = Math.Sin(yaw), pc = Math.Cos(pitch), ps = Math.Sin(pitch);
            double rc = Math.Cos(roll), rs = Math.Sin(roll);
            var m = new float[3, 3];
            m[0, 0] = (float)(rc * yc + rs * ps * ys); m[0, 1] = (float)(-rs * yc + rc * ps * ys); m[0, 2] = (float)(pc * ys);
            m[1, 0] = (float)(rs * pc); m[1, 1] = (float)(rc * pc); m[1, 2] = (float)-ps;
            m[2, 0] = (float)(-rc * ys + rs * ps * yc); m[2, 1] = (float)(rs * ys + rc * ps * yc); m[2, 2] = (float)(pc * yc);
            return FromMatrix(m);
        }

        // LTRotation(forward, up): basis right = up x forward, trueUp = forward x right, as matrix columns.
        public static LTQuat FromForwardUp(LTVec f, LTVec up)
        {
            float dot = f.x * up.x + f.y * up.y + f.z * up.z;
            if (dot > 0.9f || dot < -0.9f) up = new LTVec(f.y, f.z, f.x);
            var r = f.Cross(up);
            r = r / r.Length();
            var u = r.Cross(f);
            var m = new float[3, 3];
            m[0, 0] = r.x; m[1, 0] = r.y; m[2, 0] = r.z;
            m[0, 1] = u.x; m[1, 1] = u.y; m[2, 1] = u.z;
            m[0, 2] = f.x; m[1, 2] = f.y; m[2, 2] = f.z;
            return FromMatrix(m);
        }

        // quat_ConvertFromMatrix
        static LTQuat FromMatrix(float[,] m)
        {
            float diag = m[0, 0] + m[1, 1] + m[2, 2];
            var q = new float[4];
            if (diag < -0.999f)
            {
                int i = 0;
                if (m[1, 1] > m[0, 0]) i = 1;
                if (m[2, 2] > m[i, i]) i = 2;
                int j = (i + 1) % 3, k = (j + 1) % 3;
                float s = (float)Math.Sqrt(m[i, i] - (m[j, j] + m[k, k]) + 1);
                q[i] = s * 0.5f;
                s = 0.5f / s;
                q[3] = (m[k, j] - m[j, k]) * s;
                q[j] = (m[j, i] + m[i, j]) * s;
                q[k] = (m[k, i] + m[i, k]) * s;
                return new LTQuat(q[0], q[1], q[2], q[3]);
            }
            float t = (float)Math.Sqrt(diag + 1);
            float w = t * 0.5f;
            t = 0.5f / t;
            return new LTQuat((m[2, 1] - m[1, 2]) * t, (m[0, 2] - m[2, 0]) * t, (m[1, 0] - m[0, 1]) * t, w);
        }

        public static LTQuat AxisAngle(LTVec axis, float angle)
        {
            float s = (float)Math.Sin(angle * 0.5f);
            return new LTQuat(axis.x * s, axis.y * s, axis.z * s, (float)Math.Cos(angle * 0.5f));
        }

        public static LTQuat operator *(LTQuat a, LTQuat b) => new LTQuat(
            a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
            a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z);

        public static LTQuat Add(LTQuat a, LTQuat b) => new LTQuat(a.x + b.x, a.y + b.y, a.z + b.z, a.w + b.w);
        public static LTQuat Sub(LTQuat a, LTQuat b) => new LTQuat(a.x - b.x, a.y - b.y, a.z - b.z, a.w - b.w);

        // quat_Slerp: shortest way, linear when the two are within 0.0001 of each other.
        public static LTQuat Slerp(LTQuat a, LTQuat b, float t)
        {
            float cos = a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w;
            if (cos < 0) { cos = -cos; b = new LTQuat(-b.x, -b.y, -b.z, -b.w); }
            float s0, s1;
            if (1 - cos > 0.0001f)
            {
                double omega = Math.Acos(cos), inv = 1 / Math.Sin(omega);
                s0 = (float)(Math.Sin((1 - t) * omega) * inv);
                s1 = (float)(Math.Sin(t * omega) * inv);
            }
            else { s0 = 1 - t; s1 = t; }
            return new LTQuat(s0 * a.x + s1 * b.x, s0 * a.y + s1 * b.y, s0 * a.z + s1 * b.z, s0 * a.w + s1 * b.w);
        }

        public LTQuat Conjugate() => new LTQuat(-x, -y, -z, w);

        // v turned by this (unit) rotation: q v q*.
        public LTVec Rotate(LTVec v)
        {
            var r = this * new LTQuat(v.x, v.y, v.z, 0) * Conjugate();
            return new LTVec(r.x, r.y, r.z);
        }

        public LTVec Right() => new LTVec(1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y));
        public LTVec Up() => new LTVec(2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x));
        public LTVec Forward() => new LTVec(2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y));
    }

    // ltbeziercurve.h
    public static class Bezier
    {
        public static LTVec Evaluate(LTVec p1, LTVec p2, LTVec p3, LTVec p4, float t)
        {
            float a = 1 - t, a2 = a * a, a3 = a2 * a, t2 = t * t;
            return p1 * a3 + p2 * (3 * t * a2) + p3 * (3 * t2 * a) + p4 * (t2 * t);
        }

        public static float SubSegmentLength(LTVec p1, LTVec p2, LTVec p3, LTVec p4, float t1, float t2, int n = 20)
        {
            float s = 0, dt = (t2 - t1) / n, t = t1 + dt;
            var pa = Evaluate(p1, p2, p3, p4, t1);
            for (int i = 0; i < n; i++)
            {
                var pb = Evaluate(p1, p2, p3, p4, t);
                s += (pb - pa).Length();
                t += dt;
                pa = pb;
            }
            return s;
        }
    }
}
