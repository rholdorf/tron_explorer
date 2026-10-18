using System;
using System.Collections.Generic;

namespace Tron
{
    // A DrawPrim vertex: where it is in the level, its colour (r | g << 8 | b << 16 | a << 24) and UV.
    public struct PrimVert
    {
        public LTVec Pos;
        public uint Color;
        public float U, V;
    }

    // The camera a DrawPrim effect is drawn for: its place and axes in the level.
    public struct PrimCamera
    {
        public LTVec Pos, Right, Up, Forward;

        static float Dot(LTVec a, LTVec b) => a.x * b.x + a.y * b.y + a.z * b.z;

        // GetCamTransform: the camera's space (x right, y up, z forward).
        public LTVec ToCamera(LTVec p)
        {
            var d = p - Pos;
            return new LTVec(Dot(d, Right), Dot(d, Up), Dot(d, Forward));
        }

        public LTVec FromCamera(LTVec c) => Pos + Right * c.x + Up * c.y + Forward * c.z;
    }

    // An effect the client shell draws itself with DrawPrim (CBaseFX::Render): its texture and the states
    // it sets (BlendMode, AlphaTest; Z read, not written; no culling, no fog, the DrawPrim defaults). ColorOp
    // is Modulate and FillMode Fill on every key the levels use, so the renderer doesn't read them.
    public abstract class FxDrawPrim : FxEffect
    {
        // ELTBlendMode, in the props' combo order.
        public const int NoBlend = 0, BlendAdd = 1, BlendSaturate = 2, ModSrcAlpha = 3, ModSrcColor = 4,
            ModDstColor = 5, MulSrcColDstCol = 6, MulSrcAlphaOne = 7, MulSrcAlpha = 8, MulSrcColOne = 9,
            MulDstColZero = 10;
        // ELTTestMode, in combo order (None, Less, LessOrEqual, Greater, GreaterOrEqual, Equal, NotEqual).
        public const int AlphaGreater = 3;

        public string Texture = "";
        public int BlendMode, AlphaTest, ColorOp, FillMode = 1;

        protected override void OnInit()
        {
            var k = Key;
            Texture = k.Str("Texture");
            BlendMode = (int)k.Num("BlendMode");
            AlphaTest = (int)k.Num("AlphaTest");
            ColorOp = (int)k.Num("ColorOp");
            FillMode = (int)k.Num("FillMode", 1);
        }

        // Render: four vertices per quad (start + bisector, end + bisector, end - bisector, start - bisector,
        // drawn as 0 1 2, 0 2 3), for the camera.
        public abstract void Render(PrimCamera cam, List<PrimVert> quads);

        // The frame of the texture's .spr a quad of the last Render draws (0: its first, or the .dtx).
        public virtual int QuadFrame(int quad) => 0;

        // Byte colour of a key's colour (each (int)(c x 255) clamped to 0-255, as PreRender does).
        public static uint Color(float r, float g, float b, float a) =>
            (uint)Byte(r) | (uint)Byte(g) << 8 | (uint)Byte(b) << 16 | (uint)Byte(a) << 24;

        static int Byte(float c) => Math.Max(0, Math.Min(255, (int)(c * 255)));

        // The camera-aligned bisectors of a strip of points in camera space (PreRender / CPolyTubeFX::Update):
        // at each end the perpendicular (dy, -dx) of its segment in the camera's x-y plane, inside the mean of
        // the two segments' perpendiculars; each then scaled to the width (left as is when it is zero).
        public static void Bisectors(LTVec[] tran, int n, float width, LTVec[] bis)
        {
            for (int i = 0; i < n; i++)
            {
                LTVec b;
                if (i == 0) b = Perp(tran[0], tran[1]);
                else if (i == n - 1) b = Perp(tran[n - 2], tran[n - 1]);
                else
                {
                    var p1 = Perp(tran[i], tran[i + 1]);
                    var p2 = Perp(tran[i - 1], tran[i]);
                    b = new LTVec((p1.x + p2.x) / 2, (p1.y + p2.y) / 2, 0);
                }
                bis[i] = Norm(b, width);
            }
        }

        static LTVec Perp(LTVec start, LTVec end) => new LTVec(end.y - start.y, -(end.x - start.x), 0);

        // LTVector::Norm: scaled to the length, unless it has none.
        public static LTVec Norm(LTVec v, float len)
        {
            float mag = v.Length();
            return mag == 0 ? v : v * (len / mag);
        }

        static bool Finite(LTVec v) => !float.IsNaN(v.x + v.y + v.z) && !float.IsInfinity(v.x + v.y + v.z);

        // One quad per segment of a strip (camera space points, their bisectors, colours and U), its V 0 on
        // the + side. Quads with a corner that isn't a number (a bolt of no length) aren't drawn: D3D draws
        // nothing of them.
        protected static void Strip(PrimCamera cam, LTVec[] tran, LTVec[] bis, uint[] colors, float[] u, int n,
            bool segmentUVs, List<PrimVert> quads)
        {
            for (int i = 0; i + 1 < n; i++)
            {
                LTVec a = tran[i] + bis[i], b = tran[i + 1] + bis[i + 1], c = tran[i + 1] - bis[i + 1], d = tran[i] - bis[i];
                if (!Finite(a) || !Finite(b) || !Finite(c) || !Finite(d)) continue;
                float u1 = segmentUVs ? 0 : u[i], u2 = segmentUVs ? 1 : u[i + 1];
                quads.Add(new PrimVert { Pos = cam.FromCamera(a), Color = colors[i], U = u1, V = 0 });
                quads.Add(new PrimVert { Pos = cam.FromCamera(b), Color = colors[i + 1], U = u2, V = 0 });
                quads.Add(new PrimVert { Pos = cam.FromCamera(c), Color = colors[i + 1], U = u2, V = 1 });
                quads.Add(new PrimVert { Pos = cam.FromCamera(d), Color = colors[i], U = u1, V = 1 });
            }
        }
    }
}
