using System;
using System.Collections.Generic;

// iocam, Tron's picture-in-picture IO-node view (docs/research/screen-shake-iocam.md on research/screen-shake-iocam).
// Plain C#, no Unity, so tools/tests/test_iocam.py compiles it with .NET; IOCamView draws it.
namespace Tron
{
    // layout.txt's IO camera ([Miscellaneous] IOCameraRect / FOVX / FOVY) and its HUD frame ([IONodeCam]), in
    // 640x480 layout units; hud/iocam.json (tools/hudtext.py), these values when it is missing.
    [Serializable]
    public class IOCamLayout
    {
        public float[] rect = { 252, 105, 389, 278 };   // left, top, right, bottom
        public float fovX = 70, fovY = 60;
        public float[] center = { 320, 357 };
        public string piece1Tex = "interface/hud/ionode_hud.dtx", piece2Tex = "interface/hud/ionode_static.dtx";
        public float piece1MinAlpha = 0.27f, piece1MaxAlpha = 0.36f, piece1Period = 3, piece1Radius = 256;
        public float piece2MinInterval = 0.01f, piece2MaxInterval = 0.25f, piece2MinRadius = 248, piece2MaxRadius = 264;
        public int piece2MinFlickers = 12, piece2MaxFlickers = 22;
        public float piece2FlickerTime = 0.04f;

        public static IOCamLayout Default => new IOCamLayout();

        public float[] Center => center;
        public float Piece1Radius => piece1Radius;
    }

    // The player's IOCAM message and the client's IO camera. The server (CPlayerObj, object.lto 0x100663a5):
    // with two arguments or more, `iocam <any> <Location> [<Target>]` sends the client the position and rotation
    // the first object named Location has now (none: the message is dropped) and the first object named Target
    // (or none); with fewer, the IO camera goes off. The word after IOCAM is never read. The client (cshell.dll
    // 0x100a6c05) puts its IO camera there (it doesn't follow Location later) and draws the world through it into
    // the IOCameraRect after the main view, while it is on and the target object exists; the HUD frame shows
    // while it is on, target or not. Off forgets the target.
    public sealed class IOCam
    {
        public readonly IOCamLayout Layout;
        public readonly IONodeFrame Frame;

        public bool On { get; private set; }
        public CameraPose Pose { get; private set; }
        // The target's command-manager id, -1 for none.
        public int Target { get; private set; } = -1;
        Func<int, bool> exists = _ => true;

        // random: uniform in [0, 1) (the HUD frame's static); System.Random when null.
        public IOCam(IOCamLayout layout, Func<double> random = null)
        {
            Layout = layout ?? IOCamLayout.Default;
            Frame = new IONodeFrame(Layout, random);
        }

        // The inset is drawn: on, with a target that is still in the level.
        public bool ShowsInset => On && Target >= 0 && exists(Target);

        // The player's IOCAM handler. place(name): the first object of that name's position and rotation now, null
        // if none; find(name): the first object of that name (-1: none); exists(id): the object is still there.
        public void Handle(CommandMgr mgr, int player, Func<string, CameraPose?> place, Func<string, int> find, Func<int, bool> exists)
        {
            this.exists = exists ?? (_ => true);
            mgr.Handle(player, m =>
            {
                if (!m.Is("IOCAM")) return false;
                if (m.ArgCount < 2)
                {
                    On = false;
                    Target = -1;
                    return true;
                }
                var at = place(m.Arg(1));
                if (at == null) return false;
                On = true;
                Pose = at.Value;
                Target = m.ArgCount >= 3 ? find(m.Arg(2)) : -1;
                return true;
            });
        }

        // SetCameraFOV at creation: fovX = IOCameraFOVX x (w / h) x 0.75 (linear in the aspect, not atan-based) and
        // fovY = IOCameraFOVY, degrees, for the rectangle's w x h pixels.
        public static (float fovX, float fovY) Fov(IOCamLayout l, float w, float h) => (l.fovX * (w / h) * 0.75f, l.fovY);

