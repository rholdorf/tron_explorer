using System;
using System.Collections.Generic;

// Dialogues and their subtitles (docs/research/dialogue.md on research/dialogue; ltjs dialogue.cpp,
// character.cpp, characterfx.cpp, hudsubtitles.cpp, with Tron's changes). Plain C#, no Unity, so
// tools/tests/test_dialogues.py compiles it with .NET; LevelBuilder.Dialogues.cs plays the voices and
// TronExplorer draws the subtitle.
namespace Tron
{
    // A dialogue line as the exporter writes it (tools/dialogue.py): slot N's "<id> <speaker>", DelayN (the wait
    // before it) and StartDialogueCommandN; Voice is the file the id names ("" for ids under 1000 and cut lines),
    // Duration how long it plays (0 without one).
    public struct DialogueLine
    {
        public int Id;
        public string Speaker, Command, Voice;
        public float Delay, Duration;
    }

    public sealed class DialogueProps
    {
        public string StartCommand = "", FinishedCommand = "", CleanUpCommand = "";
        public bool RemoveWhenComplete = true;
        public DialogueLine[] Lines = new DialogueLine[0];
    }

    // A voice the viewer plays: the speaker (a command-manager id), the line's id and file, how long it lasts;
    // Local: unpanned at full volume (the player's own lines, the IO camera target's, and every line while a scene camera is on), else
    // 3D from the speaker, outer radius Radius and inner InnerRadiusPercent of it.
    public struct DialogueVoice
    {
        public int Speaker, Id;
        public string File;
        public bool Local;
        public float Radius, Duration;
    }

    // The level's dialogues, and each character's dialogue sound (CCharacter's m_eCurDlgSndType: one at a time,
    // a new line kills the one it was saying). A line lasts until its voice has played (the client reports the
    // sound done; here at the first update after its duration ran out on the server clock); a line with no sound
    // ends at once.
    //
    // Where the voice plays (PlayLipSyncSound): the player client-local; an AI (CAIHuman) and a Speaker 3D from
    // the object with its radius. While a scene camera is on only the player and IsCinematicAI characters are
    // heard, client-local at radius 10000; any other speaker's line ends silently, with no subtitle. The voice is
    // subtitled with the game string of its id (Subtitles).
    public sealed class Dialogues
    {
        public const int BaseSoundId = 1000;               // SMGR_BASE_SOUND_ID: lower ids name no file (00000)
        public const float CinematicRadius = 10000;        // DialogueCinematicSndRadius
        public const float InnerRadiusPercent = 0.25f;     // SMGR_DEFAULT_INNERRADIUSPERCENT
        public const float PlayerRadius = 512;             // CPlayerObj's sound radius
        public const string PlayerClass = "Player", AIClass = "CAIHuman", SpeakerClass = "Speaker";

        readonly CommandMgr commands;
        readonly Subtitles subtitles;
        readonly Func<int, (float radius, bool cinematic)> speakerInfo;
        readonly Func<bool> sceneLive;
        readonly Func<int, string> gameString;
        readonly List<Dialogue> dialogues = new List<Dialogue>();

        sealed class Talk { public float End; }
        readonly Dictionary<int, Talk> talking = new Dictionary<int, Talk>();
        readonly List<int> ended = new List<int>();

        // The viewer plays a voice / cuts a speaker's voice.
        public Action<DialogueVoice> PlayVoice;
        public Action<int> KillVoice;
        // Where a speaker is (its subtitle's range), and the listener (LT units).
        public Func<int, LTVec> SpeakerPos;
        public Func<LTVec> ListenerPos;
        // The speaker is the IO camera's target (IOCam.Target): Tron plays its lines CLIENTLOCAL (cshell.dll
        // 0x1016bb20), scene camera or not, so it is heard and subtitled wherever it stands.
        public Func<int, bool> IsIOCamTarget;

