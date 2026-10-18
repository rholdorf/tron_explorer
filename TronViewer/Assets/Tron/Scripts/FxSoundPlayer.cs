using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Plays the effects' sounds (FxSound) through AmbientSound, the placed sounds' rules: falloff between the
    // key's radii, earshot, the volume curve, behind-the-listener loss, priority. 3D unless PlayLocal (then
    // unpanned at full falloff); pitch changes speed too. Each voice is a GameObject under the level root
    // (LT units), pooled: a killed voice waits for the next sound. A file missing from the export plays
    // nothing (SoundLoader.Missing lists it).
    public class FxSoundPlayer : MonoBehaviour
    {
        readonly Stack<Voice> free = new Stack<Voice>();
        int made;

        sealed class Voice : IFxVoice
        {
            public FxSoundPlayer Owner;
            public AmbientSound Sound;

            public void Move(LTVec pos)
            {
                if (Sound) Sound.transform.localPosition = new Vector3(pos.x, pos.y, pos.z);
            }

            public void Kill()
            {
                if (!Sound) return;
                Sound.Source.Stop();
                Sound.gameObject.SetActive(false);
                Owner.free.Push(this);
            }
        }

        public IFxVoice Play(FxSound fx, LTVec pos)
        {
            var clip = SoundLoader.Load(fx.Sound);
            if (!clip) return null;
            var v = free.Count > 0 ? free.Pop() : null;
            if (v == null)
            {
                var go = new GameObject("FxSound" + made++);
                go.transform.SetParent(transform, false);
                v = new Voice { Owner = this, Sound = AmbientSound.Add(go, 0, 0, 100, false, 0) };
            }
            var a = v.Sound;
            a.gameObject.SetActive(true);
            a.Inner = fx.Inner;
            a.Outer = fx.Outer;
            a.Volume = fx.Volume;
            a.Local = fx.Local;
            a.Source.spatialBlend = fx.Local ? 0 : 1;
            a.Source.priority = AmbientVolume.UnityPriority(fx.Priority);
            v.Move(pos);
            a.Play(clip, fx.Loop, fx.Pitch);
            return v;
        }
    }
}
