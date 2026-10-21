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
        public const int FormatVersion = 27;
        const int HeaderSize = 32, VertexSize = 44, ColorOffset = 24;   // rgba after pos and normal

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
        public Relays Relays;         // its triggers, relays and startup commands (BuildRelays)
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
        // Command-manager id (a placed character's: its object index; a spawned one's: the id its spawn joined
        // as) -> a character's animations: Play(name, loop) plays any of them by name (its model's, its .ltb
        // children's, its ChildModel_N files'), blending in over the clip's interp time. CharacterAnim(name)
        // finds one by its object name.
        public readonly Dictionary<int, CharacterAnimation> CharacterAnims = new Dictionary<int, CharacterAnimation>();

        // The animations of the character named `name` (any case; the first drawn one with that name), null if none.
        public CharacterAnimation CharacterAnim(string name)
        {
            if (Commands == null) return null;
            foreach (var id in Commands.Named(name))
                if (CharacterAnims.TryGetValue(id, out var c)) return c;
            return null;
        }
        // World model name -> the level object that owns it (the one BuildWorldModels placed it by).
        readonly Dictionary<string, ObjectJson> worldModelOwners = new Dictionary<string, ObjectJson>(StringComparer.OrdinalIgnoreCase);
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
            int gridOffset = cidxBase + nci * 4 + lmW * lmH * 4;
            LoadLightGrid(gridOffset, ltjsGridOrder);
            var gd = Data.lightGrid.dims;
            ReadLightGroups(gridOffset + gd[0] * gd[1] * gd[2] * 3);   // LevelBuilder.LightGroups.cs

            Root = new GameObject("Level " + Data.name);
            Root.transform.localScale = Vector3.one * LT.Scale;
            JoinCommands();
            JoinCharacters();   // LevelBuilder.Spawners.cs

            BuildMaterials();

            var world = new GameObject("World");
            world.transform.SetParent(Root.transform, false);
            world.isStatic = true;
            foreach (var mi in Data.worldMeshes)
                AddRenderer(world.transform, mi, null, 1f);
            if (Data.worldCollider >= 0) AddCollider(world.transform, Data.worldCollider, "PhysicsBSP");
            if (Data.blockerCollider >= 0) AddCollider(world.transform, Data.blockerCollider, "Blockers");

            BuildWorldModels();
            JoinLightGroups();          // LevelBuilder.LightGroups.cs
            BuildActiveWorldModels();   // LevelBuilderDoors.cs
            bin = null;
            BuildModels(exportRoot);
            BuildSpawners();   // LevelBuilder.Spawners.cs
            JoinActors();      // LevelBuilder.Actors.cs
            BuildSoundFX();
            BuildSoundButeFX();
            BuildSpecialFX(exportRoot);   // LevelBuilder.SpecialFX.cs
            BuildScaleSprites();   // LevelBuilder.ScaleSprite.cs
            BuildSceneCameras();   // LevelBuilder.SceneCameras.cs
            BuildDialogues();   // LevelBuilder.Dialogues.cs
            BuildScreenShakes();   // LevelBuilder.ScreenShake.cs
            BuildIOCam(exportRoot);   // LevelBuilder.IOCam.cs
            BuildKeyframers();
            JoinObjectMessages();
            BuildSpinners();
            BuildRelays();
            StartSpecialFX();
        }

        // Every level object joins the command manager by name and class, in level order, so an object's
        // id is its index in Data.objects; builders add handlers with Commands.Handle(index, ...). Groups
        // pass their messages on to their Object1..Object50 (Tron's 50 slots). Templates are never created
        // (GameBase::ReadProp): they join without a name, keeping the ids, so nothing reaches them. Names a
        // Spawner would give are known, for the report; spawned characters join after the level's objects
        // (LevelBuilder.Spawners.cs). Ticked by CommandTicker.
        void JoinCommands()
        {
            Commands = new CommandMgr(ViewerRandom.NextDouble());
            foreach (var o in Data.objects)
            {
                if (o.Bool("Template"))
                    Commands.Join("", o.cls);
                else if (string.Equals(o.cls, "Group", StringComparison.OrdinalIgnoreCase))
                {
                    var members = new string[50];
                    for (int i = 0; i < members.Length; i++) members[i] = o.Str("Object" + (i + 1));
                    Commands.JoinGroup(o.name, members);
                }
                else
                    Commands.Join(o.name, o.cls);
            }
            foreach (var sp in Data.spawns) Commands.Spawned(sp.name, sp.cls);
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
            if (KeepsAtlas)
            {
                // A light group lights some of it: the base stays, the texture stays writable.
                var px = new byte[width * height * 4];
                Buffer.BlockCopy(bin, offset, px, 0, px.Length);
                KeepAtlas(px, width);
                lightmapAtlas.LoadRawTextureData(px);
                lightmapAtlas.Apply(false, false);
                return;
            }
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
        // node, looping their idle; CharacterAnims plays any of their animations by name (ModelAnimator). Attachments hang from their parent's socket node (a
        // prop's nodes stay at the bind pose); a character's are posed at their own animation 0, frame 0
        // (attachment models keep their geometry where it sits on the body and move it to the socket with
        // that pose), and follow it as the character moves.
        readonly List<DynamicLights.Model> litModels = new List<DynamicLights.Model>();

        // What building a model instance needs, kept for the characters spawned later (LevelBuilder.Spawners.cs).
        Transform modelRoot;
        ModelAnimator modelAnimator;
        string modelExportRoot;
        readonly MaterialPropertyBlock modelProps = new MaterialPropertyBlock();
        readonly Vector4[] lightDirs = new Vector4[ModelLighting.MaxLights];
        readonly Vector4[] lightColors = new Vector4[ModelLighting.MaxLights];

        // Spawner templates (template = 1) wait for their spawn.
        void BuildModels(string exportRoot)
        {
            if (Data.models == null || Data.models.Length == 0) return;
            var root = new GameObject("Models");
            root.transform.SetParent(Root.transform, false);
            modelRoot = root.transform;
            modelExportRoot = exportRoot;
            var built = new (LoadedModel model, Transform[] bones)[Data.models.Length];
            modelAnimator = root.AddComponent<ModelAnimator>();
            for (int n = 0; n < Data.models.Length; n++)
            {
                var inst = Data.models[n];
                if (inst.template != 0) continue;
                var obj = Data.objects[inst.obj];
                var pos = inst.pos != null && inst.pos.Length >= 3 ? new Vector3(inst.pos[0], inst.pos[1], inst.pos[2]) : obj.Position;
                int lit = litModels.Count;
                var go = BuildInstance(n, obj.name, pos, obj.Rotation, inst.sunAmount,
                                       inst.parent >= 0 ? built[inst.parent] : default, out built[n], out var character);
                if (character != null) CharacterAnims[inst.obj] = character;
                // A placed character's body (LevelBuilder.Actors.cs): its model, its attachments by socket.
                CharacterBody body = null;
                if (go && obj.cls == "CAIHuman")
                {
                    if (inst.parent < 0 && built[n].bones != null)
                    {
                        body = PlacedCharacters[inst.obj] = new CharacterBody { Animation = character };
                        body.Begin(go, inst, built[n], inst.sunAmount);
                    }
                    else if (inst.parent >= 0 && PlacedCharacters.TryGetValue(inst.obj, out body))
                        body.AddAttachment(inst.socket, go);
                    body?.Lit.AddRange(LitSince(lit));
                }
                if (go == null || inst.parent >= 0) continue;
                if (!modelObjects.TryGetValue(inst.obj, out var shown)) modelObjects[inst.obj] = shown = new List<GameObject>();
                shown.Add(go);
            }
            modelAnimator.Begin();
        }

        // Model instance n, named for its object `name`: a root instance at pos / rot under the models root, an
        // attachment on `parent`'s socket; lit at pos with sunAmount. built: its model and node Transforms
        // when it has them (characters, props with sockets). Null when it can't be drawn.
        GameObject BuildInstance(int n, string name, Vector3 pos, Quaternion rot, float sunAmount,
                                 (LoadedModel model, Transform[] bones) parent, out (LoadedModel model, Transform[] bones) built,
                                 out CharacterAnimation character)
        {
            var inst = Data.models[n];
            return BuildInstance(inst, Data.objects[inst.obj], inst.parent >= 0 ? inst.socket : null, name, pos, rot, sunAmount,
                                 parent, out built, out character);
        }

        // inst for object obj: an attachment on parent's socket `socket` when that isn't null, else a root
        // instance at pos / rot.
        GameObject BuildInstance(ModelInstanceJson inst, ObjectJson obj, string socket, string name, Vector3 pos, Quaternion rot,
                                 float sunAmount, (LoadedModel model, Transform[] bones) parent,
                                 out (LoadedModel model, Transform[] bones) built, out CharacterAnimation character)
        {
            built = default;
            character = null;
            var model = ModelLibrary.Load(modelExportRoot, inst.file, loadedModels, owned);
            if (model == null) return null;
            if (inst.pieces == null || inst.pieces.Length != model.data.pieces.Length)
            {
                Debug.LogWarning($"Model {inst.file}: {inst.pieces?.Length ?? 0} piece styles for {model.data.pieces.Length} pieces");
                return null;
            }
            bool attached = socket != null;
            var go = new GameObject($"{name} [{obj.cls}: {inst.file}]");
            if (attached)
            {
                if (!AttachToSocket(go.transform, inst.file, socket, parent)) { UnityEngine.Object.Destroy(go); return null; }
            }
            else
            {
                go.transform.SetParent(modelRoot, false);
                go.transform.localPosition = pos;
                go.transform.localRotation = rot;
                if (inst.scale != null && inst.scale.Length >= 3) go.transform.localScale = new Vector3(inst.scale[0], inst.scale[1], inst.scale[2]);
            }
            var (mesh, mats) = ModelLook(model, inst.pieces);
            Renderer r;
            if (inst.skinned != 0)
            {
                var bones = BuildBones(go.transform, model, attached);
                built = (model, bones);
                if (!attached && obj.cls == "CAIHuman")
                {
                    var anims = inst.anims != null && inst.anims.Length > 0 ? inst.anims : new[] { new AnimRefJson { name = inst.anim, @from = "" } };   // older exports
                    character = modelAnimator.Add(model, bones, anims);
                    if (!string.IsNullOrEmpty(inst.anim) && !character.Play(inst.anim, true))
                        Debug.LogWarning($"Model {inst.file}: no clip {inst.anim}");
                }
                var smr = go.AddComponent<SkinnedMeshRenderer>();
                smr.sharedMesh = mesh;
                smr.bones = bones;
                smr.localBounds = SkinnedBounds(go.transform, model, bones);
                // A character's cinematic animations carry it far from where it was built (intro: the
                // employee's M01EmpCounter walks 130 units to the counter): its bounds follow its bones, or the
                // body is culled by the box it was built in while its attachments, on their own, still show.
                if (character != null) smr.updateWhenOffscreen = true;
                r = smr;
            }
            else
            {
                // A prop with sockets can carry attachments (bin berries, tank turrets): its node
                // Transforms at the bind pose, the pose its mesh is drawn in.
                if (model.data.sockets != null && model.data.sockets.Length > 0)
                    built = (model, BuildBones(go.transform, model, false));
                go.AddComponent<MeshFilter>().sharedMesh = mesh;
                r = go.AddComponent<MeshRenderer>();
            }
            r.sharedMaterials = mats;
            if (!attached && inst.looks != null && inst.looks.Length > 0 && built.bones != null)
                AddStateModel(go, inst, obj, model, built.bones, r);
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = false;
            r.lightProbeUsage = LightProbeUsage.Off;
            r.reflectionProbeUsage = ReflectionProbeUsage.Off;

            // Per-instance D3D lighting (ModelLighting): ambient and up to 4 directional lights, 0-1.
            // Every instance has its own (attachments: their model's dims at the parent object's position);
            // DynamicLights lights it again while a dynamic light reaches it.
            var dims = inst.dims != null && inst.dims.Length >= 3 ? new Vector3(inst.dims[0], inst.dims[1], inst.dims[2]) : Vector3.zero;
            Light(r, pos, dims, inst.visRadius, sunAmount);
            litModels.Add(new DynamicLights.Model { R = r, Pos = pos, Dims = dims, VisRadius = inst.visRadius, SunAmount = sunAmount });
            return go;
        }

        // A model's D3D lighting at pos (ModelLighting) into its renderer's property block.
        void Light(Renderer r, Vector3 pos, Vector3 dims, float visRadius, float sunAmount)
        {
            var ambient = lighting.Compute(pos, dims, visRadius, sunAmount, lightDirs, lightColors);
            ModelLighting.ToUnit(lightColors);
            modelProps.Clear();
            modelProps.SetVector(AmbientId, ambient / 255f);
            modelProps.SetVectorArray(LightDirId, lightDirs);
            modelProps.SetVectorArray(LightColorId, lightColors);
            r.SetPropertyBlock(modelProps);
        }

        // The models lit since litModels held `count` (the ones a character's build just added).
        List<DynamicLights.Model> LitSince(int count) => litModels.GetRange(count, litModels.Count - count);


        // The state models (BinaryBit, SecRezzer: StateModels.cs) on their drawn model.
        public readonly List<StateModel> StateModels = new List<StateModel>();

        void AddStateModel(GameObject go, ModelInstanceJson inst, ObjectJson obj, LoadedModel model, Transform[] bones,
                           Renderer r)
        {
            var looks = new Dictionary<string, Material[]>();
            foreach (var look in inst.looks)
            {
                var mats = new Material[look.pieces.Length];
                for (int i = 0; i < mats.Length; i++)
                {
                    var m = PieceMaterials(look.pieces[i]);
                    if (m.Length != 1 || r.sharedMaterials.Length != mats.Length)
                    {
                        Debug.LogWarning($"{obj.name}: look {look.name} draws a piece more than once; its look stays as built");
                        return;
                    }
                    mats[i] = m[0];
                }
                looks[look.name] = mats;
            }
            var sm = go.AddComponent<StateModel>();
            IStateModel state = obj.cls == "BinaryBit"
                ? new BinaryBit(sm, obj.Num("EnergyRequired"), obj.Bool("StartOnInSocket", true), obj.Bool("Locked"),
                                obj.Str("PowerUpCommand"), obj.Str("TurnOnCommand"), obj.Str("TurnOffCommand"))
                : (IStateModel)new SecRezzer(sm);
            var typeName = obj.cls == "SecRezzer" ? "Disable Secrezzer" : obj.Str("ActivateType");
            var type = Array.Find(Data.activateTypes ?? Array.Empty<ActivateTypeJson>(),
                                  t => string.Equals(t.name, typeName, StringComparison.OrdinalIgnoreCase));
            var dims = inst.dims != null && inst.dims.Length >= 3 ? new Vector3(inst.dims[0], inst.dims[1], inst.dims[2]) : Vector3.one;
            sm.Init(state, model, bones, r, looks, ButeSounds, Commands, inst.obj, obj.cls, type?.on, type?.off, dims);
            StateModels.Add(sm);
        }

        // The level's soundbutes by name, any case (level.json buteSounds: the ones animation keys and ScreenShakes play).
        Dictionary<string, ButeSoundJson> buteSounds;
        Dictionary<string, ButeSoundJson> ButeSounds
        {
            get
            {
                if (buteSounds != null) return buteSounds;
                buteSounds = new Dictionary<string, ButeSoundJson>(StringComparer.OrdinalIgnoreCase);
                foreach (var b in Data.buteSounds ?? Array.Empty<ButeSoundJson>()) buteSounds[b.name] = b;
                return buteSounds;
            }
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
        static bool AttachToSocket(Transform t, string file, string socketName, (LoadedModel model, Transform[] bones) parent)
        {
            if (parent.model == null || parent.bones == null) return false;
            var socket = Array.Find(parent.model.data.sockets, s => string.Equals(s.name, socketName, StringComparison.OrdinalIgnoreCase));
            if (socket == null)
            {
                Debug.LogWarning($"Attachment {file}: no socket {socketName} on {parent.model.data.file}");
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

        readonly Dictionary<string, LoadedModel> loadedModels = new Dictionary<string, LoadedModel>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<(int, string, string, string), Material[]> styleMaterials = new Dictionary<(int, string, string, string), Material[]>();
        readonly Dictionary<string, Mesh> lookMeshes = new Dictionary<string, Mesh>();
        readonly HashSet<Material> wireMaterials = new HashSet<Material>();

        // The mesh and materials that draw a model with these piece styles (placed models, effect models):
        // one material per piece for its style's first draw; later draws repeat the piece as extra submeshes
        // of the same renderer (same skinning and property block), drawn after it; wireframe draws
        // (RENDERSTYLE_WIRE) draw their submesh's triangle edges as lines.
        (Mesh, Material[]) ModelLook(LoadedModel model, PieceStyleJson[] pieces)
        {
            var mats = new List<Material>(pieces.Length);
            var repeats = new List<int>();
            var repeatMats = new List<Material>();
            for (int i = 0; i < pieces.Length; i++)
            {
                var m = PieceMaterials(pieces[i]);
                mats.Add(m[0]);
                for (int d = 1; d < m.Length; d++)
                {
                    repeats.Add(i);
                    repeatMats.Add(m[d]);
                }
            }
            var mesh = model.mesh;
            if (repeats.Count > 0) mesh = ModelLibrary.WithRepeatedPieces(model, repeats, lookMeshes, owned);
            mats.AddRange(repeatMats);
            var wire = new List<int>();
            for (int i = 0; i < mats.Count; i++)
                if (wireMaterials.Contains(mats[i])) wire.Add(i);
            if (wire.Count > 0) mesh = ModelLibrary.WithLines(mesh, wire, lookMeshes, owned);
            return (mesh, mats.ToArray());
        }

        // A piece's materials, one per draw of its style, shared by every piece with the same style and textures.
        Material[] PieceMaterials(PieceStyleJson p)
        {
            string Tex(int i) => p.tex != null && p.tex.Length > i ? p.tex[i] : "";
            var key = (p.style, Tex(0), Tex(1), Tex(2));
            if (!styleMaterials.TryGetValue(key, out var m))
                styleMaterials[key] = m = CreateModelMaterials(Data.renderStyles[p.style], key.Item2, key.Item3, key.Item4);
            return m;
        }

        // Tron/Model materials for one compiled render style and the piece's texture list, one per draw.
        // A later draw sorts after the one before it (the engine draws a piece's passes in turn).
        Material[] CreateModelMaterials(RenderStyleJson rs, string tex1, string tex2, string tex3)
        {
            var result = new Material[rs.draws.Length];
            for (int d = 0; d < result.Length; d++)
            {
                var draw = rs.draws[d];
                var m = new Material(modelShader) { name = d == 0 ? $"{rs.name} {tex1}" : $"{rs.name} {tex1} draw {d}" };
                owned.Add(m);
                if (draw.wire != 0) wireMaterials.Add(m);
                foreach (var (prop, tex) in new[] { ("_Tex1", tex1), ("_Tex2", tex2), ("_Tex3", tex3) })
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

                // A level world model is drawn even when it starts hidden: JoinObjectMessages hides it
                // until a message shows it.
                bool visible = obj == null || (obj.Bool("Visible", true) && !obj.Bool("StartHidden"));
                if (wm.mesh >= 0 && (visible || !sky))
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
                // Non-solid ones too (Solid FALSE): SOLID 1 can make them solid (JoinObjectMessages).
                if (wm.collider >= 0 && SolidClasses.Contains(cls))
                    AddCollider(geom.transform, wm.collider, "collider");
                worldModelOwners[wm.name] = obj;
            }
        }

        // A world model the viewer moves gets a kinematic body when it has a collider, so PhysX treats the
        // collider as moving rather than re-baking a static one every frame.
        static void MakeKinematic(GameObject worldModel)
        {
            if (worldModel.GetComponentInChildren<Collider>() != null && !worldModel.GetComponent<Rigidbody>())
                worldModel.AddComponent<Rigidbody>().isKinematic = true;
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
            var mesh = BuildMesh(mj, meshIndex);
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

        Mesh BuildMesh(MeshJson mj, int meshIndex)
        {
            var mesh = new Mesh { name = mj.name };
            owned.Add(mesh);
            mesh.SetVertexBufferParams(mj.vtxCount,
                new VertexAttributeDescriptor(VertexAttribute.Position, VertexAttributeFormat.Float32, 3),
                new VertexAttributeDescriptor(VertexAttribute.Normal, VertexAttributeFormat.Float32, 3),
                new VertexAttributeDescriptor(VertexAttribute.Color, VertexAttributeFormat.UNorm8, 4),
                new VertexAttributeDescriptor(VertexAttribute.TexCoord0, VertexAttributeFormat.Float32, 2),
                new VertexAttributeDescriptor(VertexAttribute.TexCoord1, VertexAttributeFormat.Float32, 2));
            bool lit = false;
            if (litMeshes.ContainsKey(meshIndex))
            {
                // A light group lights it: it keeps its vertex bytes and stays writable (LevelBuilder.LightGroups.cs).
                var vb = new byte[mj.vtxCount * VertexSize];
                Buffer.BlockCopy(bin, vtxBase + mj.vtxOffset * VertexSize, vb, 0, vb.Length);
                mesh.SetVertexBufferData(vb, 0, 0, vb.Length);
                lit = KeepMesh(meshIndex, mesh, vb);
            }
            else
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
            mesh.UploadMeshData(!lit);
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
