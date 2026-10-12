using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Debug = UnityEngine.Debug;

namespace Tron
{
    // Entry point: level menu, loading, sky/world cameras, fog, HUD.
    public class TronExplorer : MonoBehaviour
    {
        public Shader worldShader, glowBlurShader, glowCompositeShader;

        string extractedRoot, exportRoot;
        string[] levels = Array.Empty<string>();
        LevelBuilder level;
        PlayerController player;
        Camera mainCam, skyCam, glowCam;
        RenderTexture glowRT, blurA, blurB;
        Material blurMat, compositeMat;
        bool glowEnabled = true;
        bool menuOpen = true, showHelp = true;
        Vector2 menuScroll;
        string filter = "";
        string status = "";
        Vector4 fogColor, fogParams, skyFogParams;
        float fps;

        void Start()
        {
            if (!worldShader) worldShader = Shader.Find("Tron/World");
            uiAdjust = PlayerPrefs.GetFloat(UiScalePref, 1f);
            ResolveRoots();
            DtxLoader.Root = extractedRoot;
            TextureEffects.Root = extractedRoot;
            gameObject.AddComponent<SpriteAnimator>();
            var indexPath = Path.Combine(exportRoot ?? "", "levels.json");
            if (exportRoot != null && File.Exists(indexPath))
                levels = JsonUtility.FromJson<LevelIndexJson>(File.ReadAllText(indexPath)).levels;
            else
                status = "export/levels.json não encontrado. Rode tools/export_level.py ou passe -tronroot <dir>.";

            SetupCameras();
            SetupGlow();
            Shader.SetGlobalFloat("_LTSaturate", 2); // autoexec.cfg: "Saturate" "1"
            RenderPipelineManager.beginCameraRendering += OnBeginCamera;

            var auto = GetArg("-level");
            if (auto != null) Load(auto);
            if (float.TryParse(GetArg("-benchmark"), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var secs) && level != null)
                StartCoroutine(Benchmark(secs));
        }

        // -level <name> -benchmark <seconds>: frame times at the start point with vsync off, logged
        // as one "BENCH" line, then quit. Used to measure renderer changes in the player build.
        System.Collections.IEnumerator Benchmark(float seconds)
        {
            Application.runInBackground = true; // keep measuring if the window loses focus
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = -1;
            showHelp = false;
            for (float t = 0; t < 1; t += Time.unscaledDeltaTime) yield return null; // warm-up
            var ms = new System.Collections.Generic.List<float>();
            for (float t = 0; t < seconds; t += Time.unscaledDeltaTime)
            {
                yield return null;
                ms.Add(Time.unscaledDeltaTime * 1000);
            }
            ms.Sort();
            float avg = ms.Average();
            Debug.Log($"BENCH {level.Data.name} frames={ms.Count} avg={avg:0.00}ms ({1000 / avg:0} fps) " +
                      $"p50={ms[ms.Count / 2]:0.00}ms p95={ms[(int)(ms.Count * 0.95f)]:0.00}ms {Screen.width}x{Screen.height}");
            Application.Quit();
        }

        void OnDestroy() => RenderPipelineManager.beginCameraRendering -= OnBeginCamera;

        static string GetArg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }

        // Data lives next to the Unity project: <root>/extracted (REZ contents) and <root>/export.
        void ResolveRoots()
        {
            string root = GetArg("-tronroot") ?? Environment.GetEnvironmentVariable("TRON_EXPLORER_ROOT");
            if (root == null)
            {
                var dir = new DirectoryInfo(Application.dataPath);
                while (dir != null && !File.Exists(Path.Combine(dir.FullName, "export", "levels.json"))) dir = dir.Parent;
                root = dir?.FullName;
            }
            if (root == null) return;
            extractedRoot = Path.Combine(root, "extracted");
            exportRoot = Path.Combine(root, "export");
        }

