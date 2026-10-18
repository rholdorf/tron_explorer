using System;
using System.Collections.Generic;

namespace Tron
{
    // The LightningFX effect as the game plays it (ltjs clientfxdll/lightningfx.cpp; docs/research/clientfx-types.md
    // on research/clientfx-types), drawn with DrawPrim. MaxNumBolts bolts are made with the effect, each with
    // its own MinSegmentsPerBolt-MaxSegmentsPerBolt points. Its target is its parent (the effect it is
    // linked to, or the SpecialFX object), else itself. Once its delay (MinDelay-MaxDelay, 0 at first) has
    // passed, MinNumBolts-MaxNumBolts of them (the first ones) start again: width MinBoltWidth-MaxBoltWidth,
    // life MinLifetime-MaxLifetime, from where the effect is now to an end point: the target's place, or
    // one of the target's NodeAttractors / SocketAttractors (where it is now; half the time when there is
    // also an OmniDirectionalRadius of 1 or more), or a random point within the radius, cut short where the
    // world is hit. The points step towards the end, each pushed MinPerturb-MaxPerturb sideways in the
    // bolt's up and right; the last is the end. Bolts stay where they were made. Each update the inner
    // points are jittered Pulse along the level's axes (not cumulative); a bolt's Ck and Sk run over its own
    // life (Sk scales its width); it is camera-aligned (Allignment Camera on every key). None start while
    // shutting down; it goes at once then. A bolt to its own place has no length, so its direction isn't a
    // number and nothing of it is drawn (D3D drops those triangles): CHAR_HogEnergySuck's placed objects,
    // whose attractors are a character's nodes, show nothing. Plain C#, no Unity, so
    // tools/tests/test_lightning_fx.py compiles it with .NET.
    public sealed class FxLightning : FxDrawPrim
    {
        sealed class Bolt
        {
            public LTVec[] Path, Drawn, Tran, Bis;
            public uint[] Colors;
            public float Width, Lifetime, Elapsed, Scale = 1;
            public bool Active;
        }

        readonly ClientFXMgr mgr;
        readonly List<Bolt> bolts = new List<Bolt>();
        readonly List<string> nodes = new List<string>(), sockets = new List<string>();
        readonly List<(string name, bool socket)> found = new List<(string, bool)>();
        int minBolts, maxBolts;
        float minWidth, maxWidth, minPerturb, maxPerturb, minLife, maxLife, minDelay, maxDelay, pulse, radius;
        float delay, elapsedEmission;

        public FxLightning(ClientFXMgr mgr) => this.mgr = mgr;

        float Rand(float lo, float hi) => lo + (hi - lo) * (float)mgr.Random();
        int Rand(int lo, int hi) => hi < lo ? lo : lo + (int)(mgr.Random() * (hi - lo + 1));

        // ConParse: commands split by ';', the first word of each.
        static void Names(string s, List<string> into)
        {
            foreach (var part in s.Split(';'))
            {
                var words = part.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                if (words.Length > 0) into.Add(words[0]);
            }
        }

        protected override void OnInit()
        {
            base.OnInit();
            var k = Key;
            minBolts = (int)k.Num("MinNumBolts", 1);
            maxBolts = (int)k.Num("MaxNumBolts", 5);
            int minSegs = (int)k.Num("MinSegmentsPerBolt", 10), maxSegs = (int)k.Num("MaxSegmentsPerBolt", 50);
            minWidth = k.Num("MinBoltWidth", 0.5f);
            maxWidth = k.Num("MaxBoltWidth", 3);
            minPerturb = Math.Abs(k.Num("MinPerturb", 0));
            maxPerturb = Math.Abs(k.Num("MaxPerturb", 35));
            minLife = Math.Abs(k.Num("MinLifetime", 0.1f));
            maxLife = Math.Abs(k.Num("MaxLifetime", 3));
            minDelay = Math.Abs(k.Num("MinDelay", 0));
            maxDelay = Math.Abs(k.Num("MaxDelay", 0.1f));
            pulse = k.Num("Pulse", 0);
            radius = k.Num("OmniDirectionalRadius", 0);
            Names(k.Str("NodeAttractors"), nodes);
            Names(k.Str("SocketAttractors"), sockets);
            for (int i = 0; i < maxBolts; i++)
            {
                int n = Rand(minSegs, maxSegs);
                var b = new Bolt
                {
                    Path = new LTVec[n], Drawn = new LTVec[n], Tran = new LTVec[n], Bis = new LTVec[n], Colors = new uint[n],
                };
                for (int j = 0; j < n; j++) b.Path[j] = b.Drawn[j] = CreatePos;
                bolts.Add(b);
            }
        }

