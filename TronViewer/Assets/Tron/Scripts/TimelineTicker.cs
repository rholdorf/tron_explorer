using UnityEngine;

namespace Tron
{
    // Starts each server frame: the command manager's clock (CommandMgr.BeginFrame, which the relays, the
    // pending-command table and the doors all time on), then the command objects' timelines
    // (Relays.UpdateTimelines), before the pending-command table (CommandTicker; the server shell updates the
    // lite objects first). ObjectTicker runs the level's objects after it.
    [DefaultExecutionOrder(-110)]
    public class TimelineTicker : MonoBehaviour
    {
        public CommandMgr Commands;
        public Relays Relays;

        void Update()
        {
            Commands?.BeginFrame(Time.deltaTime);
            Relays?.UpdateTimelines();
        }
    }
}
