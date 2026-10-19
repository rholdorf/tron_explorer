using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Characters and the Spawners that create them (Characters.cs; docs/research/cutscene-actors.md).
    // Every placed CAIHuman the game creates (not a template, not off in single player) joins Characters at
    // load, so its Initial runs on its first update and its messages wait for its second. A Spawner with a
    // spawn site (tools/export_level.py spawn_sites) creates its template on `spawn` / `spawnfrom`: a new
    // command-manager object under the spawn name, class CAIHuman, which then takes messages by that name
    // like a placed character (its first-update queue, then the GameBase messages: VISIBLE, SOLID, HIDDEN,
    // REMOVE). It is drawn from the template's model instances at the site, standing in its idle from that
    // moment, lit there; no AI behaviour runs.
    public partial class LevelBuilder
    {
        public Characters Characters;   // every character's first updates (JoinCharacters)
        public Spawners Spawners;       // the Spawners that create characters (BuildSpawners)

        // A spawned character's drawn models (the template's root instance first, then its attachments) and
        // its root's model and node Transforms (none when its template draws nothing), by command-manager id.
        public readonly Dictionary<int, SpawnedCharacter> SpawnedCharacters = new Dictionary<int, SpawnedCharacter>();

        public sealed class SpawnedCharacter : CharacterBody
        {
            public int Site;                 // its index in Data.spawnSites
            public ObjectJson Template;      // its props are the character's
        }

        // Right after JoinCommands: a character's first-update queue must be its first message handler.
        void JoinCharacters()
        {
            Characters = new Characters(Commands, () => Time.frameCount);
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                if (o.cls == "CAIHuman" && !o.Bool("Template") && o.Bool("SinglePlayer", true))
                    Characters.Add(i, o.Str("Initial"));
            }
            Root.GetComponent<CommandTicker>().Characters = Characters;
        }

        // After BuildModels: spawned characters are built like its instances.
        void BuildSpawners()
        {
            Spawners = new Spawners(Commands, Characters, SpawnCharacter);
            if (Data.spawnSites == null) return;
            var joined = new HashSet<int>();
            for (int k = 0; k < Data.spawnSites.Length; k++)
            {
                var s = Data.spawnSites[k];
                if (joined.Add(s.spawner)) Spawners.AddSpawner(s.spawner, Data.objects[s.spawner].Str("InitialCommand"));
                Spawners.AddSite(k, s.spawner, s.at, Data.objects[s.template].Str("Initial"));
            }
        }

        void SpawnCharacter(int id, int site)
        {
            var s = Data.spawnSites[site];
            var c = new SpawnedCharacter { Site = site, Template = Data.objects[s.template] };
            SpawnedCharacters[id] = c;
            if (s.model >= 0 && modelRoot)
            {
                var pos = new Vector3(s.pos[0], s.pos[1], s.pos[2]);
                var rot = Quaternion.Euler(s.rot[0] * Mathf.Rad2Deg, s.rot[1] * Mathf.Rad2Deg, s.rot[2] * Mathf.Rad2Deg);
                var name = Commands.Name(id);
                int lit = litModels.Count;
                var go = BuildInstance(s.model, name, pos, rot, s.sunAmount, default, out var built, out var anim);
                if (go)
                {
                    if (anim != null) CharacterAnims[id] = c.Animation = anim;
                    c.Begin(go, Data.models[s.model], built, s.sunAmount);
                    for (int n = 0; n < Data.models.Length; n++)
                        if (Data.models[n].parent == s.model)
                        {
                            var att = BuildInstance(n, name, pos, rot, s.sunAmount, built, out _, out _);
                            if (att) c.AddAttachment(Data.models[n].socket, att);
                        }
                    c.Lit.AddRange(litModels.GetRange(lit, litModels.Count - lit));
                }
            }
            var t = c.Template;
            var start = StartFlags.Visible | If(t.Bool("Solid", true), StartFlags.Solid) | If(t.Bool("Rayhit", true), StartFlags.RayHit);
            if (c.Root) JoinActor(id, c, start);
            else JoinFlags(id, start, f => Show(c.Models, f), () => Deactivate(c.Models));
        }
    }
}
