using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // The level's dialogues (Dialogues): each Dialogue object (not a template) joins with its GameBase handler
    // and ON / OFF, and is updated each frame after the command table (CommandTicker). Its speakers are found by
    // name when it plays, so spawned characters and the player (joined after the build) speak too. A voice plays
    // from the speaker (DialogueVoices): a character's drawn model, else the object's place; the subtitle is drawn
    // by TronExplorer from Subtitles. A scene camera that is live mutes the speakers that aren't cinematic.
    public partial class LevelBuilder
    {
        public Dialogues Dialogues;
        public readonly Subtitles Subtitles = new Subtitles();
        // The game string with an id (hud/strings.json), null if none; set before Build.
        public Func<int, string> GameString = _ => null;

        Dictionary<string, SpeakerJson> placedSpeakers, templateSpeakers;
        readonly Dictionary<int, Transform> speakerPlaces = new Dictionary<int, Transform>();

        // After BuildSceneCameras and BuildSpawners.
        void BuildDialogues()
        {
            placedSpeakers = new Dictionary<string, SpeakerJson>(StringComparer.OrdinalIgnoreCase);
            templateSpeakers = new Dictionary<string, SpeakerJson>(StringComparer.OrdinalIgnoreCase);
            foreach (var s in Data.speakers ?? new SpeakerJson[0])
                (s.template ? templateSpeakers : placedSpeakers)[s.name] = s;   // the last of a name, as spawn sites take it
            Dialogues = new Dialogues(Commands, Subtitles, SpeakerInfo, () => SceneCameras != null && SceneCameras.Live != null,
                                      id => GameString(id));
            var voices = Root.AddComponent<DialogueVoices>();
            voices.Host = SpeakerTransform;
            Dialogues.PlayVoice = voices.Play;
            Dialogues.KillVoice = voices.Kill;
            Dialogues.SpeakerPos = id => ToLT(SpeakerTransform(id).position);
            Dialogues.ListenerPos = () => ToLT(ListenerPosition());
            Root.GetComponent<CommandTicker>().Dialogues = Dialogues;

            var list = Data.dialogues ?? new DialogueJson[0];
            int k = 0;
            for (int i = 0; i < Data.objects.Length && k < list.Length; i++)
            {
                var o = Data.objects[i];
                if (o.cls != "Dialogue") continue;
                var d = list[k++];
                if (o.Bool("Template")) continue;
                var lines = new DialogueLine[d.lines?.Length ?? 0];
                for (int n = 0; n < lines.Length; n++)
                {
                    var l = d.lines[n];
                    lines[n] = new DialogueLine { Id = l.id, Speaker = l.speaker, Delay = l.delay, Command = l.command, Voice = l.voice, Duration = l.duration };
                }
                var p = new DialogueProps
                {
                    StartCommand = d.startCommand ?? "", FinishedCommand = d.finishedCommand ?? "", CleanUpCommand = d.cleanUpCommand ?? "",
                    RemoveWhenComplete = d.removeWhenComplete, Lines = lines,
                };
                var flags = JoinFlags(i, StartFlags.None, null, null);
                Commands.Handle(i, Dialogues.Add(i, p, flags).OnMessage);
            }
        }

        // A character's voice radius and IsCinematicAI: a placed one's from its own entry, a spawned one's from
        // its template's; the player's is its own (Dialogues.PlayerRadius).
        (float radius, bool cinematic) SpeakerInfo(int id)
        {
            SpeakerJson s = null;
            if (SpawnedCharacters.TryGetValue(id, out var sc)) templateSpeakers.TryGetValue(sc.Template.name, out s);
            else placedSpeakers.TryGetValue(Commands.Name(id), out s);
            return s != null ? (s.radius, s.cinematic) : (Dialogues.PlayerRadius, false);
        }

        // What a speaker's voice follows: its drawn model (a placed or spawned character), else a point at the
        // object's place (a Speaker; a character that draws nothing), else the level root (the player's lines are
        // unpositioned).
        Transform SpeakerTransform(int id)
        {
            var body = Body(id);
            if (body != null && body.Root) return body.Root.transform;
            if (modelObjects.TryGetValue(id, out var gos) && gos.Count > 0 && gos[0]) return gos[0].transform;
            if (speakerPlaces.TryGetValue(id, out var t)) return t;
            if (id < 0 || id >= Data.objects.Length) return Root.transform;
            var go = new GameObject("Speaker " + Data.objects[id].name);
            go.transform.SetParent(Root.transform, false);
            go.transform.localPosition = Data.objects[id].Position;
            return speakerPlaces[id] = go.transform;
        }

        LTVec ToLT(Vector3 world)
        {
            var p = Root.transform.InverseTransformPoint(world);
            return new LTVec(p.x, p.y, p.z);
        }

        static AudioListener listener;

        static Vector3 ListenerPosition()
        {
            if (!listener || !listener.isActiveAndEnabled) listener = UnityEngine.Object.FindFirstObjectByType<AudioListener>();
            return listener ? listener.transform.position : Vector3.zero;
        }
    }
}
