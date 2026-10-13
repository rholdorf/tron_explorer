using System;

namespace Tron
{
    // The messages every game object handles last, when its own class doesn't know the word (ltjs
    // gamebase.cpp GameBase::OnTrigger; docs/research/command-language.md "Per-class messages"):
    //   VISIBLE 1/0, SOLID 1/0 (1 also restores RAYHIT if the object had it), HIDDEN 1/0 (1 clears VISIBLE,
    //   SOLID and RAYHIT; 0 restores whichever of the three the object had at its first message), each
    //   argument also TRUE/FALSE in any case (no argument or any other value: handled, nothing changes), and
    //   REMOVE (the object leaves the level: from then on it takes every message and does nothing, like the
    //   relays' REMOVE). A WorldModel's StartHidden is a "Hidden 1" it sends itself at creation
    //   (WorldModel::OnObjectCreated), so HIDDEN 0 shows it.
    //
    // Plain C#, no Unity, so tools/tests/test_object_messages.py compiles it with Mono; the viewer applies
    // the flags to the object's renderers and colliders (LevelBuilder.Messages.cs).
    public sealed class GameBaseFlags
    {
        public bool Visible { get; private set; }
        public bool Solid { get; private set; }
        public bool RayHit { get; private set; }
        public bool Removed { get; private set; }

        // After a flag message (even one that changed nothing), and once on REMOVE.
        public event Action Changed;
        public event Action Remove;

        bool saved, origVisible, origSolid, origRayHit;

        public GameBaseFlags(bool visible, bool solid, bool rayHit, bool startHidden = false)
        {
            Visible = visible;
            Solid = solid;
            RayHit = rayHit;
            if (startHidden) OnMessage(new Message(new[] { "Hidden", "1" }, -1));
        }

        public bool OnMessage(Message m)
        {
            if (Removed) return true;
            if (!saved)
            {
                saved = true;
                origVisible = Visible;
                origSolid = Solid;
                origRayHit = RayHit;
            }
            if (m.Is("REMOVE"))
            {
                Removed = true;
                Remove?.Invoke();
                return true;
            }
            bool visible = m.Is("VISIBLE"), solid = m.Is("SOLID"), hidden = m.Is("HIDDEN");
            if (!visible && !solid && !hidden) return false;
            if (m.ArgCount < 1) return true;
            bool on = IsWord(m.Arg(0), "1", "TRUE"), off = IsWord(m.Arg(0), "0", "FALSE");
            if (!on && !off) return true;
            if (visible) Visible = on;
            else if (solid)
            {
                Solid = on;
                RayHit = on ? RayHit || origRayHit : false;
            }
            else if (on)
                Visible = Solid = RayHit = false;
            else
            {
                Visible |= origVisible;
                Solid |= origSolid;
                RayHit |= origRayHit;
            }
            Changed?.Invoke();
            return true;
        }

        static bool IsWord(string s, string a, string b) =>
            string.Equals(s, a, StringComparison.OrdinalIgnoreCase) || string.Equals(s, b, StringComparison.OrdinalIgnoreCase);
    }
}
