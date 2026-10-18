namespace Tron
{
    // The Null effect as the game plays it (ltjs clientfxdll/nullfx.cpp): an invisible object other keys can be
    // linked to. It starts where it was made with a velocity picked once in MinVelocity-MaxVelocity, moves by it
    // each update and then gains GravityAcceleration on y, per update and not per second (ltjs as written);
    // with Bounce, a move that would hit the world turns the velocity off the surface at 75% of its speed
    // first. Plain C#, no Unity, so tools/tests/test_camera_light_fx.py compiles it with .NET.
    public sealed class FxNull : FxEffect
    {
        readonly ClientFXMgr mgr;
        LTVec position, velocity;
        float gravity;
        bool bounce;

        public FxNull(ClientFXMgr mgr) => this.mgr = mgr;

        float Rand(float lo, float hi) => lo + (hi - lo) * (float)mgr.Random();

        static float Dot(LTVec a, LTVec b) => a.x * b.x + a.y * b.y + a.z * b.z;

        protected override void OnInit()
        {
            var k = Key;
            gravity = k.Num("GravityAcceleration", -500);
            bounce = k.Num("Bounce") != 0;
            LTVec min = k.Vec("MinVelocity", new LTVec(0, 1, 0)), max = k.Vec("MaxVelocity", new LTVec(0, 1, 0));
            velocity = new LTVec(Rand(min.x, max.x), Rand(min.y, max.y), Rand(min.z, max.z));
            position = Pos = CreatePos;
        }

        protected override void OnUpdate(float dt)
        {
            if (bounce && mgr.Intersect != null && mgr.Intersect(position, position + velocity * dt, out _, out var n))
            {
                var l = -velocity;
                var v = n * (2 * Dot(n, l)) - l;
                float len = v.Length();
                if (len > 0) v = v / len;
                velocity = v * (velocity.Length() * 0.75f);
            }
            position = position + velocity * dt;
            velocity.y += gravity;
            Pos = position;
        }
    }
}
