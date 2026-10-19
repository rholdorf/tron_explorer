using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Plays the dialogues' voices: one voice per speaker (a new line cuts the old), through AmbientSound's rules
    // (falloff, earshot, volume curve), at volume 100. 3D from the speaker, following it (inner radius 25% of the
    // outer), or client-local: unpanned and as loud as at its own place.
    public class DialogueVoices : MonoBehaviour
    {
        public Func<int, Transform> Host;
        readonly Dictionary<int, AmbientSound> voices = new Dictionary<int, AmbientSound>();

        public void Play(DialogueVoice v)
        {
            var clip = SoundLoader.Load(v.File);
            if (!clip) return;
            if (!voices.TryGetValue(v.Speaker, out var a) || !a)
            {
                var go = new GameObject("Voice");
                go.transform.SetParent(Host(v.Speaker), false);
                a = voices[v.Speaker] = AmbientSound.Add(go, 0, 0, 100, false, 2);
            }
            a.Set(AmbientSound.InnerRadiusPercent * v.Radius, v.Radius, 100, v.Local);
            a.Play(clip, false);
        }

        public void Kill(int speaker)
        {
            if (voices.TryGetValue(speaker, out var a) && a) a.Source.Stop();
        }
    }
}
