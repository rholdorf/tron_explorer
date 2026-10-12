using UnityEngine;

namespace Tron
{
    // Runs a keyframer, active at start or started by a message (KeyframerMotion, one engine update per
    // frame; LevelBuilder.BuildKeyframers joins it to the level's command manager) and puts the objects
    // it controls where it says: world models (their collider moves with them; LevelBuilder gives solid
    // ones a kinematic body) and drawn models (props, characters; attachments ride on their parent).
    // Objects the viewer doesn't draw (SpecialFX, cameras, volumes...) still count as controlled, as in
    // the engine, but have nothing to move. Model lighting stays the one computed where the model spawned.
    //
    // ActiveSound (KeyFramer::GoActive): loops from the first controlled object while the keyframer is
    // active, from the beginning on each GoActive (start, RESUME, ON), killed by GoInActive (PAUSE, OFF,
    // the end of a path that doesn't loop). Played through AmbientSound: 3D, priority 1, volume 100,
    // inner 0.25 x SoundRadius, outer SoundRadius (docs/research/ambient-sound.md).
    public class Keyframer : MonoBehaviour
    {
        KeyframerMotion motion;
        Transform[][] shown;     // per motion target, the GameObjects that show it (may be empty)
        AmbientSound sound;
        AudioClip clip;
        int activations;
        bool moved = true;

        public void Init(KeyframerMotion motion, Transform[][] shown, AmbientSound sound, AudioClip clip)
        {
            this.motion = motion;
            this.shown = shown;
            this.sound = sound;
            this.clip = clip;
        }

        // REMOVE: the keyframer leaves the level; its objects stay where they are and its sound stops.
        public void Remove()
        {
            enabled = false;
            if (sound) sound.Source.Stop();
        }

        void Update()
        {
            motion.Update(Time.deltaTime);
            // A pose can still change in the update that goes inactive; after that nothing moves.
            if (motion.Active || moved)
            {
                for (int i = 0; i < shown.Length; i++)
                {
                    if (shown[i].Length == 0) continue;
                    var t = motion.Targets[i];
                    var pos = new Vector3(t.Pos.x, t.Pos.y, t.Pos.z);
                    var rot = new Quaternion(t.Rot.x, t.Rot.y, t.Rot.z, t.Rot.w);
                    rot.Normalize();   // rotation offsets are added component-wise: not unit length
                    foreach (var tr in shown[i])
                    {
                        tr.localPosition = pos;
                        tr.localRotation = rot;
                    }
                }
            }
            moved = motion.Active;

            if (!sound) return;
            if (motion.Active && motion.Activations != activations)
            {
                activations = motion.Activations;
                sound.Play(clip, true);
            }
            else if (!motion.Active && sound.IsPlaying)
                sound.Source.Stop();
        }
    }
}
