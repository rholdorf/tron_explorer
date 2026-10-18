using System;

namespace Tron
{
    // The Sprite effect as the game plays it (ltjs clientfxdll/spritefx.cpp; docs/research/clientfx-types.md
    // on research/clientfx-types): one sprite object from Sprite, created at its parent's rotation turned to
    // Normal (offset in those axes), then placed by the base rules each update. CameraFacing without RotateAdd
    // is a billboard; any other facing, or a RotateAdd, makes it rotatable: ParentAlign keeps the parent's
    // rotation turned to Normal, AlongNormal what the base gives (the parent's), and RotateAdd (degrees per
    // second) builds a spin on the camera's rotation (CameraFacing) or the object's. BlendMode Additive or
    // Multiply (FLAG_NOLIGHT with it), DisableLight, ZBias. Ck is its colour, Sk its size. Its .spr starts over
    // on each initial frame and loops. Fogged as the engine fogs it (it isn't FLAG_FOGDISABLE). Shutting down
    // clears every object flag at once: it disappears, and a looping instance that starts it again only sets
    // FLAG_VISIBLE back, so from then on it is lit by the light grid, unbiased and a billboard (ltjs as
    // written; only m06-02's looped groups have keys that shut down and restart). DisableZ and CastVisibleRay
    // are never set in the levels and aren't read. Plain C#, no Unity, so tools/tests/test_sprite_fx.py
    // compiles it with .NET.
    public sealed class FxSprite : FxEffect
    {
        public const int CameraFacing = 0, AlongNormal = 1, ParentAlign = 2;

        public readonly LTSprite Sprite = new LTSprite { Fog = true };
        readonly ClientFXMgr mgr;
        // The light grid's light at a place (0-255), for a sprite that takes light; none: no light.
        readonly Func<LTVec, LTVec> lightAt;
        int facing;
        bool rotate, noLight, zBias, rotatable, visibleFlag;
        LTQuat normalRot, spin = new LTQuat(0, 0, 0, 1);

        public FxSprite(ClientFXMgr mgr, Func<LTVec, LTVec> lightAt = null)
        {
            this.mgr = mgr;
            this.lightAt = lightAt;
        }

        protected override void OnInit()
        {
            var k = Key;
            facing = (int)k.Num("Facing", 0);
            rotate = k.RotateAdd.x != 0 || k.RotateAdd.y != 0 || k.RotateAdd.z != 0;
            // ParseProperties: a zero normal is the z axis.
            var n = k.Vec("Normal", new LTVec(0, 0, 1));
            n = n.Length() * n.Length() > 1e-6f ? n / n.Length() : new LTVec(0, 0, 1);
            var r = n.y == 1 || n.y == -1 ? new LTVec(1, 0, 0).Cross(n) : new LTVec(0, 1, 0).Cross(n);
            normalRot = LTQuat.FromForwardUp(n, n.Cross(r));
            Rot = CreateRot * normalRot;
            Pos = CreatePos + Rot.Rotate(k.Offset);
            if (facing == CameraFacing) normalRot = new LTQuat(0, 0, 0, 1);
            int blend = (int)k.Num("BlendMode");
            Sprite.Blend = blend == 1 ? LTSprite.BlendAdditive : blend == 2 ? LTSprite.BlendMultiply : LTSprite.BlendNone;
            noLight = blend == 1 || blend == 2 || k.Num("DisableLight") != 0;
            zBias = k.Num("ZBias") != 0;
            rotatable = facing != CameraFacing || rotate;
            Sprite.File = k.Str("Sprite");
            Sync();
        }

        protected override void OnBeginUpdate()
        {
            if (ShuttingDown)
            {
                // SetObjectFlags(OFT_Flags, 0, FLAGMASK_ALL): FLAG2_ADDITIVE / MULTIPLY are Flags2 and stay.
                visibleFlag = noLight = zBias = rotatable = false;
                Sprite.Shown = false;
            }
            else if (InitialFrame) Sprite.Born = double.NaN;   // SetCurPos(0, 0)
        }

        protected override void OnUpdate(float dt)
        {
            if (Parent != null && facing == ParentAlign) Rot = rotate ? Parent.Rot : Parent.Rot * normalRot;
            if (rotate)
            {
                LTVec r = spin.Right(), u = spin.Up(), f = spin.Forward();
                var basis = facing == CameraFacing ? mgr.CameraRot : Rot;
                const float rad = (float)(Math.PI / 180);
                spin = LTQuat.AxisAngle(r, Key.RotateAdd.x * dt * rad) * spin;
                spin = LTQuat.AxisAngle(u, Key.RotateAdd.y * dt * rad) * spin;
                spin = LTQuat.AxisAngle(f, Key.RotateAdd.z * dt * rad) * spin;
                Rot = basis * spin * normalRot;
            }
            Sync();
        }

        // SetVisible: FLAG_VISIBLE only.
        protected override void OnVisible(bool shown)
        {
            visibleFlag = shown;
            Sprite.Shown = shown;
        }

        // The object as the base and the type left it: place, rotation, scale, colour (with the light at its
        // place added, clamped, when it takes light: d3d_GetSpriteColor) and flags.
        void Sync()
        {
            var s = Sprite;
            s.Pos = Pos;
            s.Rot = Rot;
            s.ScaleX = s.ScaleY = Scale;
            s.A = A;
            if (noLight || lightAt == null)
            {
                s.R = R;
                s.G = G;
                s.B = B;
            }
            else
            {
                var l = lightAt(Pos);
                s.R = Lit(R, l.x);
                s.G = Lit(G, l.y);
                s.B = Lit(B, l.z);
            }
            s.Rotatable = rotatable;
            s.ZBias = zBias;
            s.Shown = visibleFlag;
        }

        static float Lit(float color, float light) => Math.Max(0, Math.Min(255, color * 255 + light)) / 255f;
    }
}
