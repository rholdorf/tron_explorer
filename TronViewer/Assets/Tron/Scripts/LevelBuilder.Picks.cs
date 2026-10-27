using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Tron
{
    // What pick mode (PickMode.cs, #112) aims at: the drawn world meshes (the main world's and the world
    // models', not the sky's), the placed models and the SpecialFX. Recorded while building; nothing here
    // changes what is built. The meshes' triangles are read again from level.bin only when pick mode first
    // turns on: the drawn meshes keep no CPU copy, and the physics colliders are the physics BSP (invisible
    // blockers, no textures).
    public partial class LevelBuilder
    {
        // A drawn world mesh: its renderer, its Data.meshes index, and for a world model its name, class and
        // BlendMode (null for the main world).
        public sealed class PickMesh
        {
            public MeshRenderer Renderer;
            public int Mesh;
            public string Blend, WorldModel, Class;
        }

        // A drawn mesh's triangles in its own frame, in LithTech units: x, y, z per vertex, three indices per
        // triangle, and per submesh its first triangle and its material (Data.materials).
        public sealed class PickGeometry
        {
            public float[] Positions;
            public int[] Indices, SubStart, SubMat;

            public int MaterialOf(int tri)
            {
                int s = SubStart.Length - 1;
                while (s > 0 && SubStart[s] > tri) s--;
                return SubMat[s];
            }
        }

        public string Dir;   // the level's export folder
        public readonly List<PickMesh> PickMeshes = new List<PickMesh>();
        public readonly List<(int obj, Transform t)> SpecialFXObjects = new List<(int, Transform)>();
        // The models shown for each object index (a character's body, a prop), not their attachments.
        public IReadOnlyDictionary<int, List<GameObject>> ModelObjects => modelObjects;

        // The placed instance of object `obj` (not an attachment), or null.
        public ModelInstanceJson ModelInstance(int obj) =>
            Data.models == null ? null : Array.Find(Data.models, m => m.obj == obj && m.parent < 0 && m.template == 0);

        // PickMeshes' triangles, in their order.
        public PickGeometry[] ReadPickGeometry()
        {
            var b = File.ReadAllBytes(Path.Combine(Dir, "level.bin"));
            var all = new PickGeometry[PickMeshes.Count];
            for (int m = 0; m < all.Length; m++)
            {
                var mj = Data.meshes[PickMeshes[m].Mesh];
                var g = all[m] = new PickGeometry
                {
                    Positions = new float[mj.vtxCount * 3],
                    SubStart = new int[mj.subs.Length],
                    SubMat = new int[mj.subs.Length],
                };
                for (int v = 0; v < mj.vtxCount; v++)
                {
                    int o = vtxBase + (mj.vtxOffset + v) * VertexSize;
                    for (int k = 0; k < 3; k++) g.Positions[v * 3 + k] = BitConverter.ToSingle(b, o + k * 4);
                }
                int count = 0;
                for (int s = 0; s < mj.subs.Length; s++)
                {
                    g.SubStart[s] = mj.subs[s].start / 3;
                    g.SubMat[s] = mj.subs[s].mat;
                    count += mj.subs[s].count;
                }
                g.Indices = new int[count];
                Buffer.BlockCopy(b, idxBase + mj.idxOffset * 4, g.Indices, 0, count * 4);
            }
            return all;
        }
    }
}