        // speakerInfo(id): a character's voice radius and IsCinematicAI; sceneLive: a scene camera is the view
        // (PlayerMgr "using external camera"); gameString(id): the string with that id, null if none.
        public Dialogues(CommandMgr commands, Subtitles subtitles, Func<int, (float radius, bool cinematic)> speakerInfo,
                         Func<bool> sceneLive, Func<int, string> gameString)
        {
            this.commands = commands;
            this.subtitles = subtitles;
            this.speakerInfo = speakerInfo;
            this.sceneLive = sceneLive;
            this.gameString = gameString;
        }

        internal CommandMgr Commands => commands;
        internal float Now => commands.Time;

        // A Dialogue object joined as `id`; give it its messages with Commands.Handle(id, d.OnMessage) after its
        // GameBase handler (flags: a removed dialogue takes nothing and stops).
        public Dialogue Add(int id, DialogueProps p, GameBaseFlags flags)
        {
            var d = new Dialogue(this, id, p, flags);
            dialogues.Add(d);
            return d;
        }

        public IReadOnlyList<Dialogue> All => dialogues;

        // Each frame, after the command table: the voices that ended (the client's report, which also takes their
        // subtitle down), then each dialogue's update, then the subtitle's clock.
        public void Update(float frameTime)
        {
            float now = Now;
            ended.Clear();
            foreach (var kv in talking)
                if (now >= kv.Value.End) ended.Add(kv.Key);
            foreach (var id in ended)
            {
                subtitles.Clear(talking[id]);
                talking.Remove(id);
            }
            for (int i = 0; i < dialogues.Count; i++) dialogues[i].Update();
            subtitles.Update(frameTime);
        }

        // IsPlayingDialogue.
        internal bool IsTalking(int speaker) => talking.ContainsKey(speaker);

