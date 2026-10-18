using System;

// The ParticleSystem effect type (ltjs clientfxdll/particlesystemfx.cpp, docs/research/clientfx-types.md on
// research/clientfx-types): a "dumb" engine particle system the effect moves itself. Bursts on its initial
// frame and every EmissionInterval, particles placed by the emission Type, coloured and sized over their own
// life by the key's Ck / Sk, and moved by gravity, acceleration, friction and swarm. The system is updated
// whether it was drawn or not (FLAG_UPDATEUNSEEN). Plain C#: ParticleRenderer draws it,
// tools/tests/test_particle_fx.py drives it.
namespace Tron
{
    public sealed class FxParticleSystem : FxEffect
    {
        public const int BlendNone = 0, BlendAdditive = 1, BlendMultiply = 2;
        const int Sphere = 0, Point = 1, Circle = 2, Cone = 3, Cylinder = 4;
        const byte Bounce = 1, Splat = 2;

        public struct Particle
        {
            // Position and velocity in the level, or in the system's space when it moves them with it.
            public LTVec Pos, Vel;
            public float Life, Total, Angle, AngularVel;
            // Colour 0-1, alpha already 1 - the key's; the quad is 4 x Size on a side.
            public float R, G, B, A, Size;
            public byte Flags;
        }

        readonly ClientFXMgr mgr;

        // The texture: a .spr (one frame for the whole system, on its own clock) wins over a .dtx; "" none.
        public string Texture { get; private set; }
        public int Blend { get; private set; }
        // MoveParticlesWithSystem: particles live in the system's space and are drawn with its transform.
        public bool ObjectSpace { get; private set; }
        public bool Rotate { get; private set; }
        // When the engine object was made (ClientFXMgr.Time): the sprite clock's zero.
        public double Born { get; private set; }

        public Particle[] Particles = new Particle[16];
        public int Count;

        int type, perEmission;
        bool fromCenter, infiniteLife, killOnSplat, swarm;
        float interval, minLife, maxLife, minRadius, maxRadius, friction, bounce, splat, minAngVel, maxAngVel;
        LTVec plane, perp1, perp2, minVel, maxVel, acceleration, randomPoint;
        string splatEffect;
        float elapsedEmission;

        public FxParticleSystem(ClientFXMgr mgr) => this.mgr = mgr;

        float Rand(float min, float max) => min + (max - min) * (float)mgr.Random();

        static LTVec Norm(LTVec v)
        {
            float l = v.Length();
            return l > 0 ? v / l : v;
        }

        static float Dot(LTVec a, LTVec b) => a.x * b.x + a.y * b.y + a.z * b.z;

        // CParticleSystemProps::ParseProperties and CParticleSystemFX::Init.
        protected override void OnInit()
        {
            var k = Key;
            var sprite = k.Str("Sprite");
            Texture = sprite != "" ? sprite : k.Str("Texture");
            Blend = (int)k.Num("BlendMode");
            ObjectSpace = k.Num("MoveParticlesWithSystem", 1) != 0;
            Rotate = k.Num("RotateParticles") != 0;
            type = (int)k.Num("Type");
            fromCenter = k.Num("VelocityType") == 1;
            perEmission = (int)k.Num("ParticlesPerEmission", 5);
            interval = k.Num("EmissionInterval", 0.01f);
            minLife = k.Num("MinParticleLifeSpan", 2);
            maxLife = k.Num("MaxParticleLifeSpan", 3);
            minRadius = k.Num("MinRadius");
            maxRadius = k.Num("MaxRadius", 10);
            minVel = k.Vec("MinParticleVelocity", new LTVec(0, 1, 0));
            maxVel = k.Vec("MaxParticleVelocity", new LTVec(0, 1, 0));
            acceleration = k.Vec("AdditionalAcceleration") + new LTVec(0, k.Num("GravityAcceleration", -500), 0);
            friction = Math.Clamp(k.Num("Friction"), 0, 1);
            bounce = Math.Clamp(k.Num("PercentToBounce"), 0, 100);
            infiniteLife = k.Num("InfiniteLife") != 0;
            splatEffect = k.Str("SplatEffect");
            splat = k.Num("SplatPercent");
            killOnSplat = k.Num("KillOnSplat", 1) != 0;
            minAngVel = k.Num("MinAngularVelocity") * (float)Math.PI / 180;
            maxAngVel = k.Num("MaxAngularVelocity", 360) * (float)Math.PI / 180;
            // FindPerps (LTVector::Cross as the engine's).
            plane = Norm(k.Vec("EmissionPlane", new LTVec(0, 1, 0)));
            perp1 = (plane.y == 1 || plane.y == -1 ? new LTVec(1, 0, 0) : new LTVec(0, 1, 0)).Cross(plane);
            perp2 = perp1.Cross(plane);
            var r = k.RotateAdd;
            swarm = r.x != 0 || r.y != 0 || r.z != 0;
            Born = mgr.Time;
            if (type == Point) randomPoint = Norm(perp1 * Rand(-1, 1) + perp2 * Rand(-1, 1)) * Rand(minRadius, maxRadius);
        }

