using UnityEngine;

namespace Tron
{
    // Ticks the level's triggers once per frame after the pending-command table, with the player's box (its
    // CharacterController, in LT units) for their touch; no player before the spawn.
    [DefaultExecutionOrder(-90)]
    public class TriggerTicker : MonoBehaviour
    {
        public Relays Relays;
        TronExplorer explorer;
        CharacterController player;

        void Update()
        {
            if (Relays == null) return;
            if (!explorer) explorer = FindFirstObjectByType<TronExplorer>();
            if (!player)
            {
                var pc = FindFirstObjectByType<PlayerController>(FindObjectsInactive.Include);
                if (pc) player = pc.GetComponent<CharacterController>();
            }
            if (!explorer || !player || !player.gameObject.activeInHierarchy || explorer.PlayerId < 0)
            {
                Relays.UpdateObjects(-1, default, default);
                return;
            }
            var c = player.transform.TransformPoint(player.center) / LT.Scale;
            var h = new Vector3(player.radius, player.height / 2, player.radius) / LT.Scale;
            Relays.UpdateObjects(explorer.PlayerId, new LTVec(c.x - h.x, c.y - h.y, c.z - h.z),
                new LTVec(c.x + h.x, c.y + h.y, c.z + h.z));
        }
    }
}
