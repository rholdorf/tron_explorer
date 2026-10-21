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
        public Shader worldShader, modelShader, glowBlurShader, glowCompositeShader, effectShader, hudTextShader;
        // Light grid interpolation order for models (ModelLighting's ltjsGridOrder), applied on level load.
        // Also "-gridorder ltjs" on the command line.
        public bool ltjsGridOrder;

        string extractedRoot, exportRoot;
        string[] levels = Array.Empty<string>();
        LevelBuilder level;
        PlayerController player;
        PlayerUse use;
        Camera mainCam, skyCam, glowCam;
        RenderTexture glowRT, blurA, blurB;
        Material blurMat, compositeMat;
        bool glowEnabled = true;
        bool muted;
        AudioSource testSound;
        bool menuOpen = true, showHelp = true;
        Vector2 menuScroll;
        string filter = "";
        string status = "";
        Vector4 fogColor, fogParams, skyFogParams, glowFogParams;
        // The level's live render variables (fog, far planes, glow filter; ramps, sines and WorldProperties
        // messages change them) and the screen fade, both run by the player's messages (PlayerMessages).
        RenderVars renderVars = new RenderVars(new System.Collections.Generic.Dictionary<string, float>());
        int renderVarsVersion = -1;
        readonly ScreenFade fade = new ScreenFade();
        const float LevelStartFadeTime = 1.5f;   // ScreenFadeInAtLevelStartTime
        // The HUD text the player's messages show (HudText): the game's strings (cres.dll), the typed mission
        // text, the transmission queue, the font they're drawn in, and the interface sounds they play.
        System.Collections.Generic.Dictionary<int, string> gameStrings = new System.Collections.Generic.Dictionary<int, string>();
        readonly MissionText missionText = new MissionText();
        readonly TransmissionQueue transmissions = new TransmissionQueue();
        HudFont hudFont;
        AudioSource typeSound;
        [Serializable] class StringsJson { public int[] ids; public string[] texts; }
        // The dialogue subtitles (Subtitles, drawn here): on by default (Tron's Default.prf Subtitles 1), U toggles
        // them; their layout from hud/subtitles.json (layout.txt [Subtitle]).
        bool subtitlesOn = true;
        [Serializable] class SubtitleLayoutJson { public int font, fontSize = 16, numLines = 3; public float[] color; public int[] playPos, cinematicPos; public int playWidth = 256, cinematicWidth = 256; }
        SubtitleLayoutJson subtitleLayout;
        float fps;

        void Start()
        {
            if (!worldShader) worldShader = Shader.Find("Tron/World");
            if (!modelShader) modelShader = Shader.Find("Tron/Model");
            if (!effectShader) effectShader = Shader.Find("Tron/Effect");
            if (!hudTextShader) hudTextShader = Shader.Find("Hidden/Tron/HudText");
            uiAdjust = PlayerPrefs.GetFloat(UiScalePref, 1f);
            ResolveRoots();
            DtxLoader.Root = extractedRoot;
            TextureEffects.Root = extractedRoot;
            SoundLoader.Root = exportRoot == null ? null : Path.Combine(exportRoot, "sounds");
            gameObject.AddComponent<SpriteAnimator>();
            SetupHudText();
            var indexPath = Path.Combine(exportRoot ?? "", "levels.json");
            if (exportRoot != null && File.Exists(indexPath))
                levels = JsonUtility.FromJson<LevelIndexJson>(File.ReadAllText(indexPath)).levels;
            else
                status = "export/levels.json não encontrado. Rode tools/export_level.py ou passe -tronroot <dir>.";

            SetupCameras();
            SetupGlow();
            ProtoAA(); // PROTOTYPE (#97)
            ProtoSSAO(); // PROTOTYPE (#99)
            Shader.SetGlobalFloat("_LTSaturate", 2); // autoexec.cfg: "Saturate" "1"
            Shader.SetGlobalFloat("_LTScale", LT.Scale);
            RenderPipelineManager.beginCameraRendering += OnBeginCamera;

            if (GetArg("-gridorder") == "ltjs") ltjsGridOrder = true;
            // -mute: starts muted, as M does (for captures and benchmarks run next to other work).
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-mute") >= 0) { muted = true; AudioListener.volume = 0; }
            // -shots and -frames draw the same frames on every run: a fixed 60 Hz frame time and seeded randoms (#92).
            if (GetArg("-shots") != null || GetArg("-frames") != null)
            {
                Time.captureDeltaTime = 1f / 60;
                ViewerRandom.Seed(1);
            }
            var auto = GetArg("-level");
            if (auto != null) Load(auto);
            var sound = GetArg("-playsound");
            if (sound != null) PlayTestSound(sound);
            if (float.TryParse(GetArg("-benchmark"), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var secs) && level != null)
                StartCoroutine(Benchmark(secs));
            var shots = GetArg("-shots");
            if (shots != null && level != null) StartCoroutine(Shots(shots, GetArg("-out") ?? "."));
            var frames = GetArg("-frames");
            if (frames != null && level != null) StartCoroutine(Frames(frames, GetArg("-out") ?? "."));
        }

        // -level <name> -frames "<seconds> ..." -out <dir>: the screen as it is shown (HUD and subtitles too) at
        // each time after the load (game time, in fixed 60 Hz frames: the same pixels on every run), to
        // <dir>/<seconds>.png; then quit. For comparing a scene with the game's.
        System.Collections.IEnumerator Frames(string times, string outDir)
        {
            Application.runInBackground = true;
            showHelp = false;
            Directory.CreateDirectory(outDir);
            float start = Time.time;
            yield return null; // PROTOTYPE (#97): -benchcmd fires effects for -frames too
            var protoCmd = GetArg("-benchcmd");
            if (protoCmd != null) level.Commands.Run(protoCmd);
            foreach (var at in times.Split(' ', StringSplitOptions.RemoveEmptyEntries)
                                    .Select(v => float.Parse(v, System.Globalization.CultureInfo.InvariantCulture)).OrderBy(v => v))
            {
                while (Time.time - start < at) yield return null;
                yield return new WaitForEndOfFrame();
                ScreenCapture.CaptureScreenshot(Path.Combine(Path.GetFullPath(outDir), $"{at:0.0}.png"));
            }
            // PROTOTYPE (#98): -proto-seq "<start> <count>": count consecutive frames from start, f000.png ...
            var seq = GetArg("-proto-seq")?.Split(' ');
            if (seq != null)
            {
                float s0 = float.Parse(seq[0], System.Globalization.CultureInfo.InvariantCulture);
                while (Time.time - start < s0) yield return null;
                for (int f = 0; f < int.Parse(seq[1]); f++)
                {
                    yield return new WaitForEndOfFrame();
                    ScreenCapture.CaptureScreenshot(Path.Combine(Path.GetFullPath(outDir), $"f{f:000}.png"));
                    yield return null;
                }
            }
            yield return null;
            Debug.Log($"FRAMES {level.Data.name} to {outDir}");
            Application.Quit();
        }

        // -level <name> -shots <panel.json> -out <dir>: reference-panel captures (mus-y-sinak's
        // docs/reference-panel.json: shots with name, eye in metres, yaw / pitch in degrees, vertical fov). The
        // level as the player first sees it (startup commands run, the level-start fade or its safety net over),
        // then each posed shot at 1706 x 772 (2.21:1) to <dir>/<name>.png, without HUD or use prompt; then quit.
        // The poses are in the viewer's frame as they are (docs/agents/workflow.md).
        [Serializable] class PanelJson { public ShotJson[] shots; }
        [Serializable] class ShotJson { public string name; public Vector3 eye; public float yaw, pitch, fov = 40; public bool posed; }
        public const int ShotWidth = 1706, ShotHeight = 772;
        bool capturing, benchAt;

        System.Collections.IEnumerator Shots(string panelPath, string outDir)
        {
            Application.runInBackground = true;
            showHelp = false;
            menuOpen = false;
            Screen.SetResolution(ShotWidth, ShotHeight, FullScreenMode.Windowed);
            var panel = JsonUtility.FromJson<PanelJson>(File.ReadAllText(panelPath));
            Directory.CreateDirectory(outDir);
            float waited = 0;
            while (waited < 2 || (fade.Alpha > 0 && waited < ScreenFade.SafetyNetDelay + ScreenFade.SafetyNetFadeTime + 4))
            {
                yield return null;
                waited += Time.deltaTime;
            }
            capturing = true;
            ObjectTicker.FreezePlayerBox = true;
            player.Noclip = true;
            var rt = new RenderTexture(ShotWidth, ShotHeight, 0);
            int done = 0;
            foreach (var s in panel.shots)
            {
                if (!s.posed) continue;
                player.transform.position = s.eye - player.Cam.transform.localPosition;
                player.SetView(s.yaw, s.pitch);
                player.Cam.fieldOfView = s.fov;
                for (int f = 0; f < 3; f++) yield return null;
                yield return new WaitForEndOfFrame();
                var shot = ScreenCapture.CaptureScreenshotAsTexture();
                if (shot.width != ShotWidth || shot.height != ShotHeight)
                {
                    if (Mathf.Abs((float)shot.width / shot.height - (float)ShotWidth / ShotHeight) > 0.01f)
                        Debug.LogWarning($"SHOTS window is {shot.width}x{shot.height}, not 2.21:1: {s.name}'s horizontal extent differs");
                    Graphics.Blit(shot, rt);
                    var prev = RenderTexture.active;
                    RenderTexture.active = rt;
                    var scaled = new Texture2D(ShotWidth, ShotHeight, TextureFormat.RGB24, false);
                    scaled.ReadPixels(new Rect(0, 0, ShotWidth, ShotHeight), 0, 0);
                    RenderTexture.active = prev;
                    Destroy(shot);
                    shot = scaled;
                }
                File.WriteAllBytes(Path.Combine(outDir, s.name + ".png"), shot.EncodeToPNG());
                Destroy(shot);
                done++;
            }
            Debug.Log($"SHOTS {level.Data.name} {done} to {outDir} (screen {Screen.width}x{Screen.height}, waited {waited:0.0}s)");
            Application.Quit();
        }

        // -level <name> -benchmark <seconds>: frame times at the start point with vsync off, logged
        // as one "BENCH" line, then quit. Used to measure renderer changes in the player build.
        // -benchat "x y z yaw pitch" (LT units, degrees) measures from there instead (noclip); -benchcmd
        // "<command>" runs a level command after the warm-up (m10-04's explosions: "msg sparksFX00 ON; ...").
        System.Collections.IEnumerator Benchmark(float seconds)
        {
            Application.runInBackground = true; // keep measuring if the window loses focus
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = -1;
            showHelp = false;
            var at = GetArg("-benchat")?.Split(' ').Select(v => float.Parse(v, System.Globalization.CultureInfo.InvariantCulture)).ToArray();
            benchAt = at != null && at.Length == 5;   // measured from there even while a scene plays
            for (float t = 0; t < 1; t += Time.unscaledDeltaTime) // warm-up
            {
                if (at != null && at.Length == 5)
                {
                    player.Noclip = true;
                    player.transform.position = new Vector3(at[0], at[1], at[2]) * LT.Scale;
                    player.SetView(at[3], at[4]);
                }
                yield return null;
            }
            var cmd = GetArg("-benchcmd");
            if (cmd != null) level.Commands.Run(cmd);
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

        // Checks the sound pipeline outside a level's placed sounds: loops one sound file
        // ("Snd\amb\drone12.WAV"), unpositioned, until the next level load. "-playsound <path>" on the
        // command line. Returns false if the file isn't in the export.
        public bool PlayTestSound(string path)
        {
            if (testSound) Destroy(testSound.gameObject);
            var clip = SoundLoader.Load(path);
            if (!clip) { Debug.LogWarning($"Sound {path} not in the export ({SoundLoader.Root})"); return false; }
            testSound = new GameObject("Test sound").AddComponent<AudioSource>();
            testSound.clip = clip;
            testSound.loop = true;
            testSound.spatialBlend = 0;
            testSound.Play();
            return true;
        }

        void OnDestroy() => RenderPipelineManager.beginCameraRendering -= OnBeginCamera;

        // [MissionText] TypeSound / ScrollSound and the transmissions' msgfadeout soundbute: interface sounds,
        // unpositioned.
        const string TypeSoundFile = "interface/snd/type.wav", ScrollSoundFile = "interface/snd/enter.wav",
                     TransmissionSoundFile = "interface/snd/msgfadeout.wav";

        void SetupHudText()
        {
            var path = Path.Combine(exportRoot ?? "", "hud", "strings.json");
            if (exportRoot != null && File.Exists(path))
            {
                var j = JsonUtility.FromJson<StringsJson>(File.ReadAllText(path));
                for (int i = 0; i < j.ids.Length; i++) gameStrings[j.ids[i]] = j.texts[i];
            }
            else Debug.LogWarning($"{path} not found: mission texts and transmissions show nothing; run tools/export_level.py");
            hudFont = HudFont.Load(exportRoot, hudTextShader);
            var subPath = Path.Combine(exportRoot ?? "", "hud", "subtitles.json");
            if (exportRoot != null && File.Exists(subPath)) subtitleLayout = JsonUtility.FromJson<SubtitleLayoutJson>(File.ReadAllText(subPath));
            else Debug.LogWarning($"{subPath} not found: dialogues show no subtitles; run tools/export_level.py");
            typeSound = gameObject.AddComponent<AudioSource>();
            typeSound.loop = true;
            typeSound.spatialBlend = 0;
            typeSound.playOnAwake = false;
            missionText.TypeSound = on =>
            {
                if (!on) { typeSound.Stop(); return; }
                typeSound.clip = SoundLoader.Load(TypeSoundFile);
                if (typeSound.clip) typeSound.Play();
            };
            missionText.ScrollSound = () => PlayInterfaceSound(ScrollSoundFile);
        }

        void PlayInterfaceSound(string file)
        {
            var clip = SoundLoader.Load(file);
            if (clip) typeSound.PlayOneShot(clip);
        }

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
            // Camera.main: the effect manager's distance freeze and the particles' facing.
            var camGo = new GameObject("Main Camera") { tag = "MainCamera" };
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
            use = playerGo.AddComponent<PlayerUse>();
            use.Cam = mainCam;
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

        // PROTOTYPE (#97, branch prototype/remaster-aa, never merged): -proto-aa none|post|fxaa|smaa|msaa2|msaa4|stp
        // [-proto-scale <render scale>] switches the anti-aliasing for side-by-side captures and timings. stp takes
        // the main camera off the sky's stack (URP gives stacked cameras no TAA/STP), so the sky isn't drawn.
        void ProtoAA()
        {
            var asset = (UniversalRenderPipelineAsset)GraphicsSettings.currentRenderPipeline;
            asset.upscalingFilter = UpscalingFilterSelection.Auto; // built with STP so its resources ship
            var mode = GetArg("-proto-aa");
            if (mode == null) return;
            var skyData = skyCam.GetUniversalAdditionalCameraData();
            var mainData = mainCam.GetUniversalAdditionalCameraData();
            if (float.TryParse(GetArg("-proto-scale"), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var scale))
                asset.renderScale = scale;
            switch (mode)
            {
                case "msaa2": asset.msaaSampleCount = 2; break;
                case "msaa4": asset.msaaSampleCount = 4; break;
                case "post":
                case "fxaa":
                case "smaa":
                    foreach (var d in new[] { skyData, mainData })
                    {
                        d.renderPostProcessing = true;
                        d.antialiasing = mode == "fxaa" ? AntialiasingMode.FastApproximateAntialiasing
                                       : mode == "smaa" ? AntialiasingMode.SubpixelMorphologicalAntiAliasing : AntialiasingMode.None;
                        d.antialiasingQuality = AntialiasingQuality.High;
                    }
                    break;
                case "stp":
                    skyData.cameraStack.Remove(mainCam);
                    skyCam.enabled = false;
                    mainData.renderType = CameraRenderType.Base;
                    mainCam.clearFlags = CameraClearFlags.SolidColor;
                    mainCam.backgroundColor = Color.black;
                    mainData.renderPostProcessing = true;
                    mainData.antialiasing = AntialiasingMode.TemporalAntiAliasing;
                    asset.upscalingFilter = UpscalingFilterSelection.STP;
                    break;
            }
            Debug.Log($"PROTO-AA {mode} scale {asset.renderScale} msaa {asset.msaaSampleCount} filter {asset.upscalingFilter}");
        }

        // PROTOTYPE (#99, branch prototype/remaster-ssao, never merged): -proto-ssao "i=0.4,r=0.3,f=100,s=1,d=0,b=0,after=0"
        // gives the main camera renderer 1 (PC_Renderer_SSAO), sets its SSAO feature (intensity, radius, falloff,
        // samples 0 high/1 medium/2 low, downsample, blur 0 bilateral/1 gaussian/2 kawase, after opaque) and
        // makes Tron/World and Tron/Model occlude their lit term with it (_LTAO); after=1 leaves the shaders
        // alone and lets URP darken the whole frame instead. Renderer 0 (every other camera) has SSAO off.
        bool protoAO;
        void ProtoSSAO()
        {
            var arg = GetArg("-proto-ssao");
            if (arg == null) return;
            var kv = arg.Split(',').Where(x => x.Contains('=')).ToDictionary(x => x.Split('=')[0], x => float.Parse(x.Split('=')[1], System.Globalization.CultureInfo.InvariantCulture));
            float Get(string k, float d) => kv.TryGetValue(k, out var v) ? v : d;
            var asset = (UniversalRenderPipelineAsset)GraphicsSettings.currentRenderPipeline;
            var list = (ScriptableRendererData[])typeof(UniversalRenderPipelineAsset).GetField("m_RendererDataList", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance).GetValue(asset);
            var feature = list[1].rendererFeatures.First(f => f.name == "ScreenSpaceAmbientOcclusion");
            var settings = feature.GetType().GetField("m_Settings", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance).GetValue(feature);
            void Set(string f, object v)
            {
                var fi = settings.GetType().GetField(f, System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                fi.SetValue(settings, fi.FieldType.IsEnum ? Enum.ToObject(fi.FieldType, Convert.ToInt32(v)) : fi.FieldType == typeof(bool) ? (object)(Convert.ToSingle(v) != 0) : v);
            }
            Set("Intensity", Get("i", 0.4f)); Set("Radius", Get("r", 0.3f)); Set("Falloff", Get("f", 100f));
            Set("Samples", Get("s", 1)); Set("Downsample", Get("d", 0)); Set("BlurQuality", Get("b", 0));
            Set("AfterOpaque", Get("after", 0)); Set("DirectLightingStrength", Get("dl", 0.25f));
            feature.SetActive(true);
            mainCam.GetUniversalAdditionalCameraData().SetRenderer(1);
            protoAO = Get("after", 0) == 0;
            Debug.Log($"PROTO-SSAO {arg} shaders {protoAO}");
        }

        // Screen glow, as configured in the game's autoexec.cfg (ScreenGlow* console vars; the filter's are
        // render variables, which some levels sine).
        // PROTOTYPE (#98, branch prototype/remaster-glow, never merged): -proto-glow <size> [sparse|resample]
        // renders the glow at size^2 and keeps the blur's apparent radius: sparse spaces the 24 taps by size/256,
        // resample runs the engine's filter over 24*size/256 taps with weights / (size/256).
        static int GlowTextureSize = 256; const int GlowFilterSize = 24;
        static float protoK = 1; static bool protoResample;

        void SetupGlow()
        {
            if (int.TryParse(GetArg("-proto-glow"), out var gs)) { GlowTextureSize = gs; protoK = gs / 256f; protoResample = GetArg("-proto-glow-mode") == "resample"; Debug.Log($"PROTO-GLOW {gs} {(protoResample ? "resample" : "sparse")}"); }
            glowRT = new RenderTexture(GlowTextureSize, GlowTextureSize, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear) { name = "Glow" };
            blurA = new RenderTexture(GlowTextureSize, GlowTextureSize, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear) { name = "GlowBlurA" };
            blurB = new RenderTexture(GlowTextureSize, GlowTextureSize, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear) { name = "GlowBlurB" };
            foreach (var rt in new[] { glowRT, blurA, blurB }) rt.wrapMode = TextureWrapMode.Clamp;
            blurMat = new Material(glowBlurShader ? glowBlurShader : Shader.Find("Hidden/Tron/GlowBlur"));
            compositeMat = new Material(glowCompositeShader ? glowCompositeShader : Shader.Find("Hidden/Tron/GlowComposite"));
            UpdateGlowFilter();

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

        // UpdateGaussianFilter(), which the engine runs on every glow render: weight = sum(amp / exp(r *
        // radius)), r = offset^2 / center^2.
        void UpdateGlowFilter()
        {
            float amp0 = renderVars["ScreenGlowGaussAmp0"], radius0 = renderVars["ScreenGlowGaussRadius0"];
            float amp1 = renderVars["ScreenGlowGaussAmp1"], radius1 = renderVars["ScreenGlowGaussRadius1"];
            float shift = renderVars["ScreenGlowPixelShift"];
            int size = protoResample ? Mathf.RoundToInt(GlowFilterSize * protoK) : GlowFilterSize;
            float center = (size - 1) / 2f;
            var offsets = new float[128];
            var weights = new float[128];
            int n = 0;
            for (int i = 0; i < size && n < 128; i++)
            {
                float o = i - center + shift * (protoResample ? protoK : 1);
                float r = o * o / (center * center);
                float w = amp0 / Mathf.Exp(r * radius0) + amp1 / Mathf.Exp(r * radius1);
                if (protoResample) w /= protoK;
                if (w <= 0.001f / (protoResample ? protoK : 1)) continue;
                offsets[n] = protoResample ? o : o * protoK; weights[n] = w; n++;
            }
            blurMat.SetFloatArray("_GlowOffsets", offsets);
            blurMat.SetFloatArray("_GlowWeights", weights);
            blurMat.SetInt("_GlowTaps", n);
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
            // screenglowmgr.cpp: the glow fog's far plane when it's on, never beyond FarZ.
            float farZ = renderVars["FarZ"];
            if (renderVars["ScreenGlowFogEnable"] != 0) farZ = Mathf.Min(renderVars["ScreenGlowFogFarZ"], farZ);
            glowCam.farClipPlane = Mathf.Max(farZ * LT.Scale, glowCam.nearClipPlane * 2);
            // Blur last frame's glow buffer (one frame of latency).
            float uvScale = renderVars["ScreenGlowUVScale"];
            blurMat.SetVector("_GlowDir", new Vector4(uvScale, 0, 0, 0));
            Graphics.Blit(glowRT, blurA, blurMat);
            blurMat.SetVector("_GlowDir", new Vector4(0, uvScale, 0, 0));
            Graphics.Blit(blurA, blurB, blurMat);
        }

        void OnBeginCamera(ScriptableRenderContext ctx, Camera cam)
        {
            Shader.SetGlobalFloat("_LTGlowPass", cam == glowCam ? 1 : 0);
            Shader.SetGlobalFloat("_LTAO", protoAO && cam == mainCam ? 1 : 0); // PROTOTYPE (#99)
            Shader.SetGlobalVector("_LTFogColor", fogColor);
            // The glow buffer is fogged towards black with its own distances (the shaders' glow pass).
            Shader.SetGlobalVector("_LTFogParams", cam == skyCam ? skyFogParams : cam == glowCam ? glowFogParams : fogParams);
        }

        public void Load(string name)
        {
            var match = levels.FirstOrDefault(l => l == name) ?? levels.FirstOrDefault(l => l.EndsWith(name));
            if (match == null) { status = $"Fase {name} não encontrada"; return; }
            var sw = Stopwatch.StartNew();
            LogCommandReport();
            level?.Destroy();
            missionText.Clear();
            transmissions.Clear();
            DtxLoader.ClearCache();
            if (testSound) Destroy(testSound.gameObject);
            SoundLoader.ClearCache();
            level = new LevelBuilder { EffectShader = effectShader, GameString = id => gameStrings.TryGetValue(id, out var t) ? t : null };
            level.Subtitles.Enabled = subtitlesOn;
            try
            {
                level.Build(Path.Combine(exportRoot, "levels", match), worldShader, modelShader, exportRoot, ltjsGridOrder);
            }
            catch (Exception e)
            {
                Debug.LogException(e);
                status = $"Erro ao carregar {match}: {e.Message}";
                return;
            }
            // The player answers to "player" (and "ActivePlayer"); its messages count as class Player.
            PlayerId = level.Commands.Join("player", "Player");
            use.PlayerId = PlayerId;
            level.ConnectPlayer(PlayerId, player);
            ApplyWorldProperties();
            Spawn();
            // The start point's Command runs at the player's first update (Relays.StartCommand), once per
            // load: R and T only move the player. The level's StartupCommands run in the same frame, before it.
            var start = spawnPoints.Count > 0 ? spawnPoints[0] : null;
            level.Relays.StartCommand = start != null && start.cls == "GameStartPoint" ? start.Str("Command") : null;
            // The game fades in at level start; a fade in a startup or start point command (m01-01's
            // "fadeIn 2.0") replaces this one on the first frame, as a new fade does.
            fade.Start(true, LevelStartFadeTime);
            status = $"{match}: {sw.ElapsedMilliseconds} ms, {level.MissingTextures.Count} texturas ausentes";
            Debug.Log(status + (level.MissingTextures.Count > 0 ? "\n" + string.Join("\n", level.MissingTextures.Take(30)) : ""));
            if (SoundLoader.Missing.Count > 0)
                Debug.LogWarning($"{match}: {SoundLoader.Missing.Count} sons ausentes\n" + string.Join("\n", SoundLoader.Missing));
            menuOpen = false;
        }

        // The level's command-manager id of the player (handlers: level.Commands.Handle(PlayerId, ...)).
        public int PlayerId { get; private set; } = -1;

        // The loaded level's command manager (null before a load), e.g. to run a command by hand:
        // FindFirstObjectByType<TronExplorer>().Commands.Run("msg player (fadeout 1)").
        public CommandMgr Commands => level?.Commands;

        // The console report of the commands and messages nobody handled in this level so far.
        void LogCommandReport()
        {
            if (level?.Commands != null) Debug.Log(level.Commands.Report(level.Data.name));
        }

        void OnApplicationQuit() => LogCommandReport();

        // The render variables from the level's WorldProperties (its props are the server's world variables),
        // and the player's and WorldProperties' message handlers that change them.
        void ApplyWorldProperties()
        {
            var world = new System.Collections.Generic.Dictionary<string, float>();
            var wp = level.Data.objects.FirstOrDefault(o => o.cls == "WorldProperties");
            if (wp != null)
            {
                var c = wp.Vec("FogColor");
                world["FogR"] = c.x; world["FogG"] = c.y; world["FogB"] = c.z;
                foreach (var name in new[] { "FarZ", "FogEnable", "FogNearZ", "FogFarZ", "SkyFogEnable", "SkyFogNearZ", "SkyFogFarZ" })
                    if (wp.Has(name)) world[name] = wp.Num(name);
                foreach (var name in new[] { "Enable", "NearZ", "FarZ" })
                    if (wp.Has("GlowFog" + name)) world["ScreenGlowFog" + name] = wp.Num("GlowFog" + name);
            }
            renderVars = new RenderVars(world);
            renderVarsVersion = -1;
            for (int i = 0; i < level.Data.objects.Length; i++)
                if (level.Data.objects[i].cls == "WorldProperties")
                    PlayerMessages.HandleWorldProperties(level.Commands, i, renderVars);
            PlayerMessages.Handle(level.Commands, PlayerId, renderVars, fade, TeleportTo);
            HudMessages.Handle(level.Commands, PlayerId, id => gameStrings.TryGetValue(id, out var t) ? t : null,
                               missionText, transmissions, () => PlayInterfaceSound(TransmissionSoundFile));
            ApplyRenderVars();
            // In game only the Z buffer is cleared each frame (InterfaceMgr: CLEARSCREEN_RENDER); the
            // color buffer is cleared to black (0) on screen transitions. Additive/translucent sky
            // layers (e.g. m06-04's OuterShell at Index 0) therefore blend over black, not fog color.
            skyCam.backgroundColor = Color.black;
        }

        // The render variables into the fog globals, the camera far plane and the glow filter (every frame,
        // as the renderer reads its console variables; rebuilt only when one changed).
        void ApplyRenderVars()
        {
            if (renderVars.Version == renderVarsVersion) return;
            renderVarsVersion = renderVars.Version;
            var v = renderVars;
            fogColor = new Vector4(v["FogR"] / 255f, v["FogG"] / 255f, v["FogB"] / 255f, 1);
            fogParams = FogParams(v["FogEnable"] != 0, v["FogNearZ"], v["FogFarZ"]);
            skyFogParams = FogParams(v["SkyFogEnable"] != 0 && v["SkyFogFarZ"] < 1e9f, v["SkyFogNearZ"], v["SkyFogFarZ"]);
            glowFogParams = FogParams(v["ScreenGlowFogEnable"] != 0, v["ScreenGlowFogNearZ"], v["ScreenGlowFogFarZ"]);
            mainCam.farClipPlane = Mathf.Max(v["FarZ"], 1) * LT.Scale;
            if (blurMat) UpdateGlowFilter();
        }

        // A fog's shader parameters: (near, far, on, LT units to Unity); off is all zero but the scale.
        static Vector4 FogParams(bool on, float near, float far) =>
            on ? new Vector4(near, far, 1, LT.Scale) : new Vector4(0, 0, 0, LT.Scale);

        // msg player (teleport <name>): only a TeleportPoint (ltjs character.cpp); its rot is [pitch, yaw, roll].
        bool TeleportTo(string name)
        {
            var tp = level.Data.objects.FirstOrDefault(o => o.cls == "TeleportPoint" &&
                                                            string.Equals(o.name, name, StringComparison.OrdinalIgnoreCase));
            if (tp == null) return false;
            float pitch = tp.rot != null && tp.rot.Length > 0 ? tp.rot[0] : 0, yaw = tp.rot != null && tp.rot.Length > 1 ? tp.rot[1] : 0;
            player.RequestTeleport(tp.Position * LT.Scale, yaw * Mathf.Rad2Deg, pitch * Mathf.Rad2Deg);
            return true;
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
                if (kb.mKey.wasPressedThisFrame) { muted = !muted; AudioListener.volume = muted ? 0 : 1; }
                if (kb.uKey.wasPressedThisFrame && !menuOpen)
                {
                    subtitlesOn = !subtitlesOn;
                    if (level != null) level.Subtitles.Enabled = subtitlesOn;
                }
                UpdateUiScaleInput(kb);
                if (kb.rKey.wasPressedThisFrame && level != null && !menuOpen) Spawn();
                if (kb.tKey.wasPressedThisFrame && level != null && !menuOpen) Spawn(spawnIndex + 1);
                if (kb.lKey.wasPressedThisFrame && level != null && !menuOpen) LogCommandReport();
            }
            bool playing = !menuOpen && level != null;
            Cursor.lockState = playing ? CursorLockMode.Locked : CursorLockMode.None;
            Cursor.visible = !playing;
            // A scene camera's view holds the player: no input (free flight gives it back).
            var scene = level?.SceneCameraView;
            if (scene)
            {
                scene.Playing = playing;
                scene.Suspended = capturing || benchAt;
            }
            if (level?.IOCamView) level.IOCamView.Suspended = capturing || benchAt;
            if (player) player.InputEnabled = playing && !(scene && scene.ShowingScene);
            if (level != null)
            {
                renderVars.Update(Time.deltaTime);
                fade.Update(Time.deltaTime);
                missionText.Update(Time.deltaTime);
                transmissions.Update(Time.deltaTime);
                ApplyRenderVars();
            }
        }

        // The sky camera follows the main camera once everything moved it this frame (the player, a scene camera,
        // the camera jitter), then the glow camera.
        void LateUpdate()
        {
            if (skyCam && mainCam)
            {
                skyCam.transform.rotation = mainCam.transform.rotation;
                if (level != null && level.HasSky)
                    skyCam.transform.position = level.SkyViewPos(mainCam.transform.position / LT.Scale) * LT.Scale;
                skyCam.fieldOfView = mainCam.fieldOfView;
            }
            UpdateGlow();
        }

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
            // A Type 1 scene camera's letterbox (SceneCameras): black bars over the top and bottom of the screen,
            // fading; not in free flight.
            var scene = level?.SceneCameraView;
            if (Event.current.type == EventType.Repaint && scene && !scene.FreeFlight && !scene.Suspended &&
                scene.Cameras.LetterboxAlpha > 0)
            {
                var prev = GUI.color;
                GUI.color = new Color(0, 0, 0, scene.Cameras.LetterboxAlpha);
                float bar = (int)(Screen.height * SceneCameras.LetterboxBorder);
                GUI.DrawTexture(new Rect(0, 0, Screen.width, bar), Texture2D.whiteTexture);
                GUI.DrawTexture(new Rect(0, Screen.height - bar, Screen.width, bar), Texture2D.whiteTexture);
                GUI.color = prev;
            }
            // iocam's IONode frame (CHUDIOCamera), over its inset, under the rest of the HUD.
            if (Event.current.type == EventType.Repaint && level?.IOCamView && !menuOpen) level.IOCamView.DrawFrame();
            // The screen fade's black overlay, over the scene and its glow, under the viewer's HUD and menu.
            if (Event.current.type == EventType.Repaint && level != null && fade.Alpha > 0)
            {
                var prev = GUI.color;
                GUI.color = new Color(0, 0, 0, fade.Alpha);
                GUI.DrawTexture(new Rect(0, 0, Screen.width, Screen.height), Texture2D.whiteTexture);
                GUI.color = prev;
            }
            if (capturing) return;   // -shots: the scene only
            bool hudText = Event.current.type == EventType.Repaint && level != null && hudFont != null;
            // The game's HUD text goes under the menu, but over the viewer's info bar and help.
            if (hudText && menuOpen) DrawHudText();

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
            string sceneTag = scene && scene.ShowingScene ? $"   [CENA {scene.LiveName}: Espaço pula, V voo livre]"
                            : scene && scene.FreeFlight ? $"   [VOO LIVRE, cena {scene.LiveName}: V volta]" : "";
            string hud = $"{level?.Data.name}   " + (Time.captureDeltaTime > 0 ? "" : $"{fps:0} fps   ") + $"pos ({p.x:0}, {p.y:0}, {p.z:0})" + (player && player.Noclip && !(scene && scene.FreeFlight) ? "   [NOCLIP]" : "") + (muted ? "   [MUDO]" : "") + (subtitlesOn ? "" : "   [SEM LEGENDAS]") +
                (spawnPoints.Count > 0 ? $"   ponto {spawnIndex + 1}/{spawnPoints.Count}: {spawnPoints[spawnIndex].name}" : "") + sceneTag;
            var hudContent = new GUIContent(hud);
            var hs = hudStyle.CalcSize(hudContent);
            GUI.Label(new Rect(8, 8, Mathf.Min(hs.x, w - 16), hs.y), hudContent, hudStyle);
            if (showHelp)
            {
                var help = new GUIContent("WASD mover · Mouse olhar · Espaço pular · Shift andar · C agachar · N noclip (Alt rápido) · E usar · " +
                                          "Cena: Espaço pula, V voo livre · G glow · M som · U legendas · R reiniciar · T próximo ponto · L comandos não tratados (console) · Tab/Esc menu · F1 ajuda · Ctrl/Cmd +/− tamanho do texto");
                float hw = Mathf.Min(helpStyle.CalcSize(help).x, w - 16);
                GUI.Label(new Rect(8, 12 + hs.y, hw, helpStyle.CalcHeight(help, hw)), help, helpStyle);
            }
            if (hudText) DrawHudText();
        }

        // The game's HUD text, in font 0 over the screen fade, in 640 x 480 layout units (HudFont):
        // - the mission text ([MissionText]): typed at (100, 132), lines downwards, no wrapping;
        // - the transmissions ([AnnouncementMessageQueue]): each line centred on x 320, wrapped at 400, the
        //   messages bottom-justified at y 80, the newest lowest; shadow 0xBF black (ltjs CHUDMessage);
        // - the use prompt (CTargetMgr): the target's ActivateType text for its state, centred at (320, 300),
        //   yellow, grey while locked; a target whose type has no text for the state shows just the key.
        const float HudCharHeight = 14;

        // The dialogue subtitle (CHUDSubtitles): font 0 at FontSize in TextColor, a black shadow one unit down-right,
        // wrapped at the box's width; the box at FullScreenPos in play or Pos when it started under a scene camera,
        // NumLines tall. Text that fits is centred and sits on the box's bottom; longer text starts at the box's
        // left and top and scrolls up (Subtitles.TextTop), showing only the lines inside the box.
        void DrawSubtitle()
        {
            var subs = level.Subtitles;
            var l = subtitleLayout;
            if (l == null || !subs.Draws(level.Dialogues.ListenerPos(), level.SceneCameras?.Live != null)) return;
            var pos = subs.Cinematic ? l.cinematicPos : l.playPos;
            float width = subs.Cinematic ? l.cinematicWidth : l.playWidth, size = l.fontSize;
            int rgb = l.color != null && l.color.Length >= 3 ? ((int)l.color[0] << 16) | ((int)l.color[1] << 8) | (int)l.color[2] : 0xFFFFFF;
            var lines = hudFont.Lines(ColorMarkup.Parse(subs.Text, rgb), size, width);
            float top = subs.TextTop(lines.Count, hudFont.BlockHeight(lines.Count, size), pos[1], l.numLines, size);
            bool overflow = lines.Count > l.numLines;
            float widest = 0;
            foreach (var line in lines) widest = Mathf.Max(widest, hudFont.Width(line, size));
            float x = overflow ? pos[0] : pos[0] + (width - widest) / 2;
            float boxBottom = pos[1] + 2 + l.numLines * size, step = hudFont.LineHeight(size);
            for (int i = 0; i < lines.Count; i++)
            {
                float y = top + i * step;
                if (overflow && (y < pos[1] - step / 2 || y + size > boxBottom + step / 2)) continue;
                hudFont.Draw(new System.Collections.Generic.List<System.Collections.Generic.List<HudChar>> { lines[i] }, x, y, size, 1);
            }
        }

        void DrawHudText()
        {
            hudFont.Begin(Screen.width, Screen.height);
            if (missionText.Active)
                hudFont.Draw(hudFont.Lines(missionText.Chars, HudCharHeight), 100, 132, HudCharHeight, missionText.Alpha,
                             count: missionText.Visible);
            float bottom = 80;
            for (int i = transmissions.Entries.Count - 1; i >= 0; i--)
            {
                var e = transmissions.Entries[i];
                if (!e.Visible) continue;
                var lines = hudFont.Lines(e.Chars, HudCharHeight, 400);
                bottom -= hudFont.BlockHeight(lines.Count, HudCharHeight);
                hudFont.Draw(lines, 320, bottom, HudCharHeight, e.Alpha, centred: true, shadowAlpha: 0xBF / 255f);
            }
            // While a scene camera is the view only the text items draw (kHUDRenderText): no use prompt.
            var t = use ? use.Target : null;
            var scene = level.SceneCameraView;
            if (t != null && !menuOpen && !(scene && scene.ShowingScene))
            {
                var text = string.IsNullOrEmpty(t.Prompt) ? "[E]" : $"[E] {t.Prompt}";
                var color = t.Locked ? new Color(128 / 255f, 128 / 255f, 128 / 255f) : new Color(1, 1, 0);
                hudFont.DrawText(text, 320, 300 - HudCharHeight / 2, HudCharHeight, color, true);
            }
            DrawSubtitle();
            hudFont.End();
        }
    }
}
