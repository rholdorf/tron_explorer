using System;
using System.Collections.Generic;

namespace Tron
{
    // Where a character is in its animations, as the engine's tracker keeps it (ltjs animtracker.cpp,
    // docs/research/cutscene-actors.md): the clip playing, its time, looping or once, and the blend into a
    // clip that has just started. Plain C# (System only), so it compiles outside Unity and
    // tools/tests/test_anim_track.py checks it with .NET; ModelAnimator poses the bones from it.
    //
    // Play (trk_SetCurAnim with a transition, then time 0): the new clip starts at 0. When a clip played
    // before and the new one has an interp time, the pose blends from the old clip's current key (the key
    // its time was heading to) into the new clip's first key over that time, the new clip's time held at
    // 0; the time past the blend then plays the clip. Interp 0 cuts. A looping clip stays on its last key
    // at exactly its time and wraps past it (t %= last key time); a clip played once holds its last key
    // (time clamped 1 ms past it) and is Done past it, or at once with a single key (trk_IsStopped).
    public sealed class AnimTrack
    {
        public sealed class ClipInfo
        {
            public float[] Times;   // key times, seconds, from 0, never decreasing
            public float Interp;    // seconds of blend into its first key when it starts (interpMS)
        }

        const float HoldPastEnd = 0.001f;   // endTime + 1 ms

        readonly IReadOnlyList<ClipInfo> clips;
        float blendElapsed = -1;   // < 0: not blending

        public AnimTrack(IReadOnlyList<ClipInfo> clips) { this.clips = clips; }

        public int Clip { get; private set; } = -1;
        public bool Looping { get; private set; }
        public float Time { get; private set; }

        // Blending from FromClip's key FromKey into Clip's first key, at Weight (0 = all FromClip).
        public bool Blending => blendElapsed >= 0;
        public int FromClip { get; private set; } = -1;
        public int FromKey { get; private set; }
        public float Weight => Blending && clips[Clip].Interp > 0 ? Math.Min(blendElapsed / clips[Clip].Interp, 1f) : 0f;

        // Played once and past its last key (or a single key): MS_PLAYDONE.
        public bool Done
        {
            get
            {
                if (Clip < 0) return true;
                if (Looping) return false;
                var t = clips[Clip].Times;
                return t.Length <= 1 || Time > t[t.Length - 1];
            }
        }

        public void Play(int clip, bool loop)
        {
            bool transition = Clip >= 0 && clips[clip].Interp > 0;
            if (transition)
            {
                FromClip = Clip;
                FromKey = Blending ? 0 : NextKey(clips[Clip].Times, Time);
            }
            Clip = clip;
            Looping = loop;
            Time = 0;
            blendElapsed = transition ? 0 : -1;
        }

        // The clip playing starts over without a transition (SetModelLooping, then ResetModelAnimation: time 0).
        public void Restart(bool loop)
        {
            if (Clip < 0) return;
            Looping = loop;
            Time = 0;
            blendElapsed = -1;
        }

        public void Advance(float dt)
        {
            if (Clip < 0) return;
            var c = clips[Clip];
            if (Blending)
            {
                blendElapsed += dt;
                if (blendElapsed <= c.Interp) return;
                dt = blendElapsed - c.Interp;
                blendElapsed = -1;
            }
            var times = c.Times;
            if (times.Length <= 1) { Time = 0; return; }
            float end = times[times.Length - 1];
            Time += dt;
            if (!Looping) Time = Math.Min(Time, end + HoldPastEnd);
            else if (Time > end && end > 0) Time %= end;
        }

        // The key interval the time lies in (ModelAnimator.Key's rule): key k, fraction f toward k + 1.
        public void Key(out int k, out float f)
        {
            var t = clips[Clip].Times;
            float time = Math.Min(Time, t[t.Length - 1]);
            int lo = 0, hi = t.Length - 1;
            while (lo < hi)
            {
                int mid = (lo + hi + 1) >> 1;
                if (t[mid] <= time) lo = mid; else hi = mid - 1;
            }
            k = lo;
            if (k + 1 >= t.Length) { f = 0; return; }
            f = t[k + 1] > t[k] ? Math.Min(Math.Max((time - t[k]) / (t[k + 1] - t[k]), 0f), 1f) : 0f;
        }

        // The tracker's current key: the first whose time is not before t (m_CurKey), the last at the end.
        static int NextKey(float[] times, float t)
        {
            for (int i = 0; i < times.Length; i++)
                if (t <= times[i]) return i;
            return times.Length - 1;
        }
    }
}
