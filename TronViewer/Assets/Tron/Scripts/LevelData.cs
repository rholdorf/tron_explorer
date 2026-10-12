using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Mirrors tools/export_level.py (level.json). Positions are raw LithTech units.
    [Serializable] public class LevelJson
    {
        public int version;
        public string name;
        public string info;
        public float[] extMin, extMax, offset;
        public MaterialJson[] materials;
        public MeshJson[] meshes;
        public ColliderJson[] colliders;
        public int[] worldMeshes;
        public int worldCollider;
        public int blockerCollider;
        public WorldModelJson[] worldModels;
        public ObjectJson[] objects;
    }

    [Serializable] public class MaterialJson { public string tex, tex2, effect; public int shader; }
    [Serializable] public class SubMeshJson { public int mat, start, count; }

    [Serializable] public class MeshJson
    {
        public string name;
        public int vtxOffset, vtxCount, idxOffset;
        public SubMeshJson[] subs;
        public float[] min, max;
    }

    [Serializable] public class ColliderJson
    {
        public string name;
        public int vtxOffset, vtxCount, idxOffset, idxCount;
        public float[] min, max;
    }

    [Serializable] public class WorldModelJson { public string name; public int flags, mesh, collider; }

    [Serializable] public class PropJson { public string k, t, s; public float[] v; }

    [Serializable] public class ObjectJson
    {
        public string cls, name;
        public float[] pos, rot;
        public PropJson[] props;

        [NonSerialized] Dictionary<string, PropJson> _map;

        PropJson Find(string key)
        {
            if (_map == null)
            {
                _map = new Dictionary<string, PropJson>(StringComparer.OrdinalIgnoreCase);
                foreach (var p in props) _map[p.k] = p;
            }
            return _map.TryGetValue(key, out var r) ? r : null;
        }

        public bool Has(string key) => Find(key) != null;
        public string Str(string key, string def = "") { var p = Find(key); return p != null && p.t == "s" ? p.s : def; }
        public float Num(string key, float def = 0) { var p = Find(key); return p != null && p.t != "s" && p.v.Length > 0 ? p.v[0] : def; }
        public bool Bool(string key, bool def = false) { var p = Find(key); return p != null && p.t == "b" ? p.v[0] != 0 : def; }
        public Vector3 Vec(string key, Vector3 def = default)
        {
            var p = Find(key);
            return p != null && p.t == "v" && p.v.Length >= 3 ? new Vector3(p.v[0], p.v[1], p.v[2]) : def;
        }

        public Vector3 Position => new Vector3(pos[0], pos[1], pos[2]);
        // LithTech stores (pitch, yaw, roll) in radians; both engines are left-handed Y-up.
        public Quaternion Rotation => Quaternion.Euler(rot[0] * Mathf.Rad2Deg, rot[1] * Mathf.Rad2Deg, rot[2] * Mathf.Rad2Deg);
    }

    [Serializable] public class LevelIndexJson { public string[] levels; }
}
