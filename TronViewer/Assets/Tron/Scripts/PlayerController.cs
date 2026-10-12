using UnityEngine;
using UnityEngine.InputSystem;

namespace Tron
{
    // First-person movement using the game's own numbers (attributes/serverbutes.txt [Player])
    // and the player dims (24, 53, 24) half-extents. All tunables are in LithTech units.
    [RequireComponent(typeof(CharacterController))]
    public class PlayerController : MonoBehaviour
    {
        public float runSpeed = 280, walkSpeed = 115, crouchSpeed = 115, jumpSpeed = 700;
        public float gravity = 2000;          // LithTech default world gravity (units/s^2)
        public float groundAccel = 3000, airAccel = 600;
        public float stepHeight = 18;
        public float eyeHeight = 40;          // above the dims center (106 tall -> eyes at 93)
        public float crouchHalfHeight = 30;
        public float noclipSpeed = 1200;
        public float mouseSensitivity = 0.1f;

        public bool Noclip;
        public bool InputEnabled = true;
        public Camera Cam;

        CharacterController cc;
        Vector3 velocity;     // LT units/s
        float yaw, pitch;
        bool crouched;
        const float HalfHeight = 53, Radius = 24;

        void Awake()
        {
            cc = GetComponent<CharacterController>();
            ApplyDims(HalfHeight);
            cc.radius = Radius * LT.Scale;
            cc.stepOffset = stepHeight * LT.Scale;
            cc.skinWidth = 1.0f * LT.Scale;
            cc.minMoveDistance = 0;
            cc.slopeLimit = 45;
        }

        void ApplyDims(float half)
        {
            cc.height = half * 2 * LT.Scale;
            cc.center = Vector3.zero;
            if (Cam) Cam.transform.localPosition = new Vector3(0, (half - 53 + eyeHeight) * LT.Scale, 0);
        }

        public void Teleport(Vector3 worldPos, float yawDeg)
        {
            cc.enabled = false;
            transform.position = worldPos;
            cc.enabled = true;
            yaw = yawDeg;
            pitch = 0;
            velocity = Vector3.zero;
            ApplyDims(HalfHeight);
        }

        void Update()
        {
            var kb = Keyboard.current;
            var mouse = Mouse.current;
            if (kb == null || mouse == null) return;
            float dt = Mathf.Min(Time.deltaTime, 0.05f);

            if (InputEnabled)
            {
                var md = mouse.delta.ReadValue() * mouseSensitivity;
                yaw += md.x;
                pitch = Mathf.Clamp(pitch - md.y, -89f, 89f);
                if (kb.nKey.wasPressedThisFrame) Noclip = !Noclip;
            }
            transform.rotation = Quaternion.Euler(0, yaw, 0);
            if (Cam) Cam.transform.localRotation = Quaternion.Euler(pitch, 0, 0);

            Vector2 move = Vector2.zero;
            bool jump = false, walk = false, crouch = false, up = false;
            if (InputEnabled)
            {
                if (kb.wKey.isPressed || kb.upArrowKey.isPressed) move.y += 1;
                if (kb.sKey.isPressed || kb.downArrowKey.isPressed) move.y -= 1;
                if (kb.dKey.isPressed || kb.rightArrowKey.isPressed) move.x += 1;
                if (kb.aKey.isPressed || kb.leftArrowKey.isPressed) move.x -= 1;
                jump = kb.spaceKey.wasPressedThisFrame;
                up = kb.spaceKey.isPressed;
                walk = kb.leftShiftKey.isPressed;
                crouch = kb.cKey.isPressed || kb.leftCtrlKey.isPressed;
            }
            if (move.sqrMagnitude > 1) move.Normalize();

            if (Noclip)
            {
                cc.enabled = false;
                var dir = Cam.transform.forward * move.y + Cam.transform.right * move.x;
                if (up) dir += Vector3.up;
                if (crouch) dir -= Vector3.up;
                float sp = noclipSpeed * (walk ? 0.25f : 1f) * (kb.leftAltKey.isPressed ? 4f : 1f);
                transform.position += dir * sp * LT.Scale * dt;
                velocity = Vector3.zero;
                return;
            }
            cc.enabled = true;

            // Crouch: shrink dims from the top, stand up only if there is room.
            if (crouch != crouched)
            {
                if (crouch || !Physics.SphereCast(transform.position, Radius * LT.Scale * 0.9f, Vector3.up, out _, (HalfHeight * 2 - crouchHalfHeight) * LT.Scale))
                {
                    crouched = crouch;
                    float half = crouched ? crouchHalfHeight : HalfHeight;
                    float delta = (HalfHeight - crouchHalfHeight) * LT.Scale * (crouched ? -1 : 1);
                    if (cc.isGrounded) { cc.enabled = false; transform.position += Vector3.up * delta; cc.enabled = true; }
                    ApplyDims(half);
                }
            }

            float speed = crouched ? crouchSpeed : walk ? walkSpeed : runSpeed;
            var wish = (transform.forward * move.y + transform.right * move.x) * speed;
            bool grounded = cc.isGrounded;
            var horiz = new Vector3(velocity.x, 0, velocity.z);
            horiz = Vector3.MoveTowards(horiz, wish, (grounded ? groundAccel : airAccel) * dt);
            velocity.x = horiz.x;
            velocity.z = horiz.z;

            if (grounded)
            {
                if (velocity.y < 0) velocity.y = -200; // keep glued to slopes/stairs
                if (jump && !crouched) velocity.y = jumpSpeed;
            }
            velocity.y -= gravity * dt;

            var flags = cc.Move(velocity * LT.Scale * dt);
            if ((flags & CollisionFlags.Above) != 0 && velocity.y > 0) velocity.y = 0;
        }

        public float Yaw => yaw;

        public void SetView(float yawDeg, float pitchDeg) { yaw = yawDeg; pitch = Mathf.Clamp(pitchDeg, -89f, 89f); }
    }
}
