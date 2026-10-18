namespace Tron
{
    // The CamJitter effect as the game plays it (ltjs clientfxdll/camjitterfx.cpp): each update, unless shutting
    // down, the camera moves by a random amount in -1..1 on each of the level's axes times the key's Sk scale
    // times a falloff: 1 within InnerRadius of its parent (or where it was made, without one), down to 0 at
    // OuterRadius (by squared distance), nothing beyond. The camera it measures from is where it is by then
    // (other jitters this update included). The player camera puts the camera back every frame, so the shake
    // is the sum of this frame's moves (ClientFXMgr.CameraOffset; CameraJitter applies it to the view). Plain
    // C#, no Unity, so tools/tests/test_camera_light_fx.py compiles it with .NET.
    public sealed class FxCamJitter : FxEffect
    {
        readonly ClientFXMgr mgr;
        float inner2, outer2;

        public FxCamJitter(ClientFXMgr mgr) => this.mgr = mgr;

        float Rand() => (float)(mgr.Random() * 2 - 1);

        // CCamJitterProps::ParseProperties: the outer radius is always beyond the inner one.
        protected override void OnInit()
        {
            float inner = Key.Num("InnerRadius", 500), outer = Key.Num("OuterRadius", 600);
            inner2 = inner * inner;
            outer2 = outer * outer;
            if (inner2 >= outer2) outer2 = inner2 + 1;
        }

        protected override void OnUpdate(float dt)
        {
            if (ShuttingDown) return;
            var cam = mgr.Camera + mgr.CameraOffset;
            var d = (Parent != null ? Parent.Pos : CreatePos) - cam;
            float d2 = d.x * d.x + d.y * d.y + d.z * d.z;
            if (d2 > outer2) return;
            float falloff = d2 <= inner2 ? 1 : 1 - (d2 - inner2) / (outer2 - inner2);
            float x = Rand() * Scale * falloff, y = Rand() * Scale * falloff, z = Rand() * Scale * falloff;
            mgr.CameraOffset = mgr.CameraOffset + new LTVec(x, y, z);
        }
    }
}
