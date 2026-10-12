using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace Tron
{
    // Texture effect groups (textureeffectgroups/*.tfg): u32 version, u32, u32, u32 stages,
    // str16 compiled script (Tex\TexFX\*.tfs), u32 paramCount, float params[].
    // The .tfs scripts are compiled bytecode; UVPan (u/s, v/s) is reproduced exactly.
    public static class TextureEffects
    {
        public static string Root;
        static readonly List<string> unsupported = new List<string>();

        public static void Apply(Material m, string effect)
        {
            if (string.IsNullOrEmpty(effect)) return;
            var path = Path.Combine(Root, "textureeffectgroups", effect.ToLowerInvariant());
            if (!File.Exists(path)) return;
            try
            {
                using var br = new BinaryReader(File.OpenRead(path));
                br.ReadBytes(16);
                int len = br.ReadUInt16();
                var script = Encoding.ASCII.GetString(br.ReadBytes(len)).ToLowerInvariant();
                int n = br.ReadInt32();
                var p = new float[n];
                for (int i = 0; i < n; i++) p[i] = br.ReadSingle();
                if (script.EndsWith("uvpan.tfs"))
                    m.SetVector("_UVScroll", new Vector4(p[0], p[1], 0, 0));
                else if (!unsupported.Contains(script))
                    unsupported.Add(script);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"Texture effect {effect}: {e.Message}");
            }
        }

        public static void Clear() { }
    }

    // Cycles animated sprite (.spr) frames on world materials.
    public class SpriteAnimator : MonoBehaviour
    {
        struct Entry { public Material mat; public Texture2D[] frames; public float rate; }
        static readonly List<Entry> entries = new List<Entry>();

        public static void Register(Material m, Texture2D[] frames, float rate)
        {
            entries.Add(new Entry { mat = m, frames = frames, rate = rate > 0 ? rate : 10 });
        }

        public static void Clear() => entries.Clear();

        void Update()
        {
            float t = Time.time;
            foreach (var e in entries)
                if (e.mat) e.mat.SetTexture("_MainTex", e.frames[(int)(t * e.rate) % e.frames.Length]);
        }
    }
}
