using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // A drawn character, placed or spawned: its model, its attachments by position, the lit models.
    public class CharacterBody
    {
        public GameObject Root;           // its own model (the SkinnedMeshRenderer on the root)
        public readonly List<GameObject> Models = new List<GameObject>();   // Root, then its attachments
        public LoadedModel Model;
        public Transform[] Bones;
        public CharacterAnimation Animation;   // also LevelBuilder.CharacterAnims[id]; null when it has no animations
        public string Idle = "";
        public Vector3 Dims;              // its model's half-extents (LT units)
        public float SunAmount;
        public Actor Actor;
        // Attachment position (any case) -> its model; positions name the model's sockets.
        public readonly Dictionary<string, GameObject> Attachments = new Dictionary<string, GameObject>(StringComparer.OrdinalIgnoreCase);
        public readonly List<DynamicLights.Model> Lit = new List<DynamicLights.Model>();

        // Its head tracking (TrackedNodes.cs): the LookAt group, and per node in model order its bone and its bind
        // pose relative to its parent. Null without one.
        public LookAtGroup LookAt;
        public readonly List<(TrackedNode node, int bone, LTFrame fromParent)> Tracked = new List<(TrackedNode, int, LTFrame)>();

        public void Begin(GameObject root, ModelInstanceJson inst, (LoadedModel model, Transform[] bones) built, float sunAmount)
        {
            Root = root;
            Models.Add(root);
            (Model, Bones) = built;
            Idle = inst.anim ?? "";
            Dims = inst.dims != null && inst.dims.Length >= 3 ? new Vector3(inst.dims[0], inst.dims[1], inst.dims[2]) : Vector3.zero;
            SunAmount = sunAmount;
            if (Model != null && Bones != null && inst.lookAt != null && inst.lookAt.Length > 0) BuildLookAt(inst.lookAt);
        }

        // CTrackedNodeContext::_Init for kTrack_LookAt: each node the model has, constrained as given; a node
        // is the child of the next (LinkNodes); a clone copies its node's orientation. Nodes the model lacks
        // are left out (CreateTrackingNode fails).
        void BuildLookAt(LookAtNodeJson[] nodes)
        {
            var group = new LookAtGroup();
            TrackedNode previous = null;
            const float Deg = Mathf.Deg2Rad;
            foreach (var n in nodes)
            {
                int bone = NodeIndex(n.name);
                TrackedNode t = null;
                if (bone >= 0)
                {
                    LTVec? V(float[] v) => v != null && v.Length >= 3 ? new LTVec(v[0], v[1], v[2]) : (LTVec?)null;
                    float A(float[] v, int i) => v != null && v.Length > i ? v[i] * Deg : 0;
                    t = new TrackedNode(n.name, V(n.axis), V(n.up), A(n.discomfort, 0), A(n.discomfort, 1), A(n.max, 0), A(n.max, 1),
                                        n.maxVel * Deg);
                    if (previous != null) t.Child = previous;
                    Add(t, bone);
                    int clone = NodeIndex(n.clone);
                    if (clone >= 0) Add(TrackedNode.Clone(n.clone, t), clone);
                }
                previous = t;
            }
            if (Tracked.Count == 0) return;
            Tracked.Sort((a, b) => a.bone.CompareTo(b.bone));   // parents first, as the model evaluates them
            foreach (var t in Tracked) group.Nodes.Add(t.node);
            LookAt = group;

            void Add(TrackedNode t, int bone)
            {
                int parent = Model.data.nodes[bone].parent;
                var local = parent >= 0 ? Model.BindMatrix(parent).inverse * Model.BindMatrix(bone) : Model.BindMatrix(bone);
                Tracked.Add((t, bone, LevelBuilder.ToFrame(local)));
            }
        }

        int NodeIndex(string name)
        {
            if (string.IsNullOrEmpty(name)) return -1;
            var nodes = Model.data.nodes;
            for (int i = 0; i < nodes.Length; i++)
                if (string.Equals(nodes[i].name, name, StringComparison.OrdinalIgnoreCase)) return i;
            return -1;
        }

        public void AddAttachment(string position, GameObject go)
        {
            Models.Add(go);
            if (!string.IsNullOrEmpty(position)) Attachments[position] = go;
        }
    }

    // Characters as cutscene actors (Actors.cs; docs/research/cutscene-actors.md). Every drawn character,
    // placed (JoinActors, at load) or spawned (SpawnCharacter), gets an Actor between its first-update queue and
    // its GameBase handler, and its flags drawn: VISIBLE / HIDDEN on its own model, HIDDEN (HideCharacter) also
    // on its attachments, REMOVE takes it all away. The actors update after the characters' first updates
    // (CommandTicker); what they do is drawn here: a teleport or a turn moves the model (relit where it now
    // stands), ATTACH builds the level's attachable of that name on the socket the position names, DETACH
    // takes the one there away.
    public partial class LevelBuilder
    {
        public Actors Actors;
        // Command-manager id -> a placed character's body (its object index).
        public readonly Dictionary<int, CharacterBody> PlacedCharacters = new Dictionary<int, CharacterBody>();

        // CHumanAttachments' positions (tools/export_models.py ATTACHMENT_POSITIONS): ATTACH to any other does nothing.
        static readonly HashSet<string> AttachmentPositions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "RightHand", "LeftHand", "Head", "Eyes", "Nose", "Chin", "Back", "RightFoot", "LeftFoot", "Snowmobile",
            "Light", "LeftLowerArm", "LeftUpperArm", "RightLowerArm", "RightUpperArm", "LeftLowerLeg", "LeftUpperLeg",
            "RightLowerLeg", "RightUpperLeg", "UpperTorso", "Torso", "LeftShoulder", "RightShoulder", "RightHand2",
            "LeftHand2", "LeftLowerArm2", "LeftLowerLeg2", "LeftUpperArm2", "LeftUpperLeg2", "RightUpperArm2",
            "RightUpperLeg2", "RightLowerArm2", "RightLowerLeg2", "UpperTorso2", "LeftRod", "RightRod",
        };

        PlayerController player;
        int playerId = -1;

        // After BuildSpawners, before JoinObjectMessages: the placed characters' actors and flags.
        void JoinActors()
        {
            Actors = new Actors(Commands);
            Root.GetComponent<CommandTicker>().Actors = Actors;
            foreach (var kv in PlacedCharacters)
            {
                var o = Data.objects[kv.Key];
                var start = StartFlags.Visible | If(o.Bool("Solid", true), StartFlags.Solid) | If(o.Bool("Rayhit", true), StartFlags.RayHit);
                JoinActor(kv.Key, kv.Value, start);
            }
        }

        void JoinActor(int id, CharacterBody body, StartFlags start)
        {
            var root = body.Root.transform;
            var a = body.Actor = Actors.Add(id, body.Animation, body.Idle, ToLT(root.localPosition), ToLT(root.localRotation),
                                            ToLT(body.Dims));
            a.PositionOf = PositionOf;
            a.TeleportPointOf = TeleportPointOf;
            a.CastDown = (from, to) => IntersectWorld(from, to, out var hit, out _) ? hit.y : (float?)null;
            var placedAt = root.localPosition;
            a.Moved = () =>
            {
                var pos = new Vector3(a.Pos.x, a.Pos.y, a.Pos.z);
                root.localPosition = pos;
                root.localRotation = new Quaternion(a.Rot.x, a.Rot.y, a.Rot.z, a.Rot.w);
                if (pos == placedAt) return;
                placedAt = pos;
                foreach (var m in body.Lit) Relight(m, pos);
            };
            a.ShowAttachments = on => ShowAttachments(body, on);
            a.Attach = (position, name) => Attach(id, body, position, name);
            a.Detach = position => Detach(body, position);
            if (body.LookAt != null)
            {
                a.Track = on => body.LookAt.SetActive(on);
                if (tracking.Count == 0 && modelAnimator) modelAnimator.Posed += UpdateTracking;
                tracking.Add(body);
            }
            FxInstance icon = null;
            var anchor = new ActorAnchor(a);
            a.TalkIcon = on =>
            {
                Effects?.ShutDown(icon);
                icon = on ? Effects?.Start(TalkIconGroup, true, false, anchor) : null;
            };
            JoinFlags(id, start, f => ShowCharacter(body, f), () =>
            {
                Deactivate(body.Models);
                Effects?.ShutDown(icon);
                a.Remove();
            });
        }

        // cshell.dll 0x10169720: the client's talk icon, started on the character (tools/export_level.py ships it).
        const string TalkIconGroup = "AI_TALKICON";

        // An actor as what an effect follows.
        sealed class ActorAnchor : IFxObject
        {
            readonly Actor actor;
            public ActorAnchor(Actor actor) { this.actor = actor; }
            public LTVec Pos => actor.Pos;
            public LTQuat Rot => actor.Rot;

            public bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot)
            {
                pos = default;
                rot = default;
                return false;
            }
        }

        // VISIBLE, SOLID, HIDDEN on the character's own model; its attachments keep theirs (HideCharacter sets them).
        static void ShowCharacter(CharacterBody body, GameBaseFlags f)
        {
            if (!body.Root) return;
            foreach (var r in body.Root.GetComponents<Renderer>()) r.enabled = f.Visible;
            foreach (var c in body.Root.GetComponents<Collider>())
            {
                c.enabled = f.Solid || f.RayHit;
                c.gameObject.layer = f.Solid ? 0 : UseOnlyLayer;
            }
        }

        // CAttachments::HideAttachments.
        static void ShowAttachments(CharacterBody body, bool on)
        {
            for (int i = 1; i < body.Models.Count; i++)
                if (body.Models[i])
                    foreach (var r in body.Models[i].GetComponentsInChildren<Renderer>(true)) r.enabled = on;
        }

        // CAttachments::Attach: a position of the character's that is free gets the attachment of that name
        // (Data.attachables), on the model's socket of the position's name, lit where the character stands. A
        // name that draws nothing, or a socket the model lacks, creates nothing.
        void Attach(int id, CharacterBody body, string position, string name)
        {
            if (!AttachmentPositions.Contains(position) || body.Attachments.ContainsKey(position)) return;
            var inst = Array.Find(Data.attachables ?? Array.Empty<ModelInstanceJson>(),
                                  x => string.Equals(x.name, name, StringComparison.OrdinalIgnoreCase));
            if (inst == null) return;
            int lit = litModels.Count;
            var obj = id < Data.objects.Length ? Data.objects[id] : (body as SpawnedCharacter)?.Template;
            if (obj == null) return;
            var pos = body.Root.transform.localPosition;
            var go = BuildInstance(inst, obj, position, Commands.Name(id), pos, Quaternion.identity, body.SunAmount,
                                   (body.Model, body.Bones), out _, out _);
            if (!go) return;
            body.AddAttachment(position, go);
            body.Lit.AddRange(litModels.GetRange(lit, litModels.Count - lit));
            if (body.Actor != null && body.Actor.AttachmentsHidden)
                foreach (var r in go.GetComponentsInChildren<Renderer>(true)) r.enabled = false;
        }

        // CAttachments::Detach: the attachment at the position leaves.
        static void Detach(CharacterBody body, string position)
        {
            if (!body.Attachments.TryGetValue(position, out var go)) return;
            body.Attachments.Remove(position);
            body.Models.Remove(go);
            if (go) go.SetActive(false);
        }

        // The model lit again at pos (its sky visibility kept from where it was built).
        void Relight(DynamicLights.Model m, Vector3 pos)
        {
            m.Pos = pos;
            if (!m.R) return;
            var ambient = lighting.Compute(pos, m.Dims, m.VisRadius, m.SunAmount, lightDirs, lightColors);
            ModelLighting.ToUnit(lightColors);
            modelProps.Clear();
            modelProps.SetVector(AmbientId, ambient / 255f);
            modelProps.SetVectorArray(LightDirId, lightDirs);
            modelProps.SetVectorArray(LightColorId, lightColors);
            m.R.SetPropertyBlock(modelProps);
        }

        // An object's position (LT units) for FACEOBJECT: the player's, a character's where it stands, else the
        // level object's.
        LTVec? PositionOf(int id)
        {
            if (id == playerId && player)
                return ToLT(Root.transform.InverseTransformPoint(player.transform.position));
            var actor = Body(id)?.Actor;
            if (actor != null) return actor.Pos;
            if (id >= 0 && id < Data.objects.Length) return ToLT(Data.objects[id].Position);
            return null;
        }

        // A TeleportPoint's position, rotation and MoveToFloor (default on); null for any other object.
        (LTVec pos, LTQuat rot, bool moveToFloor)? TeleportPointOf(int id)
        {
            if (id < 0 || id >= Data.objects.Length) return null;
            var o = Data.objects[id];
            if (o.cls != "TeleportPoint") return null;
            return (ToLT(o.Position), ToLT(o.Rotation), o.Bool("MoveToFloor", true));
        }

        // The characters with a LookAt group, and where the player's head is on the player (its eye).
        readonly List<CharacterBody> tracking = new List<CharacterBody>();
        Vector3 playerEye;

        // Each frame once the bones are posed (ModelAnimator.Posed): every tracked node of a character still in the
        // level turns its bone toward the player's head (TRACKLOOKAT: SetTrackedTarget(player, "Head")), in the
        // level's space, parents first; a node that is off leaves the animation as it is.
        void UpdateTracking()
        {
            if (!player) return;
            float dt = Time.deltaTime;
            var level = Root.transform;
            var toLevel = level.worldToLocalMatrix;
            var eye = level.InverseTransformPoint(player.transform.TransformPoint(playerEye));
            var target = new LTVec(eye.x, eye.y, eye.z);
            foreach (var body in tracking)
            {
                if (!body.Root || !body.Root.activeInHierarchy) continue;
                foreach (var (node, index, fromParent) in body.Tracked)
                {
                    var bone = body.Bones[index];
                    var frame = ToFrame(toLevel * bone.localToWorldMatrix);
                    if (!node.Update(ToFrame(toLevel * bone.parent.localToWorldMatrix), fromParent, ref frame, target, dt)) continue;
                    var f = new Vector3(frame.F.x, frame.F.y, frame.F.z);
                    var u = new Vector3(frame.U.x, frame.U.y, frame.U.z);
                    bone.rotation = level.rotation * Quaternion.LookRotation(f, u);
                }
            }
        }

        // A matrix's rotation (its columns, scale taken out) and translation.
        internal static LTFrame ToFrame(Matrix4x4 m)
        {
            LTVec Col(int c)
            {
                var v = ((Vector3)m.GetColumn(c)).normalized;
                return new LTVec(v.x, v.y, v.z);
            }
            var t = m.GetColumn(3);
            return new LTFrame(Col(0), Col(1), Col(2), new LTVec(t.x, t.y, t.z));
        }

        // The body of the character joined as `id`, placed or spawned; null if none.
        public CharacterBody Body(int id) =>
            PlacedCharacters.TryGetValue(id, out var b) ? b : SpawnedCharacters.TryGetValue(id, out var s) ? s : null;

        // The player, for what characters look at and turn to (LevelBuilderDoors ConnectPlayer).
        void ConnectActors(int id, PlayerController p)
        {
            playerId = id;
            player = p;
            playerEye = p && p.Cam ? p.Cam.transform.localPosition : Vector3.zero;
        }

        static LTVec ToLT(Vector3 v) => new LTVec(v.x, v.y, v.z);
        static LTQuat ToLT(Quaternion q) => new LTQuat(q.x, q.y, q.z, q.w);
    }
}
