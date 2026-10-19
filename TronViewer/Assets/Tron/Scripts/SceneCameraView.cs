using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;

namespace Tron
{
    // Looks through the level's live scene camera (SceneCameras), as the game's client does each frame: the
    // main camera takes the camera object's position and full rotation (pitch and roll too) after the
    // keyframers and the player moved, and its FOV (SceneCameras.ViewFov); its AudioListener goes with it, so
    // the scene is heard from the camera. The player is held meanwhile (TronExplorer: input off;
    // PlayerController.Held). Keys while a scene plays: Space skips (CPlayerMgr::OnKeyDown, VK_SPACE), V (the
    // explorer's) leaves the scene camera for free flight from where it looks while the scene runs on, and
    // back; free flight ends with the scene. When no camera is live the view is the player's again, at the
    // normal FOV. Runs after PlayerController, before PlayerUse.
    [DefaultExecutionOrder(105)]
    public class SceneCameraView : MonoBehaviour
    {
        public SceneCameras Cameras { get; private set; }
        Dictionary<SceneCamera, Transform> transforms;
        PlayerController player;
        Vector3 eye;          // the main camera's place on the player, while the scene camera has it
        bool holding, froze;

        // Set by TronExplorer: the keys work (no menu), and the view is left alone (-shots, -benchat).
        public bool Playing;
        public bool Suspended;

        // A scene camera is the view (not in free flight).
        public bool ShowingScene => holding;
        public bool FreeFlight => player && player.FreeFlight;
        public string LiveName => Cameras.Live?.Name;

        public void Init(SceneCameras cameras, Dictionary<SceneCamera, Transform> transforms)
        {
            Cameras = cameras;
            this.transforms = transforms;
        }

        void Update()
        {
            if (!player) player = FindFirstObjectByType<PlayerController>();
            Cameras.Update(Time.deltaTime);
            var live = Cameras.Live;
            if (!player || !player.Cam || Suspended)
            {
                Release();
                return;
            }
            var kb = Keyboard.current;
            if (live == null)
            {
                if (player.FreeFlight) player.EndFreeFlight();
            }
            else if (kb != null && Playing)
            {
                if (kb.vKey.wasPressedThisFrame)
                {
                    if (player.FreeFlight) player.EndFreeFlight();
                    else
                    {
                        Release();
                        var t = transforms[live];
                        var f = t.forward;
                        player.BeginFreeFlight(t.position - player.Cam.transform.localPosition,
                            Mathf.Atan2(f.x, f.z) * Mathf.Rad2Deg, -Mathf.Asin(Mathf.Clamp(f.y, -1, 1)) * Mathf.Rad2Deg);
                    }
                }
                else if (kb.spaceKey.wasPressedThisFrame && !player.FreeFlight)
                {
                    Cameras.Skip();
                    Cameras.Update(0);   // the cameras the skip turned off are gone from this frame's view
                    live = Cameras.Live;
                }
            }
            // The triggers keep the player's box while it flies (ObjectTicker), so free flight touches nothing.
            if (player.FreeFlight != froze) ObjectTicker.FreezePlayerBox = froze = player.FreeFlight;
            player.Held = Cameras.Held && !player.FreeFlight;

            if (live == null || player.FreeFlight)
            {
                Release();
                return;
            }
            var cam = player.Cam;
            if (!holding)
            {
                eye = cam.transform.localPosition;
                holding = true;
            }
            var lt = transforms[live];
            cam.transform.SetPositionAndRotation(lt.position, lt.rotation);
            cam.fieldOfView = SceneCameras.ViewFov(Cameras.FovX);
        }

        // The view goes back to the player's eye at the normal FOV.
        void Release()
        {
            if (!holding) return;
            holding = false;
            if (!player || !player.Cam) return;
            player.Cam.transform.localPosition = eye;
            player.Cam.fieldOfView = SceneCameras.ViewFov(SceneCameras.NormalFovX);
        }

        void OnDestroy()
        {
            Release();
            if (froze) ObjectTicker.FreezePlayerBox = false;
            if (player)
            {
                player.Held = false;
                player.EndFreeFlight();
            }
        }
    }
}
