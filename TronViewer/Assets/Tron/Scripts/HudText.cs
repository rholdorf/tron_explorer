using System;
using System.Collections.Generic;

// The HUD text the player's messages show (docs/research/mission-text.md): MISSIONTEXT's typed block and
// TRANSMISSION's announcement queue, with the game's `<color r g b>` markup. Plain C#, no Unity, so
// tools/tests/test_hud_text.py compiles it with .NET; TronExplorer draws the result with HudFont and plays
// the sounds it asks for.
namespace Tron
{
    // A displayed character: its line (0 first), and its colour as 0xRRGGBB.
    public struct HudChar
    {
        public char C;
        public int Line, Rgb;
    }

    public static class ColorMarkup
    {
        // The formatted poly string's colours (Lithtech.exe 0x560fb0): from each `<color ` on, three decimal
        // numbers then everything up to `>` are skipped and the following glyphs take that colour; before the
        // first tag, the string's own. Any other `<` is text. '\n' starts a line and is not a character.
        public static List<HudChar> Parse(string text, int baseRgb)
        {
            var chars = new List<HudChar>();
            int rgb = baseRgb, line = 0;
            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (c == '\n') { line++; continue; }
                if (c == '<' && string.CompareOrdinal(text, i, "<color ", 0, 7) == 0)
                {
                    int p = i + 7, r = Number(text, ref p), g = Number(text, ref p), b = Number(text, ref p);
                    int end = text.IndexOf('>', p);
                    if (end >= 0)
                    {
                        rgb = (Clamp(r) << 16) | (Clamp(g) << 8) | Clamp(b);
                        i = end;
                        continue;
                    }
                }
                chars.Add(new HudChar { C = c, Line = line, Rgb = rgb });
            }
            return chars;
        }

        static int Number(string s, ref int p)
        {
            while (p < s.Length && s[p] == ' ') p++;
            int v = 0;
            while (p < s.Length && s[p] >= '0' && s[p] <= '9') v = v * 10 + (s[p++] - '0');
            return v;
        }

