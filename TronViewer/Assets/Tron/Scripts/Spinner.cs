using UnityEngine;

namespace Tron
{
    // Turns a spinner's world model as its SpinnerMotion says (one engine update per frame): the angles
    // (pitch, yaw, roll) accumulate from 0 and the world model is set to Rotation * Euler(pitch, yaw, roll)
    // about its position (ActiveWorldModel::CalculateNewPosRot), so it turns on the axes of its own frame.
    // Its collider is a child of the same object and turns with it. The motion also takes the spinner's
    // messages (ON, OFF...: LevelBuilder.BuildSpinners joins it to the level's command manager).
    public class Spinner : MonoBehaviour
    {
        SpinnerMotion motion;
        Quaternion baseRotation;

        public void Init(SpinnerMotion motion)
        {
            this.motion = motion;
            baseRotation = transform.localRotation;
        }

        void Update()
        {
            motion.Update(Time.deltaTime);
            var angles = new Vector3(motion.Pitch, motion.Yaw, motion.Roll) * Mathf.Rad2Deg;
            transform.localRotation = baseRotation * Quaternion.Euler(angles);
        }
    }
}
