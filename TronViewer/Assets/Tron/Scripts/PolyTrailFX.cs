using System;
using System.Collections.Generic;

namespace Tron
{
    // The PolyTrail effect as the game plays it (ltjs clientfxdll/polytubefx.cpp; docs/research/clientfx-types.md
    // on research/clientfx-types), a ribbon drawn with DrawPrim. It starts with one point where its instance
    // started (where it is when its parent is more than 256 units from there), adds the next at once and one
    // more every SectionInterval while it has fewer than TrailLen, and its last point follows the effect. Each
    // point ages: Ck runs over SectionLifespan, and points that old go (never the last). U grows by the
    // distance between points over TrailWidth and scrolls by UAdd per second. The width is TrailWidth,
    // shrinking or growing with the number of points by WidthStyle. Camera-aligned on every key the levels
    // use (Allignment Up / Right / Forward, lying in the effect's axes, aren't read). Shutting down, it adds
    // no points, its last point stays, and it goes once fewer than two remain. Plain C#, no Unity, so
    // tools/tests/test_poly_trail_fx.py compiles it with .NET.
    public sealed class FxPolyTrail : FxDrawPrim
    {
        public const int Constant = 0, SmallToBig = 1, SmallToSmall = 2, BigToSmall = 3;

        struct Point
        {
            public LTVec Pos;
            public float Elapsed, U;
            public uint Color;
        }

        readonly List<Point> points = new List<Point>();
        float interval, lifespan, uAdd, width, elapsedEmission, uOffset, drawWidth;
        int maxLength, widthStyle;
        LTVec[] tran = new LTVec[8], bis = new LTVec[8];
        uint[] colors = new uint[8];
        float[] us = new float[8];

        protected override void OnInit()
        {
            base.OnInit();
            var k = Key;
            interval = k.Num("SectionInterval", 0.1f);
            maxLength = (int)k.Num("TrailLen", 50);
            lifespan = k.Num("SectionLifespan", 1);
            uAdd = k.Num("UAdd", 0);
            width = k.Num("TrailWidth", 20);
            widthStyle = (int)k.Num("WidthStyle", Constant);
            var start = InstancePos;
            if (Parent != null && (start - Parent.Pos).Length() > 256) start = Pos;
            points.Add(new Point { Pos = start });
        }

        public int Count => points.Count;
        // The width it was last drawn with: CalcCurWidth in the update, before old points go.
        public float Width => drawWidth;

        float CurWidth()
        {
            int n = points.Count;
            switch (widthStyle)
            {
                case Constant: return width;
                case SmallToBig: return width * ((n - 2) / (float)maxLength);
                case SmallToSmall:
                    return n < (maxLength + 1) * 0.5f
                        ? width * ((n - 2) / (float)maxLength)
                        : width * ((maxLength - (n - 2)) / (float)maxLength);
                case BigToSmall: return width * ((maxLength - (n - 2)) / (float)maxLength);
                default: return 0;
            }
        }

        protected override void OnUpdate(float dt)
        {
            if (points.Count < 2 && ShuttingDown)
            {
                points.Clear();
                return;
            }
            elapsedEmission += dt;
            if (!ShuttingDown && points.Count < maxLength && (elapsedEmission > interval || points.Count == 1))
            {
                var prev = points[points.Count - 1];
                points.Add(new Point { Pos = Pos, U = prev.U + (Pos - prev.Pos).Length() / width });
                elapsedEmission = 0;
            }
            if (points.Count < 2) return;
            if (!ShuttingDown)
            {
                var last = points[points.Count - 1];
                last.Pos = Pos;
                points[points.Count - 1] = last;
            }
            drawWidth = CurWidth();
            for (int i = 0; i < points.Count; i++)
            {
                var p = points[i];
                p.Elapsed += dt;
                float t = lifespan > 0 ? (float)(p.Elapsed / lifespan % 1.0) : 0;
                float r = 1, g = 1, b = 1, a = 1;
                KeyColour(Key.Ck, t, ref r, ref g, ref b, ref a);
                p.Color = Color(r, g, b, a);
                points[i] = p;
            }
            for (int i = 0; i + 1 < points.Count; i++)
                if (points[i].Elapsed >= lifespan) points.RemoveAt(i--);
            uOffset += dt * uAdd;
        }

        public override bool IsFinishedShuttingDown => points.Count == 0;

        public override void Render(PrimCamera cam, List<PrimVert> quads)
        {
            int n = points.Count;
            if (n < 2) return;
            if (tran.Length < n)
            {
                int size = Math.Max(n, tran.Length * 2);
                tran = new LTVec[size];
                bis = new LTVec[size];
                colors = new uint[size];
                us = new float[size];
            }
            for (int i = 0; i < n; i++)
            {
                tran[i] = cam.ToCamera(points[i].Pos);
                colors[i] = points[i].Color;
                us[i] = points[i].U + uOffset;
            }
            Bisectors(tran, n, drawWidth, bis);
            Strip(cam, tran, bis, colors, us, n, false, quads);
        }

        // Its points (tests): place, age and colour.
        public IEnumerable<(LTVec pos, float elapsed, float u, uint color)> Points
        {
            get
            {
                foreach (var p in points) yield return (p.Pos, p.Elapsed, p.U + uOffset, p.Color);
            }
        }
    }
}
