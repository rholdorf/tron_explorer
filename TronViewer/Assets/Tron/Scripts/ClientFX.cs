using System;
using System.Collections.Generic;

// ClientFX effect groups as the game plays them (docs/research/clientfx-groups.md on research/clientfx-groups;
// ltjs clientfxmgr.cpp, basefx.cpp): a group instance creates every key's effect up front and runs them in
// phase intervals, each effect timed, coloured, scaled and placed by the base rules here. Effect types are
// plug-ins (ClientFXMgr.Types): a type with none is timed but has no look. Plain C#, no Unity, so
// tools/tests/test_client_fx.py compiles it with .NET.
namespace Tron
{
    // An fx key (tools/clientfx.py export_key): start / end in seconds within the phase, continual when it
    // covers the whole phase; the base props; Ck as t, r, g, b, a per key (a is a transparency, drawn
    // 1 - a) and Sk as t, scale per key; the type's own props by name.
    public sealed class FxKey
    {
        public const int Fixed = 0, Follow = 1, PlayerView = 2, NodeAttach = 3, SocketAttach = 4;

        public string Type = "", Label = "", Attach = "";
        public int Id, Link = -1, UpdatePos;
        public float Start, End, MaxStartOffset, StartOffsetInterval;
        public bool Continual, DisableAtDist, RandomizeStartOffset, SmoothShutDown = true;
        public LTVec Offset, RotateAdd;
        public float[] Ck = Array.Empty<float>(), Sk = Array.Empty<float>();
        public Dictionary<string, string> Strs = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, float[]> Nums = new Dictionary<string, float[]>(StringComparer.OrdinalIgnoreCase);

        public float Lifespan => End - Start;
        public string Str(string name, string def = "") => Strs.TryGetValue(name, out var s) ? s : def;
        public float Num(string name, float def = 0) => Nums.TryGetValue(name, out var v) && v.Length > 0 ? v[0] : def;
        public LTVec Vec(string name, LTVec def = default) =>
            Nums.TryGetValue(name, out var v) && v.Length >= 3 ? new LTVec(v[0], v[1], v[2]) : def;
    }

    // A group: its phase (s) and keys, ordered so a key motion-linked to another comes after it.
    public sealed class FxGroup
    {
        public string Name = "";
        public float Phase;
        public FxKey[] Keys = Array.Empty<FxKey>();
    }

