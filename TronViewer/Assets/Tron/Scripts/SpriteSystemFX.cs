using System;
using System.Collections.Generic;

namespace Tron
{
    // The SpriteSystem effect as the game plays it (ltjs clientfxdll/spritesystemfx.cpp), drawn with DrawPrim: a
    // burst of SpritesPerEmission sprites on its initial frame and every EmissionInterval (none while shutting
    // down, none whose sprites would all be dead), placed by EmissionType about where the effect is (the offset
    // in the level's axes, as the particle systems'), velocity MinSpriteVelocity-MaxSpriteVelocity turned with
    // the effect, life MinSpriteLifespan-MaxSpriteLifespan (InfiniteLife: they start over), each turning by
    // its MinSpriteRotation-MaxSpriteRotation (degrees, per second). Each update they move, then gain
    // GravityAcceleration on y. Drawn in camera space: a quad per sprite in front of the camera, half-width
    // Sk scale x StretchU, half-height scale x texture height / width x StretchV, turned by its rotation about
    // its centre, Ck over its own life; a RotateAdd spins all of them about the effect. AType Add is
    // MUL_SRCALPHA_ONE, Norm MOD_SRCALPHA; no alpha test, Z read only, no fog. The .spr frame comes from the
    // sprite's age over AnimationLength (the sprite file's length, the sprite's life or the key's, over
    // AnimationSpeed). Plain C#, no Unity, so tools/tests/test_sprite_system_fx.py compiles it with .NET.
    public sealed class FxSpriteSystem : FxDrawPrim
    {
        const int Sphere = 0, Point = 1, Circle = 2, Cone = 3, Cylinder = 4;
        const int AnimSprite = 0, AnimParticle = 1, AnimKey = 2;

        // A sprite file's frame count, its length (ms) and its first frame's size in texels.
        public struct SpriteFile
        {
            public int Frames, LengthMs, Width, Height;
        }

        struct Sprite
        {
            public float Elapsed, Lifespan;
            public LTVec Pos, Vel, RotAdd;
            public LTQuat Rot;
        }

        readonly ClientFXMgr mgr;
        readonly Func<string, SpriteFile> files;
        readonly List<Sprite> sprites = new List<Sprite>();
        readonly List<int> frames = new List<int>();
        SpriteFile file;
        int type, perEmission, animType;
        bool infiniteLife, spin;
        float interval, gravity, minLife, maxLife, minRadius, maxRadius, stretchU, stretchV, animSpeed, spriteLen;
        LTVec plane, perp1, perp2, minVel, maxVel, minRot, maxRot, randomPoint;
        LTQuat spinRot = new LTQuat(0, 0, 0, 1);
        float elapsedEmission;

        public int Count => sprites.Count;

        // files: what a sprite file is (null: one frame of 1 x 1).
        public FxSpriteSystem(ClientFXMgr mgr, Func<string, SpriteFile> files = null)
        {
            this.mgr = mgr;
            this.files = files;
        }

        float Rand(float lo, float hi) => lo + (hi - lo) * (float)mgr.Random();

        static LTVec Norm(LTVec v)
        {
            float l = v.Length();
            return l > 0 ? v / l : v;
        }

        static LTVec Deg(LTVec v) => v * ((float)Math.PI / 180);

