using System;

namespace Tron
{
    // How loud the engine plays a placed sound at a distance (docs/research/ambient-sound.md, §1, §2, §6).
    // Plain System math, no UnityEngine, so tools/tests/test_ambient_volume.py compiles it with Mono.
    public static class AmbientVolume
    {
        // The game's defaults: SoundVolume 75 x defaultsoundmultiplier 0.75 (class 0), applied before the
        // curve. The user's autoexec.cfg has the same values.
        public const float GameMaster = 0.75f * 75 / 100;

        // Falloff in LT volume (Lithtech.exe 0x4815d2): 1 inside InnerRadius, 0 from OuterRadius + 0.01,
        // linear between. Compared as squares, so an inner radius past the outer one wins out to itself.
        public static float Falloff(float d, float inner, float outer)
        {
            outer += 0.01f;
            if (d * d <= inner * inner) return 1;
            if (d * d >= outer * outer) return 0;
            return 1 - (d - inner) / (outer - inner);
        }

        // The DirectSound volume in dB of a sound with this Volume prop (0-100) at falloff f (times any
        // other scale, e.g. the software 3D path's behind-the-listener loss), with the integer truncations
        // of the engine's pipeline and retail SndDrv.dll's LT volume -> dB curve (0x10005470).
        public static double Decibels(int volume, float f, float master)
        {
            int raw = (byte)(volume * f);                   // uint8(Vol x f)
            int V = (ushort)(raw * master);                 // x class multiplier x master / 100
            int v = Math.Max(1, Math.Min(127, V * 127 / 100));
            double t = (1 - 1.0 / v) * 127 / 126;
            return -100 * (1 - Math.Pow(t, Math.Sqrt(127)));
        }

        // AudioSource.volume for a sound `distance` LT units from the listener. Silent beyond earshot
        // (1.5 x OuterRadius, where the engine gives it no voice), at Volume 0, and at the curve's
        // -100 dB floor (DSBVOLUME_MIN).
        public static float Gain(int volume, float inner, float outer, float distance, float master, float front = 1)
        {
            if (volume <= 0 || distance > 1.5f * outer && distance > inner) return 0;
            double db = Decibels(volume, Falloff(distance, inner, outer) * front, master);
            return db <= -100 ? 0 : (float)Math.Pow(10, db / 20);
        }

        // The software 3D path's volume scale (soundinstance.cpp C3DSoundInstance::UpdateOutput): up to 25%
        // less when the sound is behind the listener. behind: the listener's forward vector dotted with the
        // unit vector from the sound to the listener (1 = straight behind).
        public static float Front(float behind) => 1 - 0.25f * Math.Max(0, behind);

        // The engine's Priority (higher wins) as AudioSource.priority (0-256, lower wins): 0 -> 128,
        // 1 -> 96, 3 -> 32.
        public static int UnityPriority(int priority) => Math.Max(0, Math.Min(256, 128 - 32 * priority));
    }
}
