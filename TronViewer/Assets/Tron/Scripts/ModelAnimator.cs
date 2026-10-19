using System;
using System.Collections.Generic;
using Unity.Collections;
using Unity.Jobs;
using UnityEngine;
using UnityEngine.Jobs;

namespace Tron
{
    // A character's animations: the ones it can play by name (its model's, its .ltb children's and its
    // ChildModel_N files', tools/animation.py playable) and where it is in them (AnimTrack: looping or once,
    // the blend into a clip that starts). ModelAnimator poses its bones every frame.
    public sealed class CharacterAnimation : IActorAnimation
    {
        internal readonly LoadedModel model;
        internal readonly Transform[] bones;
        internal readonly ModelAnimJson[] anims;   // per track clip, the model's clip
        internal readonly AnimTrack track;
        readonly Dictionary<string, int> byName = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        readonly Action settle;   // completes the pose job before the bones are written here
        internal int slotBase;

        internal CharacterAnimation(LoadedModel model, Transform[] bones, AnimRefJson[] refs, Action settle)
        {
            this.model = model;
            this.bones = bones;
            this.settle = settle;
            var anims = new List<ModelAnimJson>();
            var infos = new List<AnimTrack.ClipInfo>();
            foreach (var r in refs ?? Array.Empty<AnimRefJson>())
            {
                int i = model.FindAnim(r.name, r.@from);
                if (i < 0 || byName.ContainsKey(r.name)) continue;
                var a = model.data.anims[i];
                var times = new float[a.keys];
                Array.Copy(model.animData, a.times, times, 0, a.keys);
                byName[r.name] = anims.Count;
                anims.Add(a);
                infos.Add(new AnimTrack.ClipInfo { Times = times, Interp = a.interp });
            }
            this.anims = anims.ToArray();
            track = new AnimTrack(infos);
        }

        // Whether `name` (any case) is one of its animations.
        public bool Has(string name) => !string.IsNullOrEmpty(name) && byName.ContainsKey(name);

        // Plays its animation `name` (any case) from the start, looping or once, blending in from the pose it
        // is in over the clip's interp time (a cut when 0, or when nothing played before). False, and
        // nothing changes, if it has no such animation (the game then tries DXBLoop: Has("DXBLoop")).
        public bool Play(string name, bool loop)
        {
            if (!Has(name)) return false;
            track.Play(byName[name], loop);
            if (!track.Blending)
            {
                // A cut shows the clip's first key at once (the level's bounds are taken from it).
                settle();
                var d = model.animData;
                var a = anims[track.Clip];
                for (int n = 0; n < bones.Length; n++)
                    bones[n].SetLocalPositionAndRotation(ModelAnimator.Position(d, a, n, 0, 0), ModelAnimator.Rotation(d, a, n, 0, 0));
            }
            return true;
        }

        // The animation playing starts over at its time 0, looping or once, without a blend (a missing animation
        // in a goal script: SetModelLooping, ResetModelAnimation).
        public void Restart(bool loop) => track.Restart(loop);

        // The animation playing (its name as the model has it), "" for none.
        public string Current => track.Clip >= 0 ? anims[track.Clip].name : "";
        public bool Looping => track.Looping;
        // Played once and past its last key (MS_PLAYDONE): the goal script's cue that it ended.
        public bool Done => track.Done;
        // Seconds into the playing animation (0 while blending in).
        public float Time => track.Time;

        // Every bone's local pose now into the arrays at slotBase.
        internal void Pose(NativeArray<Vector3> positions, NativeArray<Quaternion> rotations)
        {
            if (track.Clip < 0) return;
            var d = model.animData;
            var a = anims[track.Clip];
            if (track.Blending)
            {
                var from = anims[track.FromClip];
                float w = track.Weight;
                for (int n = 0; n < bones.Length; n++)
                {
                    positions[slotBase + n] = Vector3.LerpUnclamped(ModelAnimator.Position(d, from, n, track.FromKey, 0),
                        ModelAnimator.Position(d, a, n, 0, 0), w);
                    rotations[slotBase + n] = Quaternion.Slerp(ModelAnimator.Rotation(d, from, n, track.FromKey, 0),
                        ModelAnimator.Rotation(d, a, n, 0, 0), w);
                }
                return;
            }
            track.Key(out int k, out float f);
            for (int n = 0; n < bones.Length; n++)
            {
                positions[slotBase + n] = ModelAnimator.Position(d, a, n, k, f);
                rotations[slotBase + n] = ModelAnimator.Rotation(d, a, n, k, f);
            }
        }
    }

