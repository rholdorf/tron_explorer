using System.IO;
using System.Linq;
using UnityEngine;

namespace Tron
{
    // iocam (IOCam): the player's IOCAM message, joined once the player is (ConnectPlayer); IOCamView draws the
    // inset and its frame (hud/iocam.json), and the target's lines play in the player's head
    // (Dialogues.IsIOCamTarget).
    public partial class LevelBuilder
    {
        public IOCam IOCam;
        public IOCamView IOCamView;

        // After BuildDialogues.
        void BuildIOCam(string exportRoot)
        {
            IOCamLayout layout = null;
            var path = Path.Combine(exportRoot ?? "", "hud", "iocam.json");
            if (exportRoot != null && File.Exists(path)) layout = JsonUtility.FromJson<IOCamLayout>(File.ReadAllText(path));
            IOCam = new IOCam(layout, ViewerRandom.NextDouble());
            Dialogues.IsIOCamTarget = id => IOCam.Target == id;
            IOCamView = Root.AddComponent<IOCamView>();
            IOCamView.Init(IOCam);
        }

        // The player joins (ConnectPlayer): its IOCAM message.
        void ConnectIOCam(int id) => IOCam.Handle(Commands, id, PlaceOf, FirstAlive, Exists);

        bool Exists(int id) => !withFlags.TryGetValue(id, out var f) || !f.Removed;

        // FindNamedObjects' first object of the name that is still in the level, -1 if none.
        int FirstAlive(string name) => Commands.Named(name).Where(Exists).DefaultIfEmpty(-1).First();

        // The position and rotation the first object of that name still in the level has now (PoseOf).
        CameraPose? PlaceOf(string name) => PoseOf(FirstAlive(name));
    }
}
