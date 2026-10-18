using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // The level's SpecialFX objects (SpecialFX) and the effect groups they reach (level.json fxGroups,
    // ClientFXMgr). Each object joins the command manager with its GameBase handler first (HIDDEN and
    // VISIBLE change nothing it shows; REMOVE shuts a loop down) and then its own messages. It has a
    // transform keyframers can move; ClientFXTicker reads it each frame. Templates are never created.
    // StartOn objects turn on once every object exists (MID_ALLOBJECTSCREATED: StartSpecialFX, after the
    // relays). Effect keys whose type has no look yet count in the report as "FX <type> (NO LOOK)", once
    // per placed object. Types with a look: ParticleSystem (ParticleRenderer), LTBModel (ModelFXRenderer, keys
    // whose model loads), PlaySound (FxSoundPlayer; files load with the level, so missing ones are reported
    // with it). Effects bounce and splat on
    // the world's colliders (IntersectSegment hits the world only, so characters' and the player's
    // controllers don't count).
    public partial class LevelBuilder
    {
        public ClientFXMgr Effects;
        public Shader EffectShader;
        readonly RaycastHit[] fxHits = new RaycastHit[8];
        readonly Dictionary<int, Transform> specialFXObjects = new Dictionary<int, Transform>();
        readonly List<SpecialFX> startOn = new List<SpecialFX>();

        void BuildSpecialFX(string exportRoot)
        {
            Effects = new ClientFXMgr();
            var looks = new Dictionary<FxKey, FxModelLook>();
            foreach (var g in Data.fxGroups ?? new FxGroupJson[0])
            {
                var group = g.Group();
                Effects.Add(group);
                for (int i = 0; i < group.Keys.Length; i++)
                {
                    if (g.fx[i].type == "LTBModel" && ModelFXLook(exportRoot, g.fx[i]) is FxModelLook look) looks[group.Keys[i]] = look;
                    if (g.fx[i].type == "PlaySound") SoundLoader.Load(group.Keys[i].Str("Sound"));
                }
            }
            var effects = Effects;
            effects.Types["ParticleSystem"] = k => new FxParticleSystem(effects);
            effects.Types["LTBModel"] = k => looks.TryGetValue(k, out var l) ? new FxModel(effects, l.Clip != null ? l.Clip.length : -1) : null;
            var sounds = Root.AddComponent<FxSoundPlayer>();
            effects.Types["PlaySound"] = k => new FxSound(sounds.Play);
            effects.Intersect = IntersectWorld;
            var ticker = Root.AddComponent<ClientFXTicker>();
            ticker.Effects = Effects;
            var particles = Root.AddComponent<ParticleRenderer>();
            particles.Effects = Effects;
            particles.Shader = EffectShader;
            var models = Root.AddComponent<ModelFXRenderer>();
            models.Effects = Effects;
            models.Lighting = lighting;
            models.Looks = looks;
            GameObject parent = null;
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                if (o.cls != "SpecialFX" || o.Bool("Template")) continue;
                if (!parent)
                {
                    parent = new GameObject("SpecialFX");
                    parent.transform.SetParent(Root.transform, false);
                }
                var go = new GameObject(o.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = o.Position;
                var rot = LTQuat.FromEuler(o.rot[0], o.rot[1], o.rot[2]);
                go.transform.localRotation = new Quaternion(rot.x, rot.y, rot.z, rot.w);
                var fx = new SpecialFX(Effects, o.Str("FxName"), o.Bool("Loop", true), o.Bool("SmoothShutdown", true),
                    o.Bool("OneTime"), o.LTPosition, rot);
                var flags = JoinFlags(i, StartFlags.Visible, null, fx.Remove);
                fx.RemoveObject = () => flags.OnMessage(new Message(new[] { "REMOVE" }, -1));
                Commands.Handle(i, fx.OnMessage);
                ticker.Objects.Add((fx, go.transform));
                specialFXObjects[i] = go.transform;
                if (o.Bool("StartOn", true)) startOn.Add(fx);
                var group = Effects.Find(fx.FxName);
                if (group == null) continue;
                foreach (var k in group.Keys)
                    if (!Effects.HasLook(k.Type)) Commands.Count("FX", k.Type, "(no look)");
            }
        }

        // An LTBModel key's look: its model with its pieces' styles, its clip. None when the model doesn't load.
        FxModelLook ModelFXLook(string exportRoot, FxKeyJson k)
        {
            var file = k.props == null ? null : Array.Find(k.props, p => p.k == "Model")?.s;
            if (string.IsNullOrEmpty(file) || k.pieces == null || k.pieces.Length == 0) return null;
            var model = ModelLibrary.Load(exportRoot, file, loadedModels, owned);
            if (model == null) return null;
            if (k.pieces.Length != model.data.pieces.Length)
            {
                Debug.LogWarning($"Effect model {file}: {k.pieces.Length} piece styles for {model.data.pieces.Length} pieces");
                return null;
            }
            var (mesh, mats) = ModelLook(model, k.pieces);
            int a = model.FindAnim(k.anim);
            var clip = a >= 0 ? model.data.anims[a] : null;
            bool moves = false;
            if (clip != null)
            {
                for (int n = 0; n + 3 < clip.channels.Length; n += 4)
                    moves |= clip.channels[n + 1] > 1 || clip.channels[n + 3] > 1;
                moves |= clip.scales != null && clip.scales.Length > 0;
            }
            var d = k.dims != null && k.dims.Length >= 3 ? new Vector3(k.dims[0], k.dims[1], k.dims[2]) : Vector3.zero;
            return new FxModelLook { Model = model, Mesh = mesh, Materials = mats, Clip = clip, Moves = moves, Dims = d, VisRadius = k.visRadius };
        }

        bool IntersectWorld(LTVec from, LTVec to, out LTVec point, out LTVec normal)
        {
            point = normal = default;
            var root = Root.transform;
            var a = root.TransformPoint(new Vector3(from.x, from.y, from.z));
            var d = root.TransformPoint(new Vector3(to.x, to.y, to.z)) - a;
            float len = d.magnitude;
            if (len <= 0) return false;
            int n = Physics.RaycastNonAlloc(a, d / len, fxHits, len, ~(1 << UseOnlyLayer), QueryTriggerInteraction.Ignore);
            int best = -1;
            for (int i = 0; i < n; i++)
                if (!(fxHits[i].collider is CharacterController) && (best < 0 || fxHits[i].distance < fxHits[best].distance))
                    best = i;
            if (best < 0) return false;
            var p = root.InverseTransformPoint(fxHits[best].point);
            var nr = root.InverseTransformDirection(fxHits[best].normal);
            point = new LTVec(p.x, p.y, p.z);
            normal = new LTVec(nr.x, nr.y, nr.z);
            return true;
        }

        void StartSpecialFX()
        {
            foreach (var fx in startOn) fx.TurnOn();
            startOn.Clear();
        }
    }
}
