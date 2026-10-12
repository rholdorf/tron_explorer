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
    public sealed class RenderVars
    {
        readonly Dictionary<string, float> client = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);

        // world: the level's WorldProperties values (FogR, FogNearZ, FarZ...).
        public RenderVars(IDictionary<string, float> world)
        {
            foreach (var kv in world) client[kv.Key] = kv.Value;
        }

        public float this[string name] => client.TryGetValue(name, out float v) ? v : 0;

        public void Update(float frameTime) { }
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
                return false;
            });
        }

        public static void HandleWorldProperties(CommandMgr mgr, int id, RenderVars vars) { }
    }
}
