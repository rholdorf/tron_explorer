using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace Tron
{
    // Pick mode (F3, #112; GLOSSARY.md, Picking): aim at something in the level and record it as a Pick
    // (Picks.cs) for seiri. Off by default; until it first turns on it builds nothing and draws nothing (the
    // level only lists what it could aim at: LevelBuilder.Picks.cs), so the faithful mode is untouched.
    //
    // The crosshair aims at the drawn world (the main world's and world models' meshes, as colliders of their
    // own in a physics scene apart from the level's, so the player, its use and the effects never meet them;
    // read from level.bin on the first F3, moved along with their world models every frame), the placed
    // models (their renderers' bounds) and the SpecialFX (their points, within a narrow cone; not through a
    // wall). The nearest one is the target, outlined, its label in the HUD.
    //   left click   record the target: a model, world model or effect at once; the main world opens a box
    //                around the island of triangles it belongs to (PickIsland; a default box when the island
    //                runs into the rest of the level), Enter records it as worldGeometry
    //   right click  record the surface (material) under the crosshair
    //   B            start a cut: two left clicks set two corners of its box
    //   in a box     F / Shift+F select the next / previous face, ] or wheel up pushes it out, [ or wheel down
    //                pulls it in (Alt: 8x), Enter records, Backspace drops it
    // Picks go to PickRecord.PicksDir (-picks <dir>, else ../seiri/requests); a missing folder is reported in
    // the HUD and nothing is written.
    [DefaultExecutionOrder(120)]   // after the player and its camera moved
    public class PickMode : MonoBehaviour
    {
        const float MaxDistance = 20000;          // LithTech units
        const float IslandMaxExtent = 512;        // wider: the island leaked into the level
        const float DefaultBoxHalf = 64;
        const float BoxMinThickness = 4, CutMinThickness = 16;
        const float FaceStep = 8;
        const float FxConeTan = 0.026f, FxMinRadius = 16;   // ~1.5 degrees, at least 16 units

        public Camera Cam;
        public Shader LineShader;
        public string PicksDir;
        public bool InputEnabled;
        public bool On { get; private set; }
        public string Status { get; private set; } = "";
        public string TargetLabel => box != null ? BoxLabel() : target.Label;

        LevelBuilder level;
        string levelPath;
        Scene scene;
        PhysicsScene physics;
        GameObject root;
        GameObject[] pickObjects;
        LevelBuilder.PickGeometry[] geometry;
        // The main world's triangles together (one frame: the world isn't moved), for islands across its blocks.
        float[] worldPositions;
        int[] worldIndices;
        readonly Dictionary<int, int> worldTriStart = new Dictionary<int, int>();   // pick mesh -> first triangle
        Material lineMat;
        readonly List<Mesh> meshes = new List<Mesh>();   // the pick colliders'
        const string BoxKeys = "(F face, [ ] ou roda, Enter grava, Backspace larga)";

        enum Kind { None, Model, WorldModel, World, Effect }
        struct Target
        {
            public Kind Kind;
            public float Distance;      // metres
            public int Mesh, Tri, Obj;  // pick mesh and its triangle; object index (model, effect)
            public Vector3 Point;       // LithTech units
            public Bounds Bounds;       // model: world bounds
            public string Label;
        }
        Target target, surface;
        PickBox box;
        string boxKind;                 // "worldGeometry" or "cut"
        Target boxTarget;
        int[] islandTris;               // world triangles outlined with a worldGeometry box
        int cutCorners = -1;            // -1: no cut; 0 / 1: corners set so far
        Vector3 cutCorner;

        public void Attach(LevelBuilder level, string levelPath)
        {
            Detach();
            this.level = level;
            this.levelPath = levelPath;
        }

        public void Detach()
        {
            if (root) Destroy(root);
            foreach (var m in meshes) Destroy(m);
            meshes.Clear();
            if (scene.IsValid()) SceneManager.UnloadSceneAsync(scene);
            scene = default;
            root = null;
            pickObjects = null;
            geometry = null;
            worldPositions = null;
            worldIndices = null;
            worldTriStart.Clear();
            level = null;
            On = false;
            ClearBox();
            target = surface = default;
            Status = "";
        }

        public void Toggle()
        {
            if (level == null) return;
            On = !On;
            if (On && root == null) Build();
            if (root) root.SetActive(On);
            if (!On) { ClearBox(); target = surface = default; }
            Status = On ? (Directory.Exists(PicksDir ?? "") ? $"Picks em {PicksDir}" : $"Pasta de Picks não existe: {PicksDir} (-picks <dir>)") : "";
        }

        void Build()
        {
            geometry = level.ReadPickGeometry();
            scene = SceneManager.CreateScene("Picks " + GetInstanceID() + " " + Time.frameCount, new CreateSceneParameters(LocalPhysicsMode.Physics3D));
            physics = scene.GetPhysicsScene();
            root = new GameObject("Picks");
            SceneManager.MoveGameObjectToScene(root, scene);
            pickObjects = new GameObject[geometry.Length];
            var wp = new List<float>();
            var wi = new List<int>();
            for (int m = 0; m < geometry.Length; m++)
            {
                var g = geometry[m];
                var verts = new Vector3[g.Positions.Length / 3];
                for (int v = 0; v < verts.Length; v++)
                    verts[v] = new Vector3(g.Positions[v * 3], g.Positions[v * 3 + 1], g.Positions[v * 3 + 2]) * LT.Scale;
                var mesh = new Mesh { indexFormat = IndexFormat.UInt32, vertices = verts, triangles = g.Indices };
                meshes.Add(mesh);
                var go = new GameObject(m.ToString());
                go.transform.SetParent(root.transform, false);
                go.AddComponent<MeshCollider>().sharedMesh = mesh;
                pickObjects[m] = go;
                if (level.PickMeshes[m].WorldModel != null) continue;
                worldTriStart[m] = wi.Count / 3;
                int baseV = wp.Count / 3;
                wp.AddRange(g.Positions);
                foreach (int i in g.Indices) wi.Add(baseV + i);
            }
            worldPositions = wp.ToArray();
            worldIndices = wi.ToArray();
            if (!lineMat) lineMat = new Material(LineShader ? LineShader : Shader.Find("Hidden/Tron/PickLine")) { hideFlags = HideFlags.HideAndDontSave };
            RenderPipelineManager.endCameraRendering -= DrawOutlines;
            RenderPipelineManager.endCameraRendering += DrawOutlines;
        }

        void OnDestroy()
        {
            Detach();
            RenderPipelineManager.endCameraRendering -= DrawOutlines;
            if (lineMat) Destroy(lineMat);
        }

        void Update()
        {
            if (!On || level == null || !Cam) return;
            Sync();
            Aim();
            if (!InputEnabled) return;
            var kb = Keyboard.current;
            var mouse = Mouse.current;
            if (kb == null || mouse == null) return;
            if (box != null)
            {
                bool shift = kb.leftShiftKey.isPressed || kb.rightShiftKey.isPressed;
                bool alt = kb.leftAltKey.isPressed || kb.rightAltKey.isPressed;
                float wheel = mouse.scroll.ReadValue().y;
                if (kb.fKey.wasPressedThisFrame) NextFace(shift ? -1 : 1);
                if (kb.rightBracketKey.wasPressedThisFrame || wheel > 0) PushFace(alt ? 8 : 1);
                if (kb.leftBracketKey.wasPressedThisFrame || wheel < 0) PushFace(alt ? -8 : -1);
                if (kb.backspaceKey.wasPressedThisFrame) DropBox();
                if (kb.enterKey.wasPressedThisFrame || kb.numpadEnterKey.wasPressedThisFrame) RecordBox();
                return;
            }
            if (kb.bKey.wasPressedThisFrame) StartCut();
            if (mouse.leftButton.wasPressedThisFrame) Click();
            if (mouse.rightButton.wasPressedThisFrame) PickSurface();
        }

        // The actions the keys and buttons above run (public: the agent drives them through eval, where the
        // Editor keeps simulated input from the game).

        // Left click: a cut's next corner, else the target.
        public void Click()
        {
            if (box != null) return;
            if (cutCorners >= 0) SetCutCorner();
            else PickTarget();
        }

        public void StartCut()
        {
            if (box != null) return;
            cutCorners = 0;
            Status = "Corte: clique no primeiro canto";
        }

        public void NextFace(int step) => box?.NextFace(step);

        // Pushes the box's selected face out by `steps` FaceSteps (negative: in).
        public void PushFace(int steps)
        {
            if (box == null) return;
            box.Push(steps * FaceStep);
            islandTris = null;
        }

        public void DropBox()
        {
            if (box == null) return;
            ClearBox();
            Status = "Caixa largada";
        }

        // The pick colliders follow their renderers: moved with their world model, off while hidden.
        void Sync()
        {
            for (int m = 0; m < pickObjects.Length; m++)
            {
                var r = level.PickMeshes[m].Renderer;
                bool shown = r && r.enabled && r.gameObject.activeInHierarchy;
                var go = pickObjects[m];
                if (go.activeSelf != shown) go.SetActive(shown);
                if (shown) go.transform.SetPositionAndRotation(r.transform.position, r.transform.rotation);
            }
            Physics.SyncTransforms();
        }

        void Aim()
        {
            var t = Cam.transform;
            var ray = new Ray(t.position, t.forward);
            target = surface = default;
            float best = MaxDistance * LT.Scale;
            if (physics.Raycast(ray.origin, ray.direction, out var hit, best, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore))
            {
                int m = Array.IndexOf(pickObjects, hit.collider.gameObject);
                var pm = level.PickMeshes[m];
                best = hit.distance;
                surface = new Target
                {
                    Kind = pm.WorldModel != null ? Kind.WorldModel : Kind.World, Distance = hit.distance, Mesh = m,
                    Tri = hit.triangleIndex, Point = hit.point / LT.Scale,
                };
                target = surface;
                target.Label = pm.WorldModel != null ? $"World model {pm.WorldModel} [{pm.Class}], textura {TextureName(surface)}" : $"Mundo: textura {TextureName(surface)}";
            }
            foreach (var kv in level.ModelObjects)
                foreach (var go in kv.Value)
                {
                    if (!go || !go.activeInHierarchy) continue;
                    var r = go.GetComponent<Renderer>();
                    if (!r || !r.enabled) continue;
                    var b = r.bounds;
                    if (b.Contains(ray.origin) || !b.IntersectRay(ray, out float d) || d >= best) continue;
                    best = d;
                    var obj = level.Data.objects[kv.Key];
                    target = new Target
                    {
                        Kind = Kind.Model, Distance = d, Obj = kv.Key, Bounds = b, Point = ray.GetPoint(d) / LT.Scale,
                        Label = ModelLabel(kv.Key),
                    };
                }
            foreach (var (obj, tr) in level.SpecialFXObjects)
            {
                if (!tr) continue;
                var v = tr.position - ray.origin;
                float along = Vector3.Dot(v, ray.direction);
                if (along <= 0) continue;
                float radius = Mathf.Max(FxMinRadius * LT.Scale, along * FxConeTan);
                if ((v - ray.direction * along).magnitude > radius || along - radius >= best) continue;
                best = along;
                var o = level.Data.objects[obj];
                target = new Target
                {
                    Kind = Kind.Effect, Distance = along, Obj = obj, Point = tr.position / LT.Scale,
                    Label = $"Efeito {o.name} [{o.Str("FxName")}]",
                };
            }
        }

        string ModelLabel(int obj)
        {
            var o = level.Data.objects[obj];
            var inst = level.ModelInstance(obj);
            var skin = inst?.skins != null && inst.skins.Length > 0 ? $", textura {Path.GetFileNameWithoutExtension(inst.skins[0])}" : "";
            return $"Modelo {o.name} [{o.cls}: {inst?.file}]{skin}";
        }

        // The material of the world triangle t hit, and its texture's file name.
        MaterialJson MaterialAt(Target t) => level.Data.materials[geometry[t.Mesh].MaterialOf(t.Tri)];
        string TextureName(Target t) => Path.GetFileNameWithoutExtension(MaterialAt(t).tex ?? "");

        void PickTarget()
        {
            switch (target.Kind)
            {
                case Kind.None: Status = "Nada sob a mira"; return;
                case Kind.World: OpenIslandBox(); return;
                case Kind.WorldModel:
                {
                    var pm = level.PickMeshes[target.Mesh];
                    Write(new PickRecord("worldModel", levelPath, pm.WorldModel, DateTime.UtcNow) { Hit = ToLT(target.Point) }
                        .Id("worldModel", pm.WorldModel).Id("class", pm.Class).Id("blend", pm.Blend ?? "None"));
                    return;
                }
                case Kind.Model:
                {
                    var obj = level.Data.objects[target.Obj];
                    var inst = level.ModelInstance(target.Obj);
                    Write(new PickRecord("model", levelPath, obj.name, DateTime.UtcNow) { Hit = ToLT(target.Point) }
                        .Id("object", obj.name).Id("class", obj.cls).Id("file", inst?.file)
                        .Id("skins", inst?.skins).Id("styles", inst?.styles));
                    return;
                }
                case Kind.Effect:
                {
                    var obj = level.Data.objects[target.Obj];
                    Write(new PickRecord("effect", levelPath, obj.name, DateTime.UtcNow) { Hit = ToLT(target.Point) }
                        .Id("object", obj.name).Id("class", obj.cls).Id("fxName", obj.Str("FxName")));
                    return;
                }
            }
        }

        // Right click: the surface under the crosshair.
        public void PickSurface()
        {
            if (box != null || cutCorners >= 0) return;
            if (surface.Kind == Kind.None) { Status = "Nenhuma superfície sob a mira"; return; }
            var pm = level.PickMeshes[surface.Mesh];
            var mat = MaterialAt(surface);
            // The texture's own render settings, from its DTX command string and flags (the shader says
            // whether the engine uses EnvMap and DetailTex: LevelBuilder.IsPlainTexture).
            var dtx = string.IsNullOrEmpty(mat.tex) ? null : DtxLoader.Load(mat.tex);
            var rec = new PickRecord("surface", levelPath, TextureName(surface), DateTime.UtcNow) { Hit = ToLT(surface.Point) }
                .Id("texture", mat.tex).Id("texture2", mat.tex2).Id("effect", mat.effect).Id("shader", mat.shader)
                .Id("blend", pm.Blend ?? "None")
                .Id("envMap", dtx?.envMap).Id("envMapAlpha", dtx != null && dtx.envMapAlpha ? 1 : 0)
                .Id("detailTex", dtx?.detailTex).Id("fullbright", dtx != null && dtx.fullbright ? 1 : 0);
            if (pm.WorldModel != null) rec.Id("worldModel", pm.WorldModel);
            Write(rec);
        }

        void OpenIslandBox()
        {
            var isl = PickIsland.Grow(worldPositions, worldIndices, worldTriStart[target.Mesh] + target.Tri, IslandMaxExtent);
            boxTarget = target;
            boxKind = "worldGeometry";
            if (isl.Leaked)
            {
                var c = ToLT(target.Point);
                var half = new LTVec(DefaultBoxHalf, DefaultBoxHalf, DefaultBoxHalf);
                box = PickBox.FromCorners(c - half, c + half, BoxMinThickness);
                islandTris = null;
                Status = $"A ilha encosta no resto da fase: ajuste a caixa {BoxKeys}";
            }
            else
            {
                box = PickBox.FromCorners(isl.Min, isl.Max, BoxMinThickness);
                islandTris = isl.Triangles;
                Status = $"Ilha de {isl.Triangles.Length} triângulos {BoxKeys}";
            }
        }

        void SetCutCorner()
        {
            if (surface.Kind == Kind.None) { Status = "Corte: mire numa superfície"; return; }
            if (cutCorners == 0)
            {
                cutCorner = surface.Point;
                cutCorners = 1;
                Status = "Corte: clique no segundo canto";
                return;
            }
            box = PickBox.FromCorners(ToLT(cutCorner), ToLT(surface.Point), CutMinThickness);
            boxKind = "cut";
            boxTarget = surface;
            islandTris = null;
            cutCorners = -1;
            Status = $"Corte: ajuste a caixa {BoxKeys}";
        }

        // Enter: the box as a worldGeometry or cut Pick.
        public void RecordBox()
        {
            if (box == null) return;
            PickRecord rec;
            if (boxKind == "cut")
                rec = new PickRecord("cut", levelPath, "cut", DateTime.UtcNow);
            else
                rec = new PickRecord("worldGeometry", levelPath, TextureName(boxTarget), DateTime.UtcNow) { Hit = ToLT(boxTarget.Point) }
                    .Id("texture", MaterialAt(boxTarget).tex)
                    .Id("from", islandTris != null ? "island" : "box");
            rec.Box = box;
            Write(rec);
            ClearBox();
        }

        void ClearBox()
        {
            box = null;
            islandTris = null;
            cutCorners = -1;
        }

        string BoxLabel()
        {
            var s = box.Size;
            return $"{(boxKind == "cut" ? "Corte" : "Geometria")} {s.x:0} × {s.y:0} × {s.z:0}, face {PickBox.FaceNames[box.Face]}";
        }

        void Write(PickRecord rec)
        {
            if (string.IsNullOrEmpty(PicksDir) || !Directory.Exists(PicksDir))
            {
                Status = $"Pasta de Picks não existe: {PicksDir} (-picks <dir>); nada gravado";
                return;
            }
            var file = rec.FileName(f => File.Exists(Path.Combine(PicksDir, f)));
            File.WriteAllText(Path.Combine(PicksDir, file), rec.ToJson());
            Status = $"Pick gravado: {file}";
            Debug.Log($"Pick: {Path.Combine(PicksDir, file)}");
        }

        static LTVec ToLT(Vector3 v) => new LTVec(v.x, v.y, v.z);
        static Vector3 V(LTVec v) => new Vector3(v.x, v.y, v.z) * LT.Scale;

        // The crosshair, in OnGUI's screen space.
        public void DrawCrosshair()
        {
            if (!On || Event.current.type != EventType.Repaint) return;
            float cx = Screen.width / 2f, cy = Screen.height / 2f, len = 10, th = 2;
            var prev = GUI.color;
            GUI.color = cutCorners >= 0 ? new Color(1, 0.6f, 0.1f) : new Color(0.3f, 1, 1);
            GUI.DrawTexture(new Rect(cx - len, cy - th / 2, len * 2, th), Texture2D.whiteTexture);
            GUI.DrawTexture(new Rect(cx - th / 2, cy - len, th, len * 2), Texture2D.whiteTexture);
            GUI.color = prev;
        }

        // The target's outline (a box for models and effects, the triangle for the world), the box being edited
        // (its selected face brighter) and its island, and the cut's first corner; GL lines over the main
        // camera's image.
        void DrawOutlines(ScriptableRenderContext ctx, Camera cam)
        {
            if (!On || cam != Cam || !lineMat || level == null) return;
            lineMat.SetPass(0);
            GL.PushMatrix();
            GL.LoadProjectionMatrix(GL.GetGPUProjectionMatrix(cam.projectionMatrix, false));
            GL.modelview = cam.worldToCameraMatrix;
            GL.Begin(GL.LINES);
            if (box != null)
            {
                var c = new Color(1, 0.8f, 0.2f);
                WireBox(V(box.Min), V(box.Max), c);
                Face(c);
                if (islandTris != null)
                {
                    GL.Color(new Color(0.3f, 1, 0.4f, 0.6f));
                    var m = Matrix4x4.Scale(Vector3.one * LT.Scale);   // the main world: the level root's scale only
                    foreach (int t in islandTris) Tri(worldPositions, worldIndices, t, m);
                }
            }
            else
            {
                if (cutCorners == 1) Cross(cutCorner * LT.Scale, 24 * LT.Scale, new Color(1, 0.6f, 0.1f));
                var c = new Color(0.3f, 1, 1);
                switch (target.Kind)
                {
                    case Kind.Model: WireBox(target.Bounds.min, target.Bounds.max, c); break;
                    case Kind.Effect: Cross(target.Point * LT.Scale, 32 * LT.Scale, c); break;
                    case Kind.WorldModel:
                    case Kind.World:
                        var r = level.PickMeshes[target.Mesh].Renderer;
                        if (!r) break;
                        if (target.Kind == Kind.WorldModel) WireBox(r.bounds.min, r.bounds.max, c);
                        GL.Color(c);
                        Tri(geometry[target.Mesh].Positions, geometry[target.Mesh].Indices, target.Tri, r.localToWorldMatrix);
                        break;
                }
            }
            GL.End();
            GL.PopMatrix();
        }

        // Triangle t of (positions, indices) through m.
        static void Tri(float[] p, int[] idx, int t, Matrix4x4 m)
        {
            Vector3 P(int k) { int v = idx[t * 3 + k]; return m.MultiplyPoint3x4(new Vector3(p[v * 3], p[v * 3 + 1], p[v * 3 + 2])); }
            Vector3 a = P(0), b = P(1), c = P(2);
            GL.Vertex(a); GL.Vertex(b); GL.Vertex(b); GL.Vertex(c); GL.Vertex(c); GL.Vertex(a);
        }

        static void WireBox(Vector3 lo, Vector3 hi, Color c)
        {
            GL.Color(c);
            for (int i = 0; i < 4; i++)
            {
                // The four edges along each axis.
                Line(new Vector3(lo.x, (i & 1) == 0 ? lo.y : hi.y, (i & 2) == 0 ? lo.z : hi.z), new Vector3(hi.x, (i & 1) == 0 ? lo.y : hi.y, (i & 2) == 0 ? lo.z : hi.z));
                Line(new Vector3((i & 1) == 0 ? lo.x : hi.x, lo.y, (i & 2) == 0 ? lo.z : hi.z), new Vector3((i & 1) == 0 ? lo.x : hi.x, hi.y, (i & 2) == 0 ? lo.z : hi.z));
                Line(new Vector3((i & 1) == 0 ? lo.x : hi.x, (i & 2) == 0 ? lo.y : hi.y, lo.z), new Vector3((i & 1) == 0 ? lo.x : hi.x, (i & 2) == 0 ? lo.y : hi.y, hi.z));
            }
        }

        // The selected face of the box: its diagonals, brighter.
        void Face(Color c)
        {
            var lo = V(box.Min);
            var hi = V(box.Max);
            int axis = box.Face / 2;
            float f = axis == 0 ? (box.Face % 2 == 0 ? hi.x : lo.x) : axis == 1 ? (box.Face % 2 == 0 ? hi.y : lo.y) : (box.Face % 2 == 0 ? hi.z : lo.z);
            Vector3 Corner(float u, float v) => axis == 0 ? new Vector3(f, u, v) : axis == 1 ? new Vector3(u, f, v) : new Vector3(u, v, f);
            float u0 = axis == 0 ? lo.y : lo.x, u1 = axis == 0 ? hi.y : hi.x;
            float v0 = axis == 2 ? lo.y : lo.z, v1 = axis == 2 ? hi.y : hi.z;
            GL.Color(Color.white);
            Line(Corner(u0, v0), Corner(u1, v1));
            Line(Corner(u0, v1), Corner(u1, v0));
        }

        static void Cross(Vector3 p, float s, Color c)
        {
            GL.Color(c);
            Line(p - Vector3.right * s, p + Vector3.right * s);
            Line(p - Vector3.up * s, p + Vector3.up * s);
            Line(p - Vector3.forward * s, p + Vector3.forward * s);
        }

        static void Line(Vector3 a, Vector3 b) { GL.Vertex(a); GL.Vertex(b); }
    }
}
