using System;

namespace Tron
{
    // An OT_SPRITE as the engine draws it: its .spr (or .dtx) file, place, rotation and scale, colour (0-1,
    // already lit when the sprite takes light), blend and flags, and the client time its animation started.
    public sealed class LTSprite
    {
        public const int BlendNone = 0, BlendAdditive = 1, BlendMultiply = 2;

        public string File = "";
        public LTVec Pos;
        public LTQuat Rot = new LTQuat(0, 0, 0, 1);
        public float ScaleX = 1, ScaleY = 1;
        public float R = 1, G = 1, B = 1, A = 1;
        public int Blend;
        public bool Rotatable;   // FLAG_ROTATEABLESPRITE: a quad in its own right/up axes
        public bool Glow;        // FLAG_GLOWSPRITE: billboards grow with view depth (not the screen glow)
        public bool ZBias;       // FLAG_SPRITEBIAS: pulled 20 units toward the camera
        public bool Shown;       // FLAG_VISIBLE
        public bool Fog;         // not FLAG_FOGDISABLE: fogged (additive to black, multiply to white)
        // When its frames started (s, the drawer's clock): NaN starts them at the next draw (a new file,
        // SetCurPos(0, 0)).
        public double Born = double.NaN;
    }

    // The engine's sprite drawing (ltjs render_a d3d/drawsprite.cpp d3d_DrawSprite, d3d_DrawRotatableSprite)
    // and frame tracker (client/sprite.cpp spr_UpdateTracker). Plain C#, no Unity, so
    // tools/tests/test_sprites.py compiles it with .NET.
    public static class SpriteMath
    {
        public const float NearZ = 7;            // 3d_ops.h NEARZ
        const float BiasDist = -20;              // SPRITE_POSITION_ZBIAS
        const float MinFactorDist = 10, MaxFactorDist = 500, MinFactor = 0.1f, MaxFactor = 2;

        static float Dot(LTVec a, LTVec b) => a.x * b.x + a.y * b.y + a.z * b.z;

        // The quad's corners, in the order the engine fans them (UVs 0,0 1,0 1,1 0,1): from the texture's
        // size in texels times the scale on each side of the centre. A billboard faces the camera (right
        // and up are the camera's) and isn't drawn nearer than NearZ; a glow sprite's size is scaled by
        // 0.1-2 between 10 and 500 units of depth. A rotatable sprite lies in its rotation's right/up axes
        // and is never culled here. Z bias moves each corner 20 units toward the camera along the view axis
        // (no nearer than NearZ), scaled about the view axis so its size on screen stays the same: a
        // billboard by its centre's depth, a rotatable sprite corner by corner (corners at NearZ or nearer
        // stay). False when it isn't drawn.
        public static bool Corners(LTSprite s, float texW, float texH, LTVec camPos, LTVec camRight, LTVec camUp,
            LTVec camFwd, LTVec[] corners)
        {
            LTVec right, up;
            float z = Dot(s.Pos - camPos, camFwd);
            if (s.Rotatable)
            {
                right = s.Rot.Right() * (texW * s.ScaleX);
                up = s.Rot.Up() * (texH * s.ScaleY);
            }
            else
            {
                if (z < NearZ) return false;
                float sx = texW * s.ScaleX, sy = texH * s.ScaleY;
                if (s.Glow)
                {
                    float f = Math.Max(0, Math.Min(1, (z - MinFactorDist) / (MaxFactorDist - MinFactorDist)));
                    f = MinFactor + (MaxFactor - MinFactor) * f;
                    sx *= f;
                    sy *= f;
                }
                right = camRight * sx;
                up = camUp * sy;
            }
            corners[0] = s.Pos + up - right;
            corners[1] = s.Pos + up + right;
            corners[2] = s.Pos + right - up;
            corners[3] = s.Pos - right - up;
            if (!s.ZBias) return true;
            for (int i = 0; i < 4; i++)
            {
                var rel = corners[i] - camPos;
                float cz = s.Rotatable ? Dot(rel, camFwd) : z;
                if (s.Rotatable && cz <= NearZ) continue;
                float bias = cz + BiasDist < NearZ ? NearZ - cz : BiasDist;
                float scale = 1 + bias / cz;
                corners[i] = camRight * (Dot(rel, camRight) * scale) + camUp * (Dot(rel, camUp) * scale) +
                             camFwd * (cz + bias) + camPos;
            }
            return true;
        }

        // spr_UpdateTracker: whole milliseconds since it started, each frame 1000 / rate ms (integer division)
        // long, looping. A rate under 1 stays on the first frame.
        public static int Frame(double seconds, int rate, int frames)
        {
            if (frames < 2 || rate < 1) return 0;
            int period = 1000 / rate;
            if (period <= 0) return 0;
            long ms = (long)(seconds * 1000);
            return (int)(ms / period % frames);
        }

        // CLensFlareFX::Update for a sprite-only flare: the angle is the camera's (cos of the angle to the
        // flare, clamped at 0, times 90: not degrees), the flare shows from 90 - minAngle and grows from its
        // min to its max alpha and scale as the angle reaches 90; it sits at the object plus its forward
        // times offset. False when it isn't shown.
        public static bool Flare(LTVec objPos, LTVec objForward, LTVec camPos, LTVec camFwd, float minAngle,
            float minAlpha, float maxAlpha, float minScale, float maxScale, float offset,
            out LTVec pos, out float alpha, out float scale)
        {
            var dir = objPos - camPos;
            float len = dir.Length();
            dir = len > 0 ? dir / len : dir;
            float angle = Math.Max(0, Dot(dir, camFwd)) * 90;
            pos = objPos + objForward * offset;
            alpha = minAlpha;
            scale = minScale;
            if (angle < 90 - minAngle) return false;
            float v = (angle + minAngle - 90) / minAngle;
            alpha = minAlpha + v * (maxAlpha - minAlpha);
            scale = minScale + v * (maxScale - minScale);
            return true;
        }
    }
}