        // CSpriteSystemProps::ParseProperties and CSpriteSystem::Init.
        protected override void OnInit()
        {
            var k = Key;
            Texture = k.Str("Sprite");
            BlendMode = k.Num("AType") != 0 ? MulSrcAlphaOne : ModSrcAlpha;
            perEmission = (int)k.Num("SpritesPerEmission", 5);
            interval = k.Num("EmissionInterval", 0.01f);
            minRot = Deg(k.Vec("MinSpriteRotation", new LTVec(0, 1, 0)));
            maxRot = Deg(k.Vec("MaxSpriteRotation", new LTVec(0, 1, 0)));
            gravity = k.Num("GravityAcceleration", -500);
            minLife = k.Num("MinSpriteLifespan", 1);
            maxLife = k.Num("MaxSpriteLifespan", 2);
            minRadius = k.Num("MinRadius");
            maxRadius = k.Num("MaxRadius", 10);
            plane = Norm(k.Vec("EmissionPlane", new LTVec(0, 1, 0)));
            perp1 = (plane.y == 1 || plane.y == -1 ? new LTVec(1, 0, 0) : new LTVec(0, 1, 0)).Cross(plane);
            perp2 = perp1.Cross(plane);
            minVel = k.Vec("MinSpriteVelocity", new LTVec(0, 1, 0));
            maxVel = k.Vec("MaxSpriteVelocity", new LTVec(0, 1, 0));
            type = (int)k.Num("EmissionType");
            stretchU = k.Num("StretchU", 1);
            stretchV = k.Num("StretchV", 1);
            animType = (int)k.Num("AnimationLength");
            animSpeed = Math.Max(k.Num("AnimationSpeed", 1), 0.001f);
            infiniteLife = k.Num("InfiniteLife") != 0;
            var r = k.RotateAdd;
            spin = r.x != 0 || r.y != 0 || r.z != 0;
            file = files != null ? files(Texture) : new SpriteFile { Frames = 1, Width = 1, Height = 1 };
            // m_fSpriteLen: frames / (length / frames), as written.
            spriteLen = file.Frames > 0 && file.LengthMs > 0 ? file.Frames / ((float)file.LengthMs / file.Frames) : 0;
            if (type == Point) randomPoint = Norm(perp1 * Rand(-1, 1) + perp2 * Rand(-1, 1)) * Rand(minRadius, maxRadius);
        }

        // CSpriteSystem::Update, after the base.
        protected override void OnUpdate(float dt)
        {
            elapsedEmission += dt;
            if (!ShuttingDown)
            {
                if (InitialFrame)
                {
                    AddSprites();
                    elapsedEmission = 0;
                }
                if (interval > 0)
                {
                    while (elapsedEmission >= interval)
                    {
                        if (elapsedEmission >= maxLife)
                        {
                            elapsedEmission -= interval;
                            continue;
                        }
                        AddSprites();
                        elapsedEmission -= interval;
                        if (elapsedEmission >= interval)
                        {
                            UpdateSprites(interval);
                            dt -= interval;
                        }
                    }
                }
            }
            UpdateSprites(dt);
        }

        public override bool IsFinishedShuttingDown => sprites.Count == 0;
        public override bool IsVisibleWhileSuspended => sprites.Count != 0;
        public override void SuspendedUpdate(float dt) => UpdateSprites(dt);

        void AddSprites()
        {
            for (int i = 0; i < perEmission; i++)
            {
                LTVec pos;
                switch (type)
                {
                    case Sphere:
                        pos = Norm(new LTVec(Rand(-1, 1), Rand(-1, 1), Rand(-1, 1))) * Rand(minRadius, maxRadius);
                        break;
                    case Point:
                        pos = randomPoint;
                        break;
                    case Circle:
                        pos = Norm(perp1 * Rand(-1, 1) + perp2 * Rand(-1, 1)) * Rand(minRadius, maxRadius);
                        break;
                    case Cone:
                    {
                        float f = Rand(0, (float)Math.Sqrt(maxRadius));
                        float offset = maxRadius - f * f;
                        pos = Norm(perp1 * Rand(-1, 1) + perp2 * Rand(-1, 1));
                        pos = pos * Rand(0, minRadius * offset / maxRadius) + plane * offset;
                        break;
                    }
                    case Cylinder:
                        pos = Norm(perp1 * Rand(-1, 1) + perp2 * Rand(-1, 1)) * Rand(0, minRadius);
                        pos = pos + plane * Rand(0, maxRadius);
                        break;
                    default:
                        return;
                }
                var vel = Rot.Rotate(new LTVec(Rand(minVel.x, maxVel.x), Rand(minVel.y, maxVel.y), Rand(minVel.z, maxVel.z)));
                var rotAdd = new LTVec(Rand(minRot.x, maxRot.x), Rand(minRot.y, maxRot.y), Rand(minRot.z, maxRot.z));
                sprites.Add(new Sprite
                {
                    Pos = pos + Pos,
                    Vel = vel,
                    RotAdd = rotAdd,
                    Rot = LTQuat.FromEuler(rotAdd.x, rotAdd.y, rotAdd.z),
                    Lifespan = Rand(minLife, maxLife),
                });
            }
        }

