using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // The level's scene cameras (SceneCameras): each Camera object, in level order, joins the command manager
    // with its GameBase handler and its own messages, and gets a transform that keyframers move (166 KeyFramers
    // pan 58 cameras) and moveto cuts to a CameraPoint's place. StartActive ones are on from the start
    // (Camera::InitialUpdate). SceneCameraView looks through the live one. Templates are never created.
    public partial class LevelBuilder
    {
        public SceneCameras SceneCameras;
        public SceneCameraView SceneCameraView;

        void BuildSceneCameras()
        {
            SceneCameras = new SceneCameras(() => Commands.Time);
            var transforms = new Dictionary<SceneCamera, Transform>();
            GameObject parent = null;
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                if (o.cls != "Camera" || o.Bool("Template")) continue;
                if (!parent)
                {
                    parent = new GameObject("SceneCameras");
                    parent.transform.SetParent(Root.transform, false);
                }
                var go = new GameObject(o.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = o.Position;
                go.transform.localRotation = Rot(o);
                var p = new SceneCamera.Props
                {
                    ActiveTime = o.Num("ActiveTime", -1), OneTime = o.Bool("OneTime", true), Type = (int)o.Num("Type", 1),
                    StartActive = o.Bool("StartActive"), CanSkip = o.Bool("CanSkip", true),
                    OnSkipCleanupOnly = o.Bool("OnSkipCleanupOnly"), CleanupCommand = o.Str("CleanupCommand"),
                    FovX = o.Num("FovX", SceneCameras.NormalFovX), FovY = o.Num("FovY", SceneCameras.NormalFovY),
                };
                var flags = JoinFlags(i, StartFlags.Visible, null, null);
                var cam = SceneCameras.Add(o.name, p, flags);
                int id = i;
                var t = go.transform;
                cam.RunCommand = c => Commands.Run(c, id, id);
                cam.RemoveObject = () => flags.OnMessage(new Message(new[] { "REMOVE" }, -1));
                cam.FindPoint = CameraPoint;
                cam.MoveTo = pose =>
                {
                    t.localPosition = new Vector3(pose.Pos.x, pose.Pos.y, pose.Pos.z);
                    t.localRotation = new Quaternion(pose.Rot.x, pose.Rot.y, pose.Rot.z, pose.Rot.w);
                };
                Commands.Handle(i, cam.OnMessage);
                transforms[cam] = t;
                pointObjects[i] = t;
            }
            foreach (var c in SceneCameras.All) c.Start();
            SceneCameraView = Root.AddComponent<SceneCameraView>();
            SceneCameraView.Init(SceneCameras, transforms);
        }

        static Quaternion Rot(ObjectJson o)
        {
            var r = o.LTRotation;
            return new Quaternion(r.x, r.y, r.z, r.w);
        }

        // FindNamedObject for moveto: the first object with the name, if it's a CameraPoint.
        CameraPose? CameraPoint(string name)
        {
            int i = FirstNamed(name);
            if (i < 0 || !string.Equals(Data.objects[i].cls, "CameraPoint", StringComparison.OrdinalIgnoreCase)) return null;
            var o = Data.objects[i];
            return new CameraPose(o.LTPosition, o.LTRotation);
        }
    }
}
