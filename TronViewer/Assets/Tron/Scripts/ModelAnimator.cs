using System;
using System.Collections.Generic;
using System.Linq;
using Unity.Collections;
using Unity.Jobs;
using UnityEngine;
using UnityEngine.Jobs;

namespace Tron
{
    // A character's animations: the ones it can play by name (its model's, its .ltb children's and its
    // ChildModel_N files', tools/animation.py playable) and where it is in them (AnimTrack: looping or once,
    // the blend into a clip that starts). ModelAnimator poses its bones every frame.
    //
    // The job poses only the bones that can move (`moving`): the ones keyed in any of its clips or whose
    // constant pose differs between them, and the ones head tracking turns (AlwaysPose); the others keep the
    // pose a cut (Play) gave them. While a clip plays (not blending), only its keyed bones are sampled.
    public sealed class CharacterAnimation : IActorAnimation
    {
        internal readonly LoadedModel model;
        internal readonly Transform[] bones;
        internal readonly ModelAnimJson[] anims;   // per track clip, the model's clip
        internal readonly AnimTrack track;
        readonly Dictionary<string, int> byName = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        readonly ModelAnimator owner;
        readonly List<string[]> keyTexts = new List<string[]>();   // per track clip, its animation keys in time order
        readonly int[][] keyed;        // per track clip, its nodes with a keyed channel
        readonly bool[][] isKeyed;     // per track clip, per node
        readonly bool[] always;        // per node: posed every frame (head tracking turns it after the job)
        readonly List<int> alwaysList = new List<int>();
        internal int[] moving;         // the nodes the job poses, in slot order
        internal int[] slotOf;         // per node, its slot after slotBase; -1 when the job leaves it
        bool settled;                  // its moving bones hold the playing clip's pose, so only keyed ones change

        // Each animation key its animation crosses (the clip's cmds: "cmd msg ...", FOOTSTEP_KEY...), as it does.
        public Action<string> OnKey;
        internal int slotBase;

        internal CharacterAnimation(LoadedModel model, Transform[] bones, AnimRefJson[] refs, ModelAnimator owner)
        {
            this.model = model;
            this.bones = bones;
            this.owner = owner;
            var anims = new List<ModelAnimJson>();
            var infos = new List<AnimTrack.ClipInfo>();
            foreach (var r in refs ?? Array.Empty<AnimRefJson>())
            {
                int i = model.FindAnim(r.name, r.@from);
                if (i < 0 || byName.ContainsKey(r.name)) continue;
                var a = model.data.anims[i];
                byName[r.name] = anims.Count;
                anims.Add(a);
                infos.Add(ModelAnimator.ClipInfo(model, a, a.interp, out var texts));
                keyTexts.Add(texts);
            }
            this.anims = anims.ToArray();
            track = new AnimTrack(infos);
            keyed = new int[this.anims.Length][];
            isKeyed = new bool[this.anims.Length][];
            for (int c = 0; c < this.anims.Length; c++)
            {
                isKeyed[c] = new bool[bones.Length];
                var list = new List<int>();
                for (int n = 0; n < bones.Length; n++)
                    if (ModelAnimator.Keyed(this.anims[c], n))
                    {
                        isKeyed[c][n] = true;
                        list.Add(n);
                    }
                keyed[c] = list.ToArray();
            }
            always = new bool[bones.Length];
            Layout();
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
            FlushKeys();
            settled = false;
            if (!track.Blending)
            {
                // A cut shows the clip's first key at once (the level's bounds are taken from it).
                owner.Settle();
                var d = model.animData;
                var a = anims[track.Clip];
                for (int n = 0; n < bones.Length; n++)
                    bones[n].SetLocalPositionAndRotation(ModelAnimator.Position(d, a, n, 0, 0), ModelAnimator.Rotation(d, a, n, 0, 0));
            }
            return true;
        }

        // The animation playing starts over at its time 0, looping or once, without a blend (a missing animation
        // in a goal script: SetModelLooping, ResetModelAnimation).
        public void Restart(bool loop)
        {
            track.Restart(loop);
            FlushKeys();
        }

        // Node n is posed every frame, keyed or not: head tracking turns it over the animation after the job.
        internal void AlwaysPose(int n)
        {
            if (n < 0 || n >= always.Length || always[n]) return;
            always[n] = true;
            alwaysList.Add(n);
            Layout();
            owner.Relayout();
        }

