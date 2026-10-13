using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

// The level's command language, as the engine runs it (docs/research/command-language.md; ltjs
// conparse.cpp, commandmgr.cpp, serverutilities.cpp, gamebase.cpp, group.cpp). Plain C#, no Unity, so
// tools/tests/test_command_interpreter.py compiles it with Mono. Command strings stay text all the way:
// the exporter ships them as the objects' string properties and the viewer parses them when they run,
// as the engine does (a delayed command is text, a receiver re-parses its message, a group rebuilds it).
namespace Tron
{
    // The engine's tokenizer (cp_GetNextToken / cp_Parse; the same loop in Tron's Lithtech.exe). Kept in
    // step with tools/commands.py, which the tests check against every command string in the levels.
    public static class ConParse
    {
        public const int MaxArgs = 30;      // the 30th word ends the statement and the whole parse
        public const int MaxArgLen = 256;   // characters kept per word

        enum Token { None, Word, Semicolon }

        static bool Separator(char c) => c == ';' || c <= 31 || c == 127;

        static Token Next(string s, ref int i, StringBuilder tok)
        {
            while (i < s.Length && s[i] == ' ') i++;
            if (i >= s.Length || s[i] == '\0') return Token.None;
            tok.Clear();
            uint depth = 0;   // LTBOOL: unsigned, so a stray ')' wraps it and spaces stop ending words
            for (;; i++)
            {
                char c = i < s.Length ? s[i] : '\0';
                bool end = false;
                if (c == '\0') end = true;
                else if (c == '%')
                {
                    i++;
                    if (i >= s.Length || s[i] == '\0') end = true;
                    else Add(tok, s[i]);
                }
                else if (Separator(c))
                {
                    if (tok.Length == 0) { i++; return Token.Semicolon; }
                    return Token.Word;   // the separator is seen again by the next call
                }
                else if (c == '(')
                {
                    if (++depth != 1) Add(tok, c);
                }
                else if (c == ')')
                {
                    if (--depth == 0) { i++; end = true; }
                    else Add(tok, c);
                }
                else if (c == '"')
                {
                    if (depth != 0) { i++; end = true; }
                    else depth = 1;
                }
                else if (c == ' ' && depth == 0) end = true;
                else Add(tok, c);
                // An empty word ("()") is no token: the parse stops there.
                if (end) return tok.Length > 0 ? Token.Word : Token.None;
            }
        }

        static void Add(StringBuilder tok, char c)
        {
            if (tok.Length < MaxArgLen) tok.Append(c);
        }

        // The statements of a command string, each its words, as ConParse::Parse returns them one by one
        // (empty statements included: CRLF gives one, and every caller skips them).
        public static List<string[]> Statements(string text)
        {
            var output = new List<string[]>();
            var tok = new StringBuilder();
            var words = new List<string>();
            int i = 0;
            text = text ?? "";
            for (;;)
            {
                words.Clear();
                bool more = false;
                for (;;)
                {
                    var t = Next(text, ref i, tok);
                    if (t == Token.None) break;
                    if (t == Token.Semicolon) { more = true; break; }
                    words.Add(tok.ToString());
                    if (words.Count >= MaxArgs) break;
                }
                output.Add(words.ToArray());
                if (!more) return output;
            }
        }

        // The first statement only (CCommandMgr::IsValidCmd, msg's target list).
        public static string[] First(string text) => Statements(text)[0];
    }

    // A message one object receives: one statement of a msg's message, its words as the receiver's
    // ConParse gives them (Words[0] is the message word: "HIDDEN", "on", "goto"...). Words compare in any
    // case, as CParsedMsg tokens do.
    public sealed class Message
    {
        public readonly string[] Words;
        public readonly int Sender;   // the sending object's id (CommandMgr.Name / Class), -1 for none

        public Message(string[] words, int sender)
        {
            Words = words;
            Sender = sender;
        }

        public string Word => Words[0];
        public int ArgCount => Words.Length - 1;
        // The i-th argument after the message word (0-based), "" if there's none.
        public string Arg(int i) => i + 1 < Words.Length ? Words[i + 1] : "";
        public bool Is(string word) => string.Equals(Words[0], word, StringComparison.OrdinalIgnoreCase);
        // CParsedMsg::ReCreateMsg: the words joined by spaces (parentheses and quotes are gone).
        public override string ToString() => string.Join(" ", Words);
    }

