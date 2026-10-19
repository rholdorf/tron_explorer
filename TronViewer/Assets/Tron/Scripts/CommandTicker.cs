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
        public Actors Actors;           // then the characters' AI updates (Actors.cs)
        public Dialogues Dialogues;     // the dialogues' updates and the subtitle's clock, after them
        public ScreenShakes ScreenShakes;   // then the screen shakes' timers

        void Update()
        {
            Commands?.Update();
            Characters?.Update();
            Actors?.Update(Commands?.FrameTime ?? Time.deltaTime);
            Actors?.RunKeys();   // the animation keys their animations crossed (CMD keys run commands)
            Dialogues?.Update(Time.deltaTime);
            ScreenShakes?.Update();
        }
    }
}
