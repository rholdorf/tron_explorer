using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // The level's light groups (LightGroups.cs) on the world: a group's vertices and lightmap texels are the base
    // lighting plus every group at its live colour (LightGroups.Add, in table order), rebuilt for what a group
    // reaches when its colour changes; models are lit again from the light grid and static lights
    // (ModelLighting.UseGroups). The meshes a group reaches keep their vertex bytes; the atlas keeps its
    // base texels when a group has lightmap patches. LightGroup objects answer their messages.
    public partial class LevelBuilder
    {
        public LightGroups LightGroups;

        // A mesh with group vertices: its Unity mesh, vertex bytes, base colours and, per group, its vertices.
        sealed class LitMesh
        {
            public Mesh Mesh;
            public byte[] Vertices;
            public byte[] BaseRgb;   // 3 bytes a vertex
            public readonly List<(int group, int[] local, byte[] values)> Groups = new List<(int, int[], byte[])>();
        }

        readonly Dictionary<int, LitMesh> litMeshes = new Dictionary<int, LitMesh>();
        List<int>[] groupMeshes;              // per group, the meshes it reaches
        List<int>[] groupRects;               // per group, the lightmap rects its patches are in
        List<(int group, LightmapPatchJson patch)>[] rectPatches;   // per rect, the patches in it, in group order
        byte[] lmTexels, atlasBase, atlasPixels;
        int atlasWidth;

        // Reads the light group pools that follow the light grid (bin still loaded): which meshes each group's
        // vertices are in, and which lightmap rects its patches cover.
        void ReadLightGroups(int offset)
        {
            LightGroups = new LightGroups();
            var groups = Data.lightGroups ?? new LightGroupJson[0];
            foreach (var g in groups) LightGroups.Add(g.name, new LTVec(g.color[0], g.color[1], g.color[2]));
            groupMeshes = new List<int>[groups.Length];
            groupRects = new List<int>[groups.Length];
            var pools = Data.lightGroupPools;
            if (pools == null || groups.Length == 0) return;
            int nv = pools.vertices;
            var vidx = new uint[nv];
            Buffer.BlockCopy(bin, offset, vidx, 0, nv * 4);
            int valOffset = offset + nv * 4, texOffset = valOffset + nv;
            lmTexels = new byte[pools.texels];
            Buffer.BlockCopy(bin, texOffset, lmTexels, 0, lmTexels.Length);
            var gridSamples = new byte[pools.gridSamples];
            Buffer.BlockCopy(bin, texOffset + lmTexels.Length, gridSamples, 0, gridSamples.Length);
            lighting.UseGroups(LightGroups, groups, gridSamples);

            // Meshes by first vertex, to find the one a global vertex index is in.
            var order = new int[Data.meshes.Length];
            for (int i = 0; i < order.Length; i++) order[i] = i;
            Array.Sort(order, (a, b) => Data.meshes[a].vtxOffset.CompareTo(Data.meshes[b].vtxOffset));
            for (int gi = 0; gi < groups.Length; gi++)
            {
                var g = groups[gi];
                groupMeshes[gi] = new List<int>();
                int k = g.vtxStart, end = g.vtxStart + g.vtxCount;
                while (k < end)
                {
                    int mesh = MeshOf((int)vidx[k], order);
                    var mj = Data.meshes[mesh];
                    int first = k;
                    while (k < end && vidx[k] >= mj.vtxOffset && vidx[k] < mj.vtxOffset + mj.vtxCount) k++;
                    var local = new int[k - first];
                    var values = new byte[k - first];
                    for (int j = 0; j < local.Length; j++)
                    {
                        local[j] = (int)vidx[first + j] - mj.vtxOffset;
                        values[j] = bin[valOffset + first + j];
                    }
                    if (!litMeshes.TryGetValue(mesh, out var lm)) litMeshes[mesh] = lm = new LitMesh();
                    lm.Groups.Add((gi, local, values));
                    if (!groupMeshes[gi].Contains(mesh)) groupMeshes[gi].Add(mesh);
                }
                groupRects[gi] = new List<int>();
                foreach (var p in g.patches ?? new LightmapPatchJson[0])
                    if (!groupRects[gi].Contains(p.lm)) groupRects[gi].Add(p.lm);
            }
            var rects = Data.lightmapRects ?? new LightmapRectJson[0];
            rectPatches = new List<(int, LightmapPatchJson)>[rects.Length];
            for (int r = 0; r < rects.Length; r++) rectPatches[r] = new List<(int, LightmapPatchJson)>();
            for (int gi = 0; gi < groups.Length; gi++)
                foreach (var p in groups[gi].patches ?? new LightmapPatchJson[0])
                    rectPatches[p.lm].Add((gi, p));
        }

        int MeshOf(int vertex, int[] order)
        {
            int lo = 0, hi = order.Length - 1;
            while (lo < hi)
            {
                int mid = (lo + hi + 1) / 2;
                if (Data.meshes[order[mid]].vtxOffset <= vertex) lo = mid;
                else hi = mid - 1;
            }
            return order[lo];
        }

        // Whether the atlas must keep its base texels (a group has lightmap patches).
        bool KeepsAtlas => Data.lightmapRects != null && Data.lightmapRects.Length > 0;

        // BuildMesh hands over a mesh a group reaches, before uploading it: it stays writable.
        bool KeepMesh(int meshIndex, Mesh mesh, byte[] vertices)
        {
            if (!litMeshes.TryGetValue(meshIndex, out var lm)) return false;
            lm.Mesh = mesh;
            lm.Vertices = vertices;
            lm.BaseRgb = new byte[vertices.Length / VertexSize * 3];
            for (int v = 0, n = vertices.Length / VertexSize; v < n; v++)
                for (int c = 0; c < 3; c++) lm.BaseRgb[v * 3 + c] = vertices[v * VertexSize + ColorOffset + c];
            return true;
        }

        void KeepAtlas(byte[] pixels, int width)
        {
            atlasBase = pixels;
            atlasPixels = (byte[])pixels.Clone();
            atlasWidth = width;
        }

        // The LightGroup objects join (each sets its group now, as at its first update), then the world shows
        // every group at its colour, and follows each change.
        void JoinLightGroups()
        {
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                if (!string.Equals(o.cls, "LightGroup", StringComparison.OrdinalIgnoreCase)) continue;
                var c = o.Vec("StartColor", new Vector3(255, 255, 255));
                var obj = LightGroups.AddObject(o.name, o.Bool("StartOn"), new LTVec(c.x, c.y, c.z));
                Commands.Handle(i, obj.OnMessage);
            }
            foreach (var lm in litMeshes.Values) Relight(lm);
            if (rectPatches != null && atlasBase != null)
            {
                for (int r = 0; r < rectPatches.Length; r++) Relight(r);
                UploadAtlas();
            }
            lighting.GroupsChanged();
            LightGroups.Changed += OnLightGroupChanged;
        }

        void OnLightGroupChanged(int group)
        {
            // Models: the grid and the static lights follow the group; every model lit so far is lit again.
            lighting.GroupsChanged();
            foreach (var m in litModels)
                if (m.R) Light(m.R, m.Pos, m.Dims, m.VisRadius, m.SunAmount);
            foreach (int mesh in groupMeshes[group])
                if (litMeshes.TryGetValue(mesh, out var lm)) Relight(lm);
            if (atlasBase != null && groupRects[group].Count > 0)
            {
                foreach (int r in groupRects[group]) Relight(r);
                UploadAtlas();
            }
        }

        // A mesh's vertex colours: the base, then each group at its colour.
        void Relight(LitMesh lm)
        {
            if (lm.Mesh == null) return;
            var v = lm.Vertices;
            foreach (var (_, local, _) in lm.Groups)
                foreach (int i in local)
                    for (int c = 0; c < 3; c++) v[i * VertexSize + ColorOffset + c] = lm.BaseRgb[i * 3 + c];
            foreach (var (group, local, values) in lm.Groups)
            {
                var col = LightGroups[group].Color;
                if (col.x * 255 < 1 && col.y * 255 < 1 && col.z * 255 < 1) continue;
                for (int j = 0; j < local.Length; j++)
                {
                    int o = local[j] * VertexSize + ColorOffset;
                    // D3DCOLOR order in the vertex: r, g, b, a.
                    v[o] = LightGroups.Add(v[o], col.x, values[j]);
                    v[o + 1] = LightGroups.Add(v[o + 1], col.y, values[j]);
                    v[o + 2] = LightGroups.Add(v[o + 2], col.z, values[j]);
                }
            }
            lm.Mesh.SetVertexBufferData(v, 0, 0, v.Length);
        }

        // A section lightmap in the atlas: the base, each group's patches at its colour, then its one-texel
        // border replicated from its edge (tools/export_level.py pack_atlas).
        void Relight(int rect)
        {
            var r = Data.lightmapRects[rect];
            int w = atlasWidth;
            for (int y = r.y - 1; y <= r.y + r.h; y++)
                Array.Copy(atlasBase, ((y * w) + r.x - 1) * 4, atlasPixels, ((y * w) + r.x - 1) * 4, (r.w + 2) * 4);
            foreach (var (group, p) in rectPatches[rect])
            {
                var col = LightGroups[group].Color;
                if (col.x * 255 < 1 && col.y * 255 < 1 && col.z * 255 < 1) continue;
                for (int py = 0; py < p.h; py++)
                    for (int px = 0; px < p.w; px++)
                    {
                        byte val = lmTexels[p.start + py * p.w + px];
                        if (val == 0) continue;
                        int o = ((r.y + p.y + py) * w + r.x + p.x + px) * 4;
                        atlasPixels[o] = LightGroups.Add(atlasPixels[o], col.x, val);
                        atlasPixels[o + 1] = LightGroups.Add(atlasPixels[o + 1], col.y, val);
                        atlasPixels[o + 2] = LightGroups.Add(atlasPixels[o + 2], col.z, val);
                    }
            }
            for (int y = r.y; y < r.y + r.h; y++)
            {
                Array.Copy(atlasPixels, (y * w + r.x) * 4, atlasPixels, (y * w + r.x - 1) * 4, 4);
                Array.Copy(atlasPixels, (y * w + r.x + r.w - 1) * 4, atlasPixels, (y * w + r.x + r.w) * 4, 4);
            }
            Array.Copy(atlasPixels, (r.y * w + r.x - 1) * 4, atlasPixels, ((r.y - 1) * w + r.x - 1) * 4, (r.w + 2) * 4);
            Array.Copy(atlasPixels, ((r.y + r.h - 1) * w + r.x - 1) * 4, atlasPixels, ((r.y + r.h) * w + r.x - 1) * 4, (r.w + 2) * 4);
        }

        void UploadAtlas()
        {
            lightmapAtlas.SetPixelData(atlasPixels, 0);
            lightmapAtlas.Apply(false, false);
        }
    }
}
