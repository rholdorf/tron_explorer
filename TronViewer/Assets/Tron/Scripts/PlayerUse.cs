using UnityEngine;
using UnityEngine.InputSystem;

namespace Tron
{
    // The player's use (key E; CTargetMgr, CPlayerMgr::DoActivate, docs/research/triggers-doors.md): every
    // frame a ray from the camera along its view; the first thing it hits is the target (the static world
    // stops it; world models take it when solid, or when usable through their use-only collider). In range
    // when the hit point is within ActivationDistance (100 units, hard-coded in Tron's cshell.dll). E sends
    // the target ACTIVATE from the player; its permission sets always pass. Runs after the player moves.
    [DefaultExecutionOrder(110)]
    public class PlayerUse : MonoBehaviour
    {
        public const float ActivationDistance = 100;

        public Camera Cam;
        public int PlayerId = -1;
        // A door, switch or world model the player can use, in range; null for none.
        public ActiveWorldModelObject Target { get; private set; }

        PlayerController controller;

        void Awake() => controller = GetComponent<PlayerController>();

        void Update()
        {
            Target = null;
            if (!Cam) return;
            var t = Cam.transform;
            if (Physics.Raycast(t.position, t.forward, out var hit, ActivationDistance * LT.Scale, ~0, QueryTriggerInteraction.Ignore))
            {
                var awm = hit.collider.GetComponentInParent<ActiveWorldModelObject>();
                if (awm && awm.Awm.S.PlayerActivate) Target = awm;
            }
            var kb = Keyboard.current;
            if (Target && kb != null && kb.eKey.wasPressedThisFrame && (!controller || controller.InputEnabled))
                Target.Awm.Activate(PlayerId);
        }
    }
}
