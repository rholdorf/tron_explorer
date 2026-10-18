namespace Tron
{
    // The LTBBouncyChunk effect as the game plays it (ltjs clientfxdll/ltbbouncychunkfx.cpp; docs/research/
    // clientfx-types.md on research/clientfx-types): a full-bright model (FLAG_NOLIGHT) made with the effect
    // at the parent's place plus Offset (unrotated), with the parent's rotation, which it keeps, and its
    // scale from Sk at 0. It is its own object, made visible, so the instance's showing and hiding never
    // reach it: it stands from the instance's start until the effect goes, before its start time too. Its
    // launch is ChunkDir at ChunkSpeed tilted by up to ChunkSpread (whole numbers, rand() % 2S) about two
    // axes across it; each update it moves by its velocity, then gravity (Gravity normalized, times Amount)
    // adds to the velocity, and a hit on the world puts it on the hit plus the normal with the velocity
    // reflected at 70%. Ck colours it, Sk scales it. RotateAdd isn't read (no tumbling) and ChunkSound is
    // "..." on every key the levels reach, so it plays no impact sound. Pos is where the chunk is: effects
    // linked to it follow it. Plain C#, no Unity, so tools/tests/test_bouncy_chunk_fx.py compiles it with .NET.
    public sealed class FxChunk : FxEffect, IFxModelView
    {
        readonly ClientFXMgr mgr;
        LTVec vel, gravity;

        public LTVec ChunkPos { get; private set; }
        public LTQuat ChunkRot { get; private set; }
        public LTVec Velocity => vel;

        public FxChunk(ClientFXMgr mgr) => this.mgr = mgr;

        protected override void OnInit()
        {
            var k = Key;
            ChunkPos = CreatePos + k.Offset;
            ChunkRot = CreateRot;
            KeyScale(k.Sk, 0, ref Scale);
            var dir = Norm(k.Vec("ChunkDir", new LTVec(0, 1, 0)));
            gravity = Norm(k.Vec("Gravity", new LTVec(0, -1, 0))) * k.Num("Amount", 10);
            float speed = k.Num("ChunkSpeed", 40), spread = k.Num("ChunkSpread", 40);
            var right = dir.Cross(Norm(new LTVec(1, 0, 1)));
            var up = right.Cross(Norm(new LTVec(1, 0, 1)));
            vel = right * Tilt(spread) + up * Tilt(spread) + dir * speed;
            float len = vel.Length();
            vel = len > 0 ? vel * (speed / len) : vel;
        }

        // -S + rand() % (int)(2S): a whole number in [-S, S).
        float Tilt(float spread)
        {
            int n = (int)(spread * 2);
            return -spread + (n > 0 ? (int)(mgr.Random() * n) : 0);
        }

        protected override void OnUpdate(float dt)
        {
            var cur = ChunkPos;
            var next = cur + vel * dt;
            vel += gravity * dt;
            if (mgr.Intersect != null && mgr.Intersect(cur, next, out var point, out var normal))
            {
                next = point + normal;
                var l = -vel;
                var r = Norm(normal * (2 * Dot(normal, l)) - l);
                vel = r * (vel.Length() * 0.7f);
            }
            ChunkPos = next;
            Pos = next;
        }

        static float Dot(LTVec a, LTVec b) => a.x * b.x + a.y * b.y + a.z * b.z;

        static LTVec Norm(LTVec v)
        {
            float l = v.Length();
            return l > 0 ? v / l : v;
        }

        FxEffect IFxModelView.Effect => this;
        bool IFxModelView.Shown => true;
        LTVec IFxModelView.ModelPos => ChunkPos;
        LTQuat IFxModelView.ModelRot => ChunkRot;
        float IFxModelView.AnimTime => 0;
        bool IFxModelView.NoLight => true;
        FxModel.NodeTransform IFxModelView.Nodes { set { } }
    }
}