        void SetupCameras()
        {
            var playerGo = new GameObject("Player");
            playerGo.AddComponent<CharacterController>();
            var camGo = new GameObject("Main Camera");
            camGo.transform.SetParent(playerGo.transform, false);
            mainCam = camGo.AddComponent<Camera>();
            camGo.AddComponent<AudioListener>();
            mainCam.nearClipPlane = 2 * LT.Scale;
            mainCam.farClipPlane = 20000 * LT.Scale;
            mainCam.cullingMask = ~(1 << LevelBuilder.SkyLayer);
            // Tron 2.0 default: 90 degrees horizontal at 4:3 -> keep that vertical FOV (Hor+).
            mainCam.fieldOfView = 2 * Mathf.Atan(Mathf.Tan(45 * Mathf.Deg2Rad) * 3f / 4f) * Mathf.Rad2Deg;
            mainCam.allowHDR = false;
            var mainData = mainCam.GetUniversalAdditionalCameraData();
            mainData.renderType = CameraRenderType.Overlay;
            mainData.renderPostProcessing = false;

            player = playerGo.AddComponent<PlayerController>();
            player.Cam = mainCam;
            playerGo.SetActive(false);

            // Sky pass: the sky world models are drawn first from a fixed point (the SkyPointer
            // with SkyDims) using the player's view rotation, then the world draws over it.
            var skyGo = new GameObject("Sky Camera");
            skyCam = skyGo.AddComponent<Camera>();
            skyCam.clearFlags = CameraClearFlags.SolidColor;
            skyCam.backgroundColor = Color.black;
            skyCam.cullingMask = 1 << LevelBuilder.SkyLayer;
            skyCam.nearClipPlane = mainCam.nearClipPlane;
            skyCam.farClipPlane = 100000 * LT.Scale;
            skyCam.allowHDR = false;
            var skyData = skyCam.GetUniversalAdditionalCameraData();
            skyData.renderType = CameraRenderType.Base;
            skyData.renderPostProcessing = false;
            skyData.cameraStack.Add(mainCam);
        }

        // Screen glow, as configured in the game's autoexec.cfg (ScreenGlow* console vars).
        const int GlowTextureSize = 256, GlowFilterSize = 24;
        const float GlowAmp0 = 0f, GlowRadius0 = 0f, GlowAmp1 = 0.1f, GlowRadius1 = 3f, GlowPixelShift = -0.1f, GlowUVScale = 1f;

        void SetupGlow()
        {
            glowRT = new RenderTexture(GlowTextureSize, GlowTextureSize, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear) { name = "Glow" };
            blurA = new RenderTexture(GlowTextureSize, GlowTextureSize, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear) { name = "GlowBlurA" };
            blurB = new RenderTexture(GlowTextureSize, GlowTextureSize, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear) { name = "GlowBlurB" };
            foreach (var rt in new[] { glowRT, blurA, blurB }) rt.wrapMode = TextureWrapMode.Clamp;
            blurMat = new Material(glowBlurShader ? glowBlurShader : Shader.Find("Hidden/Tron/GlowBlur"));
            compositeMat = new Material(glowCompositeShader ? glowCompositeShader : Shader.Find("Hidden/Tron/GlowComposite"));

            // UpdateGaussianFilter(): weight = sum(amp / exp(r * radius)), r = offset^2 / center^2
            float center = (GlowFilterSize - 1) / 2f;
            var offsets = new float[32];
            var weights = new float[32];
            int n = 0;
            for (int i = 0; i < GlowFilterSize && n < 32; i++)
            {
                float o = i - center + GlowPixelShift;
                float r = o * o / (center * center);
                float w = GlowAmp0 / Mathf.Exp(r * GlowRadius0) + GlowAmp1 / Mathf.Exp(r * GlowRadius1);
                if (w <= 0.001f) continue;
                offsets[n] = o; weights[n] = w; n++;
            }
            blurMat.SetFloatArray("_GlowOffsets", offsets);
            blurMat.SetFloatArray("_GlowWeights", weights);
            blurMat.SetInt("_GlowTaps", n);

            var go = new GameObject("Glow Camera");
            glowCam = go.AddComponent<Camera>();
            glowCam.targetTexture = glowRT;
            glowCam.clearFlags = CameraClearFlags.SolidColor;
            glowCam.backgroundColor = Color.black;
            glowCam.cullingMask = mainCam.cullingMask;
            glowCam.allowHDR = false;
            glowCam.depth = -10;
            var data = glowCam.GetUniversalAdditionalCameraData();
            data.renderPostProcessing = false;
            glowCam.enabled = false;
        }

