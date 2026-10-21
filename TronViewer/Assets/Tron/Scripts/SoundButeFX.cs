using UnityEngine;

namespace Tron
{
    // A SoundButeFX: while it is on, one-shot sounds at its position, each a random file of its soundbute,
    // repeating by SoundButeTimer's rule from level start. Plays through AmbientSound with the engine's
    // fixed values for this class: volume 100, pitch 1, priority 0, no loop (the soundbute's own Volume
    // and Pitch are ignored, research §7). A file missing from the export is a silent play: the timer
    // goes on, as the engine's does when PlaySoundFromPos fails.
    public class SoundButeFX : MonoBehaviour
    {
        static readonly System.Random random = ViewerRandom.New();

        AudioClip[] clips;
        SoundButeTimer timer;
        AmbientSound sound;
        float start;

        public static SoundButeFX Add(GameObject host, SoundButeFXJson s, AudioClip[] clips)
        {
            var b = host.AddComponent<SoundButeFX>();
            b.clips = clips;
            b.timer = new SoundButeTimer(s.minDelay, s.maxDelay, random);
            b.sound = AmbientSound.Add(host, s.inner, s.outer, 100, s.ambient != 0, 0);
            b.start = Time.time;
            b.On = s.startOn;
            return b;
        }

        // ON / OFF / TOGGLE (SoundButeFX::OnTrigger): off, no new sound starts; the one playing plays to its
        // end (WaitUntilFinished, set on every one, keeps OFF from killing it).
        public bool On = true;

        void Update()
        {
            if (!On) return;
            int i = timer.Next(Time.time - start, sound.IsPlaying, clips.Length);
            if (i >= 0 && clips[i]) sound.Play(clips[i], false);
        }
    }
}