    // An object's handling of a message: true if it handled it. An object can have several (its class's,
    // then its base class's), tried in the order they were added until one returns true, the way OnTrigger
    // falls through to the base class. A message no handler takes is counted for the level's report.
    public delegate bool MessageHandler(Message message);

    // The command manager: the registry of named objects, msg dispatch, and the pending-command table.
    //
    // Level load: every level object joins once, in level order (Join; its id is its index in the level's
    // objects), then each builder adds handlers to the objects it builds (Handle). Running: Run(command,
    // sender, activeTarget) for a command property (a trigger's, a key's, the startup command). Each
    // frame: BeginFrame first (the server clock), then Update before the objects update.
    public sealed class CommandMgr
    {
        public const int MaxPending = 100;        // CMDMGR_MAX_PENDING_COMMANDS
        public const int MaxCommandLength = 255;  // a pending command's text (CMDMGR_MAX_COMMAND_LENGTH - 1)
        public const int MaxIdLength = 15;        // a pending command's id (CMDMGR_MAX_ID_LENGTH - 1)
        public const float MaxFrameTime = 0.2f;   // the server's frame time clamp
        public const string NoObject = "(no object)";

        // s_ValidCmds: verb -> word count, verb included (Tron's object.lto has the same table).
        static readonly Dictionary<string, int> Verbs = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            { "LISTCOMMANDS", 1 }, { "MSG", 3 }, { "VMSG", 3 }, { "RAND", 4 }, { "RAND2", 3 }, { "RAND3", 4 },
            { "RAND4", 5 }, { "RAND5", 6 }, { "RAND6", 7 }, { "RAND7", 8 }, { "RAND8", 9 }, { "REPEAT", 6 },
            { "REPEATID", 7 }, { "DELAY", 3 }, { "DELAYID", 4 }, { "LOOP", 4 }, { "LOOPID", 5 }, { "ABORT", 2 },
            { "SET", 3 }, { "ADD", 3 }, { "SUB", 3 }, { "IF", 4 }, { "INT", 3 }, { "OBJ", 3 }, { "WHEN", 4 },
            { "SHOWVAR", 3 },
        };

