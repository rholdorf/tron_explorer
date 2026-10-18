using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.Rendering;

namespace Tron
{
    // Draws the level's effect particle systems (FxParticleSystem) each frame as the engine does
    // (drawparticles.cpp d3d_DrawParticleSystem): each particle a quad facing the camera, 4 x its size on a
    // side, UVs 0..1, vertex colour from its keys; with RotateParticles turned by its angle snapped to 256
    // steps. Systems that move their particles with them are drawn with their place and rotation. All the
    // quads of one texture and blend go in one mesh, drawn by the main camera only (effects never reach the
    // glow buffer). A .spr shows one frame per system, on the system's own clock. Runs after the effect
    // manager (ClientFXTicker).
    [DefaultExecutionOrder(60)]
    public class ParticleRenderer : MonoBehaviour
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

        const int RotTableSize = 256;

        class Batch
        {
            public Material Mat;
            public Mesh Mesh;
            public Vert[] Verts = new Vert[256];
            public int Quads, Capacity;
        }

        readonly Dictionary<(Texture, int), Batch> batches = new Dictionary<(Texture, int), Batch>();
        readonly Dictionary<string, LTTexture> textures = new Dictionary<string, LTTexture>();

        Texture FrameOf(FxParticleSystem ps)
        {
            if (ps.Texture == "") return Texture2D.whiteTexture;
            if (!textures.TryGetValue(ps.Texture, out var t)) textures[ps.Texture] = t = DtxLoader.Load(ps.Texture);
            if (t == null) return Texture2D.whiteTexture;
            if (t.frames == null || t.frames.Length < 2) return t.tex;
            return t.frames[SpriteMath.Frame(Effects.Time - ps.Born, (int)t.frameRate, t.frames.Length)];
        }

        Batch BatchOf(Texture tex, int blend)
        {
            if (batches.TryGetValue((tex, blend), out var b)) return b;
            var mat = new Material(Shader) { name = "Effect " + tex.name, mainTexture = tex };
            switch (blend)
            {
                case FxParticleSystem.BlendAdditive:
                    mat.SetFloat("_SrcBlend", (float)BlendMode.One);
                    mat.SetFloat("_DstBlend", (float)BlendMode.One);
                    break;
                case FxParticleSystem.BlendMultiply:
                    mat.SetFloat("_SrcBlend", (float)BlendMode.Zero);
                    mat.SetFloat("_DstBlend", (float)BlendMode.SrcColor);
                    break;
                default:
                    mat.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
                    mat.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
                    break;
            }
            b = new Batch { Mat = mat, Mesh = new Mesh { name = mat.name } };
            b.Mesh.MarkDynamic();
            batches[(tex, blend)] = b;
            return b;
        }

        static byte Byte(float v) => (byte)Mathf.Clamp(Mathf.RoundToInt(v * 255), 0, 255);

        void LateUpdate()
        {
            var cam = Camera.main;
            if (Effects == null || !cam) return;
            foreach (var b in batches.Values) b.Quads = 0;
            // The camera's axes in the level (its scale doesn't turn them).
            var up = transform.InverseTransformDirection(cam.transform.up);
            var right = transform.InverseTransformDirection(cam.transform.right);
            var fwd = transform.InverseTransformDirection(cam.transform.forward);
            Vector3 ul = 2 * (up - right), ur = 2 * (up + right);
            foreach (var inst in Effects.Instances)
                foreach (var fx in inst.Effects)
                {
                    if (!(fx is FxParticleSystem ps) || !ps.Visible || ps.Count == 0) continue;
                    var b = BatchOf(FrameOf(ps), ps.Blend);
                    if (b.Verts.Length < (b.Quads + ps.Count) * 4)
                        Array.Resize(ref b.Verts, Mathf.NextPowerOfTwo((b.Quads + ps.Count) * 4));
                    var sysPos = new Vector3(ps.Pos.x, ps.Pos.y, ps.Pos.z);
                    var sysRot = new Quaternion(ps.Rot.x, ps.Rot.y, ps.Rot.z, ps.Rot.w);
                    var v = b.Verts;
                    int n = b.Quads * 4;
                    for (int i = 0; i < ps.Count; i++)
                    {
                        ref var p = ref ps.Particles[i];
                        var pos = new Vector3(p.Pos.x, p.Pos.y, p.Pos.z);
                        if (ps.ObjectSpace) pos = sysPos + sysRot * pos;
                        Vector3 a = ul, c = ur;
                        if (ps.Rotate)
                        {
                            int index = Mathf.RoundToInt(p.Angle * (RotTableSize / (2 * Mathf.PI)));
                            index = index >= 0 ? index % RotTableSize : RotTableSize - -index % RotTableSize;
                            float angle = index * (2 * Mathf.PI / RotTableSize);
                            var bu = 2 * (Mathf.Cos(angle) * up + Mathf.Sin(angle) * right);
                            var br = Vector3.Cross(bu, fwd);
                            a = bu - br;
                            c = bu + br;
                        }
                        float s = p.Size;
                        var col = new Color32(Byte(p.R), Byte(p.G), Byte(p.B), Byte(p.A));
                        v[n] = new Vert { pos = pos + a * s, col = col, uv = new Vector2(0, 0) };
                        v[n + 1] = new Vert { pos = pos + c * s, col = col, uv = new Vector2(1, 0) };
                        v[n + 2] = new Vert { pos = pos - a * s, col = col, uv = new Vector2(1, 1) };
                        v[n + 3] = new Vert { pos = pos - c * s, col = col, uv = new Vector2(0, 1) };
                        n += 4;
                    }
                    b.Quads += ps.Count;
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