        internal static bool IsCharacter(string cls) =>
            string.Equals(cls, PlayerClass, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(cls, AIClass, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(cls, SpeakerClass, StringComparison.OrdinalIgnoreCase);

        // CCharacter::PlayDialogue: ids under 1000 play nothing (and leave the current sound); otherwise the
        // speaker's current line is cut, then the client plays the new one, or doesn't (no file, or muted by a
        // scene).
        internal void PlayDialogue(int speaker, DialogueLine line)
        {
            if (line.Id < BaseSoundId) return;
            StopDialogue(speaker);
            if (string.IsNullOrEmpty(line.Voice) || line.Duration <= 0) return;   // a cut line: NullSound, no file
            var cls = commands.Class(speaker);
            bool player = string.Equals(cls, PlayerClass, StringComparison.OrdinalIgnoreCase);
            var (radius, cinematic) = speakerInfo(speaker);
            bool scene = sceneLive();
            bool io = !player && IsIOCamTarget != null && IsIOCamTarget(speaker);
            if (scene && !player && !io && !(cinematic && string.Equals(cls, AIClass, StringComparison.OrdinalIgnoreCase))) return;
            bool local = player || scene || io;
            if (scene) radius = CinematicRadius;
            else if (player) radius = PlayerRadius;
            var talk = new Talk { End = Now + line.Duration };
            talking[speaker] = talk;
            PlayVoice?.Invoke(new DialogueVoice
            {
                Speaker = speaker, Id = line.Id, File = line.Voice, Local = local, Radius = radius, Duration = line.Duration,
            });
            var text = gameString(line.Id);
            var listener = ListenerPos != null ? ListenerPos() : default;
            var pos = local || SpeakerPos == null ? new LTVec(0, 0, 0) : SpeakerPos(speaker);
            subtitles.Show(line.Id, text, pos, radius, line.Duration, talk, listener, scene);
        }

        // CCharacter::StopDialogue / KillDlgSnd: the speaker's voice is cut, and its subtitle with it.
        internal void StopDialogue(int speaker)
        {
            if (!talking.TryGetValue(speaker, out var talk)) return;
            talking.Remove(speaker);
            KillVoice?.Invoke(speaker);
            subtitles.Clear(talk);
        }
    }

    // A Dialogue object (ltjs dialogue.cpp as Tron's object.lto has it). Messages: ON and OFF; the rest is
    // GameBase's.
    // - ON (when off): on, line 1 starts Delay1 after now, the update armed for the next frame.
    // - Each update: first its speakers are looked up by name (once): when a name has no object (a character not
    //   spawned yet) it goes off without any command and waits for another ON (Tron: NOLF2 cleans up). Then the
    //   current line ends when its speaker's voice has, and the next starts its delay after that; an empty slot
    //   finishes: FinishedCommand, then off.
    // - Starting line N: StartCommand (line 1), StartDialogueCommandN, then the speaker, by exact name in any
    //   case: none, two or more (Tron), or not a character fails the line, which finishes the dialogue.
    // - Off (OFF, a finish): the current voice is cut, the CleanUpCommand runs (even when it was off), then with
    //   RemoveWhenComplete it leaves the level, else it's back to line 1 waiting for an ON.
    // The AI talk goal (talk nodes, RequestDialogue, UseAIState) isn't run: AIs don't think in the viewer.
    public sealed class Dialogue
    {
        public const int MaxLines = 20;

        readonly Dialogues owner;
        readonly int id;
        public readonly DialogueProps P;
        readonly GameBaseFlags flags;

        public bool On { get; private set; }
        bool armed, notified;
        float armedAt, nextStart = -1;
        int cur, speaker = -1;

        internal Dialogue(Dialogues owner, int id, DialogueProps p, GameBaseFlags flags)
        {
            this.owner = owner;
            this.id = id;
            P = p;
            this.flags = flags;
        }

        public string Name => owner.Commands.Name(id);

        public bool OnMessage(Message m)
        {
            if (flags.Removed) return false;
            if (m.Is("ON")) HandleOn();
            else if (m.Is("OFF")) HandleOff();
            else return false;
            return true;
        }

        float Delay(int n) => n < P.Lines.Length ? P.Lines[n].Delay : 0;

        void Arm()
        {
            armed = true;
            armedAt = owner.Now;
        }

        void HandleOn()
        {
            if (On) return;
            On = true;
            nextStart = owner.Now + Delay(0);
            Arm();
        }

        internal void Update()
        {
            if (!armed || flags.Removed || owner.Now <= armedAt) return;
            armed = false;
            if (!NotifySpeakers())
            {
                On = false;
                return;
            }
            Arm();
            if (!UpdateDialogue())
            {
                Run(P.FinishedCommand);
                HandleOff();
            }
        }

        bool NotifySpeakers()
        {
            if (notified) return true;
            foreach (var l in P.Lines)
                if (owner.Commands.Named(l.Speaker).Count == 0) return false;
            notified = true;
            return true;
        }

        bool UpdateDialogue()
        {
            float now = owner.Now;
            if (speaker >= 0 && !owner.IsTalking(speaker))
            {
                speaker = -1;
                if (++cur >= MaxLines) return false;
                nextStart = now + Delay(cur);
            }
            if (speaker < 0)
            {
                if (cur >= P.Lines.Length) return false;
                if (nextStart >= 0 && nextStart <= now) return StartDialogue();
            }
            return true;
        }

        bool StartDialogue()
        {
            if (cur == 0) Run(P.StartCommand);
            var line = P.Lines[cur];
            Run(line.Command);
            if (string.IsNullOrEmpty(line.Speaker)) return false;
            var named = owner.Commands.Named(line.Speaker);
            if (named.Count != 1 || !Dialogues.IsCharacter(owner.Commands.Class(named[0]))) return false;
            speaker = named[0];
            owner.PlayDialogue(speaker, line);
            return true;
        }

        void HandleOff()
        {
            if (On && speaker >= 0) owner.StopDialogue(speaker);
            speaker = -1;
            On = false;
            Run(P.CleanUpCommand);
            if (P.RemoveWhenComplete)
            {
                if (!flags.Removed) flags.OnMessage(new Message(new[] { "REMOVE" }, -1));
                return;
            }
            notified = false;
            cur = 0;
            nextStart = -1;
            armed = false;
        }

        void Run(string command)
        {
            if (!string.IsNullOrEmpty(command)) owner.Commands.Run(command, id, id);
        }
    }

    // The subtitle (CHUDSubtitles as Tron's cshell.dll has it): one at a time, a new one replacing it, except that
    // while one is up ids 20000-22999 (but 20836-21012) aren't shown. It shows for its voice's duration (0.04 s a
    // character without one), counted only while subtitles are on (the Subtitles console variable; Tron's
    // Default.prf has it on). A speaker's subtitle shows only while the listener is within 0.77 of its radius of
    // where it spoke, checked when it starts and each frame; the player's own lines (spoken at no place) and every
    // line while a scene camera is on skip that. The layout ([Subtitle]) is the scene's (Pos) when it starts under
    // a scene camera, else the play one (FullScreenPos).
    public sealed class Subtitles
    {
        public const float SecondsPerChar = 0.04f;
        public const float RadiusPercent = 0.77f;   // SubtitleSoundRadiusPercent

        public bool Enabled = true;

        public bool Visible { get; private set; }
        public int Id { get; private set; }
        public string Text { get; private set; } = "";
        public bool Cinematic { get; private set; }
        public float Duration { get; private set; }
        public float Elapsed { get; private set; }

        LTVec pos;
        float radius;
        object owner;

        // Ids that don't replace a subtitle that is up (Tron's Show).
        public static bool Quiet(int id) => id >= 20000 && id <= 22999 && !(id >= 20836 && id <= 21012);

        // duration < 0: none (0.04 s a character). owner: what Clear(owner) takes it down for (its sound).
        public bool Show(int id, string text, LTVec speakerPos, float radius, float duration, object owner, LTVec listener, bool scene)
        {
            if (!InRange(speakerPos, radius, listener, scene)) return false;
            if (Visible && Quiet(id)) return false;
            if (string.IsNullOrEmpty(text)) return false;
            Id = id;
            Text = text;
            pos = speakerPos;
            this.radius = radius;
            this.owner = owner;
            Duration = duration < 0 ? SecondsPerChar * text.Length : duration;
            Elapsed = 0;
            Cinematic = scene;
            Visible = true;
            return true;
        }

        static bool InRange(LTVec speakerPos, float radius, LTVec listener, bool scene) =>
            scene || speakerPos == new LTVec(0, 0, 0) || LTVec.Dist(speakerPos, listener) <= radius * RadiusPercent;

        // KillLipSyncSound: only the subtitle of that sound.
        public void Clear(object owner)
        {
            if (Visible && ReferenceEquals(this.owner, owner)) Clear();
        }

        public void Clear()
        {
            Visible = false;
            Text = "";
            Elapsed = 0;
            owner = null;
        }

        public void Update(float frameTime)
        {
            if (!Visible || !Enabled) return;
            Elapsed += frameTime;
            if (Duration < Elapsed) Clear();
        }

        // Render: drawn this frame.
        public bool Draws(LTVec listener, bool scene) => Visible && Enabled && InRange(pos, radius, listener, scene);

        // Where the text's first line goes (layout units) in a box at boxY, numLines lines of fontSize tall
        // (2 + numLines × fontSize): bottom-aligned when it fits; else top-aligned and, after numLines × T with
        // T = duration / (lines + 1), scrolling up fontSize / T a second until its last line is at the bottom.
        public float TextTop(int lines, float blockHeight, float boxY, int numLines, float fontSize)
        {
            float box = 2 + numLines * fontSize;
            if (lines <= numLines) return boxY + box - blockHeight;
            float t = Duration / (lines + 1);
            float scrolled = t > 0 ? Math.Max(0, Elapsed - numLines * t) * fontSize / t : 0;
            return boxY - Math.Min(scrolled, Math.Max(0, blockHeight + 2 - box));
        }
    }
}
