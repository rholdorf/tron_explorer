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
    // per placed object.
    public partial class LevelBuilder
    {
        public ClientFXMgr Effects;
        readonly Dictionary<int, Transform> specialFXObjects = new Dictionary<int, Transform>();
        readonly List<SpecialFX> startOn = new List<SpecialFX>();

        void BuildSpecialFX()
        {
            Effects = new ClientFXMgr();
            foreach (var g in Data.fxGroups ?? new FxGroupJson[0]) Effects.Add(g.Group());
            var ticker = Root.AddComponent<ClientFXTicker>();
            ticker.Effects = Effects;
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

        void StartSpecialFX()
        {
            foreach (var fx in startOn) fx.TurnOn();
            startOn.Clear();
        }
    }
}
