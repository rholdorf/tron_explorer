using System;
using System.Collections.Generic;

// The player's messages the viewer keeps (docs/research/player-messages.md): teleport, screen fades, and
// the render variables that ramps, sines and WorldProperties fog messages change. Plain C#, no Unity, so
// tools/tests/test_player_messages.py compiles it with Mono; TronExplorer feeds the results to the player,
// the fog globals, the camera far planes and the glow pass every frame.
namespace Tron
{
    // The client's render variables (console variables, names in any case) that the levels touch, read by
    // the viewer every frame.
    //
    // World variables have a server copy, seeded from the level's WorldProperties and set by its messages;
    // after each WorldProperties message every world variable is copied again to the client
    // (ResetDynamicWorldProperties), wiping what a ramp or sine left. Ramps and sines (Tron's cshell.dll,
    // RAMPCONSOLEVAR / SINCONSOLEVAR) run on the client copy, one per variable, and write it as the
    // console does ("%s %4.2f": two decimals, truncated for int variables).
    public sealed class RenderVars
    {
        // The world variables (WorldProperties props and messages), with the viewer's defaults.
        public static readonly IReadOnlyDictionary<string, float> WorldDefaults = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase)
        {
            { "FarZ", 20000 }, { "FogEnable", 0 }, { "FogR", 0 }, { "FogG", 0 }, { "FogB", 0 },
            { "FogNearZ", 0 }, { "FogFarZ", 0 }, { "SkyFogEnable", 0 }, { "SkyFogNearZ", 0 }, { "SkyFogFarZ", 0 },
            { "ScreenGlowFogEnable", 0 }, { "ScreenGlowFogNearZ", 0 }, { "ScreenGlowFogFarZ", 0 },
        };

