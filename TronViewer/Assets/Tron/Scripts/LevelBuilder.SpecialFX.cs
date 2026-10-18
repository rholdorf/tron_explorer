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
    // per placed object. Types with a look: ParticleSystem (ParticleRenderer). Effects bounce and splat on
    // the world's colliders (IntersectSegment hits the world only, so characters' and the player's
    // controllers don't count).
    public partial class LevelBuilder
    {
        public ClientFXMgr Effects;
        public Shader EffectShader;
        readonly RaycastHit[] fxHits = new RaycastHit[8];
        readonly Dictionary<int, Transform> specialFXObjects = new Dictionary<int, Transform>();
        readonly List<SpecialFX> startOn = new List<SpecialFX>();

        void BuildSpecialFX()
        {
            Effects = new ClientFXMgr();
            foreach (var g in Data.fxGroups ?? new FxGroupJson[0]) Effects.Add(g.Group());
            var effects = Effects;
            effects.Types["ParticleSystem"] = k => new FxParticleSystem(effects);
            effects.Intersect = IntersectWorld;
            var ticker = Root.AddComponent<ClientFXTicker>();
            ticker.Effects = Effects;
            var particles = Root.AddComponent<ParticleRenderer>();
            particles.Effects = Effects;
            particles.Shader = EffectShader;
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