    // Plays the characters' animations (tools/animation.py clips, exported by tools/export_models.py) on their
    // bone Transforms: each frame every character's track advances and its bones' local poses are sampled,
    // then a transform job writes them. All characters start their idle when the level loads, as the game's
    // AIs do when they spawn together.
    public class ModelAnimator : MonoBehaviour
    {
        readonly List<CharacterAnimation> characters = new List<CharacterAnimation>();
        TransformAccessArray transforms;
        NativeArray<Vector3> positions;
        NativeArray<Quaternion> rotations;
        JobHandle job;
        bool running, dirty;

        // A character with its bones (one per model node) and the animations it can play (`anims`, from
        // its level entry; null: none). Its bones keep their bind pose until it plays something.
        public CharacterAnimation Add(LoadedModel model, Transform[] bones, AnimRefJson[] anims)
        {
            var c = new CharacterAnimation(model, bones, anims, () => job.Complete());
            characters.Add(c);
            dirty = true;
            return c;
        }

        // Called once every character of the level is registered; later ones join on the next frame.
        public void Begin() => running = true;

        void Rebuild()
        {
            job.Complete();
            Dispose();
            var targets = new List<Transform>();
            foreach (var c in characters)
            {
                c.slotBase = targets.Count;
                targets.AddRange(c.bones);
            }
            transforms = new TransformAccessArray(targets.ToArray());
            positions = new NativeArray<Vector3>(targets.Count, Allocator.Persistent);
            rotations = new NativeArray<Quaternion>(targets.Count, Allocator.Persistent);
            dirty = false;
        }

        void Update()
        {
            if (!running || characters.Count == 0) return;
            job.Complete();   // normally done in LateUpdate
            if (dirty) Rebuild();
            float dt = Time.deltaTime;
            foreach (var c in characters)
            {
                c.track.Advance(dt);
                c.Pose(positions, rotations);
            }
            job = new PoseJob { positions = positions, rotations = rotations }.Schedule(transforms);
        }

        // Before rendering: the skinned meshes read the bones.
        void LateUpdate() => job.Complete();

        void Dispose()
        {
            if (transforms.isCreated) transforms.Dispose();
            if (positions.IsCreated) positions.Dispose();
            if (rotations.IsCreated) rotations.Dispose();
        }

        void OnDestroy()
        {
            job.Complete();
            Dispose();
        }

        // t (seconds, already wrapped: AnimTracker loops with t %= lastKeyTime) lies between key k and k + 1
        // at fraction f. k is the last key with time <= t, so a zero-length interval between two keys
        // sharing a time is never used (tools/animation.py key_at).
        internal static void Key(float[] d, ModelAnimJson a, float t, out int k, out float f)
        {
            int lo = 0, hi = a.keys - 1;
            while (lo < hi)
            {
                int mid = (lo + hi + 1) >> 1;
                if (d[a.times + mid] <= t) lo = mid; else hi = mid - 1;
            }
            k = lo;
            if (k + 1 >= a.keys) { f = 0; return; }
            float t0 = d[a.times + k], t1 = d[a.times + k + 1];
            f = t1 > t0 ? Mathf.Clamp01((t - t0) / (t1 - t0)) : 0;
        }

        // Positions interpolate linearly, rotations by slerp (TransformMaker / quat_Slerp: shortest path).
        internal static Vector3 Position(float[] d, ModelAnimJson a, int node, int k, float f)
        {
            int o = a.channels[node * 4], n = a.channels[node * 4 + 1];
            if (n <= 1) return new Vector3(d[o], d[o + 1], d[o + 2]);
            int p = o + k * 3, q = o + Mathf.Min(k + 1, n - 1) * 3;
            return Vector3.LerpUnclamped(new Vector3(d[p], d[p + 1], d[p + 2]), new Vector3(d[q], d[q + 1], d[q + 2]), f);
        }

        internal static Quaternion Rotation(float[] d, ModelAnimJson a, int node, int k, float f)
        {
            int o = a.channels[node * 4 + 2], n = a.channels[node * 4 + 3];
            if (n <= 1) return new Quaternion(d[o], d[o + 1], d[o + 2], d[o + 3]);
            int p = o + k * 4, q = o + Mathf.Min(k + 1, n - 1) * 4;
            return Quaternion.Slerp(new Quaternion(d[p], d[p + 1], d[p + 2], d[p + 3]), new Quaternion(d[q], d[q + 1], d[q + 2], d[q + 3]), f);
        }

        // A scale channel (scales: offset, count): linear between keys, a constant when count is 1.
        internal static float Scale(float[] d, int offset, int count, int k, float f) =>
            count <= 1 ? d[offset] : Mathf.LerpUnclamped(d[offset + k], d[offset + Mathf.Min(k + 1, count - 1)], f);

        struct PoseJob : IJobParallelForTransform
        {
            [ReadOnly] public NativeArray<Vector3> positions;
            [ReadOnly] public NativeArray<Quaternion> rotations;

            public void Execute(int i, TransformAccess t)
            {
                t.localPosition = positions[i];
                t.localRotation = rotations[i];
            }
        }
    }
}
