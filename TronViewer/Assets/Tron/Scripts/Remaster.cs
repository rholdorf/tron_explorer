using System;
using System.Collections.Generic;
using System.Linq;

namespace Tron
{
    // Remaster mode (GLOSSARY): presentation over faithful mode, never content or behaviour. Each technique has an
    // id and a hook that applies it on or off; F2 toggles the whole set (#96). Plain C#, no Unity, so
    // tools/tests/test_remaster.py compiles it with .NET.
    //
    // -remaster at start switches every technique on; -remaster <ids> (comma-separated) only those, and F2 toggles
    // that same set. Every launch starts faithful otherwise, and nothing is persisted.
    public sealed class Remaster
    {
        // hd: HD textures; aniso: 16x anisotropic filtering on the level's textures (4 in faithful); aa: MSAA 4x
        // with alpha-to-coverage; glow: the 512² glow buffer; ssao: SSAO on the lit term. Applied in this order
        // (aniso reaches the textures hd swapped in).
        public static readonly string[] Ids = { "hd", "aniso", "aa", "glow", "ssao" };

        readonly HashSet<string> set;
        readonly Dictionary<string, Action<bool>> hooks = new Dictionary<string, Action<bool>>();

        public bool On { get; private set; }
        public IReadOnlyCollection<string> Set => set;
        // Ids given to -remaster that aren't techniques (logged by the caller, otherwise ignored).
        public readonly string[] Unknown;

        public Remaster(IEnumerable<string> ids, bool on)
        {
            var given = ids.ToArray();
            set = new HashSet<string>(given.Where(id => Ids.Contains(id)));
            Unknown = given.Where(id => !Ids.Contains(id)).ToArray();
            On = on;
        }

        // From the command line: -remaster alone (or followed by another flag) is every technique.
        public static Remaster FromArgs(IList<string> args)
        {
            int i = args.IndexOf("-remaster");
            if (i < 0) return new Remaster(Ids, false);
            var list = i + 1 < args.Count && !args[i + 1].StartsWith("-") ? args[i + 1] : null;
            if (list == null) return new Remaster(Ids, true);
            return new Remaster(list.Split(',').Select(s => s.Trim().ToLowerInvariant()).Where(s => s.Length > 0), true);
        }

        // Whether a technique is applied now.
        public bool Has(string id) => On && set.Contains(id);

        // A technique's hook, called with Has(id) right away and on every change; techniques outside the set are
        // never called with true.
        public void Register(string id, Action<bool> apply)
        {
            hooks[id] = apply;
            apply(Has(id));
        }

        public void Toggle() => Switch(!On);

        public void Switch(bool on)
        {
            if (on == On) return;
            On = on;
            Apply();
        }

        // Every hook again (a level loaded: its textures and materials take the current mode).
        public void Apply()
        {
            foreach (var id in Ids)
                if (hooks.TryGetValue(id, out var apply)) apply(Has(id));
        }
    }
}
