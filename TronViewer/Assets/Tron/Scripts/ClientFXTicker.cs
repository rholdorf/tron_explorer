using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Runs the level's effect manager once per frame, after keyframers have moved the SpecialFX objects
    // (each object's place is read from its transform, LT units under the level root), with the camera's
    // place for the distance freeze. Client time: Time.deltaTime.
    [DefaultExecutionOrder(50)]
    public class ClientFXTicker : MonoBehaviour
    {
        public ClientFXMgr Effects;
        public readonly List<(SpecialFX fx, Transform t)> Objects = new List<(SpecialFX, Transform)>();

        void Update()
        {
            if (Effects == null) return;
            foreach (var (fx, t) in Objects)
            {
                var p = t.localPosition;
                var r = t.localRotation;
                fx.Pos = new LTVec(p.x, p.y, p.z);
                fx.Rot = new LTQuat(r.x, r.y, r.z, r.w);
            }
            var cam = Camera.main;
            var c = cam ? transform.InverseTransformPoint(cam.transform.position) : Vector3.zero;
            Effects.Update(Time.deltaTime, new LTVec(c.x, c.y, c.z));
        }

        void OnDestroy() => Effects?.Clear();
    }
}