        static int Clamp(int v) => Math.Min(v, 255);
    }

    // The mission text (CHUDMissionText with Tron's layout; ltjs timedtext.cpp CTimedText): letters appear one
    // every LetterDelay, the looping type sound playing; a character on a new line first waits LineScrollTime,
    // with the type sound stopped and the scroll sound played (NumLines 1: every new line is a scroll). The
    // block doesn't move up as the ltjs scroll would: in the game the lines fill downwards. After the last
    // letter the type sound stops; the block holds FadeDelay, then fades linearly over FadeTime. A new one
    // replaces it at once.
    public sealed class MissionText
    {
        public const int BaseRgb = 0xFF9B00;             // TextColor (255, 155, 0)
        public const float LetterDelay = 0.015f, LineScrollTime = 0.25f, FadeDelay = 3, FadeTime = 2;

        public List<HudChar> Chars { get; private set; } = new List<HudChar>();
        public int Visible { get; private set; }         // characters shown so far
        public float Alpha { get; private set; }
        public bool Active { get; private set; }

        // Sounds: the type loop on / off, the scroll sound once.
        public Action<bool> TypeSound;
        public Action ScrollSound;

        float elapsed, processed, completeAt;
        int line;
        bool typing, complete;

        public void Start(string text)
        {
            Clear();
            Chars = ColorMarkup.Parse(text ?? "", BaseRgb);
            Active = true;
            Alpha = 1;
            Update(0);
        }

        // missiontext 0 (and every replacement): nothing shows, the type sound stops.
        public void Clear()
        {
            SetTyping(false);
            Chars = new List<HudChar>();
            Visible = 0;
            Alpha = 0;
            Active = false;
            elapsed = processed = completeAt = 0;
            line = 0;
            complete = false;
        }

        public void Update(float frameTime)
        {
            if (!Active) return;
            elapsed += frameTime;
            while (!complete && processed <= elapsed)
            {
                if (Visible >= Chars.Count)
                {
                    SetTyping(false);
                    complete = true;
                    completeAt = processed;
                    break;
                }
                var c = Chars[Visible];
                if (c.Line != line)
                {
                    SetTyping(false);
                    ScrollSound?.Invoke();
                    processed += LineScrollTime;
                    line = c.Line;
                    continue;
                }
                SetTyping(true);
                Visible++;
                processed += LetterDelay;
            }
            if (!complete) return;
            float t = elapsed - completeAt - FadeDelay;
            if (t < 0) Alpha = 1;
            else if (t < FadeTime) Alpha = 1 - t / FadeTime;
            else Clear();
        }

        void SetTyping(bool on)
        {
            if (typing == on) return;
            typing = on;
            TypeSound?.Invoke(on);
        }
    }

    // A transmission (Tron's CHUDAnnouncementMsgQueue, layout [AnnouncementMessageQueue]): MaxMessages slots,
    // a new message takes the oldest one's at once and goes to the end; each fades in over FadeIn, holds
    // MessageTime and fades out over MessageFade, then hides. Drawn bottom-justified at BasePos, the newest
    // lowest; hidden ones take no space.
    public sealed class TransmissionQueue
    {
        public const int BaseRgb = 0x5AC7FF;             // TextColor (90, 199, 255)
        public const int MaxMessages = 2;
        public const float FadeIn = 1, MessageTime = 4, MessageFade = 0.5f;

        public sealed class Entry
        {
            public List<HudChar> Chars;
            public float Age;
            public bool Visible;
            public float Alpha => !Visible ? 0
                : Age < FadeIn ? Age / FadeIn
                : Age < FadeIn + MessageTime ? 1
                : Math.Max(0, 1 - (Age - FadeIn - MessageTime) / MessageFade);
        }

        // Oldest first.
        public readonly List<Entry> Entries = new List<Entry>();

        public TransmissionQueue()
        {
            for (int i = 0; i < MaxMessages; i++) Entries.Add(new Entry { Chars = new List<HudChar>() });
        }

        public void Add(string text)
        {
            var e = Entries[0];
            Entries.RemoveAt(0);
            e.Chars = ColorMarkup.Parse(text ?? "", BaseRgb);
            e.Age = 0;
            e.Visible = true;
            Entries.Add(e);
        }

        public void Update(float frameTime)
        {
            foreach (var e in Entries)
            {
                if (!e.Visible) continue;
                e.Age += frameTime;
                if (e.Age >= FadeIn + MessageTime + MessageFade) e.Visible = false;
            }
        }

        public void Clear()
        {
            foreach (var e in Entries) e.Visible = false;
        }
    }

    public static class HudMessages
    {
        // The player's MISSIONTEXT <id> and TRANSMISSION <id> (object.lto, cshell.dll). strings: the text of a
        // cres.dll string id, null if there is none. A missing string shows as the game shows it (an empty
        // mission text replaces the current one; an empty transmission takes a slot and plays its sound) and
        // is counted as "MISSINGSTRING Player <word>". transmissionSound: msgfadeout, once per transmission.
        public static void Handle(CommandMgr mgr, int player, Func<int, string> strings, MissionText missionText,
                                  TransmissionQueue transmissions, Action transmissionSound)
        {
            mgr.Handle(player, m =>
            {
                bool mission = m.Is("MISSIONTEXT");
                if (!mission && !m.Is("TRANSMISSION")) return false;
                if (m.ArgCount < 1) return false;
                int id = CommandMgr.Atol(m.Arg(0));
                if (mission && id <= 0)
                {
                    missionText.Clear();
                    return true;
                }
                var text = strings(id);
                if (text == null) mgr.Count("MISSINGSTRING", "Player", mission ? "MISSIONTEXT" : "TRANSMISSION");
                if (mission) missionText.Start(text ?? "");
                else
                {
                    // An id of 0 plays the sound and shows nothing (cshell.dll 0x100a6ecf).
                    transmissionSound?.Invoke();
                    if (id != 0) transmissions.Add(text ?? "");
                }
                return true;
            });
        }
    }
}
