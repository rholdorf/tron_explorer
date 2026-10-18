using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.Rendering;

namespace Tron
{
    // Draws the level's DrawPrim effects (FxDrawPrim: lightning bolts, poly trails) each frame as the client
    // shell does: every shown effect's quads for the main camera, texture x vertex colour (ColorOp Modulate),
    // the texture repeating (DrawPrim leaves the address mode at wrap), Z read but not written, both faces, no
    // fog. All the quads of one texture, blend mode and alpha test go in one mesh with the Tron/Effect shader,
    // drawn by the main camera only (DrawPrim effects never reach the glow buffer). Runs after the effect
    // manager (ClientFXTicker) and the effect models (whose nodes the bolts reach).
    [DefaultExecutionOrder(60)]
    public class DrawPrimRenderer : MonoBehaviour
    {
        public ClientFXMgr Effects;
        public Shader Shader;

        [StructLayout(LayoutKind.Sequential)]
        struct Vert
        {
            public Vector3 pos;
            public Color32 col;
            public Vector2 uv;
        }

        static readonly VertexAttributeDescriptor[] Layout =
        {
            new VertexAttributeDescriptor(VertexAttribute.Position, VertexAttributeFormat.Float32, 3),
            new VertexAttributeDescriptor(VertexAttribute.Color, VertexAttributeFormat.UNorm8, 4),
            new VertexAttributeDescriptor(VertexAttribute.TexCoord0, VertexAttributeFormat.Float32, 2),
        };

        class Batch
        {
            public Material Mat;
            public Mesh Mesh;
            public Vert[] Verts = new Vert[256];
            public int Quads, Capacity;
        }

        readonly Dictionary<(Texture, int, bool), Batch> batches = new Dictionary<(Texture, int, bool), Batch>();
        readonly Dictionary<string, LTTexture> textures = new Dictionary<string, LTTexture>();
        readonly List<PrimVert> quads = new List<PrimVert>();

        // ELTBlendMode (d3ddrawprim.cpp SetBlendMode): source and destination factors.
        static readonly (BlendMode src, BlendMode dst)[] Blends =
        {
            (BlendMode.One, BlendMode.Zero),
            (BlendMode.One, BlendMode.One),
            (BlendMode.OneMinusDstColor, BlendMode.One),
            (BlendMode.SrcAlpha, BlendMode.OneMinusSrcAlpha),
            (BlendMode.SrcColor, BlendMode.OneMinusSrcColor),
            (BlendMode.DstColor, BlendMode.OneMinusDstColor),
            (BlendMode.SrcColor, BlendMode.DstColor),
            (BlendMode.SrcAlpha, BlendMode.One),
            (BlendMode.SrcAlpha, BlendMode.Zero),
            (BlendMode.SrcColor, BlendMode.One),
            (BlendMode.DstColor, BlendMode.Zero),
        };

        Texture TextureOf(string file)
        {
            if (file == "") return Texture2D.whiteTexture;
            if (!textures.TryGetValue(file, out var t)) textures[file] = t = DtxLoader.Load(file);
            return t != null && t.tex ? (Texture)t.tex : Texture2D.whiteTexture;
        }

        Batch BatchOf(Texture tex, int blend, bool alphaTest)
        {
            if (batches.TryGetValue((tex, blend, alphaTest), out var b)) return b;
            var mat = new Material(Shader) { name = "DrawPrim " + tex.name, mainTexture = tex };
            var (src, dst) = Blends[blend >= 0 && blend < Blends.Length ? blend : 0];
            mat.SetFloat("_SrcBlend", (float)src);
            mat.SetFloat("_DstBlend", (float)dst);
            mat.SetFloat("_Wrap", 1);
            mat.SetFloat("_AlphaGreater", alphaTest ? 1 : 0);
            b = new Batch { Mat = mat, Mesh = new Mesh { name = mat.name } };
            b.Mesh.MarkDynamic();
            batches[(tex, blend, alphaTest)] = b;
            return b;
        }

