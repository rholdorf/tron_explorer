using UnityEngine;

namespace Tron
{
    // A door, switch or sliding/rotating world model in the level: runs its ActiveWorldModel once per
    // frame and puts the world model where it says (its collider moves with it; a solid one has a kinematic
    // body, so the player rides it). Plays the state sounds from the object through AmbientSound (3D,
    // priority 1, volume 100, inner 0.25 x SoundRadius, outer SoundRadius; a looping sound on one source,
    // one-shots on another so they play out), runs the state commands through the level's CommandMgr
    // (the AWM as sender, its activator as target), and tests the player against a new pose.
    public class ActiveWorldModelObject : MonoBehaviour, ActiveWorldModel.IHost
    {
        public ActiveWorldModel Awm { get; private set; }
        public string PromptOnText = "", PromptOffText = "";   // the ActivateType's texts

        CommandMgr commands;
        LevelJson data;
        int self;
        PlayerController player;
        CharacterController playerBody;
        AmbientSound loop, shots;
        Vector3 shownPos;
        Quaternion shownRot;
        static readonly Collider[] overlaps = new Collider[32];

        public void Init(ActiveWorldModel.Settings s, ObjectJson o, int self, LTVec? rotationPoint, CommandMgr commands, LevelJson data)
        {
            this.self = self;
            this.commands = commands;
            this.data = data;
            var pyr = new LTVec(o.rot[0], o.rot[1], o.rot[2]);
            Awm = new ActiveWorldModel(s, o.LTPosition, pyr, rotationPoint, self, -1, this);
            shownPos = transform.localPosition;
            shownRot = transform.localRotation;
        }

        public void ConnectPlayer(int id, PlayerController p)
        {
            Awm.Player = id;
            player = p;
            playerBody = p ? p.GetComponent<CharacterController>() : null;
        }

        // The use prompt for its state ("" for none).
        public string Prompt => Awm.PromptOn ? PromptOnText : PromptOffText;

        void Start() => Awm.Start();

        void Update()
        {
            // Moved by someone else (a keyframer): the state machine starts from there.
            if (transform.localPosition != shownPos) Awm.Pos = V(transform.localPosition);
            Awm.Update(commands.FrameTime);
            var pos = new Vector3(Awm.Pos.x, Awm.Pos.y, Awm.Pos.z);
            var r = Awm.Rot;
            var rot = new Quaternion(r.x, r.y, r.z, r.w);
            if (pos != shownPos || rot != shownRot)
            {
                transform.localPosition = shownPos = pos;
                transform.localRotation = shownRot = rot;
            }
        }

        // ---- IHost ----

        float ActiveWorldModel.IHost.Time => commands.Time;   // the server clock the relays and delayed commands run on

        public void PlaySound(string name, bool looped)
        {
            var clip = SoundLoader.Load(name);
            if (!clip) return;
            float outer = Awm.SoundRadius;
            if (looped)
            {
                if (!loop) loop = AmbientSound.Add(gameObject, 0.25f * outer, outer, 100, false, 1);
                loop.Play(clip, true);
            }
            else
            {
                if (!shots) shots = AmbientSound.Add(gameObject, 0.25f * outer, outer, 100, false, 1);
                shots.Source.PlayOneShot(clip);
            }
        }

        public void StopLoop()
        {
            if (loop) loop.Source.Stop();
        }

        public void Run(string command, int activator) => commands.Run(command, self, activator);

        // FindWorldModelObjectIntersections against the player: the world model put at the pose, the
        // player's capsule (a little inside its skin) overlapping any of its colliders. A player standing
        // on it rides it instead, and noclip goes through.
        public bool PlayerInside(LTVec pos, LTQuat rot)
        {
            if (!player || !playerBody || !playerBody.enabled || player.Noclip || player.StandingOn == transform) return false;
            var keepPos = transform.localPosition;
            var keepRot = transform.localRotation;
            transform.localPosition = new Vector3(pos.x, pos.y, pos.z);
            transform.localRotation = new Quaternion(rot.x, rot.y, rot.z, rot.w);
            Physics.SyncTransforms();
            var pt = playerBody.transform;
            var center = pt.TransformPoint(playerBody.center);
            float radius = Mathf.Max(0, playerBody.radius - playerBody.skinWidth);
            float half = Mathf.Max(0, playerBody.height / 2 - playerBody.radius);
            int n = Physics.OverlapCapsuleNonAlloc(center + Vector3.up * half, center - Vector3.up * half, radius, overlaps,
                ~(1 << LevelBuilder.UseOnlyLayer), QueryTriggerInteraction.Ignore);
            bool hit = false;
            for (int i = 0; i < n && !hit; i++)
                hit = overlaps[i].transform.IsChildOf(transform);
            transform.localPosition = keepPos;
            transform.localRotation = keepRot;
            Physics.SyncTransforms();
            return hit;
        }

        // The player's live position; another object's placed one.
        public LTVec? PositionOf(int obj)
        {
            if (obj < 0) return null;
            if (obj == Awm.Player) return player ? V(player.transform.position / LT.Scale) : (LTVec?)null;
            if (obj < data.objects.Length) return data.objects[obj].LTPosition;
            return null;
        }

        static LTVec V(Vector3 v) => new LTVec(v.x, v.y, v.z);
    }

    // A level object's properties for ActiveWorldModel.Settings.Read.
    public sealed class ObjectProps : ActiveWorldModel.IProps
    {
        readonly ObjectJson o;
        public ObjectProps(ObjectJson o) => this.o = o;
        public bool Bool(string key) => o.Bool(key);
        public float Num(string key) => o.Num(key);
        public string Str(string key) => o.Str(key);
        public LTVec Vec(string key) { var v = o.Vec(key); return new LTVec(v.x, v.y, v.z); }
    }
}
