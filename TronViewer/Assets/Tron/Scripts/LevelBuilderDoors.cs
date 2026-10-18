using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Doors, switches and sliding/rotating world models (ActiveWorldModel, ticket #36).
    public partial class LevelBuilder
    {
        // Colliders only the use ray sees: a non-solid world model the player can use still takes the ray
        // (FLAG_RAYHIT) but doesn't block the player. Physics ignores this layer against the player's.
        public const int UseOnlyLayer = 29;

        static readonly HashSet<string> ActiveClasses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "SlidingDoor", "RotatingDoor", "SlidingSwitch", "RotatingSwitch", "SlidingWorldModel", "RotatingWorldModel",
        };

        public readonly List<ActiveWorldModelObject> ActiveWorldModels = new List<ActiveWorldModelObject>();

        // Every door, switch and sliding/rotating world model gets its state machine on its world model's
        // GameObject (a stand-in where it has none) and answers its messages. Called while level.bin is still
        // loaded (the use-only colliders come from it).
        void BuildActiveWorldModels()
        {
            var worldModels = new Dictionary<string, GameObject>(WorldModelObjects, StringComparer.OrdinalIgnoreCase);
            var wmJson = new Dictionary<string, WorldModelJson>(StringComparer.OrdinalIgnoreCase);
            foreach (var wm in Data.worldModels) wmJson[wm.name] = wm;
            var prompts = new Dictionary<string, ActivateTypeJson>(StringComparer.OrdinalIgnoreCase);
            foreach (var t in Data.activateTypes ?? new ActivateTypeJson[0]) prompts[t.name] = t;
            Physics.IgnoreLayerCollision(0, UseOnlyLayer);

            var byIndex = new Dictionary<int, ActiveWorldModelObject>();
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                if (!ActiveClasses.Contains(o.cls)) continue;
                var s = ActiveWorldModel.Settings.Read(o.cls, new ObjectProps(o));
                if (!worldModels.TryGetValue(o.name ?? "", out var go))
                {
                    go = new GameObject($"{o.name} [{o.cls}]");
                    go.transform.SetParent(Root.transform, false);
                    go.transform.localPosition = o.Position;
                    go.transform.localRotation = o.Rotation;
                }
                // Not solid but usable: the ray still hits it.
                bool hasCollider = go.GetComponentInChildren<Collider>() != null;
                if (!hasCollider && s.PlayerActivate && o.Bool("Rayhit") && wmJson.TryGetValue(o.name, out var wj) && wj.collider >= 0)
                {
                    var geom = go.transform.Find("geom");
                    if (geom)
                    {
                        AddCollider(geom, wj.collider, "use only");
                        SetLayer(geom.Find("use only").gameObject, UseOnlyLayer);
                    }
                }
                else if (hasCollider) MakeKinematic(go);

                LTVec? rotationPoint = null;
                int pi = FirstNamed(s.RotationPoint);
                if (pi >= 0) rotationPoint = Data.objects[pi].LTPosition;
                var awm = go.AddComponent<ActiveWorldModelObject>();
                awm.Init(s, o, i, rotationPoint, Commands, Data);
                if (prompts.TryGetValue(s.ActivateType ?? "", out var prompt))
                {
                    awm.PromptOnText = prompt.on;
                    awm.PromptOffText = prompt.off;
                }
                Commands.Handle(i, awm.Awm.Handle);
                ActiveWorldModels.Add(awm);
                byIndex[i] = awm;
            }

            foreach (var kv in byIndex)
            {
                var o = Data.objects[kv.Key];
                var awm = kv.Value;
                // DoorLink: the first object with the name, if it is a door.
                if (byIndex.TryGetValue(FirstNamed(awm.Awm.DoorLink), out var link) && link.Awm.IsDoor)
                    awm.Awm.Link = link.Awm;
                // Attached world models move with it, and the use ray on them reaches it.
                foreach (var name in o.Str("Attachments").Split(';'))
                {
                    var n = name.Trim();
                    if (n.Length > 0 && worldModels.TryGetValue(n, out var att) && att != awm.gameObject)
                        att.transform.SetParent(awm.transform, true);
                }
            }
        }

        // The player joins the command manager after the level is built.
        public void ConnectPlayer(int id, PlayerController player)
        {
            foreach (var a in ActiveWorldModels) a.ConnectPlayer(id, player);
            foreach (var s in StateModels) s.ConnectPlayer(id);
        }
    }
}
