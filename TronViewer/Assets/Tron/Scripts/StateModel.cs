using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // A model whose look follows a state (StateModels.cs: BinaryBit, SecRezzer), on its drawn model: plays the
    // state's clips on its bones (once, holding the last frame, or looping) on the server clock, with the
    // pieces' uniform scales and the animation keys as they pass (BUTE_SOUND_KEY plays a soundbute from
    // the object, the others go to the state), swaps its looks (each a full set of piece materials), runs the
    // commands the state asks for with the object as sender, and is usable through a box of its dims.
    public class StateModel : MonoBehaviour, IStateModelHost, IUsable
    {
        public IStateModel State { get; private set; }

        LoadedModel model;
        Transform[] bones;
        Renderer render;
        Dictionary<string, Material[]> looks;
        Dictionary<string, ButeSoundJson> sounds;
        CommandMgr commands;
        string cls, promptOn, promptOff;
        int self, player = -1;
        AmbientSound shots;

        // Its clips as AnimTrack plays them (no blend: a state's clip cuts in), their animation keys' texts.
        AnimTrack track;
        string[][] keyTexts;
        ModelAnimJson clip;
        bool ended;

        public void Init(IStateModel state, LoadedModel model, Transform[] bones, Renderer render,
                         Dictionary<string, Material[]> looks, Dictionary<string, ButeSoundJson> sounds,
                         CommandMgr commands, int self, string cls, string promptOn, string promptOff, Vector3 useBox)
        {
            State = state;
            this.model = model;
            this.bones = bones;
            this.render = render;
            this.looks = looks;
            this.sounds = sounds;
            this.commands = commands;
            this.self = self;
            this.cls = cls;
            this.promptOn = promptOn ?? "";
            this.promptOff = promptOff ?? "";
            var anims = model.data.anims ?? Array.Empty<ModelAnimJson>();
            var infos = new AnimTrack.ClipInfo[anims.Length];
            keyTexts = new string[anims.Length][];
            for (int i = 0; i < anims.Length; i++) infos[i] = ModelAnimator.ClipInfo(model, anims[i], 0, out keyTexts[i]);
            track = new AnimTrack(infos);
            // The use ray's target: the object's dims (half-extents, LithTech units, scale included).
            var box = new GameObject("use box") { layer = LevelBuilder.UseOnlyLayer };
            box.transform.SetParent(transform, false);
            var c = box.AddComponent<BoxCollider>();
            var s = transform.localScale;
            c.size = new Vector3(2 * useBox.x / Mathf.Max(s.x, 1e-4f), 2 * useBox.y / Mathf.Max(s.y, 1e-4f), 2 * useBox.z / Mathf.Max(s.z, 1e-4f));
            commands.Handle(self, m => State.OnMessage(m, m.Sender >= 0 && m.Sender == player));
        }

        public void ConnectPlayer(int id) => player = id;

        void Start() => State.Start();

        // The clip on the server clock: its keys as it crosses them, its pose; a clip played once (or a looping one
        // with a single key) ends past its last key.
        void Update()
        {
            if (clip == null || ended) return;
            track.Advance(commands.FrameTime);
            FireKeys();
            Pose();
            if (track.Looping ? clip.length > 0 : !track.Done) return;
            ended = true;
            State.OnClipEnd();
        }

        void FireKeys()
        {
            foreach (var (c, k) in track.Fired) Key(keyTexts[c][k]);
            track.Fired.Clear();
        }

        // Each statement of an animation key (ConParse): BUTE_SOUND_KEY <soundbute> plays it, the rest go to the state.
        void Key(string text)
        {
            foreach (var w in ConParse.Statements(text))
            {
                if (w.Length == 0) continue;
                if (w.Length >= 2 && string.Equals(w[0], "BUTE_SOUND_KEY", StringComparison.OrdinalIgnoreCase)) PlaySound(w[1]);
                else State.OnKey(w);
            }
        }

        void PlaySound(string name)
        {
            if (!sounds.TryGetValue(name, out var b)) return;
            var c = SoundLoader.Load(b.AnyFile());
            if (!c) return;
            if (!shots) shots = AmbientSound.Add(gameObject, b.inner, b.outer, 100, false, 0);
            shots.Source.PlayOneShot(c);
        }

        void Pose()
        {
            var d = model.animData;
            track.Key(out int k, out float f);
            for (int n = 0; n < bones.Length; n++)
                bones[n].SetLocalPositionAndRotation(ModelAnimator.Position(d, clip, n, k, f), ModelAnimator.Rotation(d, clip, n, k, f));
            var sc = clip.scales;
            for (int i = 0; sc != null && i + 2 < sc.Length; i += 3)
                if (sc[i] < bones.Length) bones[sc[i]].localScale = Vector3.one * ModelAnimator.Scale(d, sc[i + 1], sc[i + 2], k, f);
        }

        // ---- IStateModelHost ----

        public void Play(string name, bool looping)
        {
            int i = model.FindAnim(name);
            if (i < 0) { Debug.LogWarning($"{name}: no clip {name} in {model.data.file}"); return; }
            foreach (var b in bones) b.localScale = Vector3.one;
            clip = model.data.anims[i];
            ended = false;
            track.Play(i, looping);
            FireKeys();
            Pose();
        }

        public void SetLook(string look)
        {
            if (looks.TryGetValue(look, out var mats)) render.sharedMaterials = mats;
        }

        public void Run(string command)
        {
            if (!string.IsNullOrWhiteSpace(command)) commands.Run(command, self);
        }

        public void Count(string word) => commands.Count("CLIENTFX", cls, word);

        // ---- IUsable ----

        public bool CanBeUsed => State.CanUse && render && render.enabled;
        public bool Locked => false;   // a locked bit isn't usable at all
        public string Prompt => State.Prompt == PromptState.On ? promptOn : State.Prompt == PromptState.Off ? promptOff : "";
        public void Use(int id) => State.OnMessage(new Message(new[] { "ACTIVATE" }, id), true);
    }
}
