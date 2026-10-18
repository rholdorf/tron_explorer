using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // The level's dynamic lights each frame (the shown DynaLight effects of every running instance, with a
    // radius) into ModelLighting.Dynamic, and the placed models they reach lit again with them (and once more
    // when none does), as the engine sets up every model's lights each frame. The placed models are otherwise
    // lit once, when the level is built. Runs after the effect manager (ClientFXTicker), before the effect
    // models are drawn (ModelFXRenderer, which relights its own).
    [DefaultExecutionOrder(55)]
    public class DynamicLights : MonoBehaviour
    {
        public ClientFXMgr Effects;
        public ModelLighting Lighting;

        // A placed model's lighting inputs (LevelBuilder.BuildModels).
        public sealed class Model
        {
            public Renderer R;
            public Vector3 Pos, Dims;
            public float VisRadius, SunAmount;
            public bool Dyn;
        }

        public readonly List<Model> Models = new List<Model>();

        static readonly int AmbientId = Shader.PropertyToID("_LTAmbient");
        static readonly int LightDirId = Shader.PropertyToID("_LTLightDir");
        static readonly int LightColorId = Shader.PropertyToID("_LTLightColor");
        readonly Vector4[] dirs = new Vector4[ModelLighting.MaxLights], colors = new Vector4[ModelLighting.MaxLights];
        MaterialPropertyBlock mpb;

        void LateUpdate()
        {
            if (Effects == null || Lighting == null) return;
            Lighting.Dynamic.Clear();
            foreach (var inst in Effects.Instances)
                foreach (var fx in inst.Effects)
                    if (fx is FxDynaLight d && d.Visible && d.Radius > 0)
                        Lighting.Dynamic.Add(new ModelLighting.DynamicLight
                        {
                            Pos = new Vector3(d.Pos.x, d.Pos.y, d.Pos.z),
                            Color = new Vector3(d.Color.x, d.Color.y, d.Color.z),
                            Radius = d.Radius,
                        });
            foreach (var m in Models)
            {
                bool dyn = Lighting.Dynamic.Count > 0 && Lighting.Touches(m.Pos, m.VisRadius);
                if (!dyn && !m.Dyn) continue;
                m.Dyn = dyn;
                if (!m.R) continue;
                var ambient = Lighting.Compute(m.Pos, m.Dims, m.VisRadius, m.SunAmount, dirs, colors);
                ModelLighting.ToUnit(colors);
                mpb ??= new MaterialPropertyBlock();
                mpb.Clear();
                mpb.SetVector(AmbientId, ambient / 255f);
                mpb.SetVectorArray(LightDirId, dirs);
                mpb.SetVectorArray(LightColorId, colors);
                m.R.SetPropertyBlock(mpb);
            }
        }
    }
}
