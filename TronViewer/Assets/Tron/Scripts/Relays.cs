using System;
using System.Collections.Generic;

// The level's triggers and relays, as the engine runs them (docs/research/triggers-doors.md,
// docs/research/command-language.md; ltjs trigger.cpp, noplayertrigger.cpp, eventcounter.cpp,
// commandobject.cpp, startupcommand.cpp, game/shared/timer.h, and Tron's EventCounter RESET). Groups are the command manager's
// (CommandMgr.JoinGroup). Plain C#, no Unity, so tools/tests/test_relays.py compiles it with Mono.
namespace Tron
{
    // Level load: Add each level object after it joined the command manager; it takes the relay classes and
    // adds their message handlers. Each frame, after the command manager's BeginFrame (the server clock they
    // all time on): UpdateTimelines before the command manager's Update (the lite objects update first), then
    // UpdateObjects with the player's box (the objects' update: startup
    // commands, triggers).
    public sealed class Relays
    {
        readonly CommandMgr commands;
        readonly List<Trigger> triggers = new List<Trigger>();
        readonly List<CommandObject> timelines = new List<CommandObject>();
        readonly List<(int id, string command)> startups = new List<(int, string)>();

        public Relays(CommandMgr commands) => this.commands = commands;

        // The server clock (CommandMgr.Time): the timers of command objects and triggers.
        float Time => commands.Time;

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
                case "commandobject":
                {
                    var co = new CommandObject(this, id, p);
                    timelines.Add(co);
                    commands.Handle(id, co.OnMessage);
                    return true;
                }
                case "startupcommand":
                    // Tron's StartupCommand has only Command (no NOLF2 SafeExecute / RoundCondition).
                    startups.Add((id, p.Str("Command")));
                    return true;
                default:
                    return false;
            }
        }

        // The lite objects' update (CommandObject timelines).
        public void UpdateTimelines()
        {
            // A timeline started by another's event this frame updates this frame if it comes later.
            for (int i = 0; i < timelines.Count; i++)
                if (timelines[i].Active) timelines[i].Update();
        }

        // The start point's Command (GameStartPoint), run once at the player's first update
        // (CPlayerObj::SendStartLevelCommand), sender and active target the player; then cleared. Single
        // player: only the start point the player spawned at, never again on a respawn.
        public string StartCommand { get; set; }

        // The objects' update: startup commands, the triggers with the player's touch, then the player's
        // (created after the level's objects, so it updates last): its first update runs StartCommand.
        // player is its command-manager id (-1: no player, as before the spawn), playerMin / playerMax its
        // box (LT units).
        public void UpdateObjects(int player, LTVec playerMin, LTVec playerMax)
        {
            // StartupCommand (startupcommand.cpp): its Command runs at its first update, sender and active
            // target itself, then the object removes itself.
            if (startups.Count > 0)
            {
                var run = startups.ToArray();
                startups.Clear();
                foreach (var s in run) commands.Run(s.command, s.id, s.id);
            }
            foreach (var t in triggers) t.Update(player, playerMin, playerMax);
            if (player >= 0 && StartCommand != null)
            {
                var command = StartCommand;
                StartCommand = null;
                commands.Run(command, player, player);
            }
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

        // CommandObject (commandobject.cpp, a lite object): a timeline of EventTnEm = "<ms>|<command>" (6
        // tracks of 10) that runs each event once its time has passed since ON, then FinishedCommand; the
        // events re-arm, and after NumberOfActivations runs (<= 0: no limit) the object is gone. The timer is
        // the engine's CTimer (timer.h), on the server clock.
        sealed class CommandObject
        {
            sealed class Event
            {
                public float Time;
                public string Command;
                public bool Processed;
            }

            readonly Relays relays;
            readonly int id;
            readonly List<Event> events = new List<Event>();
            readonly string finished;
            readonly int numActivations;
            readonly float totalTime;
            bool locked, removed;
            int timesActivated;
            // CTimer: start t1, duration dt, pause time tp (paused while tp > 0 in the engine; a flag here,
            // since this clock starts at 0).
            float t1, dt, tp;
            bool on, paused;

            public bool Active { get; private set; }   // updated each frame (Activate / Deactivate)

            public CommandObject(Relays relays, int id, Props p)
            {
                this.relays = relays;
                this.id = id;
                for (int track = 0; track < 6; track++)
                    for (int n = 0; n < 10; n++)
                    {
                        // strtok(s, "|") then strtok(NULL, "\0"): leading '|'s are skipped, the time ends at the
                        // next '|', the command is the rest; either missing skips the event.
                        var s = p.Str($"EventT{track}E{n}").TrimStart('|');
                        int bar = s.IndexOf('|');
                        if (bar <= 0 || bar == s.Length - 1) continue;
                        var e = new Event { Time = Atol(s.Substring(0, bar)) / 1000f, Command = s.Substring(bar + 1) };
                        events.Add(e);
                        totalTime = Math.Max(totalTime, e.Time);
                    }
                finished = p.Str("FinishedCommand");
                numActivations = (int)p.Num("NumberOfActivations", -1);
                locked = p.Bool("Locked", false);
            }

            float Now => relays.Time;
            float Elapsed => (paused ? tp : Now) - t1;
            bool Stopped => Elapsed >= dt;

            public bool OnMessage(Message m)
            {
                if (removed) return true;
                if (m.Is("ON") || m.Is("START"))
                {
                    if (events.Count == 0 || locked) return true;
                    if (!on)
                    {
                        t1 = Now;
                        dt = totalTime;
                        on = true;
                        timesActivated++;
                    }
                    Active = true;
                }
                else if (m.Is("OFF") || m.Is("STOP") || m.Is("ABORT"))
                {
                    Stop();
                    Active = false;
                }
                else if (m.Is("PAUSE"))
                {
                    if (on && !paused)
                    {
                        tp = Now;
                        paused = true;
                        Active = false;
                    }
                }
                else if (m.Is("RESUME"))
                {
                    if (on && paused)
                    {
                        t1 += Now - tp;
                        paused = false;
                        Active = true;
                    }
                }
                else if (m.Is("LOCK")) locked = true;
                else if (m.Is("UNLOCK")) locked = false;
                else if (m.Is("REMOVE")) Remove();
                else return false;
                return true;
            }

            void Stop()
            {
                dt = 0;
                on = paused = false;
            }

            void Remove()
            {
                removed = true;
                Active = false;
            }

            public void Update()
            {
                foreach (var e in events)
                {
                    if (e.Processed || e.Time > Elapsed) continue;
                    e.Processed = true;
                    relays.commands.Run(e.Command, id, id);
                }
                if (!Stopped) return;
                Stop();
                if (!string.IsNullOrEmpty(finished)) relays.commands.Run(finished, id, id);
                Active = false;
                foreach (var e in events) e.Processed = false;
                if (numActivations > 0 && timesActivated >= numActivations) Remove();
            }
        }

        // Trigger (trigger.cpp), NoPlayerTrigger (noplayertrigger.cpp) and ExitTrigger (its touch is off; the
        // level switch is out of scope, counted in the report). A box of half-extents Dims around its position, axis-aligned.
        sealed class Trigger
        {
            const int MaxCommands = 10;
            const float PollTime = 0.1f;   // NoPlayerTrigger's UPDATE_DELTA

            readonly Relays relays;
            readonly int id;
            readonly bool noPlayer, touchable;
            readonly string exitSwitch;   // an ExitTrigger's switch for the report (LEVEL / MISSION), else null
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
                if (exit) exitSwitch = p.Bool("ExitMission", false) ? "MISSION" : "LEVEL";
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
                // ExitTrigger::Activate then switches level (or mission, ExitMission): out of scope, counted.
                if (exitSwitch != null) relays.commands.Count("EXIT", relays.commands.Class(id), exitSwitch);
            }
        }
    }
}
