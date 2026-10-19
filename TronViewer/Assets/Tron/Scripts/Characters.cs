using System;
using System.Collections.Generic;

// Characters (CAIHuman) as objects of the command manager, placed or spawned, and the Spawners that create
// them (docs/research/cutscene-actors.md, spawned actors). Plain C#, no Unity, so
// tools/tests/test_spawned_characters.py compiles it with .NET; LevelBuilder.Spawners.cs draws them.
namespace Tron
{
    // The AI's first two updates (ltjs ai.cpp), the same for placed and spawned characters:
    // - until its first update ends (m_bFirstUpdate), CAI::OnTrigger queues every message it gets, words
    //   joined by spaces, messages by ';' (QueueTriggerMsg), so nothing else handles them yet;
    // - its first update sends its Initial to itself (SendMixedTriggerMsgToObject): parts that are commands
    //   run at once, its messages join the queue;
    // - its second update (PreUpdate) sends the queue to itself as one mixed message, the AI the sender.
    // A character updates on each frame after the one it was created in (the game's AIs update each frame).
    public sealed class Characters
    {
        sealed class State
        {
            public int Id, Created, Updates;
            public string Initial;
            public readonly List<string> Queue = new List<string>();
        }

        readonly CommandMgr commands;
        readonly Func<int> frame;
        readonly List<State> starting = new List<State>();

        // frame: the current frame number (Unity's Time.frameCount).
        public Characters(CommandMgr commands, Func<int> frame)
        {
            this.commands = commands;
            this.frame = frame;
        }

        // A character joined as `id` (placed: at level load; spawned: by its Spawner). Its first-update queue
        // is its first message handler, so call this before giving it any other.
        public void Add(int id, string initial)
        {
            var s = new State { Id = id, Created = frame(), Initial = initial ?? "" };
            commands.Handle(id, m =>
            {
                if (s.Updates > 0) return false;
                s.Queue.Add(m.ToString());
                return true;
            });
            starting.Add(s);
        }

        // Once per frame, after the command table.
        public void Update()
        {
            int now = frame();
            for (int i = 0; i < starting.Count; i++)
            {
                var s = starting[i];
                if (s.Created >= now) continue;
                if (s.Updates == 0)
                {
                    commands.SendMixedTo(s.Id, s.Id, s.Initial);
                    s.Updates = 1;
                    continue;
                }
                s.Updates = 2;
                starting.RemoveAt(i--);
                if (s.Queue.Count > 0) commands.SendMixedTo(s.Id, s.Id, string.Join(";", s.Queue));
            }
        }
    }

    // Spawners whose Target is a character template (ltjs spawner.cpp; the exporter's spawn sites).
    // Spawner::OnTrigger takes every message itself (no GameBase messages):
    // - `spawn [name]`: a copy of the template at the spawner's position and rotation, named `name` ("" when
    //   none: SpawnObjectTemplate renames the copy);
    // - `spawnfrom <object> [name]`: the same at that object's when exactly one object has the name;
    // - `default` / `defaultfrom` spawn the DefaultSpawn class string, which no level sets; any other
    //   message is read as a class to create, which none names: nothing.
    // Each spawn is a new object, joined under its name as a CAIHuman. Then the spawner's InitialCommand
    // runs (IsValidCmd, Process with the spawner as sender and the new character as active target).
    public sealed class Spawners
    {
        sealed class Spawner
        {
            public string InitialCommand = "";
            public readonly Dictionary<int, (int site, string initial)> Sites = new Dictionary<int, (int, string)>();
        }

        readonly CommandMgr commands;
        readonly Characters characters;
        readonly Action<int, int> build;
        readonly Dictionary<int, Spawner> spawners = new Dictionary<int, Spawner>();

        // build(id, site): draws the character just joined as `id` at spawn site `site` and adds its handlers.
        public Spawners(CommandMgr commands, Characters characters, Action<int, int> build)
        {
            this.commands = commands;
            this.characters = characters;
            this.build = build;
        }

        // A Spawner (joined as `id`) with its InitialCommand; it takes messages once it has a site.
        public void AddSpawner(int id, string initialCommand)
        {
            var sp = new Spawner { InitialCommand = initialCommand ?? "" };
            spawners[id] = sp;
            commands.Handle(id, m => OnMessage(id, sp, m));
        }

        // Spawn site `site`: spawner `spawner` creating its template (whose Initial is `initial`) at object
        // `at`'s place (the spawner's own, or a spawnfrom object's).
        public void AddSite(int site, int spawner, int at, string initial)
        {
            if (spawners.TryGetValue(spawner, out var sp)) sp.Sites[at] = (site, initial ?? "");
        }

        bool OnMessage(int id, Spawner sp, Message m)
        {
            if (m.Is("SPAWN")) Spawn(id, sp, id, m.Arg(0));
            else if (m.Is("SPAWNFROM"))
            {
                var from = commands.Named(m.Arg(0));
                Spawn(id, sp, from.Count == 1 && sp.Sites.ContainsKey(from[0]) ? from[0] : id, m.Arg(1));
            }
            return true;
        }

        void Spawn(int id, Spawner sp, int at, string name)
        {
            if (!sp.Sites.TryGetValue(at, out var site)) return;
            int character = commands.Join(name, "CAIHuman");
            characters.Add(character, site.initial);
            build(character, site.site);
            commands.Run(sp.InitialCommand, id, character);
        }
    }
}