    // What an effect follows: a SpecialFX object, another effect of the instance (a motion link), or the
    // stand-in a smooth shutdown leaves. Nodes and sockets belong to models (an effect model's).
    public interface IFxObject
    {
        LTVec Pos { get; }
        LTQuat Rot { get; }
        bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot);
    }

    // An object with a position and a rotation and nothing to attach to.
    public sealed class FxAnchor : IFxObject
    {
        public LTVec Pos { get; set; }
        public LTQuat Rot { get; set; }

        public FxAnchor(LTVec pos, LTQuat rot)
        {
            Pos = pos;
            Rot = rot;
        }

        public bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot)
        {
            pos = default;
            rot = default;
            return false;
        }
    }

    // One key's effect in an instance (CBaseFX). The base keeps its time, its state flags, its colour and
    // scale from the key's Ck / Sk, and its place from UpdatePos; a type overrides the hooks to draw.
    public class FxEffect : IFxObject
    {
        public FxKey Key { get; private set; }
        public IFxObject Parent { get; internal set; }
        public LTVec CreatePos { get; private set; }
        public LTQuat CreateRot { get; private set; }
        public LTVec Pos { get; protected set; }
        public LTQuat Rot { get; protected set; }
        public float Elapsed { get; internal set; }
        public bool Active { get; internal set; }
        public bool ShuttingDown { get; internal set; }
        public bool InitialFrame { get; internal set; }
        public bool Suspended { get; internal set; }
        // The drawn colour (alpha already 1 - the key's) and uniform scale, from the keys.
        public float R = 1, G = 1, B = 1, A = 1, Scale = 1;

        bool visible;
        public bool Visible
        {
            get => visible;
            internal set
            {
                if (visible == value) return;
                visible = value;
                OnVisible(value);
            }
        }

        // CBaseFX::Init: created at the parent (or the instance without one), the offset in world axes.
        internal void Init(FxKey key, IFxObject parent, LTVec pos, LTQuat rot)
        {
            Key = key;
            Parent = parent;
            CreatePos = parent != null ? parent.Pos : pos;
            CreateRot = parent != null ? parent.Rot : rot;
            Pos = CreatePos + key.Offset;
            Rot = CreateRot;
            OnInit();
        }

        // CBaseFX::Update: time, then the place (with a parent, the offset turns with it; without one,
        // nothing moves), then colour and scale; then the type.
        public void Update(float dt)
        {
            if (Suspended || !Active) return;
            OnBeginUpdate();
            Elapsed += dt;
            if (Parent != null)
            {
                var pr = Parent.Rot;
                var o = Key.Offset;
                var aligned = pr.Right() * o.x + pr.Up() * o.y + pr.Forward() * o.z;
                switch (Key.UpdatePos)
                {
                    case FxKey.Fixed:
                        Pos = CreatePos + aligned;
                        Rot = pr;
                        break;
                    case FxKey.Follow:
                        Pos = Parent.Pos + aligned;
                        Rot = pr;
                        break;
                    case FxKey.NodeAttach:
                    case FxKey.SocketAttach:
                        // A parent without that node or socket leaves the effect where it was.
                        if (Parent.Attachment(Key.Attach, Key.UpdatePos == FxKey.SocketAttach, out var ap, out var ar))
                        {
                            Pos = ap + aligned;
                            Rot = ar;
                        }
                        else Rot = pr;
                        break;
                    default:
                        Rot = pr;
                        break;
                }
            }
            float lifespan = Key.Lifespan;
            float t = lifespan > 0 ? (float)(Elapsed / lifespan % 1.0) : 0;
            Colour(t);
            KeyScale(t);
            OnUpdate(dt);
        }

        void Colour(float t) => KeyColour(Key.Ck, t, ref R, ref G, ref B, ref A);

        void KeyScale(float t) => KeyScale(Key.Sk, t, ref Scale);

        // CalcColour: linear between the keys around t (Ck: t, r, g, b, a per key; a drawn 1 - a), nothing
        // written past the last.
        public static void KeyColour(float[] k, float t, ref float r, ref float g, ref float b, ref float a)
        {
            for (int i = 0; i + 9 < k.Length; i += 5)
            {
                if (t >= k[i + 5]) continue;
                float span = k[i + 5] - k[i], f = span > 0 ? (t - k[i]) / span : 0;
                r = k[i + 1] + (k[i + 6] - k[i + 1]) * f;
                g = k[i + 2] + (k[i + 7] - k[i + 2]) * f;
                b = k[i + 3] + (k[i + 8] - k[i + 3]) * f;
                a = 1 - (k[i + 4] + (k[i + 9] - k[i + 4]) * f);
                return;
            }
        }

        // CalcScale: as KeyColour, Sk: t, scale per key.
        public static void KeyScale(float[] k, float t, ref float scale)
        {
            for (int i = 0; i + 3 < k.Length; i += 2)
            {
                if (t >= k[i + 2]) continue;
                float span = k[i + 2] - k[i];
                scale = k[i + 1] + (span > 0 ? (k[i + 3] - k[i + 1]) / span * (t - k[i]) : 0);
                return;
            }
        }

        // Once, after Init.
        protected virtual void OnInit() { }
        // Each update, before the base (the type's own work ahead of CBaseFX::Update).
        protected virtual void OnBeginUpdate() { }
        // Each update, after the base.
        protected virtual void OnUpdate(float dt) { }
        // When it is shown or hidden.
        protected virtual void OnVisible(bool shown) { }
        // Whether a shutting-down effect still has something to finish (live particles, trail points...).
        public virtual bool IsFinishedShuttingDown => true;
        // A frozen instance keeps it drawn (particle systems with live particles).
        public virtual bool IsVisibleWhileSuspended => false;
        // Each frame its instance is frozen.
        public virtual void SuspendedUpdate(float dt) { }
        // When it leaves the instance.
        public virtual void Term() { }
        // Once a frame while it exists, frozen or not: what the engine does to its object on its own
        // (a model's animation).
        public virtual void EngineUpdate(float dt) { }

        public virtual bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot)
        {
            pos = default;
            rot = default;
            return false;
        }
    }

    // A running group (CLIENTFX_INSTANCE): looping or one-shot, at its parent or, without one, where it
    // was started. Done when its last effect has gone.
    public sealed class FxInstance
    {
        public readonly FxGroup Group;
        public readonly bool Loop, SmoothShutdown;
        public IFxObject Parent { get; private set; }
        public readonly LTVec StartPos;
        public readonly LTQuat StartRot;
        public float Elapsed { get; private set; }
        public bool Shutdown { get; private set; }
        public bool Suspended { get; private set; }
        // In update order: reverse key order (the game pushes each new effect at the head).
        readonly List<FxEffect> effects = new List<FxEffect>();
        readonly ClientFXMgr mgr;

        public IReadOnlyList<FxEffect> Effects => effects;
        public bool Done => effects.Count == 0;

        internal FxInstance(ClientFXMgr mgr, FxGroup group, bool loop, bool smoothShutdown, IFxObject parent, LTVec pos, LTQuat rot)
        {
            this.mgr = mgr;
            Group = group;
            Loop = loop;
            SmoothShutdown = smoothShutdown;
            Parent = parent;
            StartPos = parent != null ? parent.Pos : pos;
            StartRot = parent != null ? parent.Rot : rot;
            // CreateFXKey: every key's effect, hidden and inactive; a linked key follows the effect of the
            // key it links to when that one exists, else the instance parent.
            var byId = new Dictionary<int, FxEffect>();
            foreach (var key in group.Keys)
            {
                var fx = mgr.NewEffect(key);
                IFxObject p = parent;
                if (key.Link >= 0 && byId.TryGetValue(key.Link, out var linked)) p = linked;
                fx.Init(key, p, StartPos, StartRot);
                byId[key.Id] = fx;
                effects.Insert(0, fx);
            }
        }

        // UpdateAllActiveFX for one instance: frozen, or the frame's time cut at each phase end.
        internal void Update(float dt, LTVec camera)
        {
            if (UpdateSuspended(camera))
            {
                foreach (var fx in effects) fx.SuspendedUpdate(dt);
                return;
            }
            float a = Elapsed, b = a + dt, duration = Group.Phase;
            for (;;)
            {
                bool last = b < duration;
                Interval(a, last ? b : duration);
                if (last) break;
                a = 0;
                b -= duration;
                if (duration <= 0) break;
            }
            Elapsed = b;
        }

        // UpdateInstanceSuspended (a SpecialFX instance is always shown, so only the distance counts): frozen
        // beyond the cull distance from its parent's current place (Tron) when every effect allows it.
        bool UpdateSuspended(LTVec camera)
        {
            bool suspend = false;
            if (effects.Count > 0)
            {
                var pos = Parent != null ? Parent.Pos : StartPos;
                var d = pos - camera;
                if (d.x * d.x + d.y * d.y + d.z * d.z > ClientFXMgr.CullDistance * ClientFXMgr.CullDistance)
                    suspend = effects.TrueForAll(fx => fx.Key.DisableAtDist);
            }
            if (suspend && !Suspended)
            {
                Suspended = true;
                foreach (var fx in effects)
                {
                    fx.Suspended = true;
                    if (!fx.IsVisibleWhileSuspended) fx.Visible = false;
                }
            }
            else if (!suspend && Suspended)
            {
                Suspended = false;
                foreach (var fx in effects)
                {
                    fx.Suspended = false;
                    if (fx.Active) fx.Visible = true;
                }
            }
            return Suspended;
        }

        // UpdateInstanceInterval: [a, b] inclusive at both ends, within one phase.
        internal void Interval(float a, float b)
        {
            for (int i = 0; i < effects.Count; i++)
            {
                var fx = effects[i];
                var k = fx.Key;
                float cur = a;
                if (!fx.Active && (k.Continual || (k.Start >= cur && k.Start <= b)))
                {
                    Activate(fx);
                    cur = k.Start;
                }
                if (!fx.Active) continue;
                if (fx.ShuttingDown && Loop && !Shutdown && k.Start >= cur && k.Start <= b)
                {
                    fx.Update(k.Start - cur);   // the old run, up to the restart
                    fx.ShuttingDown = false;
                    Activate(fx);
                    cur = k.Start;
                }
                if (!fx.ShuttingDown)
                {
                    bool complete = k.End <= b && k.End >= cur;
                    float end = complete ? k.End : b;
                    fx.Update(end - cur);
                    fx.InitialFrame = false;
                    if (complete)
                    {
                        if (k.Continual && Loop)
                            fx.Elapsed = k.MaxStartOffset >= 0.001f && k.Lifespan > 0 ? fx.Elapsed % k.Lifespan : 0;
                        else fx.ShuttingDown = true;
                    }
                    cur = end;
                }
                if (fx.ShuttingDown)
                {
                    fx.Update(b - cur);
                    if (fx.IsFinishedShuttingDown || !(k.SmoothShutDown && SmoothShutdown))
                    {
                        // HandleShutdownEffect: a running loop keeps it for its next start.
                        if (Loop && !Shutdown)
                        {
                            fx.Visible = false;
                            fx.Active = fx.ShuttingDown = fx.InitialFrame = false;
                        }
                        else Delete(i--);
                    }
                }
            }
        }

        void Activate(FxEffect fx)
        {
            fx.Elapsed = 0;
            fx.Active = fx.InitialFrame = true;
            fx.ShuttingDown = false;
            fx.Visible = true;
            StartOffset(fx);
        }

        // ApplyEffectStartingOffset: fake updates that pre-age the effect.
        void StartOffset(FxEffect fx)
        {
            var k = fx.Key;
            float offset = k.RandomizeStartOffset ? (float)(mgr.Random() * k.MaxStartOffset) : k.MaxStartOffset;
            if (offset < 0.01f) return;
            float step = k.StartOffsetInterval >= 0.001f ? k.StartOffsetInterval : offset, t = 0;
            for (; t + step <= offset; t += step)
            {
                fx.Update(step);
                fx.InitialFrame = false;
            }
            if (offset - t > 0.01f)
            {
                fx.Update(offset - t);
                fx.InitialFrame = false;
            }
        }

        // ShutdownClientFX. Smooth: the effects stop following (a stand-in where the parent is now takes
        // its place), inactive ones go, active ones shut down and go once finished (at once when they or
        // the key don't shut down smoothly). Otherwise every effect goes now.
        internal void ShutDown()
        {
            if (Shutdown) return;
            Shutdown = true;
            if (!SmoothShutdown)
            {
                Parent = null;
                while (effects.Count > 0) Delete(effects.Count - 1);
                return;
            }
            var anchor = new FxAnchor(Parent != null ? Parent.Pos : StartPos, Parent != null ? Parent.Rot : StartRot);
            Parent = anchor;
            for (int i = 0; i < effects.Count; i++)
            {
                var fx = effects[i];
                if (!fx.Active)
                {
                    Delete(i--);
                    continue;
                }
                fx.Parent = anchor;
                fx.ShuttingDown = true;
                if (fx.IsFinishedShuttingDown || !fx.Key.SmoothShutDown) Delete(i--);
            }
        }

        // DeleteFX: the effects that followed it lose their parent (and stay where they are).
        void Delete(int i)
        {
            var fx = effects[i];
            foreach (var other in effects)
                if (other.Parent == fx) other.Parent = null;
            fx.Visible = false;
            fx.Term();
            effects.RemoveAt(i);
        }
    }

    public delegate bool SegmentHit(LTVec from, LTVec to, out LTVec point, out LTVec normal);

    // The client's effect manager (CClientFXMgr) for one level: its groups by name, the running instances,
    // and the effect types the viewer has.
    public sealed class ClientFXMgr
    {
        public const float CullDistance = 6000;   // Tron's one cull distance (LT units)

        readonly Dictionary<string, FxGroup> groups = new Dictionary<string, FxGroup>(StringComparer.OrdinalIgnoreCase);
        readonly List<FxInstance> instances = new List<FxInstance>();
        public readonly Func<double> Random;
        // The client's time (s), summed over the updates: sprite clocks run on it.
        public double Time { get; private set; }
        // The camera's rotation in the level, for effects that face it.
        public LTQuat CameraRot = new LTQuat(0, 0, 0, 1);
        // IntersectSegment against the world, for effects that bounce or splat: the first hit from
        // `from` to `to` (LT units), its point and its surface normal. None set: nothing is hit.
        public SegmentHit Intersect;

        // Effect types by name (any case): each makes a key's effect. A type with none gets the base
        // effect: timed, no look.
        public readonly Dictionary<string, Func<FxKey, FxEffect>> Types =
            new Dictionary<string, Func<FxKey, FxEffect>>(StringComparer.OrdinalIgnoreCase);

        // random: uniform in [0, 1); System.Random when null.
        public ClientFXMgr(Func<double> random = null)
        {
            if (random == null)
            {
                var r = new Random();
                random = r.NextDouble;
            }
            Random = random;
        }

        public IReadOnlyList<FxInstance> Instances => instances;

        // FindGroupFX: the first group with the name, in any case.
        public void Add(FxGroup group)
        {
            if (!groups.ContainsKey(group.Name)) groups[group.Name] = group;
        }

        public FxGroup Find(string name) => name != null && groups.TryGetValue(name, out var g) ? g : null;

        public bool HasLook(string type) => Types.ContainsKey(type);

        internal FxEffect NewEffect(FxKey key) => Types.TryGetValue(key.Type, out var make) ? make(key) ?? new FxEffect() : new FxEffect();

        // CreateClientFX with bStartInst: every key's effect, then the keys at 0 and the continual ones
        // start in this frame. A group with no name found makes nothing (null).
        public FxInstance Start(string name, bool loop, bool smoothShutdown, IFxObject parent, LTVec pos = default, LTQuat rot = default)
        {
            var g = Find(name);
            if (g == null) return null;
            var inst = new FxInstance(this, g, loop, smoothShutdown, parent, pos, rot);
            inst.Interval(0, 0);
            instances.Add(inst);
            return inst;
        }

        public void ShutDown(FxInstance inst)
        {
            if (inst == null) return;
            inst.ShutDown();
            if (inst.Done) instances.Remove(inst);
        }

        // UpdateAllActiveFX: every instance by the client frame time; finished ones go.
        public void Update(float dt, LTVec camera)
        {
            Time += dt;
            for (int i = 0; i < instances.Count; i++)
            {
                instances[i].Update(dt, camera);
                if (instances[i].Done) instances.RemoveAt(i--);
                else foreach (var fx in instances[i].Effects) fx.EngineUpdate(dt);
            }
        }

        // Every instance goes now (level unload).
        public void Clear()
        {
            foreach (var inst in instances)
                foreach (var fx in inst.Effects) fx.Term();
            instances.Clear();
        }
    }
}
