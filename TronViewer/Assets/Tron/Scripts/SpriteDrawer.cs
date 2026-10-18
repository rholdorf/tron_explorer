using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.Rendering;

namespace Tron
{
    // Draws the level's sprites (LTSprite) each frame as the engine does (SpriteMath): the ScaleSprites' and
    // the Sprite effects' (FxSprite) of every running effect instance. A quad per shown sprite, its current
    // .spr frame (counted from its Born, set at the first draw after a new file or a restart), the vertex
    // colour its colour and alpha, sized by the frame's texture. All the quads of one frame texture, blend and
    // fog go in one mesh with the Tron/Effect shader (fogged sprites: additive towards black, multiply towards
    // white, others towards the fog colour, as d3d_GetBlendStates; every ScaleSprite is FLAG_FOGDISABLE),
    // drawn by the main camera only (sprites never reach the glow buffer). ScaleSprite objects are read from
    // their transforms (LT units under the level root) first, so keyframers move them. Runs after the effect
    // manager (ClientFXTicker) and keyframers.
    [DefaultExecutionOrder(60)]
    public class SpriteDrawer : MonoBehaviour
    {
        public Shader Shader;
        public ClientFXMgr Effects;
        public readonly List<LTSprite> Sprites = new List<LTSprite>();
        public readonly List<(ScaleSprite obj, Transform t)> Objects = new List<(ScaleSprite, Transform)>();

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

        static readonly Vector2[] Uvs = { new Vector2(0, 0), new Vector2(1, 0), new Vector2(1, 1), new Vector2(0, 1) };

        class Batch
        {
            public Material Mat;
            public Mesh Mesh;
            public Vert[] Verts = new Vert[64];
            public int Quads, Capacity;
        }

        readonly Dictionary<(Texture, int, bool), Batch> batches = new Dictionary<(Texture, int, bool), Batch>();
        readonly Dictionary<string, LTTexture> textures = new Dictionary<string, LTTexture>();
        readonly LTVec[] corners = new LTVec[4];
        double clock;
        LTVec camPos, camRight, camUp, camFwd;

        public void Add(ScaleSprite s, Transform t)
        {
            Objects.Add((s, t));
            Sprites.Add(s.Sprite);
            if (s.Flare != null) Sprites.Add(s.Flare);
        }

        LTTexture TextureOf(string file)
        {
            if (!textures.TryGetValue(file, out var t)) textures[file] = t = DtxLoader.Load(file);
            return t;
        }

        Batch BatchOf(Texture tex, int blend, bool fog)
        {
            if (batches.TryGetValue((tex, blend, fog), out var b)) return b;
            var mat = new Material(Shader) { name = "Sprite " + tex.name, mainTexture = tex };
            // _FogColor: the colour it fogs towards, a = 1 for the world's fog colour.
            switch (blend)
            {
                case LTSprite.BlendAdditive:
                    mat.SetFloat("_SrcBlend", (float)BlendMode.One);
                    mat.SetFloat("_DstBlend", (float)BlendMode.One);
                    mat.SetVector("_FogColor", new Vector4(0, 0, 0, 0));
                    break;
                case LTSprite.BlendMultiply:
                    mat.SetFloat("_SrcBlend", (float)BlendMode.Zero);
                    mat.SetFloat("_DstBlend", (float)BlendMode.SrcColor);
                    mat.SetVector("_FogColor", new Vector4(1, 1, 1, 0));
                    break;
                default:
                    mat.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
                    mat.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
                    mat.SetVector("_FogColor", new Vector4(0, 0, 0, 1));
                    break;
            }
            mat.SetFloat("_Fog", fog ? 1 : 0);
            b = new Batch { Mat = mat, Mesh = new Mesh { name = mat.name } };
            b.Mesh.MarkDynamic();
            batches[(tex, blend, fog)] = b;
            return b;
        }

        static byte Byte(float v) => (byte)Mathf.Clamp(Mathf.RoundToInt(v * 255), 0, 255);
        static LTVec V(Vector3 v) => new LTVec(v.x, v.y, v.z);

        void LateUpdate()
        {
            clock += Time.deltaTime;
            var cam = Camera.main;
            if (!cam) return;
            // The camera in the level (its scale doesn't turn the axes).
            camPos = V(transform.InverseTransformPoint(cam.transform.position));
            camRight = V(transform.InverseTransformDirection(cam.transform.right));
            camUp = V(transform.InverseTransformDirection(cam.transform.up));
            camFwd = V(transform.InverseTransformDirection(cam.transform.forward));
            foreach (var (obj, t) in Objects)
            {
                var r = t.localRotation;
                obj.Update(V(t.localPosition), new LTQuat(r.x, r.y, r.z, r.w), camPos, camFwd);
            }
            foreach (var b in batches.Values) b.Quads = 0;
            foreach (var s in Sprites) Quad(s);
            if (Effects != null)
                foreach (var inst in Effects.Instances)
                    foreach (var fx in inst.Effects)
                        if (fx is FxSprite sp) Quad(sp.Sprite);
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

        void Quad(LTSprite s)
        {
            if (double.IsNaN(s.Born)) s.Born = clock;
            if (!s.Shown) return;
            var lt = TextureOf(s.File);
            if (lt == null || !lt.tex) return;
            var tex = lt.frames != null && lt.frames.Length > 1
                ? lt.frames[SpriteMath.Frame(clock - s.Born, (int)lt.frameRate, lt.frames.Length)]
                : lt.tex;
            if (!SpriteMath.Corners(s, tex.width, tex.height, camPos, camRight, camUp, camFwd, corners)) return;
            var b = BatchOf(tex, s.Blend, s.Fog);
            if (b.Verts.Length < (b.Quads + 1) * 4) Array.Resize(ref b.Verts, b.Verts.Length * 2);
            var col = new Color32(Byte(s.R), Byte(s.G), Byte(s.B), Byte(s.A));
            int n = b.Quads * 4;
            for (int i = 0; i < 4; i++)
                b.Verts[n + i] = new Vert { pos = new Vector3(corners[i].x, corners[i].y, corners[i].z), col = col, uv = Uvs[i] };
            b.Quads++;
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
