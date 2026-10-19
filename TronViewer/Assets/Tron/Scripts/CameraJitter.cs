using UnityEngine;

namespace Tron
{
    // Shakes the view by what the camera jitter effects moved the camera this frame (ClientFXMgr.CameraOffset,
    // LT units under the level root) and by the screen shake (CameraShake, decayed by this frame's time, in the
    // same axes and units; on top of a scene camera too, as UpdateCameraDisplacement runs after the camera
    // update): added to the main camera once everything has moved (before the glow
    // camera copies it and the effects are drawn for it), taken off again before the next frame's updates, so
    // the effects measure from, and the player moves and uses from, where the camera really is.
    [DefaultExecutionOrder(-10)]
    public class CameraJitter : MonoBehaviour
    {
        public ClientFXMgr Effects;
        public CameraShake Shake;
        Transform shaken;
        Vector3 applied;

        void Update() => TakeOff();

        void LateUpdate()
        {
            var cam = Camera.main;
            var o = (Effects != null ? Effects.CameraOffset : default) + (Shake != null ? Shake.Update(Time.deltaTime) : default);
            if (!cam) return;
            if (o.x == 0 && o.y == 0 && o.z == 0) return;
            shaken = cam.transform;
            var world = transform.TransformVector(new Vector3(o.x, o.y, o.z));
            applied = shaken.parent ? shaken.parent.InverseTransformVector(world) : world;
            shaken.localPosition += applied;
        }

        void TakeOff()
        {
            if (shaken) shaken.localPosition -= applied;
            shaken = null;
        }

        void OnDestroy() => TakeOff();
    }
}
