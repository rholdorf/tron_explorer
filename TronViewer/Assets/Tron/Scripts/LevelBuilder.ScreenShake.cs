using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace Tron
{
    // The level's ScreenShake objects (ScreenShakes) and iocam (IOCam). Each ScreenShake (not a template) joins with
    // its GameBase handler (REMOVE: no more pulses) and ON / OFF; they update each frame after the command table (CommandTicker). A pulse
    // plays ShakeSound at the object (a soundbute one of its files, from level.json buteSounds; 3D, outer radius
    // SoundRadius, inner a quarter of it) and, when the player is in range, shakes the player's client: CameraShake,
    // which CameraJitter adds to the view with the camera jitter effects', scene camera or not. iocam is the
    // player's IOCAM message, joined once the player is (ConnectPlayer); IOCamView draws the inset and its frame,
    // and the target's lines play in the player's head (Dialogues.IsIOCamTarget).
    public partial class LevelBuilder
    {
        public ScreenShakes ScreenShakes;
        public readonly CameraShake CameraShake = new CameraShake();
        public IOCam IOCam;
        public IOCamView IOCamView;

        // After BuildSpecialFX (the sound player, CameraJitter) and BuildDialogues.
        void BuildScreenShakes(string exportRoot)
        {
            ScreenShakes = new ScreenShakes(Commands) { ShakeScreen = CameraShake.Add };
            Root.GetComponent<CommandTicker>().ScreenShakes = ScreenShakes;
            var jitter = Root.GetComponent<CameraJitter>();
            if (!jitter) jitter = Root.AddComponent<CameraJitter>();
            jitter.Shake = CameraShake;
            var player = Root.GetComponent<FxSoundPlayer>();
            if (!player) player = Root.AddComponent<FxSoundPlayer>();
            ScreenShakes.PlaySound = (pos, sound, radius) =>
            {
                var file = ButeSounds.TryGetValue(sound.Trim(), out var b) ? b.AnyFile() : sound;
                if (file != null) player.PlayAt(file, pos, radius * AmbientSound.InnerRadiusPercent, radius);
            };
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                if (o.cls != "ScreenShake" || o.Bool("Template")) continue;
                var a = o.Vec("Amount", Vector3.one);
                var p = new ScreenShakeProps
                {
                    Amount = new LTVec(a.x, a.y, a.z), NumShakes = (int)o.Num("NumShakes", -1), Frequency = o.Num("Frequency", 1),
                    AreaOfEffect = o.Num("AreaOfEffect", ScreenShakes.EntireLevel), ShakeSound = o.Str("ShakeSound"),
                    SoundRadius = o.Num("SoundRadius", 500),
                };
                var shake = ScreenShakes.Add(o.LTPosition, p);
                JoinFlags(i, StartFlags.None, null, () => shake.OnMessage(new Message(new[] { "OFF" }, -1)));
                Commands.Handle(i, shake.OnMessage);
            }

            IOCamLayout layout = null;
            var path = Path.Combine(exportRoot ?? "", "hud", "iocam.json");
            if (exportRoot != null && File.Exists(path)) layout = JsonUtility.FromJson<IOCamLayout>(File.ReadAllText(path));
            IOCam = new IOCam(layout);
            Dialogues.IsIOCamTarget = id => IOCam.Target == id;
            IOCamView = Root.AddComponent<IOCamView>();
            IOCamView.Init(IOCam);
        }

        // The player joins (ConnectPlayer): what the shakes measure their area from, and its IOCAM message.
        void ConnectShakes(int id, PlayerController p)
        {
            ScreenShakes.PlayerPos = () => p ? WorldToLT(p.transform.position) : (LTVec?)null;
            IOCam.Handle(Commands, id, PlaceOf, FirstAlive, Exists);
        }

        bool Exists(int id) => !withFlags.TryGetValue(id, out var f) || !f.Removed;

        // FindNamedObjects' first object of the name that is still in the level, -1 if none.
        int FirstAlive(string name) => Commands.Named(name).Where(Exists).DefaultIfEmpty(-1).First();

        // The position and rotation the first object of that name still in the level has now (PoseOf).
        CameraPose? PlaceOf(string name) => PoseOf(FirstAlive(name));
    }
}
