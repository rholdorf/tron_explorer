using System;
using System.Collections.Generic;
using System.Globalization;

namespace Tron
{
    // Where a CameraPoint is, or where moveto puts a camera.
    public struct CameraPose
    {
        public LTVec Pos;
        public LTQuat Rot;
        public CameraPose(LTVec pos, LTQuat rot) { Pos = pos; Rot = rot; }
    }

    // A scene camera: a level's Camera object (docs/research/scene-cameras.md on research/scene-cameras; ltjs
    // objectdll camera.cpp, clientshelldll camerafx.h). Its messages (Camera::OnTrigger):
    //   ON: on and live (USRFLG_CAMERA_LIVE); a camera already on only restarts its ActiveTime timer.
    //   OFF: TurnOff, even when it is off.
    //   SKIP: TurnOff as a skip, only when CanSkip and on.
    //   MOVETO <point>: a cut to the CameraPoint's position and rotation; any other object, or none, does nothing.
    //   FOV <x> <y> [t]: the client's lerp from the previous target to (x, y) over t seconds of the frames this
    //   camera is live (none: at once).
    // Everything else is GameBase's (GameBaseFlags, joined before it: a removed camera takes nothing).
    // TurnOff: the CleanupCommand runs first (sender and target the camera); a skip of an OnSkipCleanupOnly camera
    // stops there and stays on; else it goes off and not live, and a OneTime camera leaves the level.
    // ActiveTime > 0: off by itself that many seconds of server time after ON. StartActive: on at level start.
    // IsListener and AllowPlayerMovement aren't read: the scene is always heard from the camera and every camera
    // in the levels holds the player. Plain C#, no Unity, so tools/tests/test_scene_cameras.py compiles it.
    public sealed class SceneCamera
    {
        public struct Props
        {
            public float ActiveTime, FovX, FovY;
            public int Type;
            public bool OneTime, StartActive, CanSkip, OnSkipCleanupOnly;
            public string CleanupCommand;
        }

        public const int Cinematic = 1;   // CT_CINEMATIC: the only Type with the letterbox

        public readonly string Name;
        public readonly Props P;
        public readonly GameBaseFlags Flags;
        // Runs a command property (the cleanup) with the camera as sender and active target.
        public Action<string> RunCommand;
        // The CameraPoint with this name, null if the first object with it isn't one (or there's none).
        public Func<string, CameraPose?> FindPoint;
        // Puts the camera object there (a cut).
        public Action<CameraPose> MoveTo;
        // The object leaves the level (its GameBase REMOVE).
        public Action RemoveObject;

        public bool On { get; private set; }
        bool live;
        // USRFLG_CAMERA_LIVE on an object still in the level: the client may look through it.
        public bool Live => live && !Flags.Removed;

        readonly Func<float> now;
        float turnOffTime;
        // CCameraFX's FOV: the target, the previous target, the lerp's time and how far it has run.
        float fovX, fovY, prevX, prevY, fovTime, fovElapsed;

        internal SceneCamera(string name, Props p, GameBaseFlags flags, Func<float> now)
        {
            Name = name ?? "";
            P = p;
            Flags = flags;
            this.now = now;
            fovX = prevX = p.FovX;
            fovY = prevY = p.FovY;
        }

        public bool Letterboxed => P.Type == Cinematic;

        // Camera::InitialUpdate.
        public void Start()
        {
            if (P.StartActive) TurnOn();
        }

        public bool OnMessage(Message m)
        {
            if (Flags.Removed) return false;
            if (m.Is("ON")) TurnOn();
            else if (m.Is("OFF")) TurnOff(false);
            else if (m.Is("SKIP")) Skip();
            else if (m.Is("MOVETO"))
            {
                if (m.ArgCount < 1) return true;
                var pose = FindPoint?.Invoke(m.Arg(0));
                if (pose.HasValue) MoveTo?.Invoke(pose.Value);
            }
            else if (m.Is("FOV"))
            {
                if (m.ArgCount < 2) return true;
                prevX = fovX;
                prevY = fovY;
                fovX = Atof(m.Arg(0));
                fovY = Atof(m.Arg(1));
                fovTime = m.ArgCount >= 3 ? Atof(m.Arg(2)) : 0;
                fovElapsed = 0;
            }
            else return false;
            return true;
        }

        // The skip key's SKIP (CPlayerObj::DoActivate sends it to every camera that is on).
        public void Skip()
        {
            if (!Flags.Removed && P.CanSkip && On) TurnOff(true);
        }

        void TurnOn()
        {
            On = true;
            live = true;
            if (P.ActiveTime > 0) turnOffTime = now() + P.ActiveTime;
        }

        void TurnOff(bool skip)
        {
            var cleanup = P.CleanupCommand;
            if (!string.IsNullOrEmpty(cleanup) && CommandMgr.IsValid(cleanup)) RunCommand?.Invoke(cleanup);
            if (skip && P.OnSkipCleanupOnly) return;
            On = false;
            live = false;
            if (P.OneTime && !Flags.Removed) RemoveObject?.Invoke();
        }

        // Camera::Update, each server frame while on.
        internal void ServerUpdate()
        {
            if (On && !Flags.Removed && P.ActiveTime > 0 && now() > turnOffTime) TurnOff(false);
        }

