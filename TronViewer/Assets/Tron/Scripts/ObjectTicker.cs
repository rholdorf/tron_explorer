using UnityEngine;

namespace Tron
{
    // Ticks the level's objects (Relays.UpdateObjects: startup commands, triggers, the start point's command)
    // once per frame after the pending-command table, with the player's box (its CharacterController, in LT
    // units) for the triggers' touch; no player before the spawn.
    [DefaultExecutionOrder(-90)]
    public class ObjectTicker : MonoBehaviour
    {
        public Relays Relays;
        // Keeps feeding the triggers the player's last box while the camera flies elsewhere (the -shots
        // captures), so moving between poses touches nothing.
        public static bool FreezePlayerBox;
        TronExplorer explorer;
        CharacterController player;
        LTVec lastMin, lastMax;

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
            if (!FreezePlayerBox)
            {
                var c = player.transform.TransformPoint(player.center) / LT.Scale;
                var h = new Vector3(player.radius, player.height / 2, player.radius) / LT.Scale;
                lastMin = new LTVec(c.x - h.x, c.y - h.y, c.z - h.z);
                lastMax = new LTVec(c.x + h.x, c.y + h.y, c.z + h.z);
            }
            Relays.UpdateObjects(explorer.PlayerId, lastMin, lastMax);
        }
    }
}
