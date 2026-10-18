namespace Tron
{
    // A sound an effect has started: moved while it plays, killed when the effect is done with it.
    public interface IFxVoice
    {
        void Move(LTVec pos);
        void Kill();
    }

    // The PlaySound effect as the game plays it (ltjs clientfxdll/playsoundfx.cpp; docs/research/clientfx-types.md
    // on research/clientfx-types): the sound starts on the effect's first update, where the effect was before
    // that update (its create place plus offset, or where it last was when a loop restarts it). Follow keeps
    // it on the parent's place (attached: no offset); Fixed leaves it where it started. The first update
    // while shutting down kills it, even when the wave is longer, as do a frozen instance (it starts again
    // from the beginning when the instance thaws) and the effect's end. Loop loops the wave; a continual key
    // never shuts down, so its sound plays on unbroken. UseMarkers and MultiPlaySound aren't read.
    // Plain C#, no Unity, so tools/tests/test_play_sound_fx.py compiles it with .NET.
    public sealed class FxSound : FxEffect
    {
        // Starts the effect's sound at a place; null when it can't be played (no such file).
        public delegate IFxVoice Player(FxSound fx, LTVec pos);

        readonly Player play;
        IFxVoice voice;
        bool firstUpdate = true;

        public string Sound { get; private set; }
        public bool Loop { get; private set; }
        public bool Local { get; private set; }
        public int Volume { get; private set; }     // 0-100
        public int Priority { get; private set; }
        public float Inner { get; private set; }
        public float Outer { get; private set; }
        public float Pitch { get; private set; }
        public bool Playing => voice != null;

        public FxSound(Player play) => this.play = play;

        protected override void OnInit()
        {
            var k = Key;
            Sound = k.Str("Sound");
            Loop = k.Num("Loop") != 0;
            Local = k.Num("PlayLocal") != 0;
            Volume = (byte)(int)k.Num("Volume", 100);
            Priority = (byte)(int)k.Num("Priority");
            Inner = k.Num("InnerRadius");
            Outer = k.Num("OuterRadius");
            Pitch = k.Num("PitchShift", 1);
        }

        protected override void OnBeginUpdate()
        {
            if (!firstUpdate) return;
            firstUpdate = false;
            voice = play(this, Pos);
        }

        protected override void OnUpdate(float dt)
        {
            if (ShuttingDown)
            {
                Kill();
                return;
            }
            if (Key.UpdatePos == FxKey.Follow) voice?.Move(Parent != null ? Parent.Pos : CreatePos);
        }

        public override void SuspendedUpdate(float dt) => Kill();

        public override void Term() => Kill();

        // A sound that never started (no file) isn't tried again.
        void Kill()
        {
            if (voice == null) return;
            voice.Kill();
            voice = null;
            firstUpdate = true;
        }
    }
}