        void UpdateGlow()
        {
            bool on = glowEnabled && level != null && player && player.gameObject.activeSelf;
            glowCam.enabled = on;
            if (!on) return;
            glowCam.transform.SetPositionAndRotation(mainCam.transform.position, mainCam.transform.rotation);
            glowCam.fieldOfView = mainCam.fieldOfView;
            glowCam.aspect = mainCam.aspect;
            glowCam.nearClipPlane = mainCam.nearClipPlane;
            glowCam.farClipPlane = mainCam.farClipPlane;
            // Blur last frame's glow buffer (one frame of latency).
            blurMat.SetVector("_GlowDir", new Vector4(GlowUVScale, 0, 0, 0));
            Graphics.Blit(glowRT, blurA, blurMat);
            blurMat.SetVector("_GlowDir", new Vector4(0, GlowUVScale, 0, 0));
            Graphics.Blit(blurA, blurB, blurMat);
        }

        void OnBeginCamera(ScriptableRenderContext ctx, Camera cam)
        {
            Shader.SetGlobalFloat("_LTGlowPass", cam == glowCam ? 1 : 0);
            Shader.SetGlobalVector("_LTFogColor", fogColor);
            Shader.SetGlobalVector("_LTFogParams", cam == skyCam ? skyFogParams : fogParams);
        }

        public void Load(string name)
        {
            var match = levels.FirstOrDefault(l => l == name) ?? levels.FirstOrDefault(l => l.EndsWith(name));
            if (match == null) { status = $"Fase {name} não encontrada"; return; }
            var sw = Stopwatch.StartNew();
            level?.Destroy();
            DtxLoader.ClearCache();
            level = new LevelBuilder();
            try
            {
                level.Build(Path.Combine(exportRoot, "levels", match), worldShader);
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                status = $"Erro ao carregar {match}: {e.Message}";
                return;
            }
            ApplyWorldProperties();
            Spawn();
            status = $"{match}: {sw.ElapsedMilliseconds} ms, {level.MissingTextures.Count} texturas ausentes";
            Debug.Log(status + (level.MissingTextures.Count > 0 ? "\n" + string.Join("\n", level.MissingTextures.Take(30)) : ""));
            menuOpen = false;
        }

        void ApplyWorldProperties()
        {
            var wp = level.Data.objects.FirstOrDefault(o => o.cls == "WorldProperties");
            fogParams = new Vector4(0, 0, 0, LT.Scale);
            skyFogParams = fogParams;
            fogColor = Vector4.zero;
            float farZ = 20000;
            if (wp != null)
            {
                var c = wp.Vec("FogColor") / 255f;
                fogColor = new Vector4(c.x, c.y, c.z, 1);
                if (wp.Bool("FogEnable"))
                    fogParams = new Vector4(wp.Num("FogNearZ"), wp.Num("FogFarZ"), 1, LT.Scale);
                if (wp.Bool("SkyFogEnable") && wp.Num("SkyFogFarZ") < 1e9f)
                    skyFogParams = new Vector4(wp.Num("SkyFogNearZ"), wp.Num("SkyFogFarZ"), 1, LT.Scale);
                farZ = wp.Num("FarZ", farZ);
            }
            mainCam.farClipPlane = farZ * LT.Scale;
            // In game only the Z buffer is cleared each frame (InterfaceMgr: CLEARSCREEN_RENDER); the
            // color buffer is cleared to black (0) on screen transitions. Additive/translucent sky
            // layers (e.g. m06-04's OuterShell at Index 0) therefore blend over black, not fog color.
            skyCam.backgroundColor = Color.black;
        }

        // Spawn / teleport destinations: the single-player start first, then every other start and
        // TeleportPoint (scripts move the player between these, e.g. after an intro cinematic).
        System.Collections.Generic.List<ObjectJson> spawnPoints = new System.Collections.Generic.List<ObjectJson>();
        int spawnIndex;

        void Spawn(int index = 0)
        {
            spawnPoints = level.Data.objects
                .Where(o => o.cls == "GameStartPoint" || o.cls == "ArenaStartPoint" || o.cls == "TeleportPoint")
                .OrderBy(o => o.cls == "GameStartPoint" && o.Str("GameType") == "Single" ? 0 : o.cls == "GameStartPoint" ? 1 : o.cls == "ArenaStartPoint" ? 2 : 3)
                .ToList();
            player.gameObject.SetActive(true);
            player.Noclip = false;
            if (spawnPoints.Count == 0)
            {
                var c = (new Vector3(level.Data.extMin[0], level.Data.extMin[1], level.Data.extMin[2]) +
                         new Vector3(level.Data.extMax[0], level.Data.extMax[1], level.Data.extMax[2])) * 0.5f;
                player.Noclip = true;
                player.Teleport(c * LT.Scale, 0);
                return;
            }
            spawnIndex = (index % spawnPoints.Count + spawnPoints.Count) % spawnPoints.Count;
            var sp = spawnPoints[spawnIndex];
            player.Teleport(sp.Position * LT.Scale, sp.rot[1] * Mathf.Rad2Deg);
        }

