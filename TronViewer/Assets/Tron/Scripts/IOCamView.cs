using UnityEngine;
using UnityEngine.Rendering.Universal;

namespace Tron
{
    // Draws iocam (IOCam) as Tron's client does: a second camera at the pose the message gave, rendering the world
    // into IOCameraRect (scaled from 640x480 to the screen, cleared to black first) after the main view, while iocam
    // is on and its target is in the level; fovY IOCameraFOVY, fovX IOCameraFOVX x (w/h) x 0.75, the projection
    // built from both. It draws what the main camera does but the sky (no weapon either: the viewer has none); the
    // effects drawn for the main camera only (sprites, particles, DrawPrim) and the screen glow aren't in it. The
    // IONode HUD frame (IONodeFrame) is drawn by TronExplorer over it, under the rest of the HUD (DrawFrame).
    public class IOCamView : MonoBehaviour
    {
        public IOCam IOCam { get; private set; }
        // Set by TronExplorer: nothing is drawn (-shots, -benchat).
        public bool Suspended;

        Camera cam;
        LTTexture piece1, piece2;

        public void Init(IOCam ioCam)
        {
            IOCam = ioCam;
            piece1 = DtxLoader.Load(ioCam.Layout.piece1Tex);
            piece2 = DtxLoader.Load(ioCam.Layout.piece2Tex);
        }

        void Update() => IOCam?.Frame.Update(Time.deltaTime, IOCam.On && !Suspended);

        void LateUpdate()
        {
            bool show = IOCam != null && IOCam.ShowsInset && !Suspended;
            if (!show)
            {
                if (cam) cam.enabled = false;
                return;
            }
            var main = Camera.main;
            if (!cam) cam = MakeCamera();
            if (main)
            {
                cam.nearClipPlane = main.nearClipPlane;
                cam.farClipPlane = main.farClipPlane;
                cam.cullingMask = main.cullingMask;
            }
            var pose = IOCam.Pose;
            var root = transform;   // the level root (LT units)
            cam.transform.SetPositionAndRotation(root.TransformPoint(new Vector3(pose.Pos.x, pose.Pos.y, pose.Pos.z)),
                                                 root.rotation * new Quaternion(pose.Rot.x, pose.Rot.y, pose.Rot.z, pose.Rot.w));
            var r = IOCam.ScreenRect(IOCam.Layout, Screen.width, Screen.height);
            cam.pixelRect = new Rect(r[0], Screen.height - r[1] - r[3], r[2], r[3]);
            var (fovX, fovY) = IOCam.Fov(IOCam.Layout, r[2], r[3]);
            cam.fieldOfView = fovY;
            cam.aspect = Mathf.Tan(fovX * 0.5f * Mathf.Deg2Rad) / Mathf.Tan(fovY * 0.5f * Mathf.Deg2Rad);
            cam.enabled = true;
        }

        Camera MakeCamera()
        {
            var go = new GameObject("IO Camera");   // not under the level root: its scale would reach the view
            var c = go.AddComponent<Camera>();
            c.clearFlags = CameraClearFlags.SolidColor;
            c.backgroundColor = Color.black;
            c.allowHDR = false;
            c.depth = 10;   // after the sky camera and the main camera stacked on it
            var data = c.GetUniversalAdditionalCameraData();
            data.renderType = CameraRenderType.Base;
            data.renderPostProcessing = false;
            return c;
        }

        // The IONode frame (CHUDIOCamera) in 640x480 layout units stretched to the screen, in OnGUI's repaint: piece 1
        // at its alpha, the static (piece 2) at its radius while it flickers.
        public void DrawFrame()
        {
            if (IOCam == null || !IOCam.Frame.Visible) return;
            var l = IOCam.Layout;
            var f = IOCam.Frame;
            var prev = GUI.color;
            GUI.color = new Color(1, 1, 1, f.Alpha);
            Draw(piece1, l.center[0], l.center[1], l.piece1Radius);
            if (f.StaticShown) Draw(piece2, l.center[0], l.center[1], f.StaticRadius);
            GUI.color = prev;
        }

        static void Draw(LTTexture t, float cx, float cy, float radius)
        {
            if (t == null || !t.tex) return;
            float sx = Screen.width / 640f, sy = Screen.height / 480f;
            foreach (var q in IONodeFrame.Quads(cx, cy, radius))
            {
                // DTX rows are top first (v = 0 at the image's top): Unity's v runs up.
                var uv = new Rect(q[4], 1 - q[5], q[6] - q[4], -(q[7] - q[5]));
                GUI.DrawTextureWithTexCoords(new Rect(q[0] * sx, q[1] * sy, q[2] * sx, q[3] * sy), t.tex, uv, true);
            }
        }

        void OnDestroy()
        {
            if (cam) Destroy(cam.gameObject);
        }
    }
}
