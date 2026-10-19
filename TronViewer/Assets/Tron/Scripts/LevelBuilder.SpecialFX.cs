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
    // per placed object. Types with a look: ParticleSystem (ParticleRenderer), LTBModel and LTBBouncyChunk
    // (ModelFXRenderer, keys whose model loads; a chunk without one still moves what is linked to it),
    // CreateFX (it starts its group: ClientFXMgr), PlaySound (FxSoundPlayer; files load with the level, so missing ones are reported
    // with it), Sprite (SpriteDrawer, with the ScaleSprites; lit by the light grid and the dynamic lights where
    // it is when it takes light), LightningFX, PolyTrail and SpriteSystem (DrawPrimRenderer), CamJitter
    // (CameraJitter), DynaLight (DynamicLights: models and lit sprites) and Null (nothing to see; keys can be
    // linked to it). Templates that aim at a TargetObject (m05-01's
    // seekerlightning, at the spawned seeker) count as "FX TargetObject (needs character)", once per object.
    // Effects bounce and splat on
    // the world's colliders (IntersectSegment hits the world only, so characters' and the player's
    // controllers don't count).
    public partial class LevelBuilder
    {
        public ClientFXMgr Effects;
        public Shader EffectShader;
        readonly RaycastHit[] fxHits = new RaycastHit[8];
        // Objects that are only a place (SpecialFX, ScaleSprite): keyframers move their transforms.
        readonly Dictionary<int, Transform> pointObjects = new Dictionary<int, Transform>();
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
                    if ((g.fx[i].type == "LTBModel" || g.fx[i].type == "LTBBouncyChunk") && ModelFXLook(exportRoot, g.fx[i]) is FxModelLook look)
                        looks[group.Keys[i]] = look;
                    if (g.fx[i].type == "PlaySound") SoundLoader.Load(group.Keys[i].Str("Sound"));
                }
            }
            var effects = Effects;
            effects.Types["ParticleSystem"] = k => new FxParticleSystem(effects);
            effects.Types["LTBModel"] = k => looks.TryGetValue(k, out var l) ? new FxModel(effects, l.Clip != null ? l.Clip.length : -1) : null;
            effects.Types["LTBBouncyChunk"] = k => new FxChunk(effects);
            var sounds = Root.AddComponent<FxSoundPlayer>();
            effects.Types["PlaySound"] = k => new FxSound(sounds.Play);
            var light = lighting;
            Func<LTVec, LTVec> lightAt = light == null ? null : p =>
            {
                var l = light.SampleGrid(new Vector3(p.x, p.y, p.z));
                var at = new LTVec(l.x, l.y, l.z);
                foreach (var d in light.Dynamic)
                    at = at + FxDynaLight.SpriteAdd(new LTVec(d.Pos.x, d.Pos.y, d.Pos.z), d.Radius,
                        new LTVec(d.Color.x, d.Color.y, d.Color.z), p);
                return at;
            };
            effects.Types["Sprite"] = k => new FxSprite(effects, lightAt);
            Sprites().Effects = effects;
            effects.Types["LightningFX"] = k => new FxLightning(effects);
            effects.Types["PolyTrail"] = k => new FxPolyTrail();
            effects.Types["SpriteSystem"] = k => new FxSpriteSystem(effects, SpriteFileOf);
            effects.Types["CamJitter"] = k => new FxCamJitter(effects);
            effects.Types["DynaLight"] = k => new FxDynaLight(effects);
            effects.Types["Null"] = k => new FxNull(effects);
            Root.AddComponent<CameraJitter>().Effects = effects;
            var dynamic = Root.AddComponent<DynamicLights>();
            dynamic.Effects = effects;
            dynamic.Lighting = lighting;
            dynamic.Models.AddRange(litModels);
            var prims = Root.AddComponent<DrawPrimRenderer>();
            prims.Effects = effects;
            prims.Shader = EffectShader;
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
                if (o.cls != "SpecialFX") continue;
                if (o.Bool("Template"))
                {
                    if (o.Str("TargetObject") != "") Commands.Count("FX", "TargetObject", "(needs character)");
                    continue;
                }
                if (!parent)
                {
                    parent = new GameObject("SpecialFX");
                    parent.transform.SetParent(Root.transform, false);
                }
                var go = new GameObject(o.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = o.Position;
                var rot = o.LTRotation;
                go.transform.localRotation = new Quaternion(rot.x, rot.y, rot.z, rot.w);
                var fx = new SpecialFX(Effects, o.Str("FxName"), o.Bool("Loop", true), o.Bool("SmoothShutdown", true),
                    o.Bool("OneTime"), o.LTPosition, rot);
                var flags = JoinFlags(i, StartFlags.Visible, null, fx.Remove);
                fx.RemoveObject = () => flags.OnMessage(new Message(new[] { "REMOVE" }, -1));
                Commands.Handle(i, fx.OnMessage);
                ticker.Objects.Add((fx, go.transform));
                pointObjects[i] = go.transform;
                if (o.Bool("StartOn", true)) startOn.Add(fx);
                var group = Effects.Find(fx.FxName);
                if (group == null) continue;
                foreach (var k in group.Keys)
                    if (!Effects.HasLook(k.Type)) Commands.Count("FX", k.Type, "(no look)");
            }
        }

        // An LTBModel or LTBBouncyChunk key's look: its model with its pieces' styles, its clip (chunks have none).
    // None when the model doesn't load.
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
            int a = k.type == "LTBModel" ? model.FindAnim(k.anim) : -1;
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

        // A sprite system's .spr: its frames, length (each frame 1000 / rate ms) and first frame's size.
        static FxSpriteSystem.SpriteFile SpriteFileOf(string file)
        {
            var t = file == "" ? null : DtxLoader.Load(file);
            if (t == null || !t.tex) return new FxSpriteSystem.SpriteFile { Frames = 1, Width = 1, Height = 1 };
            int frames = t.frames != null ? t.frames.Length : 1, rate = (int)t.frameRate;
            return new FxSpriteSystem.SpriteFile
            {
                Frames = frames,
                LengthMs = rate > 0 ? frames * (1000 / rate) : 0,
                Width = t.tex.width,
                Height = t.tex.height,
            };
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