        // The moving nodes: keyed in a clip, a constant pose that differs between its clips, or always posed.
        void Layout()
        {
            var d = model.animData;
            var list = new List<int>();
            slotOf = new int[bones.Length];
            for (int n = 0; n < bones.Length; n++)
            {
                bool moves = always[n];
                for (int c = 0; c < anims.Length && !moves; c++)
                    moves = isKeyed[c][n] || !SamePose(d, anims[c], anims[0], n);
                slotOf[n] = moves ? list.Count : -1;
                if (moves) list.Add(n);
            }
            moving = list.ToArray();
            settled = false;
        }

        // Node n's first key is the same in both clips, exactly (Unity's == is approximate).
        static bool SamePose(float[] d, ModelAnimJson a, ModelAnimJson b, int n)
        {
            Vector3 p = ModelAnimator.Position(d, a, n, 0, 0), q = ModelAnimator.Position(d, b, n, 0, 0);
            Quaternion r = ModelAnimator.Rotation(d, a, n, 0, 0), s = ModelAnimator.Rotation(d, b, n, 0, 0);
            return p.x == q.x && p.y == q.y && p.z == q.z && r.x == s.x && r.y == s.y && r.z == s.z && r.w == s.w;
        }

        internal void FlushKeys()
        {
            if (track.Fired.Count == 0) return;
            foreach (var (clip, key) in track.Fired) OnKey?.Invoke(keyTexts[clip][key]);
            track.Fired.Clear();
        }

        // The animation playing (its name as the model has it), "" for none.
        public string Current => track.Clip >= 0 ? anims[track.Clip].name : "";
        public bool Looping => track.Looping;
        // Played once and past its last key (MS_PLAYDONE): the goal script's cue that it ended.
        public bool Done => track.Done;
        // Seconds into the playing animation (0 while blending in).
        public float Time => track.Time;

        // Its moving bones' local poses now into the arrays at slotBase, and per slot where the job takes its
        // pose from (-1: the bone is left as it is). A character playing the same clip at the same key and
        // fraction as one posed earlier this frame (`shared`) takes that one's keyed poses.
        internal void Pose(NativeArray<Vector3> positions, NativeArray<Quaternion> rotations, NativeArray<int> slots,
                           Dictionary<(ModelAnimJson, int, float), CharacterAnimation> shared)
        {
            for (int i = 0; i < moving.Length; i++) slots[slotBase + i] = -1;
            if (track.Clip < 0) return;
            var d = model.animData;
            var a = anims[track.Clip];
            if (track.Blending)
            {
                var from = anims[track.FromClip];
                float w = track.Weight;
                for (int i = 0; i < moving.Length; i++)
                {
                    int n = moving[i], s = slotBase + i;
                    positions[s] = Vector3.LerpUnclamped(ModelAnimator.Position(d, from, n, track.FromKey, 0),
                        ModelAnimator.Position(d, a, n, 0, 0), w);
                    rotations[s] = Quaternion.Slerp(ModelAnimator.Rotation(d, from, n, track.FromKey, 0),
                        ModelAnimator.Rotation(d, a, n, 0, 0), w);
                    slots[s] = s;
                }
                settled = false;
                return;
            }
            track.Key(out int k, out float f);
            if (!settled)
            {
                // After a blend, a cut or a new layout: every moving bone once, then only the keyed ones.
                foreach (int n in moving) Sample(d, a, n, k, f, positions, rotations, slots);
                settled = true;
                return;
            }
            if (shared.TryGetValue((a, k, f), out var other))
                foreach (int n in keyed[track.Clip]) slots[slotBase + slotOf[n]] = other.slotBase + other.slotOf[n];
            else
            {
                shared[(a, k, f)] = this;
                foreach (int n in keyed[track.Clip]) Sample(d, a, n, k, f, positions, rotations, slots);
            }
            var clipKeyed = isKeyed[track.Clip];
            foreach (int n in alwaysList)
                if (!clipKeyed[n]) Sample(d, a, n, k, f, positions, rotations, slots);
        }

        void Sample(float[] d, ModelAnimJson a, int n, int k, float f, NativeArray<Vector3> positions,
                    NativeArray<Quaternion> rotations, NativeArray<int> slots)
        {
            int s = slotBase + slotOf[n];
            positions[s] = ModelAnimator.Position(d, a, n, k, f);
            rotations[s] = ModelAnimator.Rotation(d, a, n, k, f);
            slots[s] = s;
        }
    }