        static LTVec V(Vector3 v) => new LTVec(v.x, v.y, v.z);

        void LateUpdate()
        {
            var cam = Camera.main;
            if (!cam || Effects == null) return;
            var pc = new PrimCamera
            {
                Pos = V(transform.InverseTransformPoint(cam.transform.position)),
                Right = V(transform.InverseTransformDirection(cam.transform.right)),
                Up = V(transform.InverseTransformDirection(cam.transform.up)),
                Forward = V(transform.InverseTransformDirection(cam.transform.forward)),
            };
            foreach (var b in batches.Values) b.Quads = 0;
            foreach (var inst in Effects.Instances)
                foreach (var fx in inst.Effects)
                {
                    if (!(fx is FxDrawPrim dp) || !dp.Visible) continue;
                    quads.Clear();
                    dp.Render(pc, quads);
                    if (quads.Count == 0) continue;
                    // AlphaTest Greater (the one test a key sets) against the reference D3D starts with, 0.
                    var b = BatchOf(TextureOf(dp.Texture), dp.BlendMode, dp.AlphaTest == FxDrawPrim.AlphaGreater);
                    int need = (b.Quads * 4 + quads.Count);
                    if (b.Verts.Length < need) Array.Resize(ref b.Verts, Mathf.NextPowerOfTwo(need));
                    int n = b.Quads * 4;
                    foreach (var q in quads)
                    {
                        uint c = q.Color;
                        b.Verts[n++] = new Vert
                        {
                            pos = new Vector3(q.Pos.x, q.Pos.y, q.Pos.z),
                            col = new Color32((byte)c, (byte)(c >> 8), (byte)(c >> 16), (byte)(c >> 24)),
                            uv = new Vector2(q.U, q.V),
                        };
                    }
                    b.Quads += quads.Count / 4;
                }
            var matrix = transform.localToWorldMatrix;
            foreach (var b in batches.Values)
            {
                if (b.Quads == 0) continue;
                var mesh = b.Mesh;
                if (b.Quads > b.Capacity)
                {
                    b.Capacity = Mathf.NextPowerOfTwo(b.Quads);
                    mesh.SetVertexBufferParams(b.Capacity * 4, Layout);
                    var idx = new int[b.Capacity * 6];
                    for (int q = 0, i = 0; q < b.Capacity; q++, i += 6)
                    {
                        idx[i] = q * 4;
                        idx[i + 1] = q * 4 + 1;
                        idx[i + 2] = q * 4 + 2;
                        idx[i + 3] = q * 4;
                        idx[i + 4] = q * 4 + 2;
                        idx[i + 5] = q * 4 + 3;
                    }
                    mesh.SetIndexBufferParams(idx.Length, IndexFormat.UInt32);
                    mesh.SetIndexBufferData(idx, 0, 0, idx.Length, MeshUpdateFlags.DontValidateIndices);
                }
                const MeshUpdateFlags flags = MeshUpdateFlags.DontValidateIndices | MeshUpdateFlags.DontRecalculateBounds |
                    MeshUpdateFlags.DontNotifyMeshUsers;
                mesh.SetVertexBufferData(b.Verts, 0, 0, b.Quads * 4, 0, flags);
                mesh.SetSubMesh(0, new SubMeshDescriptor(0, b.Quads * 6), flags);
                mesh.bounds = new Bounds(Vector3.zero, Vector3.one * 1e7f);
                var rp = new RenderParams(b.Mat)
                {
                    camera = cam,
                    worldBounds = new Bounds(Vector3.zero, Vector3.one * 1e5f),
                    shadowCastingMode = ShadowCastingMode.Off,
                    receiveShadows = false,
                };
                Graphics.RenderMesh(rp, mesh, 0, matrix);
            }
        }

        void OnDestroy()
        {
            foreach (var b in batches.Values)
            {
                Destroy(b.Mesh);
                Destroy(b.Mat);
            }
            batches.Clear();
        }
    }
}
