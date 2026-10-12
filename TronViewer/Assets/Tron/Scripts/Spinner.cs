using UnityEngine;

namespace Tron
{
    // Turns a spinner's world model (tools/spinner.py): from the level's start each axis spins up from 0
    // to its final velocity over PowerOnTime along the waveform, then keeps turning. The angles (pitch,
    // yaw, roll) accumulate from 0 and the world model is set to Rotation * Euler(pitch, yaw, roll) about
    // its position (ActiveWorldModel::CalculateNewPosRot), so it turns on the axes of its own frame.
    // Its collider is a child of the same object and turns with it.
    public class Spinner : MonoBehaviour
    {
        Vector3 final;          // rad/s
        float powerOnTime;
        int waveform;
        Quaternion baseRotation;
        Vector3 angles;         // rad
        float time;

        public void Init(SpinnerJson s)
        {
            final = new Vector3(s.velocity[0], s.velocity[1], s.velocity[2]);
            powerOnTime = s.powerOnTime;
            waveform = s.waveform;
            baseRotation = transform.localRotation;
        }

        void Update()
        {
            float dt = Time.deltaTime;
            time += dt;
            // UpdatePowerOn, then UpdateOn: velocity for this frame, then the angles move by it.
            angles += Velocity(time) * dt;
            angles.x = Mathf.Repeat(angles.x, 2 * Mathf.PI);
            angles.y = Mathf.Repeat(angles.y, 2 * Mathf.PI);
            angles.z = Mathf.Repeat(angles.z, 2 * Mathf.PI);
            transform.localRotation = baseRotation * Quaternion.Euler(angles * Mathf.Rad2Deg);
        }

        Vector3 Velocity(float t)
        {
            float p = powerOnTime > 0 ? t / powerOnTime : float.PositiveInfinity;
            if (p > 1) return final;
            float f = SpinUp(waveform, p);
            return new Vector3(Axis(final.x, f), Axis(final.y, f), Axis(final.z, f));
        }

        // Retail UpdatePowerOn (object.lto 0x1022ab60) stops an axis' ramp once v >= |final|: a positive
        // speed snaps to final, a negative one ramps until PowerOnTime is over.
        static float Axis(float final, float f)
        {
            float v = final * f;
            return v >= Mathf.Abs(final) ? final : v;
        }

        // The fraction of the final velocity reached at p = t / PowerOnTime: the integral over the ramp of
        // ActiveWorldModel::GetWaveformValue(final / PowerOnTime, p), whose 0.001 * rate term is SlowOn's
        // and SlowOff's offset.
        static float SpinUp(int waveform, float p)
        {
            switch (waveform)
            {
                case 1: return (1 - Mathf.Cos(Mathf.PI * p)) / 2;                       // Sine
                case 2: return Mathf.Sin(Mathf.PI / 2 * p) - 0.001f * p;                // SlowOff
                case 3: return 1 - Mathf.Cos(Mathf.PI / 2 * p) + 0.001f * p;            // SlowOn
                default: return p;                                                      // Linear
            }
        }
    }
}
