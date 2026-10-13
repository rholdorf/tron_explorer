using UnityEngine;

namespace Tron
{
    // Ticks the level's pending-command table once per frame, before the objects update (the server
    // shell runs CCommandMgr::Update before PreUpdateObjects): a delay queued by an object in frame N is
    // first counted down in frame N+1.
    [DefaultExecutionOrder(-100)]
    public class CommandTicker : MonoBehaviour
    {
        public CommandMgr Commands;

        void Update() => Commands?.Update();
    }
}