        // IOCameraRect scaled from 640x480 to a w x h screen: x, y (top-left), width, height in pixels.
        public static float[] ScreenRect(IOCamLayout l, float w, float h)
        {
            float sx = w / 640f, sy = h / 480f;
            var r = l.rect;
            return new[] { r[0] * sx, r[1] * sy, (r[2] - r[0]) * sx, (r[3] - r[1]) * sy };
        }
    }

    // CHUDIOCamera, the IO node's HUD frame, while iocam is on. Piece 1 (IONode_hud.dtx, a quarter of the frame) is
    // four quads mirrored about Center, each Piece1Radius square, its alpha a sine from Piece1MinAlpha to
    // Piece1MaxAlpha over Piece1Period from when it showed. Piece 2 (IONode_static.dtx), static: after a random wait
    // of Piece2MinInterval..MaxInterval it flickers Piece2MinFlickers..MaxFlickers times, Piece2FlickerTime each at
    // a random radius of Piece2MinRadius..MaxRadius, then waits again. The quads' placement, the sine's terms and
    // the whole of piece 2 are read from the attribute names (docs/research/screen-shake-iocam.md).
    public sealed class IONodeFrame
    {
        readonly IOCamLayout l;
        readonly Func<double> random;
        float t, wait, flickerLeft;
        int flickers;

        public bool Visible { get; private set; }
        public float Alpha { get; private set; }
        public bool StaticShown => Visible && flickers > 0 && wait <= 0;
        public float StaticRadius { get; private set; }

        public IONodeFrame(IOCamLayout layout, Func<double> random = null)
        {
            l = layout;
            if (random == null)
            {
                var r = new Random();
                random = r.NextDouble;
            }
            this.random = random;
        }

        float Range(float a, float b) => a + (b - a) * (float)random();

        // Each frame: on, iocam's on byte.
        public void Update(float dt, bool on)
        {
            if (!on)
            {
                Visible = false;
                return;
            }
            if (!Visible)
            {
                Visible = true;
                t = 0;
                Wait();
            }
            else t += dt;
            float a = (l.piece1MaxAlpha - l.piece1MinAlpha) / 2, b = (l.piece1MaxAlpha + l.piece1MinAlpha) / 2;
            double k = l.piece1Period > 0 ? 2 * Math.PI / l.piece1Period : 0;
            Alpha = Math.Max(0, Math.Min(1, (float)Math.Sin(t * k) * a + b));
            if (t == 0) return;
            if (wait > 0)
            {
                wait -= dt;
                if (wait > 0) return;
                Flicker();
                return;
            }
            flickerLeft -= dt;
            if (flickerLeft > 0) return;
            if (--flickers > 0) Flicker();
            else Wait();
        }

        void Wait()
        {
            wait = Range(l.piece2MinInterval, l.piece2MaxInterval);
            flickers = l.piece2MinFlickers + (int)(random() * (l.piece2MaxFlickers - l.piece2MinFlickers + 1));
        }

        void Flicker()
        {
            wait = 0;
            flickerLeft = l.piece2FlickerTime;
            StaticRadius = Range(l.piece2MinRadius, l.piece2MaxRadius);
        }

        // A frame piece's four quads about (cx, cy) with half-size r: x, y (top-left), w, h in layout units and
        // the texture's u0, v0, u1, v1 (v down the image): as is top-left, mirrored across and down for the others.
        public static List<float[]> Quads(float cx, float cy, float r) => new List<float[]>
        {
            new[] { cx - r, cy - r, r, r, 0f, 0f, 1f, 1f },
            new[] { cx, cy - r, r, r, 1f, 0f, 0f, 1f },
            new[] { cx - r, cy, r, r, 0f, 1f, 1f, 0f },
            new[] { cx, cy, r, r, 1f, 1f, 0f, 0f },
        };
    }
}
