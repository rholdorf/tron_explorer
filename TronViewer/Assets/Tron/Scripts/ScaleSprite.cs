using System;

namespace Tron
{
    // A ScaleSprite object (ltjs objectdll scalesprite.cpp; docs/research/clientfx-types.md on
    // research/clientfx-types): one sprite from Filename, scaled ScaleX/ScaleY, coloured Color/255 with Alpha
    // and lit (it isn't FLAG_NOLIGHT: the light at its place adds, clamped); Additive or Multiply (both
    // unfogged), Rotatable or FlushWithWorld (rotatable), Glow, ZBias. StartOn shows it. Its own messages:
    //   ON / OFF set FLAG_VISIBLE (the same flag HIDDEN / VISIBLE set, through GameBaseFlags);
    //   DAMAGE swaps to DamagedFilename (when set); DESTROY to DestroyedFilename, or removes the object.
    // Everything else is GameBase's. CreateSprite adds the client lens flare (lensflarefx.cpp, SpriteOnly):
    // a full-bright, Z-biased SpriteFile sprite at the object plus forward x SpriteOffset that shows while the
    // object is visible and the camera looks within MinAngle of it, growing to MaxSpriteScale.
    // FlushWithWorld (never set in the levels) isn't placed against the world. Plain C#, no Unity, so
    // tools/tests/test_scale_sprite.py compiles it with .NET.
    public sealed class ScaleSprite
    {
        public readonly LTSprite Sprite = new LTSprite();
        public readonly LTSprite Flare;   // null without CreateSprite
        public readonly GameBaseFlags Flags;
        readonly string damaged, destroyed;
        readonly float minAngle, minAlpha, maxAlpha, minScale, maxScale, offset;
        // The object leaves the level (its GameBase REMOVE).
        public Action RemoveObject;

        public struct Props
        {
            public string File, Damaged, Destroyed, FlareFile;
            public float ScaleX, ScaleY, Alpha, MinAngle, MinAlpha, MaxAlpha, MinScale, MaxScale, Offset;
            public LTVec Color;   // 0-255
            public bool Additive, Multiply, Rotatable, FlushWithWorld, Glow, ZBias, StartOn, CreateSprite, FlareAdditive;
        }

        // light: the light at its place (0-255, the world light table), added to its colour. flags: its
        // GameBase flags, made visible when StartOn.
        public ScaleSprite(Props p, LTVec pos, LTQuat rot, LTVec light, GameBaseFlags flags)
        {
            var s = Sprite;
            s.File = p.File ?? "";
            s.Pos = pos;
            s.Rot = rot;
            s.ScaleX = p.ScaleX;
            s.ScaleY = p.ScaleY;
            s.R = Lit(p.Color.x, light.x);
            s.G = Lit(p.Color.y, light.y);
            s.B = Lit(p.Color.z, light.z);
            s.A = p.Alpha;
            s.Blend = p.Additive ? LTSprite.BlendAdditive : p.Multiply ? LTSprite.BlendMultiply : LTSprite.BlendNone;
            s.Rotatable = p.Rotatable || p.FlushWithWorld;
            s.Glow = p.Glow;
            s.ZBias = p.ZBias;
            damaged = p.Damaged ?? "";
            destroyed = p.Destroyed ?? "";
            Flags = flags;
            s.Shown = flags.Visible && !flags.Removed;
            Flags.Changed += () => Sprite.Shown = Flags.Visible && !Flags.Removed;
            Flags.Remove += () => Sprite.Shown = false;
            if (p.CreateSprite && !string.IsNullOrEmpty(p.FlareFile))
            {
                Flare = new LTSprite
                {
                    File = p.FlareFile, Pos = pos, ZBias = true,
                    Blend = p.FlareAdditive ? LTSprite.BlendAdditive : LTSprite.BlendNone,
                };
                minAngle = p.MinAngle;
                minAlpha = p.MinAlpha;
                maxAlpha = p.MaxAlpha;
                minScale = p.MinScale;
                maxScale = p.MaxScale;
                offset = p.Offset;
            }
        }

        // The vertex colour of a lit sprite (d3d_GetSpriteColor): colour + light, clamped to 0-255.
        static float Lit(float color, float light) => Math.Max(0, Math.Min(255, color + light)) / 255f;

        public bool OnMessage(Message m)
        {
            if (Flags.Removed) return false;
            if (m.Is("DESTROY"))
            {
                if (destroyed != "") Swap(destroyed);
                else RemoveObject?.Invoke();
            }
            else if (m.Is("DAMAGE"))
            {
                if (damaged != "") Swap(damaged);
            }
            else if (m.Is("ON")) Flags.SetVisible(true);
            else if (m.Is("OFF")) Flags.SetVisible(false);
            else return false;
            return true;
        }

        // SetObjectFilenames: a new file, its frames from the start.
        void Swap(string file)
        {
            Sprite.File = file;
            Sprite.Born = double.NaN;
        }

        // Each frame, with the object where it is now and the camera.
        public void Update(LTVec pos, LTQuat rot, LTVec camPos, LTVec camFwd)
        {
            Sprite.Pos = pos;
            Sprite.Rot = rot;
            if (Flare == null) return;
            bool on = SpriteMath.Flare(pos, rot.Forward(), camPos, camFwd, minAngle, minAlpha, maxAlpha, minScale,
                maxScale, offset, out var fp, out float a, out float sc);
            Flare.Shown = Sprite.Shown && on;
            Flare.Pos = fp;
            Flare.A = a;
            Flare.ScaleX = Flare.ScaleY = sc;
        }
    }
}