        // The target's attractors that it has now (the engine lists the names its model has at Init).
        void FindAttractors()
        {
            found.Clear();
            if (Parent == null) return;
            foreach (var n in nodes)
                if (Parent.Attachment(n, false, out _, out _)) found.Add((n, false));
            foreach (var s in sockets)
                if (Parent.Attachment(s, true, out _, out _)) found.Add((s, true));
        }

        void EmitBolts(float dt)
        {
            elapsedEmission += dt;
            if (!(delay < elapsedEmission)) return;
            int active = Rand(minBolts, maxBolts);
            FindAttractors();
            bool attractors = found.Count > 0, useRadius = radius >= 1;
            for (int i = 0; i < bolts.Count && i < active; i++)
            {
                var b = bolts[i];
                b.Width = Rand(minWidth, maxWidth);
                b.Lifetime = Rand(minLife, maxLife);
                b.Elapsed = 0;
                b.Active = true;
                var end = Parent != null ? Parent.Pos : Pos;
                if (attractors && (!useRadius || Rand(0, 1) != 0))
                {
                    var (name, socket) = found[Rand(0, found.Count - 1)];
                    if (Parent.Attachment(name, socket, out var ap, out _)) end = ap;
                }
                else if (useRadius)
                {
                    var r = new LTVec(Rand(-1f, 1f), Rand(-1f, 1f), Rand(-1f, 1f));
                    r = r / r.Length() * Rand(-radius, radius);
                    end = Pos + r;
                    if (mgr.Intersect != null && mgr.Intersect(Pos, end, out var hit, out _)) end = hit;
                }
                var p = Pos;
                var dir = end - p;
                float step = dir.Length() / b.Path.Length;
                float perturb = Rand(minPerturb, maxPerturb);
                dir = dir / dir.Length();
                var rot = LTQuat.FromForwardUp(dir, new LTVec(0, 1, 0));
                LTVec f = rot.Forward(), u = rot.Up(), rt = rot.Right();
                for (int j = 0; j < b.Path.Length; j++)
                {
                    b.Path[j] = p;
                    p += f * step;
                    p += u * Rand(-perturb, perturb);
                    p += rt * Rand(-perturb, perturb);
                    if (j == b.Path.Length - 1) b.Path[j] = end;
                }
            }
            elapsedEmission = 0;
            delay = Rand(minDelay, maxDelay);
        }

        protected override void OnUpdate(float dt)
        {
            if (!ShuttingDown) EmitBolts(dt);
            foreach (var b in bolts)
            {
                b.Elapsed += dt;
                if (b.Lifetime < b.Elapsed) b.Active = false;
            }
            // PreRender: the jitter, the bolt's colour and width from its keys over its life.
            foreach (var b in bolts)
            {
                if (b.Path.Length < 2 || !b.Active) continue;
                int n = b.Path.Length;
                if (dt > 0.001f)
                    for (int j = 0; j < n; j++)
                    {
                        var v = b.Path[j];
                        v += new LTVec(0, 0, 1) * Rand(-pulse, pulse);
                        v += new LTVec(0, 1, 0) * Rand(-pulse, pulse);
                        v += new LTVec(1, 0, 0) * Rand(-pulse, pulse);
                        b.Drawn[j] = j == 0 || j == n - 1 ? b.Path[j] : v;
                    }
                float t = b.Lifetime > 0 ? (float)(b.Elapsed / b.Lifetime % 1.0) : 0;
                float scale = 1, r = 1, g = 1, bl = 1, a = 1;
                KeyScale(Key.Sk, t, ref scale);
                KeyColour(Key.Ck, t, ref r, ref g, ref bl, ref a);
                uint c = Color(r, g, bl, a);
                for (int j = 0; j < n; j++) b.Colors[j] = c;
                b.Scale = scale;
            }
        }

        public override void Render(PrimCamera cam, List<PrimVert> quads)
        {
            foreach (var b in bolts)
            {
                if (!b.Active || b.Path.Length < 2) continue;
                int n = b.Path.Length;
                for (int j = 0; j < n; j++) b.Tran[j] = cam.ToCamera(b.Drawn[j]);
                Bisectors(b.Tran, n, b.Width * b.Scale, b.Bis);
                Strip(cam, b.Tran, b.Bis, b.Colors, null, n, true, quads);
            }
        }

        // Bolts drawn now (tests).
        public int ActiveBolts => bolts.FindAll(b => b.Active).Count;
        public IEnumerable<LTVec[]> ActivePaths
        {
            get
            {
                foreach (var b in bolts)
                    if (b.Active) yield return b.Drawn;
            }
        }
    }
}
