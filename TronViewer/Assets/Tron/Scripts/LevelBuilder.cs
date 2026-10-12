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
    public partial class LevelBuilder
    {
        public const int SkyLayer = 30;
        public const int FormatVersion = 18;
        const int HeaderSize = 32, VertexSize = 44;

        // World model classes that collide like solid brushes (WorldModel family). Kept in step with
        // tools/floor.py SOLID_CLASSES / HIDDEN_CLASSES (the exporter's MoveToFloor caster).
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
        public CommandMgr Commands;   // the level's command manager (JoinCommands)
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
        // Object index -> the model instances drawn for it that aren't attachments (a bin and its frame).
        readonly Dictionary<int, List<GameObject>> modelObjects = new Dictionary<int, List<GameObject>>();
        public readonly List<string> MissingTextures = new List<string>();

        Material[] materials;
        readonly Dictionary<(int, string, float, int, bool), Material> blendedMaterials = new Dictionary<(int, string, float, int, bool), Material>();
        readonly List<UnityEngine.Object> owned = new List<UnityEngine.Object>();
        Shader shader, modelShader;
        Texture2D lightmapAtlas;
        ModelLighting lighting;
        byte[] bin;
        int vtxBase, idxBase, cvtxBase, cidxBase;

        public void Build(string levelDir, Shader worldShader, Shader modelShader, string exportRoot, bool ltjsGridOrder)
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
            int lmW = BitConverter.ToInt32(bin, 24), lmH = BitConverter.ToInt32(bin, 28);
            LoadLightmapAtlas(lmW, lmH, cidxBase + nci * 4);
            LoadLightGrid(cidxBase + nci * 4 + lmW * lmH * 4, ltjsGridOrder);

            Root = new GameObject("Level " + Data.name);
            Root.transform.localScale = Vector3.one * LT.Scale;
            JoinCommands();

            BuildMaterials();

            var world = new GameObject("World");
            world.transform.SetParent(Root.transform, false);
            world.isStatic = true;
            foreach (var mi in Data.worldMeshes)
                AddRenderer(world.transform, mi, null, 1f);
            if (Data.worldCollider >= 0) AddCollider(world.transform, Data.worldCollider, "PhysicsBSP");
            if (Data.blockerCollider >= 0) AddCollider(world.transform, Data.blockerCollider, "Blockers");

            BuildWorldModels();
            BuildActiveWorldModels();   // LevelBuilderDoors.cs
            bin = null;
            BuildModels(exportRoot);
            BuildSoundFX();
            BuildSoundButeFX();
            BuildKeyframers();
            RelayTicker.Build(this);
        }

        // Every level object joins the command manager by name and class, in level order, so an object's
        // id is its index in Data.objects; builders add handlers with Commands.Handle(index, ...). Groups
        // pass their messages on to their Object1..Object50 (Tron's 50 slots). Ticked by CommandTicker.
        void JoinCommands()
        {
            Commands = new CommandMgr();
            foreach (var o in Data.objects)
            {
                if (string.Equals(o.cls, "Group", StringComparison.OrdinalIgnoreCase))
                {
                    var members = new string[50];
                    for (int i = 0; i < members.Length; i++) members[i] = o.Str("Object" + (i + 1));
                    Commands.JoinGroup(o.name, members);
                }
                else
                    Commands.Join(o.name, o.cls);
            }
            Root.AddComponent<CommandTicker>().Commands = Commands;
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

        // The light grid follows the lightmap atlas (tools/export_level.py); models are lit from it.
        void LoadLightGrid(int offset, bool ltjsGridOrder)
        {
            var d = Data.lightGrid.dims;
            var grid = new byte[d[0] * d[1] * d[2] * 3];
            if (offset + grid.Length > bin.Length) throw new Exception("level.bin: light grid truncated");
            Buffer.BlockCopy(bin, offset, grid, 0, grid.Length);
            lighting = new ModelLighting(Data, grid, ltjsGridOrder);
        }

        // Section shaders whose texture pass is multiplied over a lightmap (d3d_renderblock.cpp).
        static bool IsLightmapped(int shader) => shader == 4 || shader == 9;

        // Dual-texture sections without a second texture (all of them in the retail data; the exporter
        // refuses any other): the engine falls back to the plain Gouraud_Texture / Lightmap_Texture
        // shader, which ignores the texture's EnvMap and DetailTex (docs/research/dual-texture.md).
        static bool IsPlainTexture(int shader) => shader == 8 || shader == 9;

        void BuildMaterials()
        {
            materials = new Material[Data.materials.Length];
            for (int i = 0; i < materials.Length; i++)
            {
                var mj = Data.materials[i];
                var m = CreateMaterial(mj.tex, !IsPlainTexture(mj.shader));
                if (IsLightmapped(mj.shader) && lightmapAtlas)
                {
                    m.SetTexture("_LightmapTex", lightmapAtlas);
                    m.SetFloat("_UseLightmap", 1);
                }
                TextureEffects.Apply(m, mj.effect);
                materials[i] = m;
            }
        }

        // A world-shader material for one LithTech texture, honoring its DTX command string
        // (EnvMap and DetailTex only when `useEnvAndDetail`: the engine picked an env/detail shader).
        Material CreateMaterial(string tex, bool useEnvAndDetail)
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
            var env = !useEnvAndDetail || string.IsNullOrEmpty(t.envMap) ? null : DtxLoader.Load(t.envMap);
            if (env != null)
            {
                m.SetTexture("_EnvTex", env.tex);
                m.SetFloat("_UseEnv", 1);
                m.SetFloat("_EnvAlpha", t.envMapAlpha ? 1 : 0);
            }
            var det = !useEnvAndDetail || string.IsNullOrEmpty(t.detailTex) ? null : DtxLoader.Load(t.detailTex);
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

        // Model instances (see tools/export_models.py), at their spawn position (after MoveToFloor). Props:
        // a MeshRenderer at the bind pose. Characters: a SkinnedMeshRenderer over one Transform per model
        // node, looping their clip (ModelAnimator). Attachments hang from their parent's socket node (a
        // prop's nodes stay at the bind pose); a character's are posed at their own animation 0, frame 0
        // (attachment models keep their geometry where it sits on the body and move it to the socket with
        // that pose), and follow it as the character moves.
        void BuildModels(string exportRoot)
        {
            if (Data.models == null || Data.models.Length == 0) return;
            var root = new GameObject("Models");
            root.transform.SetParent(Root.transform, false);
            var styleMaterials = new Dictionary<(int, string, string), Material[]>();
            var models = new Dictionary<string, LoadedModel>(StringComparer.OrdinalIgnoreCase);
            var repeatMeshes = new Dictionary<string, Mesh>();
            var repeats = new List<int>();
            var repeatMats = new List<Material>();
            var built = new (LoadedModel model, Transform[] bones)[Data.models.Length];
            var mpb = new MaterialPropertyBlock();
            var lightDirs = new Vector4[ModelLighting.MaxLights];
            var lightColors = new Vector4[ModelLighting.MaxLights];
            var animator = root.AddComponent<ModelAnimator>();
            for (int n = 0; n < Data.models.Length; n++)
            {
                var inst = Data.models[n];
                var model = ModelLibrary.Load(exportRoot, inst.file, models, owned);
                if (model == null) continue;
                if (inst.pieces == null || inst.pieces.Length != model.data.pieces.Length)
                {
                    Debug.LogWarning($"Model {inst.file}: {inst.pieces?.Length ?? 0} piece styles for {model.data.pieces.Length} pieces");
                    continue;
                }
                var obj = Data.objects[inst.obj];
                var go = new GameObject($"{obj.name} [{obj.cls}: {inst.file}]");
                var pos = inst.pos != null && inst.pos.Length >= 3 ? new Vector3(inst.pos[0], inst.pos[1], inst.pos[2]) : obj.Position;
                if (inst.parent >= 0)
                {
                    if (!AttachToSocket(go.transform, inst, built[inst.parent])) { UnityEngine.Object.Destroy(go); continue; }
                }
                else
                {
                    go.transform.SetParent(root.transform, false);
                    if (!modelObjects.TryGetValue(inst.obj, out var shown)) modelObjects[inst.obj] = shown = new List<GameObject>();
                    shown.Add(go);
                    go.transform.localPosition = pos;
                    go.transform.localRotation = obj.Rotation;
                    if (inst.scale != null && inst.scale.Length >= 3) go.transform.localScale = new Vector3(inst.scale[0], inst.scale[1], inst.scale[2]);
                }
                // One material per piece for its style's first draw; later draws repeat the piece as extra
                // submeshes of the same renderer (same skinning and property block), drawn after it.
                var mats = new Material[inst.pieces.Length];
                repeats.Clear();
                repeatMats.Clear();
                for (int i = 0; i < mats.Length; i++)
                {
                    var p = inst.pieces[i];
                    string tex1 = p.tex != null && p.tex.Length > 0 ? p.tex[0] : "", tex2 = p.tex != null && p.tex.Length > 1 ? p.tex[1] : "";
                    var key = (p.style, tex1, tex2);
                    if (!styleMaterials.TryGetValue(key, out var m))
                        styleMaterials[key] = m = CreateModelMaterials(Data.renderStyles[p.style], tex1, tex2);
                    mats[i] = m[0];
                    for (int d = 1; d < m.Length; d++)
                    {
                        repeats.Add(i);
                        repeatMats.Add(m[d]);
                    }
                }
                var mesh = model.mesh;
                if (repeats.Count > 0)
                {
                    mesh = ModelLibrary.WithRepeatedPieces(model, repeats, repeatMeshes, owned);
                    var all = new Material[mats.Length + repeatMats.Count];
                    mats.CopyTo(all, 0);
                    repeatMats.CopyTo(all, mats.Length);
                    mats = all;
                }
                Renderer r;
                if (inst.skinned != 0)
                {
                    var bones = BuildBones(go.transform, model, inst.parent >= 0);
                    built[n] = (model, bones);
                    if (inst.parent < 0 && !string.IsNullOrEmpty(inst.anim) && !animator.Play(model, inst.anim, bones))
                        Debug.LogWarning($"Model {inst.file}: no clip {inst.anim}");
                    var smr = go.AddComponent<SkinnedMeshRenderer>();
                    smr.sharedMesh = mesh;
                    smr.bones = bones;
                    smr.localBounds = SkinnedBounds(go.transform, model, bones);
                    r = smr;
                }
                else
                {
                    // A prop with sockets can carry attachments (bin berries, tank turrets): its node
                    // Transforms at the bind pose, the pose its mesh is drawn in.
                    if (model.data.sockets != null && model.data.sockets.Length > 0)
                        built[n] = (model, BuildBones(go.transform, model, false));
                    go.AddComponent<MeshFilter>().sharedMesh = mesh;
                    r = go.AddComponent<MeshRenderer>();
                }
                r.sharedMaterials = mats;
                r.shadowCastingMode = ShadowCastingMode.Off;
                r.receiveShadows = false;
                r.lightProbeUsage = LightProbeUsage.Off;
                r.reflectionProbeUsage = ReflectionProbeUsage.Off;

                // Per-instance D3D lighting (ModelLighting): ambient and up to 4 directional lights, 0-1.
                // Every instance has its own (attachments: their model's dims at the parent object's position).
                var dims = inst.dims != null && inst.dims.Length >= 3 ? new Vector3(inst.dims[0], inst.dims[1], inst.dims[2]) : Vector3.zero;
                var ambient = lighting.Compute(pos, dims, inst.visRadius, inst.sunAmount, lightDirs, lightColors);
                for (int i = 0; i < lightColors.Length; i++) lightColors[i] /= 255f;
                mpb.Clear();
                mpb.SetVector(AmbientId, ambient / 255f);
                mpb.SetVectorArray(LightDirId, lightDirs);
                mpb.SetVectorArray(LightColorId, lightColors);
                r.SetPropertyBlock(mpb);
            }
            animator.Begin();
        }

        static readonly int AmbientId = Shader.PropertyToID("_LTAmbient");
        static readonly int LightDirId = Shader.PropertyToID("_LTLightDir");
        static readonly int LightColorId = Shader.PropertyToID("_LTLightColor");

        // One Transform per model node, parented like the node tree. Bind pose: local = parent bind^-1 x bind.
        // Otherwise the exported first-frame pose (parent-relative position + rotation).
        static Transform[] BuildBones(Transform owner, LoadedModel model, bool firstFramePose)
        {
            var nodes = model.data.nodes;
            var bones = new Transform[nodes.Length];
            for (int i = 0; i < nodes.Length; i++)
            {
                var b = new GameObject(nodes[i].name).transform;
                int parent = nodes[i].parent;
                b.SetParent(parent >= 0 ? bones[parent] : owner, false);
                if (firstFramePose)
                {
                    var q = nodes[i].pose;
                    b.localPosition = new Vector3(q[0], q[1], q[2]);
                    b.localRotation = new Quaternion(q[3], q[4], q[5], q[6]);
                }
                else
                {
                    var local = parent >= 0 ? model.BindMatrix(parent).inverse * model.BindMatrix(i) : model.BindMatrix(i);
                    b.localPosition = local.GetColumn(3);
                    b.localRotation = local.rotation;
                }
                bones[i] = b;
            }
            return bones;
        }

        // CLTCommonShared::GetAttachmentTransform: the attachment sits at the parent's socket (node x socket
        // rotation/position, zero offset) and takes the socket's scale (r_ProcessAttachment).
        static bool AttachToSocket(Transform t, ModelInstanceJson inst, (LoadedModel model, Transform[] bones) parent)
        {
            if (parent.model == null || parent.bones == null) return false;
            var socket = Array.Find(parent.model.data.sockets, s => string.Equals(s.name, inst.socket, StringComparison.OrdinalIgnoreCase));
            if (socket == null)
            {
                Debug.LogWarning($"Attachment {inst.file}: no socket {inst.socket} on {parent.model.data.file}");
                return false;
            }
            t.SetParent(parent.bones[socket.node], false);
            t.localPosition = new Vector3(socket.pos[0], socket.pos[1], socket.pos[2]);
            t.localRotation = new Quaternion(socket.rot[0], socket.rot[1], socket.rot[2], socket.rot[3]);
            t.localScale = new Vector3(socket.scale[0], socket.scale[1], socket.scale[2]);
            return true;
        }

        // The bind-pose mesh bounds carried by each bone's skin matrix, in the renderer's space: exact at
        // the bind pose, and covers attachments whose first-frame pose moves the geometry.
        static Bounds SkinnedBounds(Transform owner, LoadedModel model, Transform[] bones)
        {
            var mb = model.mesh.bounds;
            var bindposes = model.mesh.bindposes;
            var toOwner = owner.worldToLocalMatrix;
            var result = new Bounds();
            for (int i = 0; i < bones.Length; i++)
            {
                var skin = toOwner * bones[i].localToWorldMatrix * bindposes[i];
                for (int c = 0; c < 8; c++)
                {
                    var corner = new Vector3((c & 1) != 0 ? mb.max.x : mb.min.x, (c & 2) != 0 ? mb.max.y : mb.min.y, (c & 4) != 0 ? mb.max.z : mb.min.z);
                    var p = skin.MultiplyPoint3x4(corner);
                    if (i == 0 && c == 0) result = new Bounds(p, Vector3.zero);
                    else result.Encapsulate(p);
                }
            }
            return result;
        }

        // Tron/Model materials for one compiled render style and the piece's texture list, one per draw.
        // A later draw sorts after the one before it (the engine draws a piece's passes in turn).
        Material[] CreateModelMaterials(RenderStyleJson rs, string tex1, string tex2)
        {
            var result = new Material[rs.draws.Length];
            for (int d = 0; d < result.Length; d++)
            {
                var draw = rs.draws[d];
                var m = new Material(modelShader) { name = d == 0 ? $"{rs.name} {tex1}" : $"{rs.name} {tex1} draw {d}" };
                owned.Add(m);
                foreach (var (prop, tex) in new[] { ("_Tex1", tex1), ("_Tex2", tex2) })
                {
                    if (string.IsNullOrEmpty(tex)) continue;
                    var t = DtxLoader.Load(tex);
                    if (t != null) m.SetTexture(prop, t.tex);
                    else MissingTextures.Add(tex);
                }
                // lit < 0: the draw has no such pass (glow-only draws, draws without glow).
                if (draw.passes.Length > 0) SetPass(m, "_S", draw.passes[0], "_TF0", "_P0");
                else m.SetVector("_P0", new Vector4(-1, 0, 0, 0));
                if (draw.passes.Length > 1) SetPass(m, "_T", draw.passes[1], "_TF1", "_P1");
                if (draw.glow.Length > 0) SetPass(m, "_G", draw.glow[0], "_TFG", "_PG");
                else m.SetVector("_PG", new Vector4(-1, 0, 0, 0));
                if (draw.glow.Length > 1) SetPass(m, "_H", draw.glow[1], "_TFH", "_PH");
                m.SetVector("_MatDiffuse", Vec(rs.lighting.diffuse));
                m.SetVector("_MatEmissive", Vec(rs.lighting.emissive));
                m.SetVector("_MatAmbient", Vec(rs.lighting.ambient));
                m.SetFloat("_SrcBlend", draw.blend[0]);
                m.SetFloat("_DstBlend", draw.blend[1]);
                m.SetFloat("_ZWrite", draw.zwrite);
                m.SetFloat("_ZTest", draw.ztest);
                m.SetFloat("_Cull", draw.cull);
                // Blended draws go after the opaque world, like the engine's translucent model list.
                int queue = draw.blend[0] != (int)BlendMode.One || draw.blend[1] != (int)BlendMode.Zero ? (int)RenderQueue.Transparent
                          : draw.passes.Length > 0 && draw.passes[0].alphaTest[0] != 0 ? (int)RenderQueue.AlphaTest
                          : (int)RenderQueue.Geometry;
                m.renderQueue = d == 0 ? queue : Math.Max(queue, result[d - 1].renderQueue + 1);
                result[d] = m;
            }
            return result;
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

            // Spinners that start on turn their world model.
            if (Data.spinners == null) return;
            foreach (var s in Data.spinners)
            {
                if (!WorldModelObjects.TryGetValue(s.worldModel, out var go)) continue;
                MakeKinematic(go);
                go.AddComponent<Spinner>().Init(s);
            }
        }

        // A world model the viewer moves gets a kinematic body when it has a collider, so PhysX treats the
        // collider as moving rather than re-baking a static one every frame.
        static void MakeKinematic(GameObject worldModel)
        {
            if (worldModel.GetComponentInChildren<Collider>() != null && !worldModel.GetComponent<Rigidbody>())
                worldModel.AddComponent<Rigidbody>().isKinematic = true;
        }

        // Keyframers live at start move the objects named in their ObjectName (KeyFramer::CreateKeyList:
        // every object with each name) along their path (Keyframer). An object is shown by its world model
        // when it has one, else by its drawn models; one the viewer doesn't draw has nothing to move but
        // still counts (a keyframer with no object at all never goes active).
        void BuildKeyframers()
        {
            if (Data.keyframers == null || Data.keyframers.Length == 0) return;
            var byName = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var n = Data.objects[i].name;
                if (string.IsNullOrEmpty(n)) continue;
                if (!byName.TryGetValue(n, out var list)) byName[n] = list = new List<int>();
                list.Add(i);
            }
            var worldModels = new Dictionary<string, GameObject>(WorldModelObjects, StringComparer.OrdinalIgnoreCase);
            var parent = new GameObject("Keyframers");
            parent.transform.SetParent(Root.transform, false);
            foreach (var kf in Data.keyframers)
            {
                var motion = kf.Motion();
                var shown = new List<Transform[]>();
                foreach (var name in kf.targets)
                {
                    if (!byName.TryGetValue(name, out var objs)) continue;
                    foreach (int i in objs)
                    {
                        var obj = Data.objects[i];
                        Transform[] gos;
                        Vector3 pos = obj.Position;
                        if ((SolidClasses.Contains(obj.cls) || HiddenClasses.Contains(obj.cls)) && worldModels.TryGetValue(obj.name, out var wm))
                        {
                            gos = new[] { wm.transform };
                            MakeKinematic(wm);
                        }
                        else if (modelObjects.TryGetValue(i, out var models))
                        {
                            gos = models.ConvertAll(m => m.transform).ToArray();
                            pos = gos[0].localPosition;   // after MoveToFloor
                        }
                        else gos = Array.Empty<Transform>();
                        motion.AddTarget(new LTVec(pos.x, pos.y, pos.z), LTQuat.FromEuler(obj.rot[0], obj.rot[1], obj.rot[2]));
                        shown.Add(gos);
                    }
                }
                if (motion.Targets.Count == 0) continue;

                var go = new GameObject($"{kf.name} [KeyFramer]");
                go.transform.SetParent(parent.transform, false);
                AmbientSound sound = null;
                AudioClip clip = null;
                if (!string.IsNullOrEmpty(kf.activeSound) && (clip = SoundLoader.Load(kf.activeSound)))
                {
                    // The sound follows the first controlled object; one that isn't drawn gets a stand-in.
                    var host = shown[0].Length > 0 ? shown[0][0].gameObject : null;
                    if (!host)
                    {
                        host = new GameObject("ActiveSound");
                        host.transform.SetParent(parent.transform, false);
                        var t0 = motion.Targets[0].Pos;
                        host.transform.localPosition = new Vector3(t0.x, t0.y, t0.z);
                        shown[0] = new[] { host.transform };
                    }
                    sound = AmbientSound.Add(host, 0.25f * kf.soundRadius, kf.soundRadius, 100, false, 1);
                }
                go.AddComponent<Keyframer>().Init(motion, shown.ToArray(), sound, clip);
            }
        }

        // SoundFX that start on play from level start at their position (SoundFX::InitialUpdate), with the
        // engine's falloff and volume (AmbientSound). A file missing from the export is skipped and listed
        // in SoundLoader.Missing.
        void BuildSoundFX()
        {
            if (Data.soundFX == null || Data.soundFX.Length == 0) return;
            var parent = new GameObject("SoundFX");
            parent.transform.SetParent(Root.transform, false);
            foreach (var s in Data.soundFX)
            {
                var clip = SoundLoader.Load(s.file);
                if (!clip) continue;
                var go = new GameObject(s.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = new Vector3(s.pos[0], s.pos[1], s.pos[2]);
                AmbientSound.Add(go, s.inner, s.outer, s.volume, s.ambient != 0, s.priority).Play(clip, s.loop != 0, s.pitch);
            }
        }

        // SoundButeFX that start on: random files of their soundbute from level start (SoundButeFX). Missing
        // files are listed in SoundLoader.Missing; one with none of its files exported is skipped.
        void BuildSoundButeFX()
        {
            if (Data.soundButeFX == null || Data.soundButeFX.Length == 0) return;
            var parent = new GameObject("SoundButeFX");
            parent.transform.SetParent(Root.transform, false);
            foreach (var s in Data.soundButeFX)
            {
                var clips = Array.ConvertAll(s.files ?? new string[0], SoundLoader.Load);
                if (!Array.Exists(clips, c => c)) continue;
                var go = new GameObject(s.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = new Vector3(s.pos[0], s.pos[1], s.pos[2]);
                SoundButeFX.Add(go, s, clips);
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