        // UpdateSprites: the dead go (swap-removed, as CSwapList::Free), the rest move.
        void UpdateSprites(float dt)
        {
            if (dt < 0.0001f) return;
            if (spin)
            {
                const float rad = (float)Math.PI / 180;
                var r = Key.RotateAdd;
                spinRot = LTQuat.AxisAngle(spinRot.Right(), r.x * dt * rad) * spinRot;
                spinRot = LTQuat.AxisAngle(spinRot.Up(), r.y * dt * rad) * spinRot;
                spinRot = LTQuat.AxisAngle(spinRot.Forward(), r.z * dt * rad) * spinRot;
            }
            for (int i = 0; i < sprites.Count; i++)
            {
                var s = sprites[i];
                s.Elapsed += dt;
                if (s.Elapsed >= s.Lifespan)
                {
                    if (infiniteLife) s.Elapsed %= s.Lifespan;
                    else
                    {
                        sprites[i] = sprites[sprites.Count - 1];
                        sprites.RemoveAt(sprites.Count - 1);
                        i--;
                        continue;
                    }
                }
                s.Pos = s.Pos + s.Vel * dt;
                s.Vel.y += gravity * dt;
                s.Rot = LTQuat.AxisAngle(s.Rot.Right(), s.RotAdd.x * dt) * s.Rot;
                s.Rot = LTQuat.AxisAngle(s.Rot.Up(), s.RotAdd.y * dt) * s.Rot;
                s.Rot = LTQuat.AxisAngle(s.Rot.Forward(), s.RotAdd.z * dt) * s.Rot;
                sprites[i] = s;
            }
        }

        public override int QuadFrame(int quad) => quad < frames.Count ? frames[quad] : 0;

        // CSpriteSystem::Render and SetupParticle. Colour and scale carry over from the sprite before when its
        // keys don't reach (the engine's locals; scale starts at 0.2). Sprites behind the camera aren't drawn.
        public override void Render(PrimCamera cam, List<PrimVert> quads)
        {
            frames.Clear();
            float r = 1, g = 1, b = 1, a = 1, scale = 0.2f;
            float animLen = animType == AnimSprite ? spriteLen : animType == AnimKey ? Key.Lifespan : 1;
            animLen /= animSpeed;
            float aspect = file.Width > 0 ? (float)file.Height / file.Width : 1;
            var corners = new LTVec[4];
            foreach (var s in sprites)
            {
                var pos = s.Pos;
                if (spin) pos = Rot.Rotate(spinRot.Rotate(pos - Pos)) + Pos;
                float t = s.Lifespan > 0 ? s.Elapsed / s.Lifespan : 0;
                KeyColour(Key.Ck, t, ref r, ref g, ref b, ref a);
                KeyScale(Key.Sk, t, ref scale);
                int frame = 0;
                if (file.Frames > 1)
                {
                    if (animType == AnimParticle) animLen = s.Lifespan * animSpeed;
                    frame = (int)(file.Frames * s.Elapsed / animLen) % file.Frames;
                }
                var c = cam.ToCamera(pos);
                if (c.z < 0) continue;
                float w = scale * stretchU, h = scale * aspect * stretchV;
                corners[0] = new LTVec(c.x - w, c.y + h, c.z);
                corners[1] = new LTVec(c.x + w, c.y + h, c.z);
                corners[2] = new LTVec(c.x + w, c.y - h, c.z);
                corners[3] = new LTVec(c.x - w, c.y - h, c.z);
                if (s.Rot.x != 0 || s.Rot.y != 0 || s.Rot.z != 0 || s.Rot.w != 1)
                    for (int i = 0; i < 4; i++) corners[i] = s.Rot.Rotate(corners[i] - c) + c;
                uint col = Color(r, g, b, a);
                quads.Add(new PrimVert { Pos = cam.FromCamera(corners[0]), Color = col, U = 0, V = 0 });
                quads.Add(new PrimVert { Pos = cam.FromCamera(corners[1]), Color = col, U = 1, V = 0 });
                quads.Add(new PrimVert { Pos = cam.FromCamera(corners[2]), Color = col, U = 1, V = 1 });
                quads.Add(new PrimVert { Pos = cam.FromCamera(corners[3]), Color = col, U = 0, V = 1 });
                frames.Add(frame);
            }
        }
    }
}
