using System;

namespace Tron
{
    // When a SoundButeFX plays its next sound (SoundButeFX::Update, ltjs soundbutefx.cpp, retail object.lto
    // 0x1022c1d0; docs/research/ambient-sound.md §7): the first at level start, then once U(MinDelay,
    // MaxDelay) seconds have passed since the last one *started* and it has ended (WaitUntilFinished, set
    // on every one in the game), each a uniformly random file of the soundbute (no Weight keys in Tron).
    // Plain System, no UnityEngine, so tools/tests/test_sound_bute_timer.py compiles it with Mono.
    public class SoundButeTimer
    {
        readonly float minDelay, maxDelay;
        readonly Random random;
        float lastPlay, delay;   // both 0 at start, like the engine's: the first sound plays right away

        public SoundButeTimer(float minDelay, float maxDelay, Random random)
        {
            this.minDelay = minDelay;
            this.maxDelay = maxDelay;
            this.random = random;
        }

        // Called every frame with the time since level start (s) and whether the last sound still plays.
        // Returns which of the soundbute's `files` to play now, or -1.
        public int Next(float time, bool playing, int files)
        {
            if (time - lastPlay < delay || playing || files <= 0) return -1;
            lastPlay = time;
            delay = minDelay + (maxDelay - minDelay) * (float)random.NextDouble();
            return random.Next(files);
        }
    }
}