    // Plays the characters' animations (tools/animation.py clips, exported by tools/export_models.py) on their
    // bone Transforms: each frame every character's track advances and its moving bones' local poses are
    // sampled (once per clip, key and fraction for characters at the same place in the same clip), then a
    // transform job writes them. All characters start their idle when the level loads, as the game's AIs do
    // when they spawn together.
    public class ModelAnimator : MonoBehaviour
    {
        readonly List<CharacterAnimation> characters = new List<CharacterAnimation>();
        readonly Dictionary<(ModelAnimJson, int, float), CharacterAnimation> shared =
            new Dictionary<(ModelAnimJson, int, float), CharacterAnimation>();
        TransformAccessArray transforms;
        NativeArray<Vector3> positions;
        NativeArray<Quaternion> rotations;
        NativeArray<int> slots;
        JobHandle job;
        bool running, dirty;

        // A character with its bones (one per model node) and the animations it can play (`anims`, from
        // its level entry; null: none). Its bones keep their bind pose until it plays something.
        public CharacterAnimation Add(LoadedModel model, Transform[] bones, AnimRefJson[] anims)
        {
            var c = new CharacterAnimation(model, bones, anims, this);
            characters.Add(c);
            dirty = true;
            return c;
        }

        // Called once every character of the level is registered; later ones join on the next frame.
        public void Begin() => running = true;

        // Completes the pose job before bones are written outside it.
        internal void Settle() => job.Complete();

        // A character's moving bones changed: the job's transforms are rebuilt on the next frame.
        internal void Relayout() => dirty = true;

        void Rebuild()
        {
            job.Complete();
            Dispose();
            var targets = new List<Transform>();
            foreach (var c in characters)
            {
                c.slotBase = targets.Count;
                foreach (int n in c.moving) targets.Add(c.bones[n]);
            }
            transforms = new TransformAccessArray(targets.ToArray());
            positions = new NativeArray<Vector3>(targets.Count, Allocator.Persistent);
            rotations = new NativeArray<Quaternion>(targets.Count, Allocator.Persistent);
            slots = new NativeArray<int>(targets.Count, Allocator.Persistent);
            dirty = false;
        }

        void Update()
        {
            if (!running || characters.Count == 0) return;
            job.Complete();   // normally done in LateUpdate
            if (dirty) Rebuild();
            float dt = Time.deltaTime;
            shared.Clear();
            foreach (var c in characters)
            {
                c.track.Advance(dt);
                c.FlushKeys();
                c.Pose(positions, rotations, slots, shared);
            }
            job = new PoseJob { positions = positions, rotations = rotations, slots = slots }.Schedule(transforms);
        }

        // Before rendering: the skinned meshes read the bones.
        // Then what turns bones over the animation (head tracking) has them posed.
        public event Action Posed;

        void LateUpdate()
        {
            job.Complete();
            Posed?.Invoke();
        }

        void Dispose()
        {
            if (transforms.isCreated) transforms.Dispose();
            if (positions.IsCreated) positions.Dispose();
            if (rotations.IsCreated) rotations.Dispose();
            if (slots.IsCreated) slots.Dispose();
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

        // Whether node n has a keyed position or rotation in the clip (more than one key).
        internal static bool Keyed(ModelAnimJson a, int n) => a.channels[n * 4 + 1] > 1 || a.channels[n * 4 + 3] > 1;

        // A clip as AnimTrack plays it, blending in over `interp` seconds, its animation keys in time order (their
        // texts in `texts`).
        internal static AnimTrack.ClipInfo ClipInfo(LoadedModel model, ModelAnimJson a, float interp, out string[] texts)
        {
            var times = new float[a.keys];
            Array.Copy(model.animData, a.times, times, 0, a.keys);
            var cmds = (a.cmds ?? Array.Empty<AnimCmdJson>()).OrderBy(c => c.t).ToArray();
            texts = Array.ConvertAll(cmds, c => c.s ?? "");
            return new AnimTrack.ClipInfo { Times = times, Interp = interp, Keys = Array.ConvertAll(cmds, c => c.t) };
        }

        // A scale channel (scales: offset, count): linear between keys, a constant when count is 1.
        internal static float Scale(float[] d, int offset, int count, int k, float f) =>
            count <= 1 ? d[offset] : Mathf.LerpUnclamped(d[offset + k], d[offset + Mathf.Min(k + 1, count - 1)], f);

        struct PoseJob : IJobParallelForTransform
        {
            [ReadOnly] public NativeArray<Vector3> positions;
            [ReadOnly] public NativeArray<Quaternion> rotations;
            [ReadOnly] public NativeArray<int> slots;   // where transform i's pose is; -1: left as it is

            public void Execute(int i, TransformAccess t)
            {
                int s = slots[i];
                if (s < 0) return;
                t.localPosition = positions[s];
                t.localRotation = rotations[s];
            }
        }
    }
}
