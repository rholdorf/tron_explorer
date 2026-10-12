using UnityEngine;
using UnityEngine.InputSystem;

namespace Tron
{
    // First-person movement using the game's own numbers (attributes/serverbutes.txt [Player])
    // and the player dims (24, 53, 24) half-extents. All tunables are in LithTech units.
    // Runs after Spinner and Keyframer (default order 0), so a world model the player stands on has
    // already moved this frame when the player rides it.
    [DefaultExecutionOrder(100)]
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

        // The moving world model the player stands on (one with a kinematic body: a solid spinner's or a
        // live keyframer's), and its pose when the player last moved; a static floor is null.
        Transform standingOn;
        Vector3 standingPos;
        Quaternion standingRot;
        Collider ground;          // during a move: the most upward-facing surface hit
        float groundNormalY;

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
            standingOn = null;
            ApplyDims(HalfHeight);
        }

        // msg player (teleport <TeleportPoint>): done on the player's next update (CCharacter::UpdateTeleport),
        // since the command may run in the middle of a move. The view turns to the point's pitch and yaw, the
        // player drops to the floor below it and stops (PlayerMessages.DropToFloor).
        bool teleportPending;
        Vector3 teleportPos;
        float teleportYaw, teleportPitch;

        public void RequestTeleport(Vector3 worldPos, float yawDeg, float pitchDeg)
        {
            teleportPending = true;
            teleportPos = worldPos;
            teleportYaw = yawDeg;
            teleportPitch = pitchDeg;
        }

        void DoTeleport()
        {
            teleportPending = false;
            var pos = teleportPos;
            cc.enabled = false;   // not hit by its own cast
            Physics.SyncTransforms();
            if (Physics.Raycast(pos, Vector3.down, out var hit, PlayerMessages.FloorCastDistance * LT.Scale,
                                ~(1 << LevelBuilder.SkyLayer), QueryTriggerInteraction.Ignore))
                pos.y = PlayerMessages.DropToFloor(pos.y / LT.Scale, hit.point.y / LT.Scale, HalfHeight) * LT.Scale;
            Teleport(pos, teleportYaw);
            pitch = Mathf.Clamp(teleportPitch, -89f, 89f);
        }

        void Update()
        {
            if (teleportPending) DoTeleport();
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
                standingOn = null;
                return;
            }
            cc.enabled = true;
            // On the ground from the player's own last move: the carry's move below doesn't count.
            bool grounded = cc.isGrounded;
            Ride();

            // Crouch: shrink dims from the top, stand up only if there is room.
            if (crouch != crouched)
            {
                if (crouch || !Physics.SphereCast(transform.position, Radius * LT.Scale * 0.9f, Vector3.up, out _, (HalfHeight * 2 - crouchHalfHeight) * LT.Scale))
                {
                    crouched = crouch;
                    float half = crouched ? crouchHalfHeight : HalfHeight;
                    float delta = (HalfHeight - crouchHalfHeight) * LT.Scale * (crouched ? -1 : 1);
                    if (grounded) { cc.enabled = false; transform.position += Vector3.up * delta; cc.enabled = true; }
                    ApplyDims(half);
                }
            }

            float speed = crouched ? crouchSpeed : walk ? walkSpeed : runSpeed;
            var wish = (transform.forward * move.y + transform.right * move.x) * speed;
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

            ground = null;
            groundNormalY = 0.001f;
            var flags = cc.Move(velocity * LT.Scale * dt);
            if ((flags & CollisionFlags.Above) != 0 && velocity.y > 0) velocity.y = 0;
            StandOn(ground);
        }

        // The engine carries what stands on a solid world model when the world model moves or turns
        // (MoveObject, RotateWorldModel with MO_MOVESTANDINGONS; on the client CMoveMgr::OnObjectMove and
        // OnObjectRotate do it for every solid world model): the rider is moved, with collision, to where
        // Riding.Carry puts it. Its view is not turned and it gains no velocity.
        void Ride()
        {
            if (!standingOn) return;
            // Colliders follow their transforms only at the physics step (autoSyncTransforms is off):
            // bring the world models' colliders to this frame's pose before moving against them.
            Physics.SyncTransforms();
            var pos = standingOn.position;
            var rot = standingOn.rotation;
            if (pos == standingPos && rot == standingRot) return;
            var to = Riding.Carry(V(transform.position), V(standingPos), Q(standingRot), V(pos), Q(rot));
            cc.Move(new Vector3(to.x, to.y, to.z) - transform.position);
        }

        // CPlayerMover::SetStandingOn: after its move the player stands on the object below it, unless the
        // surface is vertical. Only a moving world model (kinematic body) is remembered.
        void StandOn(Collider c)
        {
            var body = c ? c.attachedRigidbody : null;
            standingOn = body && body.isKinematic ? body.transform : null;
            if (!standingOn) return;
            standingPos = standingOn.position;
            standingRot = standingOn.rotation;
        }

        void OnControllerColliderHit(ControllerColliderHit hit)
        {
            if (hit.normal.y > groundNormalY)
            {
                ground = hit.collider;
                groundNormalY = hit.normal.y;
            }
        }

        static LTVec V(Vector3 v) => new LTVec(v.x, v.y, v.z);
        static LTQuat Q(Quaternion q) => new LTQuat(q.x, q.y, q.z, q.w);

        public float Yaw => yaw;

        public void SetView(float yawDeg, float pitchDeg) { yaw = yawDeg; pitch = Mathf.Clamp(pitchDeg, -89f, 89f); }
    }
}
