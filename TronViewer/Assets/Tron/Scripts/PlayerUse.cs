using UnityEngine;
using UnityEngine.InputSystem;

namespace Tron
{
    // Something the player can use: a door, switch or world model (ActiveWorldModelObject), or a model whose
    // look follows a state (StateModel: binary bits, security rezzers).
    public interface IUsable
    {
        bool CanBeUsed { get; }
        bool Locked { get; }      // the prompt shows grey
        string Prompt { get; }    // the ActivateType's text for its state, "" for none
        void Use(int player);     // ACTIVATE from the player
    }

    // The player's use (key E; CTargetMgr, CPlayerMgr::DoActivate, docs/research/triggers-doors.md): every
    // frame a ray from the camera along its view; the first thing it hits is the target (the static world
    // stops it; world models take it when solid, or when usable through their use-only collider; models
    // through their use box). In range when the hit point is within ActivationDistance (100 units,
    // hard-coded in Tron's cshell.dll). E sends the target ACTIVATE from the player; its permission sets
    // and a binary bit's energy always pass. Runs after the player moves.
    [DefaultExecutionOrder(110)]
    public class PlayerUse : MonoBehaviour
    {
        public const float ActivationDistance = 100;

        public Camera Cam;
        public int PlayerId = -1;
        // What the player can use, in range; null for none.
        public IUsable Target { get; private set; }

        PlayerController controller;

        void Awake() => controller = GetComponent<PlayerController>();

        void Update()
        {
            Target = null;
            if (!Cam) return;
            var t = Cam.transform;
            if (Physics.Raycast(t.position, t.forward, out var hit, ActivationDistance * LT.Scale, ~0, QueryTriggerInteraction.Ignore))
            {
                var usable = hit.collider.GetComponentInParent<IUsable>();
                if (usable != null && usable.CanBeUsed) Target = usable;
            }
            var kb = Keyboard.current;
            if (Target != null && kb != null && kb.eKey.wasPressedThisFrame && (!controller || controller.InputEnabled))
                Target.Use(PlayerId);
        }
    }
}
