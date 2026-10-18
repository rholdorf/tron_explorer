using System;

namespace Tron
{
    // The DynaLight effect as the game plays it (ltjs clientfxdll/dynalightfx.cpp): an engine dynamic light where
    // the effect is, its colour the key's Ck colour times its alpha (with Flicker, first times 0.3-0.49 anew each
    // update), clamped to 0-1, its radius the key's Sk scale; shutting down, radius 0. Tron leaves
    // DynamicLightWorld at 0 (autoexec.cfg doesn't set it) and no key sets ForceLightWorld, so it lights models
    // and lit sprites, never the world (d3d_ProcessLight). Shown while the effect is: a hidden light lights
    // nothing. Plain C#, no Unity, so tools/tests/test_camera_light_fx.py compiles it with .NET; ModelLighting
    // and the sprites read it.
    public sealed class FxDynaLight : FxEffect
    {
        readonly ClientFXMgr mgr;
        bool flicker;

        // The light's colour (0-255, as SetLightColor stores it in bytes) and radius.
        public LTVec Color { get; private set; }
        public float Radius { get; private set; }

        public FxDynaLight(ClientFXMgr mgr) => this.mgr = mgr;

        // Flicker is an integer prop (200 on the one key the levels reach), on when not 0.
        protected override void OnInit() => flicker = Key.Num("Flicker") != 0;

        protected override void OnUpdate(float dt)
        {
            if (ShuttingDown)
            {
                Radius = 0;
                return;
            }
            float r = R, g = G, b = B;
            if (flicker)
            {
                float f = 0.3f + 0.19f * (float)mgr.Random();
                r *= f;
                g *= f;
                b *= f;
            }
            Color = new LTVec(Byte(r * A), Byte(g * A), Byte(b * A));
            Radius = Scale;
        }

        static float Byte(float c) => (int)(Math.Max(0, Math.Min(1, c)) * 255);

        // What a model gets from a dynamic light (setupmodel.cpp: a D3D point light, attenuation 1, 0,
        // 19 / radius^2, range radius): its colour at a point, nothing at the radius or beyond (GetLightSample).
        public static LTVec Sample(LTVec light, float radius, LTVec color, LTVec at)
        {
            var d = at - light;
            float d2 = d.x * d.x + d.y * d.y + d.z * d.z;
            if (d2 >= radius * radius) return default;
            return color * (1 / (1 + 19 * d2 / (radius * radius)));
        }

        // What a lit sprite gets from a dynamic light (3d_ops.cpp d3d_CalcLightAdd): each channel c becomes
        // 2c - 255 (a dim light darkens) times 0.7 x (1 - distance / radius), within the radius.
        public static LTVec SpriteAdd(LTVec light, float radius, LTVec color, LTVec at)
        {
            float d = LTVec.Dist(light, at);
            if (d * d >= radius * radius) return default;
            float f = (1 - d / radius) * 0.7f;
            return new LTVec((2 * color.x - 255) * f, (2 * color.y - 255) * f, (2 * color.z - 255) * f);
        }
    }
}