        // Client-only variables the levels ramp or sine: the screen glow filter, as Tron's autoexec.cfg sets it.
        static readonly Dictionary<string, float> ClientDefaults = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase)
        {
            { "ScreenGlowUVScale", 1 }, { "ScreenGlowPixelShift", -0.1f }, { "ScreenGlowGaussAmp0", 0 },
            { "ScreenGlowGaussRadius0", 0 }, { "ScreenGlowGaussAmp1", 0.1f }, { "ScreenGlowGaussRadius1", 3 },
        };

        // Int console variables (the renderer's FogR/G/B, 0-255).
        static readonly HashSet<string> Ints = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "FogR", "FogG", "FogB" };

        sealed class Wave
        {
            public string Name;
            public bool Sine;
            public float Start, End, Period, Elapsed;   // ramp
            public float Center, Amplitude, Saved;      // sine
        }

        readonly Dictionary<string, float> server = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, float> client = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        readonly List<Wave> waves = new List<Wave>();

        // world: the level's WorldProperties values by variable name (FogR, FogNearZ, FarZ...); the others
        // keep their defaults.
        public RenderVars(IDictionary<string, float> world)
        {
            foreach (var kv in WorldDefaults) server[kv.Key] = kv.Value;
            foreach (var kv in world) if (server.ContainsKey(kv.Key)) server[kv.Key] = kv.Value;
            foreach (var kv in ClientDefaults) client[kv.Key] = kv.Value;
            CopyWorld();
        }

        // The client value, 0 for a variable the client doesn't have.
        public float this[string name] => client.TryGetValue(name, out float v) ? v : 0;

        // Bumped whenever a value may have changed, so readers can skip rebuilding.
        public int Version { get; private set; }

        // A WorldProperties message: the server's variable, then every world variable copied again.
        public void SetWorld(string name, float value)
        {
            server[name] = value;
            CopyWorld();
        }

        void CopyWorld()
        {
            foreach (var kv in server) Write(kv.Key, kv.Value, false);
        }

        // RAMPCONSOLEVAR: from start (or the current value) to end over period seconds, then hold end.
        public void Ramp(string name, float? start, float end, float period)
        {
            if (!Begin(name)) return;
            waves.Add(new Wave { Name = name, Start = start ?? client[name], End = end, Period = period });
        }

        // SINCONSOLEVAR: center + amplitude sin(2 pi t / period), center = min + max/2 as Tron's client
        // computes it (not the midpoint), amplitude = (max - min)/2; looped until stopped.
        public void Sine(string name, float min, float max, float period)
        {
            if (!Begin(name)) return;
            waves.Add(new Wave
            {
                Name = name, Sine = true, Period = period, Center = min + max * 0.5f, Amplitude = (max - min) * 0.5f,
                Saved = client[name],
            });
        }

        // SINCONSOLEVAR off/stop (revert false) or revert/restore (revert true: the value from before the sine).
        public void Stop(string name, bool revert)
        {
            int i = waves.FindIndex(w => string.Equals(w.Name, name, StringComparison.OrdinalIgnoreCase));
            if (i < 0) return;
            if (revert && waves[i].Sine) Write(name, waves[i].Saved, true);
            waves.RemoveAt(i);
        }

        // A new ramp or sine replaces the variable's running one; a variable the client lacks is ignored.
        bool Begin(string name)
        {
            waves.RemoveAll(w => string.Equals(w.Name, name, StringComparison.OrdinalIgnoreCase));
            return client.ContainsKey(name);
        }

        // Every client frame.
        public void Update(float frameTime)
        {
            for (int i = 0; i < waves.Count; i++)
            {
                var w = waves[i];
                w.Elapsed += frameTime;
                if (w.Sine)
                {
                    if (w.Period > 0) w.Elapsed %= w.Period;
                    double t = w.Period > 0 ? w.Elapsed / w.Period : 0;
                    Write(w.Name, w.Center + w.Amplitude * (float)Math.Sin(2 * Math.PI * t), true);
                }
                else if (w.Elapsed >= w.Period)
                {
                    Write(w.Name, w.End, true);
                    waves.RemoveAt(i--);
                }
                else Write(w.Name, w.Start + (w.End - w.Start) * w.Elapsed / w.Period, true);
            }
        }

        void Write(string name, float value, bool console)
        {
            if (console) value = (float)Math.Round(value, 2, MidpointRounding.AwayFromZero);
            if (Ints.Contains(name)) value = (float)Math.Truncate(value);
            client[name] = value;
            Version++;
        }
    }

    // The black screen fade (ltjs interfacemgr.cpp): a new fade replaces the running one; its overlay's
    // alpha eases as 1 - SlowOn(1 - p), p = elapsed/total for a fade-out (0 -> 1) and remaining/total for a
    // fade-in (1 -> 0). After a fade-out the screen stays black until a fade-in. Input is never blocked.
    public sealed class ScreenFade
    {
        bool fadeIn = true;
        float total = 1, elapsed = 1;

        public float Alpha { get; private set; }

        public void Start(bool fadeIn, float time)
        {
            this.fadeIn = fadeIn;
            total = time;
            elapsed = 0;
            Alpha = AlphaAt(0);
        }

        public void Update(float frameTime)
        {
            elapsed = Math.Min(elapsed + frameTime, total);
            Alpha = AlphaAt(elapsed);
        }

        float AlphaAt(float t)
        {
            float p = total > 0 ? Math.Min(Math.Max(t / total, 0), 1) : 1;
            if (fadeIn) p = 1 - p;
            return 1 - SlowOn(1 - p);
        }

        // wavefn.cpp WaveFn_SlowOn.
        static float SlowOn(float v) => v < 0.5f ? (1 - (float)Math.Cos(Math.PI * v)) / 2 : v;
    }

    public static class PlayerMessages
    {
        public const float MinFadeTime = 0.1f;

        // The player's handler. teleport(name): moves the player to the TeleportPoint of that name on its
        // next update; false if no TeleportPoint has the name (the message is then counted as unhandled).
        public static void Handle(CommandMgr mgr, int player, RenderVars vars, ScreenFade fade, Func<string, bool> teleport)
        {
            mgr.Handle(player, m =>
            {
                if (m.Is("TELEPORT")) return m.ArgCount >= 1 && teleport(m.Arg(0));
                if (m.Is("FADEIN") || m.Is("FADEOUT"))
                {
                    // Tron's handler: a time under 0.1 s is refused; the optional second argument (sent to
                    // the client as the fade's second type) has no effect we know of.
                    float time = m.ArgCount >= 1 ? CommandMgr.Atof(m.Arg(0)) : 0;
                    if (time < MinFadeTime) return false;
                    fade.Start(m.Is("FADEIN"), time);
                    return true;
                }
                if (m.Is("RAMPCONSOLEVAR"))
                {
                    // <cvar> [start] <end> <period>
                    if (m.ArgCount == 3) vars.Ramp(m.Arg(0), null, Num(m, 1), Num(m, 2));
                    else if (m.ArgCount == 4) vars.Ramp(m.Arg(0), Num(m, 1), Num(m, 2), Num(m, 3));
                    else return false;
                    return true;
                }
                if (m.Is("SINCONSOLEVAR"))
                {
                    // <cvar> {off | stop | revert | restore | <min> <max> <period>}
                    if (m.ArgCount == 4) vars.Sine(m.Arg(0), Num(m, 1), Num(m, 2), Num(m, 3));
                    else if (m.ArgCount == 2 && (Word(m, 1, "off") || Word(m, 1, "stop"))) vars.Stop(m.Arg(0), false);
                    else if (m.ArgCount == 2 && (Word(m, 1, "revert") || Word(m, 1, "restore"))) vars.Stop(m.Arg(0), true);
                    else return false;
                    return true;
                }
                return false;
            });
        }

        // Tron's WorldProperties messages (object.lto; ltjs worldproperties.cpp): each sets the server's
        // variable, then every world variable is copied again to the client. FARZ isn't one of them.
        static readonly Dictionary<string, string> WorldMessages = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "FOGENABLE", "FogEnable" }, { "FOGNEARZ", "FogNearZ" }, { "FOGFARZ", "FogFarZ" },
            { "SKYFOGENABLE", "SkyFogEnable" }, { "SKYFOGNEARZ", "SkyFogNearZ" }, { "SKYFOGFARZ", "SkyFogFarZ" },
            { "SCREENGLOWFOGENABLE", "ScreenGlowFogEnable" }, { "SCREENGLOWFOGNEARZ", "ScreenGlowFogNearZ" },
            { "SCREENGLOWFOGFARZ", "ScreenGlowFogFarZ" },
        };

        public static void HandleWorldProperties(CommandMgr mgr, int id, RenderVars vars)
        {
            mgr.Handle(id, m =>
            {
                if (m.Is("FOGCOLOR"))
                {
                    if (m.ArgCount < 3) return false;
                    vars.SetWorld("FogR", Num(m, 0));
                    vars.SetWorld("FogG", Num(m, 1));
                    vars.SetWorld("FogB", Num(m, 2));
                    return true;
                }
                if (!WorldMessages.TryGetValue(m.Word, out var name) || m.ArgCount < 1) return false;
                vars.SetWorld(name, Num(m, 0));
                return true;
            });
        }

        static float Num(Message m, int i) => CommandMgr.Atof(m.Arg(i));

        static bool Word(Message m, int i, string word) => string.Equals(m.Arg(i), word, StringComparison.OrdinalIgnoreCase);
    }
}
