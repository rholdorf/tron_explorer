using System;

namespace Tron
{
    // A SpecialFX object (ltjs serverspecialfx.cpp; Tron's object.lto the same, plus TARGET): plays its
    // effect group through the client's effect manager (docs/research/clientfx-groups.md §5).
    //   Loop: ON (when off) starts one instance at t = 0 that follows the object; OFF (when on) and REMOVE
    //     shut it down, smoothly when SmoothShutdown. ON while on does nothing.
    //   Not Loop: every ON starts another one-shot where the object is, with no parent, overlapping those
    //     still playing; OFF only flips the state; OneTime removes the object after its first ON (the
    //     effect plays out). REMOVE touches no one-shot.
    //   TRIGGER toggles; TARGET (Tron, unused by the levels) turns it off and makes the sender its target.
    // HIDDEN and VISIBLE don't reach the effect (the server object is never drawn): the GameBase handler
    // takes them. Plain C#, no Unity, so tools/tests/test_client_fx.py compiles it with .NET.
    public sealed class SpecialFX : IFxObject
    {
        readonly ClientFXMgr mgr;
        public readonly string FxName;
        public readonly bool Loop, SmoothShutdown, OneTime;

        public LTVec Pos { get; set; }
        public LTQuat Rot { get; set; }
        public bool IsOn { get; private set; }
        public FxInstance Instance { get; private set; }   // a looping one's running instance
        public int Target { get; private set; } = -1;     // TARGET's sender
        // OneTime: the object leaves the level (its GameBase REMOVE).
        public Action RemoveObject;

        public SpecialFX(ClientFXMgr mgr, string fxName, bool loop, bool smoothShutdown, bool oneTime, LTVec pos, LTQuat rot)
        {
            this.mgr = mgr;
            FxName = fxName ?? "";
            Loop = loop;
            SmoothShutdown = smoothShutdown;
            OneTime = oneTime;
            Pos = pos;
            Rot = rot;
        }

        public bool OnMessage(Message m)
        {
            if (m.Is("TRIGGER"))
            {
                if (IsOn) TurnOff();
                else TurnOn();
            }
            else if (m.Is("ON")) TurnOn();
            else if (m.Is("OFF")) TurnOff();
            else if (m.Is("TARGET"))
            {
                TurnOff();
                Target = m.Sender;
            }
            else return false;
            return true;
        }

        public void TurnOn()
        {
            if (!Loop)
            {
                mgr.Start(FxName, false, SmoothShutdown, null, Pos, Rot);
                if (OneTime) RemoveObject?.Invoke();
            }
            else if (!IsOn) Instance = mgr.Start(FxName, true, SmoothShutdown, this);
            IsOn = true;
        }

        public void TurnOff()
        {
            if (!IsOn) return;
            if (Loop) StopInstance();
            IsOn = false;
        }

        // The object is gone: the client shuts its instance down as for OFF.
        public void Remove() => StopInstance();

        void StopInstance()
        {
            mgr.ShutDown(Instance);
            Instance = null;
        }

        public bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot)
        {
            pos = default;
            rot = default;
            return false;
        }
    }
}
