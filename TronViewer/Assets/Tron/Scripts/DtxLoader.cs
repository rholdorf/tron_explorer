using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace Tron
{
    // A LithTech texture as the renderer sees it: pixels plus the DTX command-string links.
    public class LTTexture
    {
        public Texture2D tex;
        public int alphaRef;            // 0 = no alpha test
        public bool fullbright;
        public string envMap;           // "EnvMap x" / "EnvMapAlpha x"
        public bool envMapAlpha;
        public string detailTex;        // "DetailTex x"
        public float detailScale = 1;
        public float detailAngle;       // degrees
        public bool hasAlpha;
        public float uvScale = 1;       // UI mipmap offset (Extra[4])
        // Animated sprite (.spr) frames; tex == frames[0]
        public Texture2D[] frames;
        public float frameRate;
    }

    // Reads DTX v-5 (LithTech Jupiter) textures straight into GPU formats.
    // Layout: 164-byte header (dtxmgr.h) then each mip level in order.
    public static class DtxLoader
    {
        const int HeaderSize = 164;
        static readonly Dictionary<string, LTTexture> cache = new Dictionary<string, LTTexture>();
        public static string Root;

        public static void ClearCache()
        {
            foreach (var t in cache.Values)
            {
                if (t == null) continue;
                if (t.frames != null) foreach (var f in t.frames) UnityEngine.Object.Destroy(f);
                else if (t.tex) UnityEngine.Object.Destroy(t.tex);
            }
            cache.Clear();
        }

        public static string Normalize(string path) => path.Replace('\\', '/').Trim().ToLowerInvariant();

        public static LTTexture Load(string path)
        {
            if (string.IsNullOrEmpty(path)) return null;
            path = Normalize(path);
            if (cache.TryGetValue(path, out var cached)) return cached;
            LTTexture result = null;
            try
            {
                result = path.EndsWith(".spr") ? LoadSprite(path) : LoadDtx(path);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"Texture {path}: {e.Message}");
            }
            cache[path] = result;
            return result;
        }

        static LTTexture LoadSprite(string path)
        {
            var full = Path.Combine(Root, path);
            if (!File.Exists(full)) return null;
            using var br = new BinaryReader(File.OpenRead(full));
            int frameCount = br.ReadInt32();
            int frameRate = br.ReadInt32();
            br.ReadBytes(12); // transparent, translucent, colorkey
            var frames = new List<Texture2D>();
            LTTexture first = null;
            for (int i = 0; i < frameCount; i++)
            {
                int len = br.ReadUInt16();
                var name = Encoding.ASCII.GetString(br.ReadBytes(len));
                var t = LoadDtx(Normalize(name));
                if (t == null) continue;
                first ??= t;
                frames.Add(t.tex);
            }
            if (first == null) return null;
            first.frames = frames.ToArray();
            first.frameRate = frameRate;
            return first;
        }

        static LTTexture LoadDtx(string path)
        {
            var full = Path.Combine(Root, path);
            if (!File.Exists(full)) return null;
            var data = File.ReadAllBytes(full);
            if (data.Length < HeaderSize) return null;
            int version = BitConverter.ToInt32(data, 4);
            if (version != -5) throw new Exception($"unsupported DTX version {version}");
            int width = BitConverter.ToUInt16(data, 8);
            int height = BitConverter.ToUInt16(data, 10);
            int mips = Math.Max(1, (int)BitConverter.ToUInt16(data, 12));
            int flags = BitConverter.ToInt32(data, 16);
            byte bpp = data[24 + 2];
            var lt = new LTTexture
            {
                fullbright = (flags & 1) != 0,
                uvScale = 1 << data[24 + 4],
                detailScale = BitConverter.ToSingle(data, 24 + 6) + 1f,
                detailAngle = (short)(data[24 + 10] | (data[24 + 11] << 8)),
            };
            ParseCommand(lt, Encoding.ASCII.GetString(data, 36, 128).Split('\0')[0]);

            TextureFormat fmt;
            int blockBytes;
            bool dxt3 = false;
            switch (bpp)
            {
                case 0: case 3: fmt = TextureFormat.BGRA32; blockBytes = 0; lt.hasAlpha = true; break;
                case 4: fmt = TextureFormat.DXT1; blockBytes = 8; break;
                case 5: fmt = TextureFormat.DXT5; dxt3 = true; blockBytes = 16; lt.hasAlpha = true; break;
                case 6: fmt = TextureFormat.DXT5; blockBytes = 16; lt.hasAlpha = true; break;
                default: throw new Exception($"unsupported BPP ident {bpp}");
            }

            // Measure the available mip chain (some files carry fewer levels than declared).
            int offset = HeaderSize, total = 0, usable = 0;
            for (int m = 0; m < mips; m++)
            {
                int w = Math.Max(1, width >> m), h = Math.Max(1, height >> m);
                int size = blockBytes == 0 ? w * h * 4 : Math.Max(1, (w + 3) / 4) * Math.Max(1, (h + 3) / 4) * blockBytes;
                if (offset + total + size > data.Length) break;
                total += size;
                usable++;
            }
            if (usable == 0) return null;
            if (blockBytes != 0 && (width % 4 != 0 || height % 4 != 0))
                throw new Exception($"compressed texture size {width}x{height} not a multiple of 4");

            var tex = new Texture2D(width, height, fmt, usable, true) { name = path, wrapMode = TextureWrapMode.Repeat, filterMode = FilterMode.Trilinear, anisoLevel = 4 };
            var raw = new byte[total];
            Buffer.BlockCopy(data, offset, raw, 0, total);
            if (dxt3) raw = Dxt3ToDxt5(raw);
            tex.LoadRawTextureData(raw);
            tex.Apply(false, true);
            lt.tex = tex;
            return lt;
        }

        static void ParseCommand(LTTexture lt, string cmd)
        {
            // e.g. "EnvMap Tex\Env\Env003.dtx; DetailTex Worldtextures\tron\circuits3.dtx", "AlphaRef 128"
            foreach (var part in cmd.Split(';'))
            {
                var tok = part.Trim().Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                if (tok.Length < 2) continue;
                switch (tok[0].ToLowerInvariant())
                {
                    case "alpharef": int.TryParse(tok[1], out lt.alphaRef); break;
                    case "envmap": lt.envMap = tok[1]; break;
                    case "envmapalpha": lt.envMap = tok[1]; lt.envMapAlpha = true; break;
                    case "detailtex": lt.detailTex = tok[1]; break;
                }
            }
        }

        // Unity has no DXT3 format: re-encode the explicit 4-bit alpha as a DXT5 alpha block
        // using an 8-step palette (a0=255, a1=0 -> 6 interpolated levels + 0 + 255).
        static byte[] Dxt3ToDxt5(byte[] src)
        {
            var dst = new byte[src.Length];
            for (int b = 0; b < src.Length; b += 16)
            {
                ulong idx = 0;
                for (int p = 0; p < 16; p++)
                {
                    int a4 = (src[b + p / 2] >> ((p & 1) * 4)) & 0xF;
                    int a8 = a4 * 17;
                    // DXT5 palette with a0 > a1: codes 0..7 = 255, 0, 6/7*255+1/7*0 ... -> pick nearest
                    int code = NearestDxt5Code(a8);
                    idx |= (ulong)code << (3 * p);
                }
                dst[b] = 255; dst[b + 1] = 0;
                for (int k = 0; k < 6; k++) dst[b + 2 + k] = (byte)(idx >> (8 * k));
                Buffer.BlockCopy(src, b + 8, dst, b + 8, 8);
            }
            return dst;
        }

        static readonly int[] dxt5Pal = { 255, 0, 219, 182, 146, 109, 73, 36 };
        static int NearestDxt5Code(int a)
        {
            int best = 0, bd = 999;
            for (int i = 0; i < 8; i++) { int d = Math.Abs(dxt5Pal[i] - a); if (d < bd) { bd = d; best = i; } }
            return best;
        }
    }
}
