using UnityEngine;

namespace Tron
{
    // A sound placed in the level, played with the engine's rules (docs/research/ambient-sound.md):
    // every frame its AudioSource.volume is set from the distance to the AudioListener (AmbientVolume:
    // linear falloff between the radii, retail LT volume -> dB curve, earshot), so Unity's own rolloff
    // stays flat and only pans. Ambient sounds are unpanned (spatialBlend 0), the others 3D with the
    // software path's behind-the-listener loss. The voice limit is Unity's 32 real voices
    // (ProjectSettings/AudioManager.asset, the engine's MaxSWVoices); Unity drops the least important
    // (priority) and least audible first and keeps virtual voices' playback position, like the engine.
    //
    // Shared by every ambient sound: SoundFX (LevelBuilder.BuildSoundFX), SoundButeFX, keyframers'
    // ActiveSound and effects' PlaySound (FxSoundPlayer). Add it to the GameObject the sound follows, then Play.
    public class AmbientSound : MonoBehaviour
    {
        // Scales every placed sound before the curve; the game's defaults by default.
        public static float Master = AmbientVolume.GameMaster;

        public float Inner, Outer;   // LT units
        public int Volume = 100;     // 0-100
        public bool Ambient;
        // PLAYSOUND_LOCAL (an effect's PlayLocal): unpanned and as loud as at its own place, wherever it is.
        public bool Local;
        public AudioSource Source { get; private set; }
        public bool IsPlaying => Source.isPlaying;

        static AudioListener listener;

        // priority: the engine's (higher wins; SoundFX its prop, SoundButeFX 0, ActiveSound 1).
        public static AmbientSound Add(GameObject host, float inner, float outer, int volume, bool ambient, int priority)
        {
            var a = host.AddComponent<AmbientSound>();
            a.Inner = inner;
            a.Outer = outer;
            a.Volume = volume;
            a.Ambient = ambient;
            var s = a.Source = host.AddComponent<AudioSource>();
            s.playOnAwake = false;
            s.volume = 0;
            s.spatialBlend = ambient ? 0 : 1;
            s.dopplerLevel = 0;
            s.rolloffMode = AudioRolloffMode.Custom;
            s.SetCustomCurve(AudioSourceCurveType.CustomRolloff, AnimationCurve.Constant(0, 1, 1));
            s.maxDistance = 1e6f;
            s.priority = AmbientVolume.UnityPriority(priority);
            return a;
        }

        // An object's own sound (a door's state sounds, a keyframer's ActiveSound): 3D, volume 100, priority 1,
        // inner a quarter of its sound radius, outer the radius.
        public static AmbientSound AddObjectSound(GameObject host, float radius) =>
            Add(host, 0.25f * radius, radius, 100, false, 1);

        // Starts a clip from its beginning. A non-looping one stops at its end (IsPlaying turns false).
        // pitch changes speed too, like the engine's PLAYSOUND_CTRL_PITCH.
        public void Play(AudioClip clip, bool loop, float pitch = 1)
        {
            Source.clip = clip;
            Source.loop = loop;
            Source.pitch = pitch;
            UpdateVolume();
            Source.Play();
        }

        // Silent ones (SoundFX waiting for ON) cost nothing.
        void LateUpdate()
        {
            if (Source.isPlaying) UpdateVolume();
        }

        void UpdateVolume()
        {
            if (!listener || !listener.isActiveAndEnabled) listener = FindFirstObjectByType<AudioListener>();
            if (!listener) return;
            var lt = listener.transform;
            var toListener = lt.position - transform.position;
            float d = Local ? 0 : toListener.magnitude / LT.Scale;
            float front = Ambient || Local || d < 1e-3f ? 1 : AmbientVolume.Front(Vector3.Dot(lt.forward, toListener / toListener.magnitude));
            Source.volume = AmbientVolume.Gain(Volume, Inner, Outer, d, Master, front);
        }
    }
}