        // GameBaseLite classes: their names are looked up only when no regular object has the name.
        static readonly HashSet<string> LiteClasses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "CommandObject", "Group",
        };

        sealed class Entry
        {
            public string Name, Class;
            public bool Lite;
            public readonly List<MessageHandler> Handlers = new List<MessageHandler>();
        }

        sealed class Pending
        {
            public string Command, Id = "";
            public float Delay, MinDelay, MaxDelay;
            public int Times = -1;   // counted (REPEAT) runs left; -1 uncounted
            public int Sender, Target;
        }

        public struct UnhandledCount
        {
            public string Verb, Class, Word;
            public int Count;
        }

        readonly List<Entry> objects = new List<Entry>();
        readonly Dictionary<string, List<int>> byName = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);
        readonly Pending[] pending = new Pending[MaxPending];
        readonly Dictionary<(string, string, string), int> unhandled = new Dictionary<(string, string, string), int>();
        readonly Func<double> random;
        // CCommandMgr's m_pActiveSender / m_pActiveTarget. Like the engine, Run and the table set them and
        // clear them afterwards (not restore): statements after a msg that ran other commands see none.
        int activeSender = -1, activeTarget = -1;

        // random: uniform in [0, 1) (GetRandom); System.Random when null.
        public CommandMgr(Func<double> random = null)
        {
            if (random == null)
            {
                var r = new Random();
                random = r.NextDouble;
            }
            this.random = random;
        }

        // ---- Registry ----

        // A level object joins by name and class; returns its id. Names match in any case, and several
        // objects can share one (they all get its messages).
        public int Join(string name, string cls)
        {
            int id = objects.Count;
            objects.Add(new Entry { Name = name ?? "", Class = cls ?? "", Lite = LiteClasses.Contains(cls ?? "") });
            if (!string.IsNullOrEmpty(name))
            {
                if (!byName.TryGetValue(name, out var ids)) byName[name] = ids = new List<int>();
                ids.Add(id);
            }
            return id;
        }

        // Adds a message handler to a joined object (see MessageHandler for the order).
        public void Handle(int id, MessageHandler handler) => objects[id].Handlers.Add(handler);

        // A Group (group.cpp): passes every message on, rebuilt from its words, to each member name, with
        // itself as the sender. Members: its Object1..Object50 names (empty ones skipped).
        public int JoinGroup(string name, IEnumerable<string> members)
        {
            int id = Join(name, "Group");
            var names = members.Where(m => !string.IsNullOrEmpty(m)).ToArray();
            Handle(id, m =>
            {
                var text = m.ToString();
                if (text.Length > MaxCommandLength) text = text.Substring(0, MaxCommandLength);
                foreach (var n in names) Send(id, n, text);
                return true;
            });
            return id;
        }

        public string Name(int id) => id >= 0 && id < objects.Count ? objects[id].Name : "";
        public string Class(int id) => id >= 0 && id < objects.Count ? objects[id].Class : "";

        // ---- Running ----

        // CCommandMgr::IsValidCmd: a string runs only if its first statement is a verb with its exact
        // word count. That's how "*msg", "xmsg" and "(FR)msg" comment a whole string out.
        public static bool IsValid(string command) => VerbCount(ConParse.First(command ?? "")) > 0;

        static int VerbCount(string[] words) =>
            words.Length > 0 && Verbs.TryGetValue(words[0], out int n) && n == words.Length ? n : 0;

        // Runs a command property as every object does: `if (IsValidCmd(s)) Process(s, sender, target)`.
        // sender / activeTarget: object ids or -1. False if the string doesn't run or a verb failed (an
        // ABORT of nothing pending): the statements after a failed one are dropped.
        public bool Run(string command, int sender = -1, int activeTarget = -1) =>
            IsValid(command) && Process(command, sender, activeTarget);

        // SendTriggerMsgToObjects: sends a message to every object named `name` (a lite object only when
        // no regular one has the name), right away. A message that is itself a command runs as one instead.
        public void Send(int sender, string name, string message)
        {
            if (string.IsNullOrEmpty(name))
            {
                if (IsValid(message)) Process(message, sender, -1);
                return;
            }
            if (string.Equals(name, "OtherPlayers", StringComparison.OrdinalIgnoreCase)) return;   // one player
            bool toPlayer = string.Equals(name, "ActivePlayer", StringComparison.OrdinalIgnoreCase) ||
                            string.Equals(name, "player", StringComparison.OrdinalIgnoreCase);
            if (toPlayer) name = "player";

            var found = new List<int>();
            if (byName.TryGetValue(name, out var ids))
                found.AddRange(ids.Where(i => !objects[i].Lite));
            // To the player: the sender becomes the active player.
            if (toPlayer && found.Count > 0) sender = found[0];
            if (IsValid(message))
            {
                Process(message, sender, found.Count > 0 ? found[0] : -1);
                return;
            }
            if (found.Count == 0 && ids != null)
            {
                int lite = ids.FindIndex(i => objects[i].Lite);   // only the first one
                if (lite >= 0) found.Add(ids[lite]);
            }
            if (found.Count == 0)
            {
                foreach (var words in ConParse.Statements(message))
                    if (words.Length > 0) Count("MSG", NoObject, words[0]);
                return;
            }
            foreach (var id in found) Deliver(sender, id, message);
        }

        // ---- The server clock ----

        // The server's time (s since the level loaded) and this frame's time, both from clamped frame times.
        // Everything timed on the server runs on it: the pending-command table, the relays' timers, doors.
        public float Time { get; private set; }
        public float FrameTime { get; private set; }

        // A new server frame, before anything updates: the clock advances by the frame time, clamped.
        public void BeginFrame(float frameTime)
        {
            FrameTime = Math.Min(frameTime, MaxFrameTime);
            Time += FrameTime;
        }

        // The pending-command table, once per frame before the objects update (the server shell's
        // CCommandMgr::Update): slots in index order, each delay counted down by the frame time.
        public void Update()
        {
            float dt = FrameTime;
            for (int i = 0; i < MaxPending; i++)
            {
                var p = pending[i];
                if (p == null) continue;
                p.Delay -= dt;
                if (p.Delay > 0) continue;
                activeTarget = p.Target;
                activeSender = p.Sender;
                ProcessCmd(p.Command, i);
                activeTarget = activeSender = -1;
                if (pending[i] != p) continue;   // it aborted itself
                if (p.Times >= 0 && --p.Times <= 0) { pending[i] = null; continue; }
                if (p.MaxDelay > 0) p.Delay = RandomFloat(p.MinDelay, p.MaxDelay);
                else pending[i] = null;
            }
        }

        public int PendingCount => pending.Count(p => p != null);

        // ---- Report ----

        // Messages no handler took (verb MSG, the target's class or NoObject, the message word) and verbs
        // the viewer doesn't run (variables: INT, SET, ADD, SUB, IF, WHEN, OBJ, VMSG...), and what objects count
        // themselves (an ExitTrigger's level switch), most frequent first.
        public IEnumerable<UnhandledCount> Unhandled =>
            unhandled.OrderByDescending(kv => kv.Value).ThenBy(kv => kv.Key.Item1).ThenBy(kv => kv.Key.Item2)
                .ThenBy(kv => kv.Key.Item3)
                .Select(kv => new UnhandledCount { Verb = kv.Key.Item1, Class = kv.Key.Item2, Word = kv.Key.Item3, Count = kv.Value });

        // The console report: one line per (verb, class, message) with its count.
        public string Report(string level)
        {
            var rows = Unhandled.ToList();
            var sb = new StringBuilder();
            sb.Append($"{level}: {rows.Sum(r => r.Count)} commands and messages nobody handled ({rows.Count} kinds)");
            foreach (var r in rows)
                sb.Append($"\n{r.Count,6}  {r.Verb} {r.Class} {r.Word}".TrimEnd());
            return sb.ToString();
        }

        // Counts something the viewer skips for the report: one row per (verb, class, word).
        public void Count(string verb, string cls, string word)
        {
            var key = (verb.ToUpperInvariant(), cls, word.ToUpperInvariant());
            unhandled.TryGetValue(key, out int n);
            unhandled[key] = n + 1;
        }

        // ---- The command manager ----

        bool Process(string command, int sender, int target)
        {
            activeSender = sender;
            activeTarget = target;
            bool ok = ProcessCmd(command, -1);
            activeSender = activeTarget = -1;
            return ok;
        }

        // ProcessCmd: every statement whose verb and word count are right runs; a verb that fails stops the
        // rest. slot: the pending slot running this command (-1 for none), which a delay must not reuse.
        bool ProcessCmd(string command, int slot)
        {
            foreach (var words in ConParse.Statements(command))
            {
                if (VerbCount(words) == 0) continue;
                if (!Execute(words, slot)) return false;
            }
            return true;
        }

        bool Execute(string[] w, int slot)
        {
            var verb = w[0].ToUpperInvariant();
            switch (verb)
            {
                case "MSG":
                    foreach (var target in ConParse.First(w[1]))
                    {
                        // "<Class>Name": only the name counts; no name means the active target.
                        var name = target;
                        int lt = name.IndexOf('<'), gt = lt >= 0 ? name.IndexOf('>', lt) : -1;
                        if (gt >= 0) name = name.Substring(gt + 1);
                        if (name.Length == 0 && activeTarget >= 0) name = objects[activeTarget].Name;
                        if (name.Length > 0) Send(activeSender, name, w[2]);
                    }
                    return true;
                case "DELAY": return Queue(w[2], "", Atof(w[1]), 0, 0, -1, -1, slot);
                case "DELAYID": return Queue(w[3], w[1], Atof(w[2]), 0, 0, -1, -1, slot);
                case "LOOP": return Queue(w[3], "", 0, Atof(w[1]), Atof(w[2]), -1, -1, slot);
                case "LOOPID": return Queue(w[4], w[1], 0, Atof(w[2]), Atof(w[3]), -1, -1, slot);
                case "REPEAT": return Queue(w[5], "", 0, Atof(w[3]), Atof(w[4]), Atol(w[1]), Atol(w[2]), slot);
                case "REPEATID": return Queue(w[6], w[1], 0, Atof(w[4]), Atof(w[5]), Atol(w[2]), Atol(w[3]), slot);
                case "ABORT":
                    for (int i = 0; i < MaxPending; i++)
                        if (pending[i] != null && pending[i].Id.Length > 0 &&
                            string.Equals(pending[i].Id, w[1], StringComparison.OrdinalIgnoreCase))
                        {
                            pending[i] = null;   // only the first one with that id
                            return true;
                        }
                    return false;
                case "RAND":
                {
                    float p = Atof(w[1]);
                    if (p < 0.001f || p > 1f) return false;
                    var cmd = RandomFloat(0, 1) < p ? w[2] : w[3];
                    return IsValid(cmd) && ProcessCmd(cmd, slot);
                }
                case "INT": case "OBJ": case "IF": case "WHEN": case "VMSG": case "SHOWVAR": case "LISTCOMMANDS":
                    // No variables (the levels' only WHEN never fires): accepted, nothing happens.
                    Count(verb, "", "");
                    return true;
                case "SET": case "ADD": case "SUB":
                    // No variable is declared, so these fail like the engine's on an unknown variable.
                    Count(verb, "", "");
                    return false;
                default:   // RAND2..RAND8: one of the commands, uniformly
                {
                    int k = RandomInt(1, w.Length - 1);
                    return IsValid(w[k]) && ProcessCmd(w[k], slot);
                }
            }
        }

        // AddDelayedCmd, for a verb whose nested command is valid (it fails otherwise). maxDelay > 0: a
        // random delay in [minDelay, maxDelay], drawn again after each run (LOOP, REPEAT); maxTimes > 0:
        // runs a random number of times in [minTimes, maxTimes]. The first free slot that isn't the
        // running one; a full table runs the command now and fails.
        bool Queue(string command, string id, float delay, float minDelay, float maxDelay, int minTimes, int maxTimes, int slot)
        {
            if (!IsValid(command)) return false;
            for (int i = 0; i < MaxPending; i++)
            {
                if (pending[i] != null || i == slot) continue;
                pending[i] = new Pending
                {
                    Command = command.Length > MaxCommandLength ? command.Substring(0, MaxCommandLength) : command,
                    Id = id.Length > MaxIdLength ? id.Substring(0, MaxIdLength) : id,
                    Times = maxTimes > 0 ? RandomInt(minTimes, maxTimes) : -1,
                    MinDelay = minDelay, MaxDelay = maxDelay,
                    Delay = maxDelay > 0 ? RandomFloat(minDelay, maxDelay) : delay,
                    Sender = activeSender, Target = activeTarget,
                };
                return true;
            }
            ProcessCmd(command, -1);
            return false;
        }

        float RandomFloat(float min, float max) => min + (max - min) * (float)random();

        int RandomInt(int min, int max) => Math.Min(max, min + (int)(random() * (max - min + 1)));

        // C atof / atol: the longest leading number, 0 if there's none.
        public static float Atof(string s)
        {
            int i = 0, n = s.Length;
            while (i < n && char.IsWhiteSpace(s[i])) i++;
            int start = i;
            if (i < n && (s[i] == '+' || s[i] == '-')) i++;
            int digits = 0;
            while (i < n && char.IsDigit(s[i])) { i++; digits++; }
            if (i < n && s[i] == '.') { i++; while (i < n && char.IsDigit(s[i])) { i++; digits++; } }
            if (digits == 0) return 0;
            if (i < n && (s[i] == 'e' || s[i] == 'E'))
            {
                int j = i + 1;
                if (j < n && (s[j] == '+' || s[j] == '-')) j++;
                if (j < n && char.IsDigit(s[j])) { i = j; while (i < n && char.IsDigit(s[i])) i++; }
            }
            return float.TryParse(s.Substring(start, i - start), System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out float v) ? v : 0;
        }

        static int Atol(string s) => (int)Atof(s.Split('.', 'e', 'E')[0]);

        void Deliver(int sender, int id, string message)
        {
            // SendTriggerMsgToObject: a command runs as one, with this object as the active target.
            if (IsValid(message))
            {
                Process(message, sender, id);
                return;
            }
            // GameBase::TriggerMsg: one OnTrigger per statement of the message.
            var o = objects[id];
            foreach (var words in ConParse.Statements(message))
            {
                if (words.Length == 0) continue;
                var m = new Message(words, sender);
                bool handled = false;
                foreach (var h in o.Handlers)
                    if (h(m)) { handled = true; break; }
                if (!handled) Count("MSG", o.Class, words[0]);
            }
        }
    }
}
