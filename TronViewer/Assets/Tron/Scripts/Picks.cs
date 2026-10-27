using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace Tron
{
    // A Pick (GLOSSARY.md, Picking; #112): one thing aimed at and confirmed in pick mode, written as one JSON
    // file for seiri to turn into a Piece or a Cut. It says what was chosen, not what to make of it: its level,
    // kind, the fields that identify it there, a name, and points and boxes in LithTech units, the level's own
    // frame (what extracted/ has). Plain C# (System only), so tools/tests/test_picks.py checks it with .NET;
    // PickMode.cs aims and writes.
    //
    // Kinds: "model" (a placed .ltb: object, class, file, skins), "worldModel" (a door, spinner, glass: its
    // world model and class), "worldGeometry" (furniture built into the world: a box), "surface" (a material:
    // texture, second texture, effect, shader, blend), "effect" (a SpecialFX: object, FxName), "cut" (a box).
    public sealed class PickRecord
    {
        public const int Format = 1;

        public readonly string Kind, Level, Name;
        public readonly DateTime Time;
        public LTVec? Hit;
        public PickBox Box;
        readonly List<KeyValuePair<string, object>> identity = new List<KeyValuePair<string, object>>();

        public PickRecord(string kind, string level, string name, DateTime time)
        {
            Kind = kind;
            Level = level ?? "";
            Name = name ?? "";
            Time = time.ToUniversalTime();
        }

        public PickRecord Id(string key, string value) { identity.Add(new KeyValuePair<string, object>(key, value ?? "")); return this; }
        public PickRecord Id(string key, float value) { identity.Add(new KeyValuePair<string, object>(key, value)); return this; }
        public PickRecord Id(string key, string[] values) { identity.Add(new KeyValuePair<string, object>(key, values ?? new string[0])); return this; }

        public string ToJson()
        {
            var sb = new StringBuilder();
            sb.Append("{\n");
            sb.Append($"  \"format\": {Format},\n");
            sb.Append($"  \"level\": {Str(Level)},\n");
            sb.Append($"  \"kind\": {Str(Kind)},\n");
            sb.Append($"  \"name\": {Str(Name)},\n");
            sb.Append($"  \"time\": {Str(Time.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture))},\n");
            sb.Append("  \"identity\": {");
            for (int i = 0; i < identity.Count; i++)
                sb.Append(i == 0 ? "" : ",").Append($"\n    {Str(identity[i].Key)}: {Value(identity[i].Value)}");
            sb.Append(identity.Count > 0 ? "\n  }" : "}");
            if (Hit.HasValue) sb.Append($",\n  \"hit\": {Vec(Hit.Value)}");
            if (Box != null) sb.Append($",\n  \"box\": {{\"min\": {Vec(Box.Min)}, \"max\": {Vec(Box.Max)}}}");
            sb.Append("\n}\n");
            return sb.ToString();
        }

        static string Value(object v)
        {
            switch (v)
            {
                case float f: return Num(f);
                case string[] a:
                    var parts = new string[a.Length];
                    for (int i = 0; i < a.Length; i++) parts[i] = Str(a[i]);
                    return "[" + string.Join(", ", parts) + "]";
                default: return Str((string)v);
            }
        }

        static string Num(float f) => f.ToString("0.###", CultureInfo.InvariantCulture);
        static string Vec(LTVec v) => $"[{Num(v.x)}, {Num(v.y)}, {Num(v.z)}]";

        static string Str(string s)
        {
            var sb = new StringBuilder("\"");
            foreach (char c in s)
            {
                if (c == '"' || c == '\\') sb.Append('\\').Append(c);
                else if (c < ' ') sb.Append($"\\u{(int)c:x4}");
                else sb.Append(c);
            }
            return sb.Append('"').ToString();
        }

        // "<level>_<name>.json" (the level's last path part; the name in lower case, anything but letters and
        // digits a dash; the kind for a name with neither), "-2", "-3", ... after the name while `exists` says that file is already there.
        public string FileName(Func<string, bool> exists)
        {
            var level = Level.Substring(Level.LastIndexOf('/') + 1);
            var name = new StringBuilder();
            foreach (char c in Name.ToLowerInvariant())
                if (char.IsLetterOrDigit(c)) name.Append(c);
                else if (name.Length > 0 && name[name.Length - 1] != '-') name.Append('-');
            var clean = name.ToString().Trim('-');
            var stem = $"{level}_{(clean.Length > 0 ? clean : Kind)}";
            var file = stem + ".json";
            for (int n = 2; exists(file); n++) file = $"{stem}-{n}.json";
            return file;
        }

        // Where Picks go: -picks <dir>, else seiri's requests/ beside this repo (root: the folder holding
        // extracted/ and export/).
        public static string PicksDir(string[] args, string root)
        {
            int i = Array.IndexOf(args, "-picks");
            if (i >= 0 && i + 1 < args.Length && !args[i + 1].StartsWith("-")) return args[i + 1];
            return root == null ? null : Path.GetFullPath(Path.Combine(root, "..", "seiri", "requests"));
        }
    }

    // The suggested island for a worldGeometry Pick: the world triangles connected to the hit one. Furniture
    // built into the world is mostly a separate island (m01-01: 242 islands, consoles some 280 x 112 x 260
    // units); where it shares vertices with the floor or walls the island runs into the rest of the level,
    // so growing stops once its box is wider than maxExtent on any axis and the island has leaked (pick mode
    // then suggests a box around the hit instead). Triangles connect through vertices at the same position
    // (within Weld units), not just shared indices: the exporter splits vertices by UVs and lightmaps.
    public static class PickIsland
    {
        public const float Weld = 0.5f;

        public sealed class Result
        {
            public int[] Triangles;   // ascending
            public LTVec Min, Max;
            public bool Leaked;
        }

        // positions: x, y, z per vertex; indices: three per triangle; seed: a triangle.
        public static Result Grow(float[] positions, int[] indices, int seed, float maxExtent)
        {
            int triCount = indices.Length / 3;
            var byPos = new Dictionary<(long, long, long), List<int>>();
            for (int t = 0; t < triCount; t++)
                for (int k = 0; k < 3; k++)
                {
                    var key = Key(positions, indices[t * 3 + k]);
                    if (!byPos.TryGetValue(key, out var list)) byPos[key] = list = new List<int>();
                    list.Add(t);
                }
            var r = new Result();
            var seen = new HashSet<int> { seed };
            var queue = new Queue<int>();
            queue.Enqueue(seed);
            bool first = true;
            while (queue.Count > 0)
            {
                int t = queue.Dequeue();
                for (int k = 0; k < 3; k++)
                {
                    int v = indices[t * 3 + k];
                    var p = new LTVec(positions[v * 3], positions[v * 3 + 1], positions[v * 3 + 2]);
                    if (first) { r.Min = r.Max = p; first = false; }
                    r.Min = new LTVec(Math.Min(r.Min.x, p.x), Math.Min(r.Min.y, p.y), Math.Min(r.Min.z, p.z));
                    r.Max = new LTVec(Math.Max(r.Max.x, p.x), Math.Max(r.Max.y, p.y), Math.Max(r.Max.z, p.z));
                }
                var e = r.Max - r.Min;
                if (e.x > maxExtent || e.y > maxExtent || e.z > maxExtent) { r.Leaked = true; break; }
                for (int k = 0; k < 3; k++)
                    foreach (int n in byPos[Key(positions, indices[t * 3 + k])])
                        if (seen.Add(n)) queue.Enqueue(n);
            }
            var tris = new List<int>(seen);
            tris.Sort();
            r.Triangles = tris.ToArray();
            return r;
        }

        static (long, long, long) Key(float[] p, int v) =>
            ((long)Math.Round(p[v * 3] / Weld), (long)Math.Round(p[v * 3 + 1] / Weld), (long)Math.Round(p[v * 3 + 2] / Weld));
    }

    // The box a worldGeometry or cut Pick holds, in LithTech units, axis-aligned in the level's frame. Pick mode
    // edits it one face at a time: the selected face (FaceNames order) is pushed out or pulled in, never closer
    // than MinThickness to the opposite one.
    public sealed class PickBox
    {
        public static readonly string[] FaceNames = { "+x", "-x", "+y", "-y", "+z", "-z" };
        public LTVec Min, Max;
        public int Face;
        public float MinThickness;

        public PickBox(LTVec min, LTVec max) { Min = min; Max = max; }

        // The box spanning two corners; an axis thinner than minThickness (two clicks on one floor) grows to it
        // about its middle.
        public static PickBox FromCorners(LTVec a, LTVec b, float minThickness)
        {
            var box = new PickBox(new LTVec(Math.Min(a.x, b.x), Math.Min(a.y, b.y), Math.Min(a.z, b.z)),
                                  new LTVec(Math.Max(a.x, b.x), Math.Max(a.y, b.y), Math.Max(a.z, b.z))) { MinThickness = minThickness };
            for (int axis = 0; axis < 3; axis++)
            {
                float lo = Get(box.Min, axis), hi = Get(box.Max, axis);
                if (hi - lo >= minThickness) continue;
                float mid = (lo + hi) / 2;
                box.Min = Set(box.Min, axis, mid - minThickness / 2);
                box.Max = Set(box.Max, axis, mid + minThickness / 2);
            }
            return box;
        }

        public void NextFace(int step) => Face = ((Face + step) % 6 + 6) % 6;

        // Moves the selected face `amount` units outwards (negative: inwards).
        public void Push(float amount)
        {
            int axis = Face / 2;
            if (Face % 2 == 0)
                Max = Set(Max, axis, Math.Max(Get(Max, axis) + amount, Get(Min, axis) + MinThickness));
            else
                Min = Set(Min, axis, Math.Min(Get(Min, axis) - amount, Get(Max, axis) - MinThickness));
        }

        public LTVec Center => (Min + Max) * 0.5f;
        public LTVec Size => Max - Min;

        static float Get(LTVec v, int axis) => axis == 0 ? v.x : axis == 1 ? v.y : v.z;
        static LTVec Set(LTVec v, int axis, float f) =>
            axis == 0 ? new LTVec(f, v.y, v.z) : axis == 1 ? new LTVec(v.x, f, v.z) : new LTVec(v.x, v.y, f);
    }
}
