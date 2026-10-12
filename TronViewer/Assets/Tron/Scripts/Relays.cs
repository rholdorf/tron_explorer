using System;
using System.Collections.Generic;

// The level's triggers and relays, as the engine runs them (docs/research/triggers-doors.md,
// docs/research/command-language.md; ltjs trigger.cpp, noplayertrigger.cpp, eventcounter.cpp,
// commandobject.cpp, game/shared/timer.h, and Tron's EventCounter RESET). Groups are the command manager's
// (CommandMgr.JoinGroup). Plain C#, no Unity, so tools/tests/test_relays.py compiles it with Mono.
namespace Tron
{
    // Level load: Add each level object after it joined the command manager; it takes the relay classes and
    // adds their message handlers. Each frame: UpdateTimelines before the command manager's Update (the lite
    // objects update first), then UpdateTriggers with the player's box (the objects' update).
    public sealed class Relays
    {
        const float MaxFrameTime = CommandMgr.MaxFrameTime;

        readonly CommandMgr commands;
        readonly List<Trigger> triggers = new List<Trigger>();

        public Relays(CommandMgr commands) => this.commands = commands;

        // The server clock (s since the level loaded): clamped frame times, as the pending-command table's.
        public float Time { get; private set; }

        // A level object (its command-manager id, class, position and props: strings, and numbers, bools
        // and vectors as floats). False if it isn't a relay class.
        public bool Add(int id, string cls, LTVec pos, IReadOnlyDictionary<string, string> strs,
            IReadOnlyDictionary<string, float[]> nums)
        {
            var p = new Props(strs, nums);
            switch (cls.ToLowerInvariant())
            {
                case "trigger": case "noplayertrigger": case "exittrigger":
                {
                    var t = new Trigger(this, id, cls, pos, p);
                    triggers.Add(t);
                    commands.Handle(id, t.OnMessage);
                    return true;
                }
                case "eventcounter":
                    commands.Handle(id, new EventCounter(commands, id, p).OnMessage);
                    return true;
                default:
                    return false;
            }
        }

        // The lite objects' update (CommandObject timelines); it advances the clock.
        public void UpdateTimelines(float frameTime)
        {
            Time += Math.Min(frameTime, MaxFrameTime);
        }

        // The triggers' update and the player's touch: player is its command-manager id (-1: no player, as
        // before the spawn), playerMin / playerMax its box (LT units).
        public void UpdateTriggers(int player, LTVec playerMin, LTVec playerMax)
        {
            foreach (var t in triggers) t.Update(player, playerMin, playerMax);
        }

        readonly struct Props
        {
            readonly IReadOnlyDictionary<string, string> strs;
            readonly IReadOnlyDictionary<string, float[]> nums;

            public Props(IReadOnlyDictionary<string, string> strs, IReadOnlyDictionary<string, float[]> nums)
            {
                this.strs = strs;
                this.nums = nums;
            }

            public string Str(string k) => strs != null && strs.TryGetValue(k, out var s) ? s ?? "" : "";
            public float Num(string k, float def) =>
                nums != null && nums.TryGetValue(k, out var v) && v != null && v.Length > 0 ? v[0] : def;
            public bool Bool(string k, bool def) => Num(k, def ? 1 : 0) != 0;
            public LTVec Vec(string k, LTVec def) =>
                nums != null && nums.TryGetValue(k, out var v) && v != null && v.Length >= 3 ? new LTVec(v[0], v[1], v[2]) : def;
        }

        // C atol: the leading integer, 0 if there's none.
        static int Atol(string s)
        {
            int i = 0, n = 0, sign = 1;
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
            if (i < s.Length && (s[i] == '+' || s[i] == '-')) sign = s[i++] == '-' ? -1 : 1;
            while (i < s.Length && char.IsDigit(s[i])) n = n * 10 + (s[i++] - '0');
            return sign * n;
        }

        // EventCounter (eventcounter.cpp): a count that runs EventNIncToValCmd / EventNDecToValCmd of every
        // event whose EventNValue it steps onto (sender and active target the counter). Tron adds RESET:
        // back to StartingValue, running nothing.
        sealed class EventCounter
        {
            const int MaxEvents = 10;

            readonly CommandMgr commands;
            readonly int id, start;
            readonly int[] values = new int[MaxEvents];
            readonly string[] inc = new string[MaxEvents], dec = new string[MaxEvents];
            int count;
            bool locked;

            public EventCounter(CommandMgr commands, int id, Props p)
            {
                this.commands = commands;
                this.id = id;
                for (int i = 0; i < MaxEvents; i++)
                {
                    values[i] = (int)p.Num($"Event{i + 1}Value", -1);
                    inc[i] = p.Str($"Event{i + 1}IncToValCmd");
                    dec[i] = p.Str($"Event{i + 1}DecToValCmd");
                }
                count = start = (int)p.Num("StartingValue", 0);
            }

            public bool OnMessage(Message m)
            {
                // INC/DEC [n]: n steps, at least one.
                int steps = Math.Max(1, m.ArgCount > 0 ? Atol(m.Arg(0)) : 1);
                if (m.Is("INC") || m.Is("INCREMENT"))
                    for (int i = 0; i < steps; i++) Step(+1);
                else if (m.Is("DEC") || m.Is("DECREMENT"))
                    for (int i = 0; i < steps; i++) Step(-1);
                else if (m.Is("LOCK")) locked = true;
                else if (m.Is("UNLOCK")) locked = false;
                else if (m.Is("RESET")) count = start;
                else if (m.Is("REPORT")) { }   // prints the count to the game's console
                else return false;
                return true;
            }

