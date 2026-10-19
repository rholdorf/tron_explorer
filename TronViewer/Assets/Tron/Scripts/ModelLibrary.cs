using System;
using System.Collections.Generic;
using System.IO;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Rendering;

namespace Tron
{
    public class LoadedModel
    {
        public ModelJson data;
        public Mesh mesh;   // one submesh per piece, LOD 0, bind pose, LithTech units; bones = data.nodes
                            // (shared; ModelLibrary.WithRepeatedPieces makes variants for multi-draw styles)
        public float[] animData;   // the clips' float block (data.anims index into it)

        // Index of the clip named `name` in data.anims, or -1: the model's own (or its .ltb children's), or,
        // given `from`, the one from that ChildModel_N file.
        public int FindAnim(string name, string from = "")
        {
            if (data.anims == null || string.IsNullOrEmpty(name)) return -1;
            for (int i = 0; i < data.anims.Length; i++)
                if (string.Equals(data.anims[i].name, name, StringComparison.OrdinalIgnoreCase)
                    && string.Equals(data.anims[i].@from ?? "", from ?? "", StringComparison.OrdinalIgnoreCase)) return i;
            return -1;
        }

        // A node's model-space bind matrix (the exporter writes it row-major).
        public Matrix4x4 BindMatrix(int node)
        {
            var t = data.nodes[node].transform;
            var m = new Matrix4x4();
            for (int r = 0; r < 4; r++)
                for (int c = 0; c < 4; c++)
                    m[r, c] = t[r * 4 + c];
            return m;
        }
    }

    // Reads exported models (export/models/<file>.json + .bin, see tools/export_models.py).
    public static class ModelLibrary
    {
        public const int FormatVersion = 5;
        const int HeaderSize = 24, VertexSize = 44, BoneWeightSize = 8;

        // Loaded once per level; the meshes go to `owned` so the level frees them.
        public static LoadedModel Load(string exportRoot, string file, Dictionary<string, LoadedModel> cache, List<UnityEngine.Object> owned)
        {
            if (cache.TryGetValue(file, out var cached)) return cached;
            LoadedModel result = null;
            try
            {
                var basePath = Path.Combine(exportRoot, "models", file);
                var data = JsonUtility.FromJson<ModelJson>(File.ReadAllText(basePath + ".json"));
                if (data.version != FormatVersion) throw new Exception($"model format v{data.version}, expected v{FormatVersion}");
                var bin = File.ReadAllBytes(basePath + ".bin");
                if (bin[0] != 'T' || bin[1] != 'R' || bin[2] != 'M' || bin[3] != 'D') throw new Exception("bad model .bin");
                int nv = BitConverter.ToInt32(bin, 8), ni = BitConverter.ToInt32(bin, 12), nInf = BitConverter.ToInt32(bin, 16);
                int nAnim = BitConverter.ToInt32(bin, 20);
                var mesh = new Mesh { name = file };
                owned.Add(mesh);
                mesh.SetVertexBufferParams(nv,
                    new VertexAttributeDescriptor(VertexAttribute.Position, VertexAttributeFormat.Float32, 3),
                    new VertexAttributeDescriptor(VertexAttribute.Normal, VertexAttributeFormat.Float32, 3),
                    new VertexAttributeDescriptor(VertexAttribute.Color, VertexAttributeFormat.UNorm8, 4),
                    new VertexAttributeDescriptor(VertexAttribute.TexCoord0, VertexAttributeFormat.Float32, 2),
                    new VertexAttributeDescriptor(VertexAttribute.TexCoord1, VertexAttributeFormat.Float32, 2));
                using (var vb = new NativeArray<byte>(nv * VertexSize, Allocator.Temp))
                {
                    NativeArray<byte>.Copy(bin, HeaderSize, vb, 0, vb.Length);
                    mesh.SetVertexBufferData(vb, 0, 0, vb.Length);
                }
                mesh.SetIndexBufferParams(ni, IndexFormat.UInt32);
                using (var ib = new NativeArray<byte>(ni * 4, Allocator.Temp))
                {
                    NativeArray<byte>.Copy(bin, HeaderSize + nv * VertexSize, ib, 0, ib.Length);
                    mesh.SetIndexBufferData(ib, 0, 0, ib.Length);
                }
                // Skin: influences per vertex, then Unity BoneWeight1s (heaviest first); bones are the
                // model's nodes, bind poses their inverse bind matrices.
                int skinBase = HeaderSize + nv * VertexSize + ni * 4;
                using (var counts = new NativeArray<byte>(nv, Allocator.Temp))
                using (var weights = new NativeArray<byte>(nInf * BoneWeightSize, Allocator.Temp))
                {
                    NativeArray<byte>.Copy(bin, skinBase, counts, 0, nv);
                    NativeArray<byte>.Copy(bin, skinBase + nv, weights, 0, weights.Length);
                    mesh.SetBoneWeights(counts, weights.Reinterpret<BoneWeight1>(1));
                }
                // Animation clips follow the skin.
                var animData = new float[nAnim];
                Buffer.BlockCopy(bin, skinBase + nv + nInf * BoneWeightSize, animData, 0, nAnim * 4);
                var loaded = new LoadedModel { data = data, mesh = mesh, animData = animData };
                var bindposes = new Matrix4x4[data.nodes.Length];
                for (int i = 0; i < bindposes.Length; i++) bindposes[i] = loaded.BindMatrix(i).inverse;
                mesh.bindposes = bindposes;
                mesh.subMeshCount = data.pieces.Length;
                var bounds = new Bounds();
                for (int i = 0; i < data.pieces.Length; i++)
                {
                    var p = data.pieces[i];
                    var b = new Bounds();
                    b.SetMinMax(new Vector3(p.min[0], p.min[1], p.min[2]), new Vector3(p.max[0], p.max[1], p.max[2]));
                    if (i == 0) bounds = b; else bounds.Encapsulate(b);
                    mesh.SetSubMesh(i, new SubMeshDescriptor(p.idxOffset, p.idxCount)
                    {
                        baseVertex = p.vtxOffset, firstVertex = p.vtxOffset, vertexCount = p.vtxCount, bounds = b,
                    }, MeshUpdateFlags.DontRecalculateBounds | MeshUpdateFlags.DontValidateIndices);
                }
                mesh.bounds = bounds;
                mesh.UploadMeshData(false);   // kept readable: SkinnedMeshRenderers draw it too
                result = loaded;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"Model {file}: {e.Message}");
            }
            cache[file] = result;
            return result;
        }

