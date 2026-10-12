using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // The level's triggers and relays (Relays): every level object of a relay class is handed to them at
    // load. This ticks the command objects' timelines once per frame before the pending-command table (the
    // server shell updates the lite objects first); TriggerTicker ticks the triggers after it.
    [DefaultExecutionOrder(-110)]
    public class RelayTicker : MonoBehaviour
    {
        public Relays Relays;

        public static Relays Build(LevelBuilder level)
        {
            var relays = new Relays(level.Commands);
            var objects = level.Data.objects;
            for (int i = 0; i < objects.Length; i++)
            {
                var o = objects[i];
                var strs = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                var nums = new Dictionary<string, float[]>(StringComparer.OrdinalIgnoreCase);
                foreach (var p in o.props)
                {
                    if (p.t == "s") strs[p.k] = p.s;
                    else nums[p.k] = p.v;
                }
                relays.Add(i, o.cls, new LTVec(o.pos[0], o.pos[1], o.pos[2]), strs, nums);
            }
            level.Root.AddComponent<RelayTicker>().Relays = relays;
            level.Root.AddComponent<TriggerTicker>().Relays = relays;
            return relays;
        }

        void Update() => Relays?.UpdateTimelines(Time.deltaTime);
    }
}