        // CCameraFX::UpdateFOV, each frame this camera is the live one.
        internal void UpdateFov(float frameTime) => fovElapsed += frameTime;

        public float FovX => fovElapsed < fovTime ? prevX + (fovX - prevX) * (fovElapsed / fovTime) : fovX;
        public float FovY => fovElapsed < fovTime ? prevY + (fovY - prevY) * (fovElapsed / fovTime) : fovY;

        // atof: the number at the start of the word, 0 if none.
        static float Atof(string s)
        {
            int n = 0;
            while (n < s.Length && (char.IsDigit(s[n]) || s[n] == '.' || s[n] == '-' || s[n] == '+')) n++;
            return float.TryParse(s.Substring(0, n), NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v : 0;
        }
    }

    // The level's scene cameras, in level order (the client's camera list), and what the view does with them
    // (ltjs CPlayerMgr::UpdateAlternativeCamera, TurnOn/TurnOffAlternativeCamera, CInterfaceMgr::UpdateLetterBox):
    // the first live camera is the view, with its FOV; with none the view is the player's at the normal 90/78. A
    // Type 1 camera letterboxes: black bars over the top and bottom 17% of the screen (LetterBoxPercent 0.66),
    // fading in over 0.5 s and out over 1.0 s. While a camera is live the player is held (input off, no
    // horizontal velocity) and the skip key sends SKIP to every camera that is on.
    public sealed class SceneCameras
    {
        public const float NormalFovX = 90, NormalFovY = 78;   // the console's FovX / FovY
        public const float LetterboxBorder = (1 - 0.66f) / 2;   // of the screen's height, top and bottom
        public const float LetterboxFadeIn = 0.5f, LetterboxFadeOut = 1.0f;

        readonly List<SceneCamera> cameras = new List<SceneCamera>();
        readonly Func<float> now;
        float clientTime, boxEnd;
        bool wasBox;

        // A skip has been sent to the cameras (after their cleanups ran). The game skips nothing else directly:
        // a scene unwinds through its cameras' cleanup commands. The place for what a skip does to the rest of a
        // scene (dialogue, #75).
        public event Action Skipped;

        // now: the server clock (ActiveTime).
        public SceneCameras(Func<float> now) => this.now = now;

        public IReadOnlyList<SceneCamera> All => cameras;
        public SceneCamera Add(string name, SceneCamera.Props p, GameBaseFlags flags)
        {
            var c = new SceneCamera(name, p, flags, now);
            cameras.Add(c);
            return c;
        }

        // The camera the view looks through this frame (null: the player's view).
        public SceneCamera Live { get; private set; }
        // PlayingCinematic: the player is held.
        public bool Held => Live != null;
        public float FovX { get; private set; } = NormalFovX;
        public float FovY { get; private set; } = NormalFovY;
        public float LetterboxAlpha { get; private set; }

        // Each frame: the cameras' server update (ActiveTime), then the client's: the first live camera, its FOV
        // lerp, the letterbox.
        public void Update(float frameTime)
        {
            foreach (var c in cameras) c.ServerUpdate();
            Live = null;
            foreach (var c in cameras)
                if (c.Live) { Live = c; break; }
            if (Live != null)
            {
                Live.UpdateFov(frameTime);
                FovX = Live.FovX;
                FovY = Live.FovY;
            }
            else
            {
                FovX = NormalFovX;
                FovY = NormalFovY;
            }
            UpdateLetterbox(Live != null && Live.Letterboxed, frameTime);
        }

        void UpdateLetterbox(bool on, float frameTime)
        {
            clientTime += frameTime;
            if (on != wasBox) boxEnd = clientTime + (on ? LetterboxFadeIn : LetterboxFadeOut);
            wasBox = on;
            float left = Math.Max(0, boxEnd - clientTime);
            LetterboxAlpha = on ? 1 - left / LetterboxFadeIn : left / LetterboxFadeOut;
        }

        // The skip key (Space) during a scene: SKIP to every camera that is on, in the server's object list
        // order, which is the reverse of level order (the engine adds each new object at the list's head,
        // servermgr.cpp; GetNextObject walks from the head). A camera's cleanup can turn on a camera earlier in
        // level order, already passed, which stays on: the intro's cam1 skipped starts the titles' tcam.
        public void Skip()
        {
            if (Live == null) return;
            for (int i = cameras.Count - 1; i >= 0; i--)
                if (cameras[i].On) cameras[i].Skip();
            Skipped?.Invoke();
        }

        // The viewer's vertical FOV for the game's (FovX, FovY): the game sets both angles on the screen as they
        // are, so its 4:3 picture is a little squeezed (90/78 isn't 4:3). The viewer keeps the picture undistorted
        // and keeps what the game shows across a 4:3 screen: the vertical angle of FovX at 4:3; a wider screen
        // sees more at the sides (Hor+), as the player's view does (90 across: 73.74 down). FovY isn't used.
        public static float ViewFov(float fovX) =>
            (float)(2 * Math.Atan(Math.Tan(fovX * Math.PI / 360) * 3 / 4) * 180 / Math.PI);
    }
}
