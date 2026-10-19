using System;

// Models whose look follows a state (docs/research/secrezzer-binarybit.md; Tron's object.lto): BinaryBit and
// SecRezzer. Plain C#, no Unity, so tools/tests/test_state_models.py compiles it with .NET; StateModel (the
// Unity side) plays the clips, swaps the looks, plays the clips' sounds and runs the commands they ask for.
namespace Tron
{
    // What a state model asks of its object.
    public interface IStateModelHost
    {
        // Starts a clip from its first frame; a clip that doesn't loop holds its last frame and reports
        // its end (OnClipEnd). Its animation keys come back through OnKey as they pass.
        void Play(string clip, bool loop);
        void SetLook(string look);
        // A command string, the object as sender.
        void Run(string command);
        // Something the viewer skips (a ClientFX), for the level's report.
        void Count(string word);
    }

    // The activate type's state (ACTIVATETYPE: on, off; Tron's BinaryBit also sets 2, which has no text).
    public enum PromptState { On, Off, None }

    public interface IStateModel
    {
        bool CanUse { get; }
        PromptState Prompt { get; }
        void Start();
        bool OnMessage(Message m, bool fromPlayer);
        void OnKey(string[] words);   // a statement of an animation key, as ConParse splits it
        void OnClipEnd();
    }

    // BinaryBit (object.lto 0x100129b0): powered down, flying to its socket, Yes or No. Its byte's render
    // style (slot 0) is the look: idle (blue), yes (amber), no (red).
    // - Spawn: PoweredDown; with no EnergyRequired it powers up at once (Yes or No by StartOnInSocket, no
    //   animation), else it waits powered down.
    // - ACTIVATE: powered down, the power-up (the player's energy transfer is always granted): the trail
    //   ClientFX (skipped, counted), PowerUpCommand, the Idle tumble; ATSOCKET then lands it on Yes or No.
    //   On Yes / No it flips: the Yes or No clip (its RS key swaps the look at 300 ms), then Turn{On,Off}
    //   Command and the Idle tumble. Nothing while flying or flipping.
    // - LOCK / UNLOCK: use off / on.
    public sealed class BinaryBit : IStateModel
    {
        public enum State { PoweredDown, Flying, Yes, No }

        readonly IStateModelHost host;
        readonly bool needsEnergy, startOnInSocket;
        readonly string powerUpCommand, turnOnCommand, turnOffCommand;
        bool canActivate, flipping;

        public State Current { get; private set; }
        public bool Locked { get; private set; }

        public BinaryBit(IStateModelHost host, float energyRequired, bool startOnInSocket, bool locked,
                         string powerUpCommand, string turnOnCommand, string turnOffCommand)
        {
            this.host = host;
            needsEnergy = energyRequired > 0;
            this.startOnInSocket = startOnInSocket;
            Locked = locked;
            this.powerUpCommand = powerUpCommand;
            this.turnOnCommand = turnOnCommand;
            this.turnOffCommand = turnOffCommand;
        }

        public bool CanUse => canActivate && !Locked && Current != State.Flying;

        public PromptState Prompt => Current == State.Yes ? PromptState.On : Current == State.No ? PromptState.Off : PromptState.None;

        // InitialUpdate (0x10013830).
        public void Start()
        {
            canActivate = !Locked;
            host.SetLook("idle");
            host.Play("PoweredDown", false);
            if (needsEnergy) return;
            Current = State.Flying;
            DoPowerUp();
        }

        public bool OnMessage(Message m, bool fromPlayer)
        {
            if (m.Is("ACTIVATE")) { Activate(); return true; }
            if (m.Is("LOCK")) { Locked = true; canActivate = false; return true; }
            if (m.Is("UNLOCK"))
            {
                // Use comes back unless a flip is under way (it gives it back when done).
                Locked = false;
                if (!flipping) canActivate = true;
                return true;
            }
            if (m.Is("ATSOCKET")) { DoPowerUp(); return true; }   // in any state, as the game does
            return false;
        }

        // HandleActivateMessage (0x10013f10); every permission set and the energy transfer pass.
        void Activate()
        {
            if (Locked) return;
            switch (Current)
            {
                case State.PoweredDown:
                    if (needsEnergy) PowerUp();
                    break;
                case State.Yes: ChangeState(State.No); break;
                case State.No: ChangeState(State.Yes); break;
            }
        }

        // PowerUp (0x10014190).
        void PowerUp()
        {
            ChangeState(State.Flying);
            host.Run(powerUpCommand);
            host.Play("Idle", true);
        }

        // DoPowerUp (0x10013e70).
        void DoPowerUp()
        {
            ChangeState(startOnInSocket ? State.Yes : State.No);
            canActivate = !Locked;
        }

        // ChangeState (0x10013940): a flip plays its clip; landing from the flight swaps the look at once.
        void ChangeState(State to)
        {
            if (to == Current) return;
            var from = Current;
            Current = to;
            if (to == State.Flying)
            {
                host.Count("BinaryBit_Trail");
                return;
            }
            if (to != State.Yes && to != State.No) return;
            bool yes = to == State.Yes;
            if (from == State.Yes || from == State.No)
            {
                host.Play(yes ? "Yes" : "No", false);
                canActivate = false;
                flipping = true;
            }
            else if (from == State.Flying) host.SetLook(yes ? "yes" : "no");
        }

        // Animation keys (0x10014260): "RS <slot> <file>" swaps the render style (slot 0 is the look).
        public void OnKey(string[] w)
        {
            if (w.Length < 3 || !string.Equals(w[0], "RS", StringComparison.OrdinalIgnoreCase) || w[1] != "0") return;
            var file = w[2].ToLowerInvariant();
            host.SetLook(file.Contains("_yes") ? "yes" : file.Contains("_no") ? "no" : "idle");
        }

        // Update (0x10012a5d): a flip's clip done, its command, then the tumble.
        public void OnClipEnd()
        {
            if (!flipping) return;
            flipping = false;
            host.Run(Current == State.Yes ? turnOnCommand : turnOffCommand);
            host.Play("Idle", true);
            canActivate = !Locked;
        }
    }

    // SecRezzer (object.lto vtable 0x10285b2c): spawns in Idle (side panels open, skin idle). The player's use
    // disables it: skin off, the Disable clip (panels fold), then Disabled. Its ON / OFF / IDLE come from AIs
    // and spawn backup, which the viewer doesn't run: they stay unhandled, in the level's report.
    public sealed class SecRezzer : IStateModel
    {
        public enum State { Idle, Disabling, Disabled }

        readonly IStateModelHost host;

        public State Current { get; private set; }

        public SecRezzer(IStateModelHost host) => this.host = host;

        public bool CanUse => Current == State.Idle;

        public PromptState Prompt => Current == State.Idle ? PromptState.On : PromptState.Off;

        public void Start()
        {
            host.SetLook("idle");
            host.Play("Idle", false);
        }

        // OnTrigger (0x10044080): only the player's ACTIVATE, in idle, disables it.
        public bool OnMessage(Message m, bool fromPlayer)
        {
            if (!m.Is("ACTIVATE")) return false;
            if (fromPlayer && Current == State.Idle)
            {
                Current = State.Disabling;
                host.SetLook("off");
                host.Play("Disable", false);
            }
            return true;
        }

        public void OnKey(string[] words) { }

        public void OnClipEnd()
        {
            if (Current != State.Disabling) return;
            Current = State.Disabled;
            host.Play("Disabled", false);
        }
    }
}