        // CParticleSystemFX::Update, after the base: emission unless shutting down, then the particles.
        protected override void OnUpdate(float dt)
        {
            if (!ShuttingDown)
            {
                elapsedEmission += dt;
                if (InitialFrame)
                {
                    AddParticles();
                    elapsedEmission = 0;
                }
                if (interval > 0)
                {
                    // An emission whose particles are all dead by now isn't made.
                    float startEmissions = interval + maxLife;
                    while (elapsedEmission >= interval)
                    {
                        if (elapsedEmission >= startEmissions)
                        {
                            elapsedEmission -= interval;
                            continue;
                        }
                        AddParticles();
                        elapsedEmission -= interval;
                        if (elapsedEmission >= interval)
                        {
                            UpdateParticles(interval);
                            dt -= interval;
                        }
                    }
                }
            }
            UpdateParticles(dt);
        }

        public override bool IsFinishedShuttingDown => Count == 0;
        public override bool IsVisibleWhileSuspended => Count != 0;
        public override void SuspendedUpdate(float dt)
        {
            if (Active) UpdateParticles(dt);
        }

        void AddParticles()
        {
            var k = Key;
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
                        pos = default;
                        break;
                }
                LTVec vel;
                if (fromCenter) vel = pos * (Rand(minVel.x, maxVel.x) / pos.Length());
                else vel = new LTVec(Rand(minVel.x, maxVel.x), Rand(minVel.y, maxVel.y), Rand(minVel.z, maxVel.z));
                // In the level, the velocity turns with the system; the spawn offset doesn't.
                if (!ObjectSpace)
                {
                    vel = Rot.Rotate(vel);
                    pos = pos + Pos;
                }
                var p = new Particle { Pos = pos, Vel = vel, Life = Rand(minLife, maxLife) };
                p.Total = p.Life;
                if (k.Ck.Length >= 5)
                {
                    p.R = k.Ck[1];
                    p.G = k.Ck[2];
                    p.B = k.Ck[3];
                    p.A = 1 - k.Ck[4];
                }
                else p.R = p.G = p.B = p.A = 1;
                p.Size = k.Sk.Length >= 2 ? k.Sk[1] : 1;
                if (Rotate)
                {
                    p.Angle = Rand(0, 2 * (float)Math.PI);
                    p.AngularVel = Rand(minAngVel, maxAngVel);
                }
                if (bounce > 0.001f && Rand(0, 100) < bounce) p.Flags |= Bounce;
                if (splatEffect != "" && splat > 0.001f && Rand(0, 100) < splat) p.Flags |= Splat;
                if (Count == Particles.Length) Array.Resize(ref Particles, Count * 2);
                Particles[Count++] = p;
            }
        }

        // UpdateParticles: age, move, swarm, accelerate, then colour and size by the keys over the particle's
        // life; then bounces and splats against the world.
        void UpdateParticles(float dt)
        {
            var acc = acceleration * dt;
            float frictionCoef = (float)Math.Pow(1 - friction, dt);
            LTQuat swarmRot = default;
            if (swarm)
            {
                var r = Key.RotateAdd;
                swarmRot = LTQuat.FromEuler(r.x * dt, r.y * dt, r.z * dt);
            }
            if (ObjectSpace) acc = Rot.Conjugate().Rotate(acc);
            var ck = Key.Ck;
            var sk = Key.Sk;
            int n = 0, bouncing = 0;
            for (int i = 0; i < Count; i++)
            {
                var p = Particles[i];
                p.Life -= dt;
                if (p.Life <= 0)
                {
                    if (!infiniteLife) continue;
                    p.Life = p.Total - -p.Life % p.Total;
                }
                else
                {
                    p.Angle += p.AngularVel * dt;
                    p.Pos = p.Pos + p.Vel * dt;
                    if (ObjectSpace && swarm) p.Pos = swarmRot.Rotate(p.Pos);
                    p.Vel = p.Vel * frictionCoef + acc;
                    float t = 1 - p.Life / p.Total;
                    KeyColour(ck, t, ref p.R, ref p.G, ref p.B, ref p.A);
                    KeyScale(sk, t, ref p.Size);
                }
                if (p.Flags != 0) bouncing++;
                Particles[n++] = p;
            }
            Count = n;
            if (bouncing > 0 && mgr.Intersect != null) Collide(dt);
        }

        void Collide(float dt)
        {
            int n = 0;
            for (int i = 0; i < Count; i++)
            {
                var p = Particles[i];
                bool keep = true;
                if (p.Flags != 0)
                {
                    LTVec from = p.Pos, to = p.Pos + p.Vel * dt;
                    if (ObjectSpace)
                    {
                        from = Pos + Rot.Rotate(from);
                        to = Pos + Rot.Rotate(to);
                    }
                    if (mgr.Intersect(from, to, out var point, out var normal))
                    {
                        // The velocity reflected about the world normal, even in the system's space.
                        if ((p.Flags & Bounce) != 0) p.Vel = (p.Vel - normal * (2 * Dot(p.Vel, normal))) * 0.75f;
                        if ((p.Flags & Splat) != 0)
                        {
                            mgr.Start(splatEffect, false, true, null, point, SplatRotation(normal));
                            keep = !killOnSplat;
                        }
                    }
                }
                if (keep) Particles[n++] = p;
            }
            Count = n;
        }

        // Forward along the hit normal, a random up.
        LTQuat SplatRotation(LTVec forward)
        {
            var up = new LTVec(Rand(-1, 1), Rand(-1, 1), Rand(-1, 1));
            up = Dot(up, up) < 0.1f ? new LTVec(0, 1, 0) : Norm(up);
            if (Dot(up, forward) > 0.95f) up = new LTVec(up.x, up.z, -up.y);
            return LTQuat.FromForwardUp(forward, up);
        }

        public override void Term() => Count = 0;
    }
}