        void Update()
        {
            fps = Mathf.Lerp(fps, 1f / Mathf.Max(Time.unscaledDeltaTime, 1e-4f), 0.05f);
            var kb = Keyboard.current;
            if (kb != null)
            {
                if (kb.escapeKey.wasPressedThisFrame || kb.tabKey.wasPressedThisFrame) menuOpen = !menuOpen || level == null;
                if (kb.f1Key.wasPressedThisFrame) showHelp = !showHelp;
                if (kb.gKey.wasPressedThisFrame) glowEnabled = !glowEnabled;
                UpdateUiScaleInput(kb);
                if (kb.rKey.wasPressedThisFrame && level != null && !menuOpen) Spawn();
                if (kb.tKey.wasPressedThisFrame && level != null && !menuOpen) Spawn(spawnIndex + 1);
            }
            bool playing = !menuOpen && level != null;
            Cursor.lockState = playing ? CursorLockMode.Locked : CursorLockMode.None;
            Cursor.visible = !playing;
            if (player) player.InputEnabled = playing;
            if (skyCam && mainCam) skyCam.transform.rotation = mainCam.transform.rotation;
            if (skyCam && mainCam && level != null && level.HasSky)
                skyCam.transform.position = level.SkyViewPos(mainCam.transform.position / LT.Scale) * LT.Scale;
            if (skyCam && mainCam) skyCam.fieldOfView = mainCam.fieldOfView;
        }

        void LateUpdate() => UpdateGlow();

        // ---- UI scaling -------------------------------------------------------------------
        // IMGUI draws in physical pixels, so on a Retina/HiDPI display everything is half size.
        // Lay the UI out in logical points (96 dpi reference, like the OS does) and scale it with
        // GUI.matrix. The user can fine-tune with Ctrl/Cmd + '=' / '-' / '0'; the choice persists.
        const string UiScalePref = "ui_scale_adjust";
        float uiAdjust = 1f;
        float uiScale = 1f;
        GUIStyle hudStyle, helpStyle, titleStyle, buttonStyle, fieldStyle, statusStyle, panelStyle;
        Texture2D panelTex;
        float stylesScale = -1;

        float AutoUiScale()
        {
            float dpi = Screen.dpi > 0 ? Screen.dpi : 96f;
            float byDpi = dpi / 96f;
            // A window much smaller than the screen should not get huge text.
            float byHeight = Screen.height / 900f;
            return Mathf.Clamp(Mathf.Min(byDpi, Mathf.Max(byHeight, 1f)), 1f, 4f);
        }

        void UpdateUiScaleInput(Keyboard kb)
        {
            bool mod = kb.leftCtrlKey.isPressed || kb.rightCtrlKey.isPressed || kb.leftCommandKey.isPressed || kb.rightCommandKey.isPressed;
            if (!mod) return;
            float prev = uiAdjust;
            if (kb.equalsKey.wasPressedThisFrame || kb.numpadPlusKey.wasPressedThisFrame) uiAdjust *= 1.1f;
            if (kb.minusKey.wasPressedThisFrame || kb.numpadMinusKey.wasPressedThisFrame) uiAdjust /= 1.1f;
            if (kb.digit0Key.wasPressedThisFrame) uiAdjust = 1f;
            uiAdjust = Mathf.Clamp(uiAdjust, 0.5f, 3f);
            if (prev != uiAdjust) { PlayerPrefs.SetFloat(UiScalePref, uiAdjust); PlayerPrefs.Save(); }
        }