        // The model's mesh plus submeshes that repeat the given pieces (in order, after the model's own),
        // so one renderer draws a piece again with another material: a render style's later draws share
        // the skinning, bones and property block of the first. Cached per model and piece list.
        public static Mesh WithRepeatedPieces(LoadedModel model, List<int> pieces, Dictionary<string, Mesh> cache, List<UnityEngine.Object> owned)
        {
            var key = model.data.file + "|" + string.Join(",", pieces);
            if (cache.TryGetValue(key, out var mesh)) return mesh;
            mesh = UnityEngine.Object.Instantiate(model.mesh);   // copies vertices, skin, bind poses, submeshes
            mesh.name = $"{model.mesh.name} +{pieces.Count}";
            owned.Add(mesh);
            const MeshUpdateFlags flags = MeshUpdateFlags.DontRecalculateBounds | MeshUpdateFlags.DontValidateIndices;
            int n = model.mesh.subMeshCount;
            // Each repeat gets its own copy of the piece's indices, appended to the index buffer:
            // submeshes sharing an index range make Unity warn ("shares part of its index buffer").
            var repeats = new SubMeshDescriptor[pieces.Count];
            using (var src = Mesh.AcquireReadOnlyMeshData(model.mesh))
            {
                var srcIndices = src[0].GetIndexData<uint>();
                int total = srcIndices.Length;
                foreach (int p in pieces) total += model.mesh.GetSubMesh(p).indexCount;
                using (var indices = new NativeArray<uint>(total, Allocator.Temp))
                {
                    NativeArray<uint>.Copy(srcIndices, indices, srcIndices.Length);
                    int at = srcIndices.Length;
                    for (int j = 0; j < pieces.Count; j++)
                    {
                        var d = model.mesh.GetSubMesh(pieces[j]);
                        NativeArray<uint>.Copy(srcIndices, d.indexStart, indices, at, d.indexCount);
                        d.indexStart = at;
                        repeats[j] = d;
                        at += d.indexCount;
                    }
                    mesh.SetIndexBufferParams(total, IndexFormat.UInt32);
                    mesh.SetIndexBufferData(indices, 0, 0, total, flags);
                }
            }
            mesh.subMeshCount = n + pieces.Count;
            for (int j = 0; j < pieces.Count; j++)
                mesh.SetSubMesh(n + j, repeats[j], flags);
            mesh.bounds = model.mesh.bounds;
            mesh.UploadMeshData(false);
            cache[key] = mesh;
            return mesh;
        }

        // The mesh with the given submeshes drawn as the edges of their triangles (D3DFILL_WIREFRAME: each
        // edge once per submesh, one pixel wide). Cached per mesh and submesh list.
        public static Mesh WithLines(Mesh source, List<int> subs, Dictionary<string, Mesh> cache, List<UnityEngine.Object> owned)
        {
            var key = source.name + "|lines " + string.Join(",", subs);
            if (cache.TryGetValue(key, out var mesh)) return mesh;
            mesh = UnityEngine.Object.Instantiate(source);
            mesh.name = $"{source.name} lines";
            owned.Add(mesh);
            var edges = new HashSet<(int, int)>();
            var lines = new List<int>();
            foreach (int s in subs)
            {
                var tris = source.GetIndices(s, false);
                int baseVertex = (int)source.GetBaseVertex(s);
                edges.Clear();
                lines.Clear();
                for (int t = 0; t + 2 < tris.Length; t += 3)
                    for (int e = 0; e < 3; e++)
                    {
                        int a = tris[t + e], b = tris[t + (e + 1) % 3];
                        if (edges.Add(a < b ? (a, b) : (b, a)))
                        {
                            lines.Add(a);
                            lines.Add(b);
                        }
                    }
                mesh.SetIndices(lines, MeshTopology.Lines, s, false, baseVertex);
            }
            mesh.bounds = source.bounds;
            mesh.UploadMeshData(false);
            cache[key] = mesh;
            return mesh;
        }
    }
}
