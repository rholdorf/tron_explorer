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
        public Characters Characters;   // the characters' first updates, after the command table
        public Dialogues Dialogues;     // the dialogues' updates and the subtitle's clock, after them

        void Update()
        {
            Commands?.Update();
            Characters?.Update();
            Dialogues?.Update(Time.deltaTime);
        }
    }
}