        void EnsureStyles()
        {
            if (stylesScale == uiScale && hudStyle != null) return;
            stylesScale = uiScale;
            if (!panelTex)
            {
                panelTex = new Texture2D(1, 1) { hideFlags = HideFlags.DontSave };
                panelTex.SetPixel(0, 0, new Color(0, 0.02f, 0.05f, 0.72f));
                panelTex.Apply();
            }
            panelStyle = new GUIStyle(GUI.skin.box) { padding = new RectOffset(12, 12, 10, 10) };
            panelStyle.normal.background = panelTex;
            hudStyle = new GUIStyle(GUI.skin.label) { fontSize = 16, wordWrap = false, padding = new RectOffset(8, 8, 4, 4) };
            hudStyle.normal.textColor = new Color(0.75f, 0.95f, 1f);
            hudStyle.normal.background = panelTex;
            helpStyle = new GUIStyle(hudStyle) { fontSize = 14, wordWrap = true };
            helpStyle.normal.textColor = new Color(0.8f, 0.85f, 0.9f);
            titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 20, fontStyle = FontStyle.Bold };
            titleStyle.normal.textColor = new Color(0.4f, 0.9f, 1f);
            buttonStyle = new GUIStyle(GUI.skin.button) { fontSize = 15, alignment = TextAnchor.MiddleLeft, padding = new RectOffset(10, 10, 6, 6) };
            fieldStyle = new GUIStyle(GUI.skin.textField) { fontSize = 15, padding = new RectOffset(6, 6, 4, 4) };
            statusStyle = new GUIStyle(GUI.skin.label) { fontSize = 13, wordWrap = true };
        }

        void OnGUI()
        {
            GUI.matrix = Matrix4x4.identity;
            if (Event.current.type == EventType.Repaint && glowCam && glowCam.enabled && !menuOpen)
                Graphics.DrawTexture(new Rect(0, 0, Screen.width, Screen.height), blurB, compositeMat);

            uiScale = AutoUiScale() * uiAdjust;
            EnsureStyles();
            GUI.matrix = Matrix4x4.Scale(new Vector3(uiScale, uiScale, 1));
            // Logical (point) size of the screen.
            float w = Screen.width / uiScale, h = Screen.height / uiScale;

            if (menuOpen)
            {
                float pw = Mathf.Min(480, w - 32);
                GUILayout.BeginArea(new Rect(16, 16, pw, h - 32), panelStyle);
                GUILayout.Label("TRON 2.0 — Explorador de Fases", titleStyle);
                GUILayout.Space(6);
                GUILayout.BeginHorizontal();
                GUILayout.Label("Filtro:", hudStyle, GUILayout.ExpandWidth(false));
                filter = GUILayout.TextField(filter, fieldStyle);
                GUILayout.EndHorizontal();
                GUILayout.Space(6);
                menuScroll = GUILayout.BeginScrollView(menuScroll);
                foreach (var l in levels)
                {
                    if (filter.Length > 0 && l.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    if (GUILayout.Button(l, buttonStyle)) Load(l);
                }
                GUILayout.EndScrollView();
                if (!string.IsNullOrEmpty(status)) GUILayout.Label(status, statusStyle);
                GUILayout.Label($"Escala da interface: {uiScale:0.00}×  (Ctrl/Cmd + = / − / 0)", statusStyle);
                GUILayout.EndArea();
                return;
            }

            var p = player ? player.transform.position / LT.Scale : Vector3.zero;
            string hud = $"{level?.Data.name}   {fps:0} fps   pos ({p.x:0}, {p.y:0}, {p.z:0})" + (player && player.Noclip ? "   [NOCLIP]" : "") +
                (spawnPoints.Count > 0 ? $"   ponto {spawnIndex + 1}/{spawnPoints.Count}: {spawnPoints[spawnIndex].name}" : "");
            var hudContent = new GUIContent(hud);
            var hs = hudStyle.CalcSize(hudContent);
            GUI.Label(new Rect(8, 8, Mathf.Min(hs.x, w - 16), hs.y), hudContent, hudStyle);
            if (showHelp)
            {
                var help = new GUIContent("WASD mover · Mouse olhar · Espaço pular · Shift andar · C agachar · N noclip (Alt rápido) · " +
                                          "G glow · R reiniciar · T próximo ponto · Tab/Esc menu · F1 ajuda · Ctrl/Cmd +/− tamanho do texto");
                float hw = Mathf.Min(helpStyle.CalcSize(help).x, w - 16);
                GUI.Label(new Rect(8, 12 + hs.y, hw, helpStyle.CalcHeight(help, hw)), help, helpStyle);
            }
        }
    }
}
