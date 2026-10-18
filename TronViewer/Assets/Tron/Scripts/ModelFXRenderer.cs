using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Tron
{
    // An LTBModel or LTBBouncyChunk key's look, built once per level (LevelBuilder.SpecialFX): its model, the mesh and
    // materials its pieces draw with, the clip it plays (null = none) and its lighting inputs.
    public sealed class FxModelLook
    {
        public LoadedModel Model;
        public Mesh Mesh;
        public Material[] Materials;
        public ModelAnimJson Clip;
        public bool Moves;   // the clip keys a node or a scale: posed every frame
        public Vector3 Dims;
        public float VisRadius;
    }

    // Draws the level's effect models (FxModel) and chunks (FxChunk) as the level's other models are drawn:
    // a renderer per effect with its look's materials (so they reach the glow buffer through [GlowRSMap]),
    // placed, turned and scaled as the effect says, posed at its clip time when the clip moves, lit by
    // ModelLighting where it is (again once it has moved 32 units, and every frame a dynamic light reaches
    // it), or full bright (FLAG_NOLIGHT: ambient white, no lights), with the lights scaled by its colour and its
    // lit passes faded by its alpha. Renderers are pooled per key: an effect that ends hands its renderer to the
    // next one the same key makes. Runs after the effect manager (ClientFXTicker) and the dynamic lights.
    [DefaultExecutionOrder(60)]
    public class ModelFXRenderer : MonoBehaviour
    {
        public ClientFXMgr Effects;
        public ModelLighting Lighting;
        public Dictionary<FxKey, FxModelLook> Looks;

        const float RelightDistance = 32;

        static readonly int AmbientId = Shader.PropertyToID("_LTAmbient");
        static readonly int LightDirId = Shader.PropertyToID("_LTLightDir");
        static readonly int LightColorId = Shader.PropertyToID("_LTLightColor");
        static readonly int TransparencyId = Shader.PropertyToID("_LTTransparency");

        sealed class View
        {
            public FxKey Key;
            public FxModelLook Look;
            public Transform T;
            public Renderer R;
            public Transform[] Bones;
            public int Frame;
            public Vector3 LitAt;
            public bool Lit, DynLit;
            public Vector3 Ambient;
            public readonly Vector4[] Dirs = new Vector4[ModelLighting.MaxLights];
            public readonly Vector4[] Colors = new Vector4[ModelLighting.MaxLights];
            public Color Colour = new Color(-1, 0, 0, 0);
            public float PosedAt = -1;
        }

        readonly Dictionary<IFxModelView, View> views = new Dictionary<IFxModelView, View>();
        readonly Dictionary<FxKey, Stack<View>> pool = new Dictionary<FxKey, Stack<View>>();
        readonly List<IFxModelView> gone = new List<IFxModelView>();
        readonly Vector4[] scaled = new Vector4[ModelLighting.MaxLights];
        MaterialPropertyBlock mpb;
        Transform container;

        void LateUpdate()
        {
            if (Effects == null) return;
            int frame = Time.frameCount;
            foreach (var inst in Effects.Instances)
                foreach (var fx in inst.Effects)
                {
                    if (!(fx is IFxModelView m)) continue;
                    if (!views.TryGetValue(m, out var v))
                    {
                        v = Acquire(m);
                        if (v == null) continue;
                        views[m] = v;
                    }
                    v.Frame = frame;
                    Draw(m, v);
                }
            foreach (var kv in views)
                if (kv.Value.Frame != frame) gone.Add(kv.Key);
            foreach (var m in gone)
            {
                var v = views[m];
                views.Remove(m);
                m.Nodes = null;
                v.R.enabled = false;
                pool[v.Key].Push(v);
            }
            gone.Clear();
        }

        View Acquire(IFxModelView m)
        {
            var key = m.Effect.Key;
            if (!Looks.TryGetValue(key, out var look)) return null;
            if (!pool.TryGetValue(key, out var free)) pool[key] = free = new Stack<View>();
            var v = free.Count > 0 ? free.Pop() : Create(key, look);
            v.PosedAt = -1;
            m.Nodes = (string name, bool socket, out LTVec pos, out LTQuat rot) => Attachment(v, name, socket, out pos, out rot);
            return v;
        }

        View Create(FxKey key, FxModelLook look)
        {
            if (!container)
            {
                container = new GameObject("FX models").transform;
                container.SetParent(transform, false);
            }
            var go = new GameObject($"{key.Label} [{look.Model.data.file}]");
            go.transform.SetParent(container, false);
            var v = new View { Key = key, Look = look, T = go.transform };
            if (look.Clip != null)
            {
                // Bones as the model's nodes at the clip's first frame; skinned like the characters.
                v.Bones = new Transform[look.Model.data.nodes.Length];
                for (int i = 0; i < v.Bones.Length; i++)
                {
                    var b = new GameObject(look.Model.data.nodes[i].name).transform;
                    int parent = look.Model.data.nodes[i].parent;
                    b.SetParent(parent >= 0 ? v.Bones[parent] : go.transform, false);
                    v.Bones[i] = b;
                }
                Pose(v, 0);
                var smr = go.AddComponent<SkinnedMeshRenderer>();
                smr.sharedMesh = look.Mesh;
                smr.bones = v.Bones;
                // The model's visibility radius (the engine culls models by it) covers what the clip moves.
                float rad = Mathf.Max(look.VisRadius, look.Mesh.bounds.max.magnitude, look.Mesh.bounds.min.magnitude);
                smr.localBounds = new Bounds(Vector3.zero, Vector3.one * 2 * rad);
                v.R = smr;
            }
            else
            {
                go.AddComponent<MeshFilter>().sharedMesh = look.Mesh;
                v.R = go.AddComponent<MeshRenderer>();
            }
            v.R.sharedMaterials = look.Materials;
            v.R.shadowCastingMode = ShadowCastingMode.Off;
            v.R.receiveShadows = false;
            v.R.lightProbeUsage = LightProbeUsage.Off;
            v.R.reflectionProbeUsage = ReflectionProbeUsage.Off;
            v.R.enabled = false;
            return v;
        }

        void Draw(IFxModelView m, View v)
        {
            if (!m.Shown)
            {
                if (v.R.enabled) v.R.enabled = false;
                return;
            }
            var fx = m.Effect;
            LTVec p = m.ModelPos;
            LTQuat q = m.ModelRot;
            var pos = new Vector3(p.x, p.y, p.z);
            v.T.SetLocalPositionAndRotation(pos, new Quaternion(q.x, q.y, q.z, q.w));
            v.T.localScale = Vector3.one * fx.Scale;
            if (v.Bones != null && (v.Look.Moves || v.PosedAt < 0) && m.AnimTime != v.PosedAt)
            {
                Pose(v, m.AnimTime);
                v.PosedAt = m.AnimTime;
            }
            bool relight = !v.Lit || (pos - v.LitAt).sqrMagnitude > RelightDistance * RelightDistance;
            // A dynamic light changes every frame: lit again while one reaches it, and once more when none does.
            bool dyn = !m.NoLight && Lighting != null && Lighting.Touches(pos, v.Look.VisRadius);
            relight |= dyn || v.DynLit;
            v.DynLit = dyn;
            if (relight && m.NoLight)
            {
                v.Ambient = Vector3.one;
                System.Array.Clear(v.Dirs, 0, v.Dirs.Length);
                System.Array.Clear(v.Colors, 0, v.Colors.Length);
                v.Lit = true;
            }
            else if (relight)
            {
                v.Ambient = Lighting != null ? Lighting.Compute(pos, v.Look.Dims, v.Look.VisRadius, 0, v.Dirs, v.Colors) / 255f : Vector3.zero;
                ModelLighting.ToUnit(v.Colors);
                v.LitAt = pos;
                v.Lit = true;
            }
            var c = new Color(fx.R, fx.G, fx.B, fx.A);
            if (relight || c != v.Colour)
            {
                v.Colour = c;
                mpb ??= new MaterialPropertyBlock();
                mpb.Clear();
                var rgb = new Vector4(c.r, c.g, c.b, 1);
                mpb.SetVector(AmbientId, Vector4.Scale(v.Ambient, rgb));
                for (int i = 0; i < scaled.Length; i++) scaled[i] = Vector4.Scale(v.Colors[i], rgb);
                mpb.SetVectorArray(LightDirId, v.Dirs);
                mpb.SetVectorArray(LightColorId, scaled);
                mpb.SetFloat(TransparencyId, 1 - c.a);
                v.R.SetPropertyBlock(mpb);
            }
            if (!v.R.enabled) v.R.enabled = true;
        }

        // The clip at t on the bones (positions, rotations, the uniform scales of vertex-animated pieces).
        static void Pose(View v, float t)
        {
            var clip = v.Look.Clip;
            var d = v.Look.Model.animData;
            ModelAnimator.Key(d, clip, Mathf.Min(t, clip.length), out int k, out float f);
            var bones = v.Bones;
            for (int n = 0; n < bones.Length; n++)
                bones[n].SetLocalPositionAndRotation(ModelAnimator.Position(d, clip, n, k, f), ModelAnimator.Rotation(d, clip, n, k, f));
            var sc = clip.scales;
            for (int i = 0; sc != null && i + 2 < sc.Length; i += 3)
                if (sc[i] < bones.Length) bones[sc[i]].localScale = Vector3.one * ModelAnimator.Scale(d, sc[i + 1], sc[i + 2], k, f);
        }

        // GetNodeTransform / GetSocketTransform in the level: the posed node (the bind pose without a clip),
        // a socket on it.
        bool Attachment(View v, string name, bool socket, out LTVec pos, out LTQuat rot)
        {
            pos = default;
            rot = default;
            var data = v.Look.Model.data;
            int node = -1;
            var lp = Vector3.zero;
            Quaternion lr = Quaternion.identity;
            if (socket)
            {
                var s = data.sockets == null ? null : Array.Find(data.sockets, x => string.Equals(x.name, name, StringComparison.OrdinalIgnoreCase));
                if (s == null) return false;
                node = s.node;
                lp = new Vector3(s.pos[0], s.pos[1], s.pos[2]);
                lr = new Quaternion(s.rot[0], s.rot[1], s.rot[2], s.rot[3]);
            }
            else node = Array.FindIndex(data.nodes, x => string.Equals(x.name, name, StringComparison.OrdinalIgnoreCase));
            if (node < 0) return false;
            Matrix4x4 world;
            if (v.Bones != null) world = container.worldToLocalMatrix * v.Bones[node].localToWorldMatrix;
            else world = Matrix4x4.TRS(v.T.localPosition, v.T.localRotation, v.T.localScale) * v.Look.Model.BindMatrix(node);
            var p = world.MultiplyPoint3x4(lp);
            var r = world.rotation * lr;
            pos = new LTVec(p.x, p.y, p.z);
            rot = new LTQuat(r.x, r.y, r.z, r.w);
            return true;
        }
    }
}