            void Step(int by)
            {
                if (locked || (by < 0 && count <= 0)) return;
                count += by;
                var cmds = by > 0 ? inc : dec;
                for (int i = 0; i < MaxEvents; i++)
                    if (values[i] == count && !string.IsNullOrEmpty(cmds[i])) commands.Run(cmds[i], id, id);
            }
        }

        // Trigger (trigger.cpp), NoPlayerTrigger (noplayertrigger.cpp) and ExitTrigger (its touch is off; the
        // level switch is out of scope). A box of half-extents Dims around its position, axis-aligned.
        sealed class Trigger
        {
            const int MaxCommands = 10;
            const float PollTime = 0.1f;   // NoPlayerTrigger's UPDATE_DELTA

            readonly Relays relays;
            readonly int id;
            readonly bool noPlayer, touchable;
            readonly LTVec min, max;
            readonly string[] commandList = new string[MaxCommands];
            readonly float triggerDelay, sendDelay;
            readonly int activationCount, numActivations;
            bool locked, removed;
            float lastTouch = float.NegativeInfinity;   // never touched (the engine's 0 is a server time)
            bool active = true, delaying, polling;
            float startDelay, nextPoll;
            int currentActivation, timesActivated;
            int toucher = -1;

            public Trigger(Relays relays, int id, string cls, LTVec pos, Props p)
            {
                this.relays = relays;
                this.id = id;
                noPlayer = string.Equals(cls, "NoPlayerTrigger", StringComparison.OrdinalIgnoreCase);
                bool exit = string.Equals(cls, "ExitTrigger", StringComparison.OrdinalIgnoreCase);
                touchable = !noPlayer && !exit && p.Bool("PlayerTriggerable", true);
                var dims = p.Vec("Dims", new LTVec(5, 5, 5));
                min = pos - dims;
                max = pos + dims;
                for (int i = 0; i < MaxCommands; i++) commandList[i] = p.Str("Command" + (i + 1));
                triggerDelay = p.Num("TriggerDelay", 0);
                sendDelay = p.Num("SendDelay", 0);
                activationCount = (int)p.Num("ActivationCount", 1);
                numActivations = (int)p.Num("NumberOfActivations", 1);
                locked = p.Bool("Locked", false);
            }

            float Now => relays.Time;

            public bool OnMessage(Message m)
            {
                if (removed) return true;
                if (m.Is("TRIGGER")) DoTrigger(m.Sender);
                else if (m.Is("LOCK")) locked = true;
                else if (m.Is("UNLOCK")) locked = false;   // doesn't fire it
                else if (m.Is("REMOVE")) removed = true;
                else return false;
                return true;
            }

            public void Update(int player, LTVec pMin, LTVec pMax)
            {
                if (removed) return;
                // The engine's MID_UPDATE: a pending SendDelay, then NoPlayerTrigger's poll.
                if (delaying) UpdateDelayingActivate();
                if (polling && Now >= nextPoll)
                {
                    if (player >= 0 && Overlaps(pMin, pMax)) nextPoll = Now + PollTime;
                    else
                    {
                        polling = false;
                        Activate();
                    }
                }
                // The touch notify, every frame the player's box overlaps the trigger's.
                if (touchable && player >= 0 && Overlaps(pMin, pMax)) DoTrigger(player);
            }

            bool Overlaps(LTVec a, LTVec b) =>
                a.x < max.x && b.x > min.x && a.y < max.y && b.y > min.y && a.z < max.z && b.z > min.z;

            // DoTrigger: TriggerDelay holds touches and messages alike; a locked or waiting trigger still takes
            // the time.
            void DoTrigger(int sender)
            {
                if (Now < lastTouch + triggerDelay) return;
                lastTouch = Now;
                toucher = sender;
                if (active && !locked) RequestActivate();
            }

            // RequestActivate: inactive until SendDelay is over, checked now without a TriggerDelay, else from
            // the next update on.
            void RequestActivate()
            {
                startDelay = Now;
                delaying = true;
                active = false;
                if (triggerDelay <= 0) UpdateDelayingActivate();
            }

            void UpdateDelayingActivate()
            {
                if (Now < startDelay + sendDelay) return;
                // NoPlayerTrigger::Activate only starts the wait for the player to leave.
                if (noPlayer)
                {
                    if (!polling) nextPoll = Now + PollTime;
                    polling = true;
                }
                else Activate();
                delaying = false;
                active = true;
            }

            // Trigger::Activate: every ActivationCount-th activation, at most NumberOfActivations times
            // (<= 0: no limit), runs Command1..10 with the toucher as the sender.
            void Activate()
            {
                if (++currentActivation < activationCount) return;
                currentActivation = 0;
                if (numActivations > 0)
                {
                    if (timesActivated >= numActivations) return;
                    timesActivated++;
                }
                int sender = toucher;
                toucher = -1;
                foreach (var c in commandList)
                    if (!string.IsNullOrEmpty(c)) relays.commands.Run(c, sender, id);
            }
        }
    }
}
