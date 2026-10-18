using System.Collections.Generic;
using Unity.Collections;
using Unity.Jobs;
using UnityEngine;
using UnityEngine.Jobs;

namespace Tron
{
    // Loops the characters' clips (tools/animation.py, exported by tools/export_models.py) on their bone
    // Transforms. All characters start their clip when the level loads, as the game's AIs do when they
    // spawn together, so each clip is sampled once per frame for every character playing it; a transform
    // job then writes the keyed nodes' local poses. Constant channels are set once, in Play.
    public class ModelAnimator : MonoBehaviour
    {
        class Clip
        {
            public LoadedModel model;
            public ModelAnimJson anim;
            public int[] keyed;      // nodes with a keyed channel
            public int poseBase;     // their first slot in the pose arrays
        }

        readonly Dictionary<(LoadedModel, int), Clip> clips = new Dictionary<(LoadedModel, int), Clip>();
        readonly List<Clip> clipList = new List<Clip>();
        readonly List<Transform> targets = new List<Transform>();
        readonly List<int> targetSlots = new List<int>();
        int poseCount;
        TransformAccessArray transforms;
        NativeArray<Vector3> positions;
        NativeArray<Quaternion> rotations;
        NativeArray<int> slots;
        JobHandle job;
        float startTime;
        bool running;

        // Poses `bones` (one per model node) at frame 0 of the model's clip `name` and, if the clip moves,
        // loops it. False if the model has no such clip.
        public bool Play(LoadedModel model, string name, Transform[] bones)
        {
            int index = model.FindAnim(name);
            if (index < 0) return false;
            var anim = model.data.anims[index];
            var d = model.animData;
            for (int n = 0; n < bones.Length; n++)
                bones[n].SetLocalPositionAndRotation(Position(d, anim, n, 0, 0), Rotation(d, anim, n, 0, 0));
            if (anim.length <= 0) return true;
            if (!clips.TryGetValue((model, index), out var clip))
            {
                var keyed = new List<int>();
                for (int n = 0; n < bones.Length; n++)
                    if (anim.channels[n * 4 + 1] > 1 || anim.channels[n * 4 + 3] > 1) keyed.Add(n);
                if (keyed.Count == 0) return true;
                clip = new Clip { model = model, anim = anim, keyed = keyed.ToArray(), poseBase = poseCount };
                poseCount += clip.keyed.Length;
                clips[(model, index)] = clip;
                clipList.Add(clip);
            }
            for (int i = 0; i < clip.keyed.Length; i++)
            {
                targets.Add(bones[clip.keyed[i]]);
                targetSlots.Add(clip.poseBase + i);
            }
            return true;
        }

        // Called once every character is registered.
        public void Begin()
        {
            if (targets.Count == 0) return;
            transforms = new TransformAccessArray(targets.ToArray());
            positions = new NativeArray<Vector3>(poseCount, Allocator.Persistent);
            rotations = new NativeArray<Quaternion>(poseCount, Allocator.Persistent);
            slots = new NativeArray<int>(targetSlots.ToArray(), Allocator.Persistent);
            targets.Clear();
            targetSlots.Clear();
            startTime = Time.time;
            running = true;
        }

        void Update()
        {
            if (!running) return;
            job.Complete();   // normally done in LateUpdate
            float t = Time.time - startTime;
            foreach (var c in clipList)
            {
                var d = c.model.animData;
                var a = c.anim;
                Key(d, a, t % a.length, out int k, out float f);
                for (int i = 0; i < c.keyed.Length; i++)
                {
                    positions[c.poseBase + i] = Position(d, a, c.keyed[i], k, f);
                    rotations[c.poseBase + i] = Rotation(d, a, c.keyed[i], k, f);
                }
            }
            job = new PoseJob { positions = positions, rotations = rotations, slots = slots }.Schedule(transforms);
        }

        // Before rendering: the skinned meshes read the bones.
        void LateUpdate() => job.Complete();

        void OnDestroy()
        {
            job.Complete();
            if (transforms.isCreated) transforms.Dispose();
            if (positions.IsCreated) positions.Dispose();
            if (rotations.IsCreated) rotations.Dispose();
            if (slots.IsCreated) slots.Dispose();
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
            [ReadOnly] public NativeArray<int> slots;

            public void Execute(int i, TransformAccess t)
            {
                int s = slots[i];
                t.localPosition = positions[s];
                t.localRotation = rotations[s];
            }
        }
    }
}
