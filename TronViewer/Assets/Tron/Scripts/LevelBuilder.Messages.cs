using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // The level objects the viewer builds and the messages they take (ticket #33; the per-class table in
    // docs/research/command-language.md): keyframers, spinners, SoundFX and SoundButeFX, active or on at
    // start or not, joined to the level's command manager with their class's messages; and every built
    // object (world models, models, those) with the GameBase messages (GameBaseFlags: VISIBLE, SOLID,
    // HIDDEN, REMOVE), drawn by its renderers and solid by its colliders. Each object's GameBase handler
    // comes first, so a removed object takes no more messages; the class words don't overlap with it.
    public partial class LevelBuilder
    {
        // Object ids that have their GameBase handler, and their flags.
        readonly Dictionary<int, GameBaseFlags> withFlags = new Dictionary<int, GameBaseFlags>();

        // The level's object ids by name (any case), in level order: built once, on first use.
        Dictionary<string, List<int>> objectsByName;
        static readonly List<int> NoObjects = new List<int>();

        // The ids of every object with this name, in level order (none: empty).
        List<int> ObjectsNamed(string name)
        {
            if (objectsByName == null)
            {
                objectsByName = new Dictionary<string, List<int>>(StringComparer.OrdinalIgnoreCase);
                for (int i = 0; i < Data.objects.Length; i++)
                {
                    var n = Data.objects[i].name;
                    if (string.IsNullOrEmpty(n)) continue;
                    if (!objectsByName.TryGetValue(n, out var list)) objectsByName[n] = list = new List<int>();
                    list.Add(i);
                }
            }
            return !string.IsNullOrEmpty(name) && objectsByName.TryGetValue(name, out var ids) ? ids : NoObjects;
        }

        // The first object with this name, -1 if none.
        int FirstNamed(string name)
        {
            var ids = ObjectsNamed(name);
            return ids.Count > 0 ? ids[0] : -1;
        }

        // The GameBase flags an object starts with (its Visible, Solid and Rayhit props; StartHidden).
        [Flags]
        enum StartFlags { None = 0, Visible = 1, Solid = 2, RayHit = 4, Hidden = 8 }

        static StartFlags If(bool on, StartFlags flag) => on ? flag : StartFlags.None;

        // A drawn model object's (a prop, a placed or spawned character: its template's props) start flags.
        static StartFlags ModelStart(ObjectJson o) =>
            StartFlags.Visible | If(o.Bool("Solid", true), StartFlags.Solid) | If(o.Bool("Rayhit", true), StartFlags.RayHit);

        // Gives object `id` its GameBase handler. show: applies the flags to what draws it (also at once);
        // remove: what REMOVE does to it.
        GameBaseFlags JoinFlags(int id, StartFlags start, Action<GameBaseFlags> show, Action remove)
        {
            var f = new GameBaseFlags((start & StartFlags.Visible) != 0, (start & StartFlags.Solid) != 0,
                (start & StartFlags.RayHit) != 0, (start & StartFlags.Hidden) != 0);
            if (show != null)
            {
                f.Changed += () => show(f);
                show(f);
            }
            if (remove != null) f.Remove += remove;
            Commands.Handle(id, f.OnMessage);
            withFlags[id] = f;
            return f;
        }

        // Visible: its renderers draw. Solid: its colliders block. RayHit without Solid: they only take the
        // use ray (UseOnlyLayer, as LevelBuilderDoors does for usable non-solid world models). Neither: off.
        static void Show(IEnumerable<GameObject> gos, GameBaseFlags f)
        {
            foreach (var go in gos)
            {
                if (!go) continue;
                foreach (var r in go.GetComponentsInChildren<Renderer>(true)) r.enabled = f.Visible;
                foreach (var c in go.GetComponentsInChildren<Collider>(true))
                {
                    c.enabled = f.Solid || f.RayHit;
                    // A state model's use box only ever takes the use ray (StateModel).
                    c.gameObject.layer = f.Solid && !c.GetComponentInParent<StateModel>() ? 0 : UseOnlyLayer;
                }
            }
        }

        static void Deactivate(IEnumerable<GameObject> gos)
        {
            foreach (var go in gos)
                if (go) go.SetActive(false);
        }

        // World models (their owning object's Visible, Solid, Rayhit and StartHidden props; WorldModel's
        // DESTROY only clears NeverDestroy, so it does nothing here), then the drawn models (props and
        // characters, with their attachments; drawn as built, solid as their props say).
        void JoinObjectMessages()
        {
            foreach (var kv in worldModelOwners)
            {
                var obj = kv.Value;
                if (obj == null) continue;
                var named = ObjectsNamed(obj.name);
                int k = named.FindIndex(i => Data.objects[i] == obj);   // the owner, of the objects with its name
                if (k < 0 || withFlags.ContainsKey(named[k])) continue;
                int id = named[k];
                if (!WorldModelObjects.TryGetValue(kv.Key, out var wm)) continue;
                var gos = new[] { wm };
                var start = If(obj.Bool("Visible", true), StartFlags.Visible) |
                            If(SolidClasses.Contains(obj.cls) && obj.Bool("Solid", true), StartFlags.Solid) |
                            If(obj.Bool("Rayhit", true), StartFlags.RayHit) | If(obj.Bool("StartHidden"), StartFlags.Hidden);
                JoinFlags(id, start, f => Show(gos, f), () => Deactivate(gos));
                Commands.Handle(id, m => m.Is("DESTROY"));
            }
            foreach (var kv in modelObjects)
            {
                if (withFlags.ContainsKey(kv.Key)) continue;
                var obj = Data.objects[kv.Key];
                var gos = kv.Value;
                JoinFlags(kv.Key, ModelStart(obj), f => Show(gos, f), () => Deactivate(gos));
            }
        }

        // The level's triggers and relays (Relays): every level object is handed to them with its props, and
        // they take the relay classes. TimelineTicker and ObjectTicker run them each frame.
        void BuildRelays()
        {
            Relays = new Relays(Commands);
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                // One of three ways the viewer reads object props, not unified yet: here as string and number
                // tables (Relays.Props, so Relays stays plain C#); doors through ActiveWorldModel.IProps
                // (ObjectProps); keyframers, spinners and sounds pre-read by the exporter (tools/keyframer.py,
                // spinner.py, sounds.py, ambient.py).
                var strs = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                var nums = new Dictionary<string, float[]>(StringComparer.OrdinalIgnoreCase);
                foreach (var p in o.props)
                {
                    if (p.t == "s") strs[p.k] = p.s;
                    else nums[p.k] = p.v;
                }
                Relays.Add(i, o.cls, o.LTPosition, strs, nums);
            }
            var timelines = Root.AddComponent<TimelineTicker>();
            timelines.Commands = Commands;
            timelines.Relays = Relays;
            Root.AddComponent<ObjectTicker>().Relays = Relays;
        }

        // Spinners turn their world model (Spinner) as their SpinnerMotion says, from level start if they
        // start on, else once ON comes; their commands (OnCommand...) run with the spinner as sender.
        void BuildSpinners()
        {
            if (Data.spinners == null) return;
            foreach (var s in Data.spinners)
            {
                if (!WorldModelObjects.TryGetValue(s.worldModel, out var go)) continue;
                var obj = Data.objects[s.obj];
                int id = s.obj;
                var motion = new SpinnerMotion(s.Settings(), prop => Commands.Run(obj.Str(prop), id));
                MakeKinematic(go);
                go.AddComponent<Spinner>().Init(motion);
                Commands.Handle(id, motion.OnMessage);
            }
        }

        // Keyframers move the objects named in their ObjectName (KeyFramer::CreateKeyList: every object with
        // each name) along their path (Keyframer), from level start if they start active, else once a
        // message starts them; their keys' commands run through the command manager with the keyframer as
        // sender and active target. An object is shown by its world model when it has one, else by its drawn
        // models; one the viewer doesn't draw has nothing to move but still counts (a keyframer with no
        // object at all never goes active, though it still takes its messages).
        void BuildKeyframers()
        {
            if (Data.keyframers == null || Data.keyframers.Length == 0) return;
            var worldModels = new Dictionary<string, GameObject>(WorldModelObjects, StringComparer.OrdinalIgnoreCase);
            var parent = new GameObject("Keyframers");
            parent.transform.SetParent(Root.transform, false);
            foreach (var kf in Data.keyframers)
            {
                int id = kf.obj;
                var motion = kf.Motion();
                motion.RunCommand = c => Commands.Run(c, id, id);
                Keyframer keyframer = null;
                JoinFlags(id, StartFlags.Visible, null, () => { if (keyframer) keyframer.Remove(); });
                Commands.Handle(id, motion.OnMessage);

                var shown = new List<Transform[]>();
                foreach (var name in kf.targets)
                {
                    foreach (int i in ObjectsNamed(name))
                    {
                        var obj = Data.objects[i];
                        Transform[] gos;
                        Vector3 pos = obj.Position;
                        if ((SolidClasses.Contains(obj.cls) || HiddenClasses.Contains(obj.cls)) && worldModels.TryGetValue(obj.name, out var wm))
                        {
                            gos = new[] { wm.transform };
                            MakeKinematic(wm);
                        }
                        else if (modelObjects.TryGetValue(i, out var models))
                        {
                            gos = models.ConvertAll(m => m.transform).ToArray();
                            pos = gos[0].localPosition;   // after MoveToFloor
                        }
                        else if (pointObjects.TryGetValue(i, out var sfx)) gos = new[] { sfx };
                        else gos = Array.Empty<Transform>();
                        motion.AddTarget(new LTVec(pos.x, pos.y, pos.z), obj.LTRotation);
                        shown.Add(gos);
                    }
                }
                if (motion.Targets.Count == 0) continue;

                var go = new GameObject($"{kf.name} [KeyFramer]");
                go.transform.SetParent(parent.transform, false);
                AmbientSound sound = null;
                AudioClip clip = null;
                if (!string.IsNullOrEmpty(kf.activeSound) && (clip = SoundLoader.Load(kf.activeSound)))
                {
                    // The sound follows the first controlled object; one that isn't drawn gets a stand-in.
                    var host = shown[0].Length > 0 ? shown[0][0].gameObject : null;
                    if (!host)
                    {
                        host = new GameObject("ActiveSound");
                        host.transform.SetParent(parent.transform, false);
                        var t0 = motion.Targets[0].Pos;
                        host.transform.localPosition = new Vector3(t0.x, t0.y, t0.z);
                        shown[0] = new[] { host.transform };
                    }
                    sound = AmbientSound.AddObjectSound(host, kf.soundRadius);
                }
                keyframer = go.AddComponent<Keyframer>();
                keyframer.Init(motion, shown.ToArray(), sound, clip);
            }
        }

        // SoundFX play at their position (SoundFX::InitialUpdate when StartOn) with the engine's falloff
        // and volume (AmbientSound). Messages (SoundFX::OnTrigger): ON / TRIGGER play from the start (a
        // soundbute name picks one of its files each time), OFF / KILL stop, TOGGLE stops a sound that
        // plays, else plays. A file missing from the export plays nothing and is listed in
        // SoundLoader.Missing; files load on their first play.
        void BuildSoundFX()
        {
            if (Data.soundFX == null || Data.soundFX.Length == 0) return;
            var parent = new GameObject("SoundFX");
            parent.transform.SetParent(Root.transform, false);
            var random = new System.Random();
            foreach (var s in Data.soundFX)
            {
                var go = new GameObject(s.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = new Vector3(s.pos[0], s.pos[1], s.pos[2]);
                var sound = AmbientSound.Add(go, s.inner, s.outer, s.volume, s.ambient != 0, s.priority);
                var files = s.files != null && s.files.Length > 0 ? s.files : new[] { s.file };
                Action play = () =>
                {
                    sound.Source.Stop();
                    var clip = SoundLoader.Load(files[random.Next(files.Length)]);
                    if (clip) sound.Play(clip, s.loop != 0, s.pitch);
                };
                if (s.startOn) play();
                JoinFlags(s.obj, StartFlags.Visible, null, () => { sound.Source.Stop(); go.SetActive(false); });
                Commands.Handle(s.obj, OnOffToggle(play, () => sound.Source.Stop(), () => sound.IsPlaying, "TRIGGER", "KILL"));
            }
        }

        // SoundButeFX: random files of their soundbute while on (SoundButeFX), from level start if they start
        // on. ON / OFF / TOGGLE switch it (SoundButeFX::OnTrigger). Missing files are listed in
        // SoundLoader.Missing; one with none of its files exported is skipped.
        void BuildSoundButeFX()
        {
            if (Data.soundButeFX == null || Data.soundButeFX.Length == 0) return;
            var parent = new GameObject("SoundButeFX");
            parent.transform.SetParent(Root.transform, false);
            foreach (var s in Data.soundButeFX)
            {
                var clips = Array.ConvertAll(s.files ?? new string[0], SoundLoader.Load);
                if (!Array.Exists(clips, c => c)) continue;
                var go = new GameObject(s.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = new Vector3(s.pos[0], s.pos[1], s.pos[2]);
                var fx = SoundButeFX.Add(go, s, clips);
                JoinFlags(s.obj, StartFlags.Visible, null, () => go.SetActive(false));
                Commands.Handle(s.obj, OnOffToggle(() => fx.On = true, () => fx.On = false, () => fx.On));
            }
        }

        // A sound's messages (SoundFX / SoundButeFX::OnTrigger): ON (or alsoOn) switches it on, OFF (or
        // alsoOff) off, TOGGLE off if it is on, else on.
        static MessageHandler OnOffToggle(Action on, Action off, Func<bool> isOn, string alsoOn = null, string alsoOff = null) => m =>
        {
            if (m.Is("ON") || (alsoOn != null && m.Is(alsoOn))) on();
            else if (m.Is("OFF") || (alsoOff != null && m.Is(alsoOff))) off();
            else if (m.Is("TOGGLE"))
            {
                if (isOn()) off();
                else on();
            }
            else return false;
            return true;
        };
    }
}
