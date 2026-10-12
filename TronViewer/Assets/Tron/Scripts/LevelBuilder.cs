using System;
using System.Collections.Generic;
using System.IO;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Rendering;

namespace Tron
{
    // Builds a Unity hierarchy from an exported level (level.json + level.bin).
    // Geometry stays in LithTech units under a root scaled by LT.Scale.
    public class LevelBuilder
    {
        public const int SkyLayer = 30;
        public const int FormatVersion = 5;
        const int HeaderSize = 32, VertexSize = 44;

        // World model classes that collide like solid brushes (WorldModel family).
        static readonly HashSet<string> SolidClasses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "WorldModel", "SlidingDoor", "RotatingDoor", "Door", "SlidingWorldModel", "RotatingWorldModel",
            "SpinningWorldModel", "SlidingSwitch", "RotatingSwitch", "Breakable", "DemoSkyWorldModel",
        };
        // Brush volumes: never drawn by the game, never solid.
        static readonly HashSet<string> HiddenClasses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "DynamicOccluderVolume", "VolumeBrush", "EndlessFall", "SafteyNet", "Wind", "Electricity", "EnergyZone",
            "LightCycleSlowZone", "LightCycleSpeedZone", "HealthZone",
        };

        public LevelJson Data;
        public GameObject Root;
        public Vector3 SkyViewMin, SkyViewMax;   // LT units
        public bool HasSky;

        // d3d_SetupSkyStuff: the sky eye moves inside the view box proportionally to where the
        // camera is inside the world extents.
        public Vector3 SkyViewPos(Vector3 camLT)
        {
            var min = new Vector3(Data.extMin[0], Data.extMin[1], Data.extMin[2]);
            var max = new Vector3(Data.extMax[0], Data.extMax[1], Data.extMax[2]);
            var t = new Vector3((camLT.x - min.x) / (max.x - min.x), (camLT.y - min.y) / (max.y - min.y), (camLT.z - min.z) / (max.z - min.z));
            return SkyViewMin + Vector3.Scale(SkyViewMax - SkyViewMin, t);
        }
        public readonly Dictionary<string, GameObject> WorldModelObjects = new Dictionary<string, GameObject>();
        public readonly List<string> MissingTextures = new List<string>();

        Material[] materials;
        readonly Dictionary<(int, string, float, int, bool), Material> blendedMaterials = new Dictionary<(int, string, float, int, bool), Material>();
        readonly List<UnityEngine.Object> owned = new List<UnityEngine.Object>();
        Shader shader, modelShader;
        Texture2D lightmapAtlas;
        byte[] bin;
        int vtxBase, idxBase, cvtxBase, cidxBase;

        public void Build(string levelDir, Shader worldShader, Shader modelShader, string exportRoot)
        {
            shader = worldShader;
            this.modelShader = modelShader;
            Data = JsonUtility.FromJson<LevelJson>(File.ReadAllText(Path.Combine(levelDir, "level.json")));
            if (Data.version != FormatVersion) throw new Exception($"level format v{Data.version}, expected v{FormatVersion}: re-run tools/export_level.py");
            bin = File.ReadAllBytes(Path.Combine(levelDir, "level.bin"));
            if (bin[0] != 'T' || bin[1] != 'R' || bin[2] != 'L' || bin[3] != 'V') throw new Exception("bad level.bin");
            int nv = BitConverter.ToInt32(bin, 8), ni = BitConverter.ToInt32(bin, 12);
            int ncv = BitConverter.ToInt32(bin, 16), nci = BitConverter.ToInt32(bin, 20);
            vtxBase = HeaderSize;
            idxBase = vtxBase + nv * VertexSize;
            cvtxBase = idxBase + ni * 4;
            cidxBase = cvtxBase + ncv * 12;
            LoadLightmapAtlas(BitConverter.ToInt32(bin, 24), BitConverter.ToInt32(bin, 28), cidxBase + nci * 4);

            Root = new GameObject("Level " + Data.name);
            Root.transform.localScale = Vector3.one * LT.Scale;

            BuildMaterials();

            var world = new GameObject("World");
            world.transform.SetParent(Root.transform, false);
            world.isStatic = true;
            foreach (var mi in Data.worldMeshes)
                AddRenderer(world.transform, mi, null, 1f);
            if (Data.worldCollider >= 0) AddCollider(world.transform, Data.worldCollider, "PhysicsBSP");
            if (Data.blockerCollider >= 0) AddCollider(world.transform, Data.blockerCollider, "Blockers");

            BuildWorldModels();
            bin = null;
            BuildModels(exportRoot);
        }

        // One RGBA atlas of all section lightmaps (see tools/export_level.py); raw values, like the DTX path.
        void LoadLightmapAtlas(int width, int height, int offset)
        {
            if (width == 0 || height == 0) return;
            lightmapAtlas = new Texture2D(width, height, TextureFormat.RGBA32, false, true)
            {
                name = "Lightmaps", wrapMode = TextureWrapMode.Clamp, filterMode = FilterMode.Bilinear,
            };
            owned.Add(lightmapAtlas);
            using (var px = new NativeArray<byte>(width * height * 4, Allocator.Temp))
            {
                NativeArray<byte>.Copy(bin, offset, px, 0, px.Length);
                lightmapAtlas.LoadRawTextureData(px);
            }
            lightmapAtlas.Apply(false, true);
        }

        // Section shaders whose texture pass is multiplied over a lightmap (d3d_renderblock.cpp).
        static bool IsLightmapped(int shader) => shader == 4 || shader == 9;

        void BuildMaterials()
        {
            materials = new Material[Data.materials.Length];
            for (int i = 0; i < materials.Length; i++)
            {
                var mj = Data.materials[i];
                var m = CreateMaterial(mj.tex);
                if (IsLightmapped(mj.shader) && lightmapAtlas)
                {
                    m.SetTexture("_LightmapTex", lightmapAtlas);
                    m.SetFloat("_UseLightmap", 1);
                }
                TextureEffects.Apply(m, mj.effect);
                materials[i] = m;
            }
        }

        // A world-shader material for one LithTech texture, honoring its DTX command string.
        Material CreateMaterial(string tex)
        {
            var m = new Material(shader) { name = tex };
            owned.Add(m);
            var t = DtxLoader.Load(tex);
            if (t == null)
            {
                if (!string.IsNullOrEmpty(tex)) MissingTextures.Add(tex);
                return m;
            }
            m.SetTexture("_MainTex", t.tex);
            if (t.uvScale != 1) m.SetTextureScale("_MainTex", Vector2.one * t.uvScale);
            if (t.alphaRef > 0) m.SetFloat("_Cutoff", t.alphaRef / 255f);
            if (t.fullbright) m.SetFloat("_Fullbright", 1);
            var env = string.IsNullOrEmpty(t.envMap) ? null : DtxLoader.Load(t.envMap);
            if (env != null)
            {
                m.SetTexture("_EnvTex", env.tex);
                m.SetFloat("_UseEnv", 1);
                m.SetFloat("_EnvAlpha", t.envMapAlpha ? 1 : 0);
            }
            var det = string.IsNullOrEmpty(t.detailTex) ? null : DtxLoader.Load(t.detailTex);
            if (det != null)
            {
                float rad = t.detailAngle * Mathf.Deg2Rad;
                m.SetTexture("_DetailTex", det.tex);
                m.SetFloat("_UseDetail", 1);
                m.SetVector("_DetailScale", new Vector4(t.detailScale, t.detailScale, Mathf.Cos(rad), Mathf.Sin(rad)));
            }
            if (t.frames != null && t.frames.Length > 1)
                SpriteAnimator.Register(m, t.frames, t.frameRate);
            return m;
        }

        // Model instances (see tools/export_models.py), drawn at the bind pose for now.
        void BuildModels(string exportRoot)
        {
            if (Data.models == null || Data.models.Length == 0) return;
            var root = new GameObject("Models");
            root.transform.SetParent(Root.transform, false);
            var styleMaterials = new Dictionary<(int, string, string), Material>();
            var models = new Dictionary<string, LoadedModel>(StringComparer.OrdinalIgnoreCase);
            foreach (var inst in Data.models)
            {
                var model = ModelLibrary.Load(exportRoot, inst.file, models, owned);
                if (model == null) continue;
                if (inst.pieces == null || inst.pieces.Length != model.data.pieces.Length)
                {
                    Debug.LogWarning($"Model {inst.file}: {inst.pieces?.Length ?? 0} piece styles for {model.data.pieces.Length} pieces");
                    continue;
                }
                var obj = Data.objects[inst.obj];
                var go = new GameObject($"{obj.name} [{obj.cls}: {inst.file}]");
                go.transform.SetParent(root.transform, false);
                go.transform.localPosition = obj.Position;
                go.transform.localRotation = obj.Rotation;
                if (inst.scale != null && inst.scale.Length >= 3) go.transform.localScale = new Vector3(inst.scale[0], inst.scale[1], inst.scale[2]);
                go.AddComponent<MeshFilter>().sharedMesh = model.mesh;
                var mats = new Material[inst.pieces.Length];
                for (int i = 0; i < mats.Length; i++)
                {
                    var p = inst.pieces[i];
                    string t1 = p.tex != null && p.tex.Length > 0 ? p.tex[0] : "", t2 = p.tex != null && p.tex.Length > 1 ? p.tex[1] : "";
                    var key = (p.style, t1, t2);
                    if (!styleMaterials.TryGetValue(key, out var m))
                        styleMaterials[key] = m = CreateModelMaterial(Data.renderStyles[p.style], t1, t2);
                    mats[i] = m;
                }
                var mr = go.AddComponent<MeshRenderer>();
                mr.sharedMaterials = mats;
                mr.shadowCastingMode = ShadowCastingMode.Off;
                mr.receiveShadows = false;
                mr.lightProbeUsage = LightProbeUsage.Off;
                mr.reflectionProbeUsage = ReflectionProbeUsage.Off;
            }
        }

        // A Tron/Model material for one compiled render style and the piece's texture list.
        Material CreateModelMaterial(RenderStyleJson rs, string tex1, string tex2)
        {
            var m = new Material(modelShader) { name = $"{rs.name} {tex1}" };
            owned.Add(m);
            foreach (var (prop, tex) in new[] { ("_Tex1", tex1), ("_Tex2", tex2) })
            {
                if (string.IsNullOrEmpty(tex)) continue;
                var t = DtxLoader.Load(tex);
                if (t != null) m.SetTexture(prop, t.tex);
                else MissingTextures.Add(tex);
            }
            SetPass(m, "_S", rs.passes[0], "_TF0", "_P0");
            if (rs.passes.Length > 1) SetPass(m, "_T", rs.passes[1], "_TF1", "_P1");
            SetPass(m, "_G", rs.glow, "_TFG", "_PG");
            m.SetVector("_MatDiffuse", Vec(rs.material.diffuse));
            m.SetVector("_MatEmissive", Vec(rs.material.emissive));
            m.SetVector("_MatAmbient", Vec(rs.material.ambient));
            m.SetFloat("_SrcBlend", rs.blend[0]);
            m.SetFloat("_DstBlend", rs.blend[1]);
            m.SetFloat("_ZWrite", rs.zwrite);
            m.SetFloat("_ZTest", rs.ztest);
            m.SetFloat("_Cull", rs.cull);
            // Blended styles draw after the opaque world, like the engine's translucent model list.
            if (rs.blend[0] != (int)BlendMode.One || rs.blend[1] != (int)BlendMode.Zero) m.renderQueue = (int)RenderQueue.Transparent;
            else if (rs.passes[0].alphaTest[0] != 0) m.renderQueue = (int)RenderQueue.AlphaTest;
            return m;
        }

        static void SetPass(Material m, string stagePrefix, RenderPassJson p, string tf, string flags)
        {
            var s = p.stages;
            m.SetVector(stagePrefix + "0a", new Vector4(s[0], s[1], s[2], s[3]));
            m.SetVector(stagePrefix + "0b", new Vector4(s[4], s[5], s[6], s[7]));
            m.SetVector(stagePrefix + "1a", new Vector4(s[8], s[9], s[10], s[11]));
            m.SetVector(stagePrefix + "1b", new Vector4(s[12], s[13], s[14], s[15]));
            m.SetVector(tf, Vec(p.tfactor));
            m.SetVector(flags, new Vector4(p.lit, p.blendOver, p.alphaTest[0], p.alphaTest[1]));
        }

        static Vector4 Vec(float[] v) => new Vector4(v[0], v[1], v[2], v[3]);

        // skySlot >= 0: sky object drawn painter-style in SkyPointer.Index order with no Z buffer
        // (d3d_drawsky.cpp disables Z read/write for the whole sky pass).
        Material GetMaterial(int index, string blendMode, float alpha, int skySlot = -1, bool noFog = false)
        {
            if (string.IsNullOrEmpty(blendMode)) blendMode = "None";
            if (blendMode == "None" && skySlot < 0 && !noFog) return materials[index];
            var key = (index, blendMode, alpha, skySlot, noFog);
            if (blendedMaterials.TryGetValue(key, out var m)) return m;
            m = new Material(materials[index]);
            owned.Add(m);
            TextureEffects.RegisterClone(materials[index], m);
            SpriteAnimator.RegisterClone(materials[index], m);
            if (noFog) m.SetFloat("_NoFog", 1);
            if (blendMode != "None")
            {
                m.renderQueue = (int)RenderQueue.Transparent;
                m.SetFloat("_ZWrite", 0);
                m.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
                m.SetFloat("_DstBlend", (float)(blendMode == "Additive" ? BlendMode.One : BlendMode.OneMinusSrcAlpha));
            }
            if (skySlot >= 0)
            {
                m.SetFloat("_ZWrite", 0);
                m.SetFloat("_ZTest", (float)CompareFunction.Always);
                m.renderQueue = (int)RenderQueue.Background + skySlot;
            }
            blendedMaterials[key] = m;
            return m;
        }

        void BuildWorldModels()
        {
            // Name -> owning object (prefer brush classes over point objects that share the name).
            var owners = new Dictionary<string, ObjectJson>(StringComparer.OrdinalIgnoreCase);
            foreach (var o in Data.objects)
            {
                if (string.IsNullOrEmpty(o.name)) continue;
                bool brush = SolidClasses.Contains(o.cls) || HiddenClasses.Contains(o.cls);
                if (!owners.TryGetValue(o.name, out var prev) || (brush && !(SolidClasses.Contains(prev.cls) || HiddenClasses.Contains(prev.cls))))
                    owners[o.name] = o;
            }
            // SkyPointer (ltengineobjects.cpp): each one puts SkyObjectName into sky slot Index; the one
            // with non-zero SkyDims defines the SkyDef view box pos +- SkyDims * InnerPercent.
            var skySlots = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (var o in Data.objects)
            {
                if (o.cls != "SkyPointer") continue;
                skySlots[o.Str("SkyObjectName")] = (int)o.Num("Index");
                var dims = o.Vec("SkyDims");
                if (dims.x != 0 && dims.y != 0 && dims.z != 0)
                {
                    var inner = Vector3.Scale(dims, new Vector3(o.Num("InnerPercentX", 0.1f), o.Num("InnerPercentY", 0.1f), o.Num("InnerPercentZ", 0.1f)));
                    SkyViewMin = o.Position - inner;
                    SkyViewMax = o.Position + inner;
                    HasSky = true;
                }
            }

            var wmRoot = new GameObject("WorldModels");
            wmRoot.transform.SetParent(Root.transform, false);
            var skyRoot = new GameObject("Sky");
            skyRoot.transform.SetParent(Root.transform, false);

            foreach (var wm in Data.worldModels)
            {
                owners.TryGetValue(wm.name, out var obj);
                bool sky = skySlots.TryGetValue(wm.name, out int skySlot);
                string cls = obj?.cls ?? "";
                if (!sky && (obj == null || HiddenClasses.Contains(cls))) continue;
                if (wm.mesh < 0 && (sky || !SolidClasses.Contains(cls))) continue;

                // Object transform: geometry is stored in world space at the object's initial
                // placement, so the child carries the inverse transform.
                var go = new GameObject($"{wm.name} [{(sky ? "Sky" : cls)}]");
                go.transform.SetParent(sky ? skyRoot.transform : wmRoot.transform, false);
                var pos = obj?.Position ?? Vector3.zero;
                var rot = obj != null ? obj.Rotation : Quaternion.identity;
                go.transform.localPosition = pos;
                go.transform.localRotation = rot;
                var geom = new GameObject("geom");
                geom.transform.SetParent(go.transform, false);
                var inv = Quaternion.Inverse(rot);
                geom.transform.localRotation = inv;
                geom.transform.localPosition = inv * -pos;
                WorldModelObjects[wm.name] = go;

                bool visible = obj == null || (obj.Bool("Visible", true) && !obj.Bool("StartHidden"));
                if (wm.mesh >= 0 && visible)
                {
                    string blend = obj?.Str("BlendMode", "None") ?? "None";
                    // WorldModel "Alpha" is baked into vertex alpha by the preprocessor (worldmodel.cpp:
                    // "Pre-Processor looks at this value"); runtime object alpha stays 1. Only BlendMode
                    // (FLAG2_ADDITIVE / FLAG2_FORCETRANSLUCENT) decides whether blending is enabled.
                    float alpha = 1f;
                    bool noFog = obj != null && obj.Bool("FogDisable");
                    AddRenderer(geom.transform, wm.mesh, blend, alpha, sky ? skySlot : -1, noFog);
                }
                if (sky)
                {
                    SetLayer(go, SkyLayer);
                    continue;
                }
                if (wm.collider >= 0 && SolidClasses.Contains(cls) && obj.Bool("Solid", true))
                    AddCollider(geom.transform, wm.collider, "collider");
            }
        }

        static void SetLayer(GameObject go, int layer)
        {
            go.layer = layer;
            foreach (Transform c in go.transform) SetLayer(c.gameObject, layer);
        }

        void AddRenderer(Transform parent, int meshIndex, string blend, float alpha, int skySlot = -1, bool noFog = false)
        {
            var mj = Data.meshes[meshIndex];
            var go = new GameObject(mj.name);
            go.transform.SetParent(parent, false);
            go.isStatic = parent.gameObject.isStatic;
            var mesh = BuildMesh(mj);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mr = go.AddComponent<MeshRenderer>();
            var mats = new Material[mj.subs.Length];
            for (int i = 0; i < mats.Length; i++) mats[i] = GetMaterial(mj.subs[i].mat, blend, alpha, skySlot, noFog);
            mr.sharedMaterials = mats;
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = false;
            mr.lightProbeUsage = LightProbeUsage.Off;
            mr.reflectionProbeUsage = ReflectionProbeUsage.Off;
        }

        Mesh BuildMesh(MeshJson mj)
        {
            var mesh = new Mesh { name = mj.name };
            owned.Add(mesh);
            mesh.SetVertexBufferParams(mj.vtxCount,
                new VertexAttributeDescriptor(VertexAttribute.Position, VertexAttributeFormat.Float32, 3),
                new VertexAttributeDescriptor(VertexAttribute.Normal, VertexAttributeFormat.Float32, 3),
                new VertexAttributeDescriptor(VertexAttribute.Color, VertexAttributeFormat.UNorm8, 4),
                new VertexAttributeDescriptor(VertexAttribute.TexCoord0, VertexAttributeFormat.Float32, 2),
                new VertexAttributeDescriptor(VertexAttribute.TexCoord1, VertexAttributeFormat.Float32, 2));
            using (var vb = new NativeArray<byte>(mj.vtxCount * VertexSize, Allocator.Temp))
            {
                NativeArray<byte>.Copy(bin, vtxBase + mj.vtxOffset * VertexSize, vb, 0, vb.Length);
                mesh.SetVertexBufferData(vb, 0, 0, vb.Length);
            }
            int idxCount = 0;
            foreach (var s in mj.subs) idxCount += s.count;
            mesh.SetIndexBufferParams(idxCount, IndexFormat.UInt32);
            using (var ib = new NativeArray<byte>(idxCount * 4, Allocator.Temp))
            {
                NativeArray<byte>.Copy(bin, idxBase + mj.idxOffset * 4, ib, 0, ib.Length);
                mesh.SetIndexBufferData(ib, 0, 0, ib.Length);
            }
            var bounds = new Bounds();
            bounds.SetMinMax(new Vector3(mj.min[0], mj.min[1], mj.min[2]), new Vector3(mj.max[0], mj.max[1], mj.max[2]));
            mesh.subMeshCount = mj.subs.Length;
            for (int i = 0; i < mj.subs.Length; i++)
                mesh.SetSubMesh(i, new SubMeshDescriptor(mj.subs[i].start, mj.subs[i].count) { bounds = bounds, firstVertex = 0, vertexCount = mj.vtxCount },
                    MeshUpdateFlags.DontRecalculateBounds | MeshUpdateFlags.DontValidateIndices);
            mesh.bounds = bounds;
            mesh.UploadMeshData(true);
            return mesh;
        }

        void AddCollider(Transform parent, int colliderIndex, string name)
        {
            var cj = Data.colliders[colliderIndex];
            var verts = new Vector3[cj.vtxCount];
            for (int i = 0; i < verts.Length; i++)
            {
                int o = cvtxBase + (cj.vtxOffset + i) * 12;
                // Cook in meters (PhysX dislikes huge triangles); the child undoes the parent scale.
                verts[i] = new Vector3(BitConverter.ToSingle(bin, o), BitConverter.ToSingle(bin, o + 4), BitConverter.ToSingle(bin, o + 8)) * LT.Scale;
            }
            var idx = new int[cj.idxCount];
            Buffer.BlockCopy(bin, cidxBase + cj.idxOffset * 4, idx, 0, idx.Length * 4);
            var mesh = new Mesh { name = cj.name, indexFormat = IndexFormat.UInt32 };
            owned.Add(mesh);
            mesh.vertices = verts;
            mesh.triangles = idx;
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localScale = Vector3.one / LT.Scale;
            go.AddComponent<MeshCollider>().sharedMesh = mesh;
        }

        public void Destroy()
        {
            if (Root) UnityEngine.Object.Destroy(Root);
            foreach (var o in owned) UnityEngine.Object.Destroy(o);
            owned.Clear();
            SpriteAnimator.Clear();
            TextureEffects.Clear();
        }
    }

    public static class LT
    {
        // 1 LithTech unit in meters: player dims (24, 53, 24) half-extents -> 106 units ~ 1.8 m.
        public const float Scale = 0.017f;
    }
}
