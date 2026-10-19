using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Mirrors tools/export_level.py (level.json). Positions are raw LithTech units.
    [Serializable] public class LevelJson
    {
        public int version;
        public string name;
        public string info;
        public float[] extMin, extMax, offset;
        public MaterialJson[] materials;
        public MeshJson[] meshes;
        public ColliderJson[] colliders;
        public int[] worldMeshes;
        public int worldCollider;
        public int blockerCollider;
        public WorldModelJson[] worldModels;
        public SpinnerJson[] spinners;       // spinners, on at start or not (tools/spinner.py)
        public SoundFXJson[] soundFX;        // SoundFX, on at start or not (tools/ambient.py)
        public SoundButeFXJson[] soundButeFX; // SoundButeFX, on at start or not (tools/ambient.py)
        public KeyframerJson[] keyframers;   // keyframers, active at start or not (tools/keyframer.py)
        public ActivateTypeJson[] activateTypes; // the use prompts its objects name (tools/activate.py)
        public SpawnJson[] spawns;           // the names spawners give what they create (tools/commands.py spawn_names)
        public SpawnSiteJson[] spawnSites;   // where Spawners create characters (tools/export_level.py spawn_sites)
        public DialogueJson[] dialogues;     // its Dialogue objects, in object order (tools/dialogue.py)
        public SpeakerJson[] speakers;       // the AIs and Speakers a line can name, templates too (tools/dialogue.py)
        public FxGroupJson[] fxGroups;       // the effect groups its SpecialFX reach (tools/clientfx.py export_group)
        public string[] fxMissing;           // names that find no group
        public ObjectJson[] objects;
        public ModelInstanceJson[] models;
        public ModelInstanceJson[] attachables; // what `attach <position> <name>` hangs on a character, by name
        public ButeSoundJson[] buteSounds;   // the soundbutes the state models' clips (BUTE_SOUND_KEY) and the ScreenShakes play
        public RenderStyleJson[] renderStyles;
        public LightGridJson lightGrid;      // samples follow the lightmap atlas in level.bin
        public StaticLightJson[] lights;
        public SunJson sun;                  // black when the level has none
    }

    // A level object that shows a model: object index, model file, skin and render style slots,
    // and per exported piece its render style (index into renderStyles) and texture list.
    // skinned: drawn by a SkinnedMeshRenderer over the model's nodes (characters and their attachments).
    // parent >= 0: an attachment, carried by that instance (a character or a prop) at its model socket `socket`.
    // dims: half-extents (LT units, scaled); visRadius: the model's; sunAmount: 0-1 sky visibility toward the sun.
    // Attachments carry their own (their model's dims, at the parent object's position).
    // pos: where the instance spawns (the object's position after MoveToFloor; attachments: their parent's).
    // anim: the clip a character loops (a name in its model's anims), "" for none.
    // template 1: a CAIHuman template a Spawner copies (and its attachments), built only at a spawn site.
    // name (attachables): the attachment name an ATTACH message gives (tools/export_level.py attachables).
    // childModels (characters): its ChildModel_N files. anims (characters): every animation it can play by
    // name, in lookup order, one per name (tools/animation.py playable): the model's clip (from "") or a
    // ChildModel_N file's.
    [Serializable] public class ModelInstanceJson { public int obj; public string file; public string[] skins, styles; public float[] scale; public PieceStyleJson[] pieces; public int skinned, parent; public string socket; public float[] pos; public string anim; public float[] dims; public float visRadius, sunAmount; public string[] clips; public LookJson[] looks; public string[] childModels; public AnimRefJson[] anims; public int template; public string name; public LookAtNodeJson[] lookAt; }
    // A node a character turns to look at something (tools/export_models.py Resolver.look_at_nodes): axis and up
    // empty for the defaults, angles in degrees.
    [Serializable] public class LookAtNodeJson { public string name, clone; public float[] axis, up, discomfort, max; public float maxVel; }
    [Serializable] public class AnimRefJson { public string name, @from; }
    // A state model's look (BinaryBit idle / yes / no, SecRezzer idle / off / on / spawn): its pieces then.
    [Serializable] public class LookJson { public string name; public PieceStyleJson[] pieces; }
    // A soundbute an animation key plays: one of its files at random, radii in LithTech units.
    [Serializable] public class ButeSoundJson
    {
        public string name;
        public string[] files;
        public float inner, outer;

        // One of its files at random (the sound manager's pick), null when it has none.
        public string AnyFile() => files != null && files.Length > 0 ? files[UnityEngine.Random.Range(0, files.Length)] : null;
    }

    // Model lighting inputs (tools/modellight.py). Colors are 0-255.
    [Serializable] public class LightGridJson { public float[] origin, cell; public int[] dims; }
    // A static object light: cosFov > -0.99 is a spot along dir; att "Quartic", "Linear" or "D3D" (attCoefs).
    [Serializable] public class StaticLightJson { public string name, cls, att; public float[] pos, dir, color, attCoefs; public float radius, cosFov, toAmbient; }
    [Serializable] public class SunJson { public float[] dir, color; public float toAmbient; }
    [Serializable] public class PieceStyleJson { public int style; public string[] tex; }

    // A render style compiled for the model shader (tools/renderstyle.py compile_style, export_models.Styles):
    // its lighting (LightingMaterial) and one draw per hardware pass, drawn in order.
    [Serializable] public class RenderStyleJson
    {
        public string name;
        public RenderStyleLightingJson lighting;
        public RenderDrawJson[] draws;
    }
    // One draw of a piece: its states, the passes it evaluates (1, or 2 folded; none = glow only) and
    // its glow-buffer passes (none = no glow; 2 = two alpha passes folded, premultiplied).
    [Serializable] public class RenderDrawJson
    {
        public int[] blend;          // Unity BlendMode src, dst
        public int zwrite, ztest, cull, wire;   // wire: RENDERSTYLE_WIRE, the triangles' edges
        public RenderPassJson[] passes, glow;
    }
    [Serializable] public class RenderStyleLightingJson { public float[] ambient, diffuse, emissive; }
    // stages: 2 stages x (colorOp, colorArg1, colorArg2, texture slot, alphaOp, alphaArg1, alphaArg2, uv set)
    [Serializable] public class RenderPassJson { public float[] stages, tfactor, alphaTest; public int lit, blendOver; }

    [Serializable] public class MaterialJson { public string tex, tex2, effect; public int shader; }
    [Serializable] public class SubMeshJson { public int mat, start, count; }

    [Serializable] public class MeshJson
    {
        public string name;
        public int vtxOffset, vtxCount, idxOffset;
        public SubMeshJson[] subs;
        public float[] min, max;
    }

    [Serializable] public class ColliderJson
    {
        public string name;
        public int vtxOffset, vtxCount, idxOffset, idxCount;
        public float[] min, max;
    }

    [Serializable] public class WorldModelJson { public string name; public int flags, mesh, collider; }

    // A SpinningWorldModel (tools/spinner.py): its world model, obj (its object index, its command-manager
    // id), startOn, final angular velocity per axis (rad/s, pitch yaw roll in its own frame), the spin-up
    // and spin-down times (s), its wave (tools/waveform.py: 0 Linear, 1 Sine, 2 SlowOff, 3 SlowOn) and the
    // props of its on / off state machine (SpinnerMotion).
    [Serializable] public class SpinnerJson
    {
        public string worldModel;
        public int obj, waveform;
        public bool startOn, triggerOff, locked, forceMove, forceMoveOn, forceMoveOff;
        public float[] velocity;
        public float powerOnTime, powerOffTime, moveDelay, onWaitTime, offWaitTime;

        public SpinnerMotion.Settings Settings() => new SpinnerMotion.Settings
        {
            Final = new LTVec(velocity[0], velocity[1], velocity[2]), PowerOnTime = powerOnTime, PowerOffTime = powerOffTime,
            MoveDelay = moveDelay, OnWaitTime = onWaitTime, OffWaitTime = offWaitTime, Waveform = waveform,
            StartOn = startOn, TriggerOff = triggerOff, Locked = locked, ForceMove = forceMove, ForceMoveOn = forceMoveOn,
            ForceMoveOff = forceMoveOff,
        };
    }

    // A SoundFX: obj (its object index), startOn, the game's file path (files: a soundbute's files, one
    // picked per play, else empty), radii (LT units), Volume 0-100, PitchShift, the engine's Priority,
    // ambient (unpanned) and loop as 0/1.
    [Serializable] public class SoundFXJson { public string name, file; public string[] files; public int obj; public bool startOn; public float[] pos; public float inner, outer, pitch; public int volume, priority, ambient, loop; }

    // A SoundButeFX: obj (its object index), startOn, the files its soundbute picks from (game paths), radii
    // (LT units), the delay range (s) between sound starts, ambient (unpanned) as 0/1.
    [Serializable] public class SoundButeFXJson { public string name; public int obj; public bool startOn; public string[] files; public float[] pos; public float inner, outer, minDelay, maxDelay; public int ambient; }

    // A KeyFramer (tools/keyframer.py): obj (its object index, its command-manager id), how it starts, its
    // base key name, the names of the objects it moves, its settings (totalPathTime > 0: velocity mode) and
    // wave (tools/waveform.py: 0 Linear, 1 Sine, 2 SlowOff, 3 SlowOn), its ActiveSound ("" for none) and
    // its keys.
    [Serializable] public class KeyframerJson
    {
        public string name, baseKeyName;
        public int obj;
        public bool startActive, startPaused;
        public string[] targets;
        public bool looping, alignToPath, ignoreOffsets;
        public float totalPathTime;
        public int wave;
        public string activeSound;
        public float soundRadius;
        public KeyJson[] keys;

        // The keyframer's motion, with no targets yet.
        public KeyframerMotion Motion() =>
            new KeyframerMotion(Array.ConvertAll(keys, k => k.MotionKey()), looping, totalPathTime, wave, alignToPath, ignoreOffsets)
            {
                BaseKeyName = baseKeyName ?? "", StartActive = startActive, StartPaused = startPaused,
            };
    }
    // A path key: position (LT units), pitch/yaw/roll (radians), running time (s), absolute Bezier
    // controls (empty when absent) and the command it runs when reached (text, "" for none).
    [Serializable] public class KeyJson
    {
        public float[] pos, pyr, bezPrev, bezNext;
        public float time;
        public string command;

        public KeyframerMotion.Key MotionKey()
        {
            var key = new KeyframerMotion.Key
            {
                Pos = LTV(pos), PYR = LTV(pyr), Time = time, Command = command ?? "",
                HasPrev = bezPrev != null && bezPrev.Length >= 3, HasNext = bezNext != null && bezNext.Length >= 3,
            };
            if (key.HasPrev) key.BezPrev = LTV(bezPrev);
            if (key.HasNext) key.BezNext = LTV(bezNext);
            return key;
        }

        static LTVec LTV(float[] v) => new LTVec(v[0], v[1], v[2]);
    }

    // An ActivateType: the use prompt shown while its object is on / off ("" for none).
    [Serializable] public class ActivateTypeJson { public string name, on, off; }

    // A name a `spawn` / `spawnfrom` gives the object a Spawner creates, and the class of its template.
    [Serializable] public class SpawnJson { public string name, cls; }
    // A Spawner creating its CAIHuman template (object indices) at object `at`'s place (the spawner's, or a
    // spawnfrom object's): the template's root model instance (-1: it draws nothing), where the character
    // stands there (LT units, after MoveToFloor), the place's rotation (Euler, radians) and the sky's light.
    [Serializable] public class SpawnSiteJson { public int spawner, at, template, model; public float[] pos, rot; public float sunAmount; }

    // A Dialogue object (by its name, the n-th Dialogue in object order) and its lines from slot 1 to the first
    // empty one: id, speaker name, the delay before it (s), its StartDialogueCommandN, its voice file ("" for
    // 00000 and cut lines) and how long that plays (s, 0 without one).
    [Serializable] public class DialogueJson { public string name, startCommand, finishedCommand, cleanUpCommand; public bool removeWhenComplete, useAIState; public DialogueLineJson[] lines; }
    [Serializable] public class DialogueLineJson { public int id; public string speaker, command, voice; public float delay, duration; }
    // A CAIHuman or Speaker: how far its voice carries (LT units), IsCinematicAI, and whether it's a template.
    [Serializable] public class SpeakerJson { public string name, cls; public float radius; public bool cinematic, template; }

    // An effect group: phase (s) and its keys at detail High, a linked key after the key it follows.
    [Serializable] public class FxGroupJson
    {
        public string name;
        public float phase;
        public FxKeyJson[] fx;

        public FxGroup Group() => new FxGroup { Name = name, Phase = phase, Keys = Array.ConvertAll(fx ?? new FxKeyJson[0], k => k.Key()) };
    }
    // An fx key (tools/clientfx.py export_key): ck t, r, g, b, a per key (a a transparency), sk t, scale per
    // key; props the type's own (combos as their index, paths normalized). LTBModel keys also carry their
    // model's look (tools/export_level.py fx_models): pieces as a placed model's, the clip it plays ("" = the
    // model has none), its lighting inputs.
    [Serializable] public class FxKeyJson
    {
        public string type, label, attach;
        public int id, link, updatePos;
        public float start, end, maxStartOffset, startOffsetInterval;
        public bool continual, disableAtDist, randomizeStartOffset, smoothShutDown;
        public float[] offset, rotateAdd, ck, sk;
        public PropJson[] props;
        public PieceStyleJson[] pieces;
        public string anim;
        public float[] dims;
        public float visRadius;

        public FxKey Key()
        {
            var k = new FxKey
            {
                Type = type ?? "", Label = label ?? "", Attach = attach ?? "", Id = id, Link = link, UpdatePos = updatePos,
                Start = start, End = end, Continual = continual, MaxStartOffset = maxStartOffset,
                StartOffsetInterval = startOffsetInterval, RandomizeStartOffset = randomizeStartOffset,
                DisableAtDist = disableAtDist, SmoothShutDown = smoothShutDown,
                Offset = new LTVec(offset[0], offset[1], offset[2]), RotateAdd = new LTVec(rotateAdd[0], rotateAdd[1], rotateAdd[2]),
                Ck = ck ?? new float[0], Sk = sk ?? new float[0],
            };
            foreach (var p in props ?? new PropJson[0])
            {
                if (p.t == "s") k.Strs[p.k] = p.s;
                else k.Nums[p.k] = p.v;
            }
            return k;
        }
    }

    [Serializable] public class PropJson { public string k, t, s; public float[] v; }

    [Serializable] public class ObjectJson
    {
        public string cls, name;
        public float[] pos, rot;
        public PropJson[] props;

        [NonSerialized] Dictionary<string, PropJson> _map;

        PropJson Find(string key)
        {
            if (_map == null)
            {
                _map = new Dictionary<string, PropJson>(StringComparer.OrdinalIgnoreCase);
                foreach (var p in props) _map[p.k] = p;
            }
            return _map.TryGetValue(key, out var r) ? r : null;
        }

        public bool Has(string key) => Find(key) != null;
        public string Str(string key, string def = "") { var p = Find(key); return p != null && p.t == "s" ? p.s : def; }
        public float Num(string key, float def = 0) { var p = Find(key); return p != null && p.t != "s" && p.v.Length > 0 ? p.v[0] : def; }
        public bool Bool(string key, bool def = false) { var p = Find(key); return p != null && p.t == "b" ? p.v[0] != 0 : def; }
        public Vector3 Vec(string key, Vector3 def = default)
        {
            var p = Find(key);
            return p != null && p.t == "v" && p.v.Length >= 3 ? new Vector3(p.v[0], p.v[1], p.v[2]) : def;
        }

        public Vector3 Position => new Vector3(pos[0], pos[1], pos[2]);
        public LTVec LTPosition => new LTVec(pos[0], pos[1], pos[2]);   // the same, for the plain C# cores
        // LithTech stores (pitch, yaw, roll) in radians; both engines are left-handed Y-up.
        public Quaternion Rotation => Quaternion.Euler(rot[0] * Mathf.Rad2Deg, rot[1] * Mathf.Rad2Deg, rot[2] * Mathf.Rad2Deg);
        public LTQuat LTRotation => LTQuat.FromEuler(rot[0], rot[1], rot[2]);   // the engine's LTRotation, for the cores
    }

    [Serializable] public class LevelIndexJson { public string[] levels; }

    // Mirrors tools/export_models.py (export/models/<file>.json).
    [Serializable] public class ModelJson { public int version; public string file; public ModelPieceJson[] pieces; public ModelNodeJson[] nodes; public ModelSocketJson[] sockets; public ModelAnimJson[] anims; }
    // An animation clip in the model .bin's float block (tools/export_models.py clip_block): `keys` key
    // times (seconds) at `times`; channels: per node posOffset, posCount, rotOffset, rotCount (offsets in
    // floats; a count is 1 for a constant channel, else keys). Parent-relative position xyz, quaternion xyzw.
    // scales: node, offset, count per node whose vertex-animated piece the clip scales uniformly (1 float a
    // key); cmds: its animation keys (t in seconds). interp: seconds of blend from the previous pose into
    // its first key when it starts (0: a cut). from: "" for the model's or its .ltb children's animation, else
    // the ChildModel_N file it comes from (the same name can come from several).
    [Serializable] public class ModelAnimJson { public string name, @from; public float length, interp; public int keys, times; public int[] channels, scales; public AnimCmdJson[] cmds; }
    [Serializable] public class AnimCmdJson { public float t; public string s; }
    [Serializable] public class ModelPieceJson
    {
        public string name;
        public int[] textures;
        public int style, kind, bone, vtxOffset, vtxCount, idxOffset, idxCount;
        public float[] min, max;
    }
    // transform: model-space bind matrix, row-major m[row][col] (column vectors, translation in column 3).
    // pose: parent-relative position xyz + quaternion xyzw at frame 0 of animation 0.
    [Serializable] public class ModelNodeJson { public string name; public int parent; public float[] transform, pose; }
    // Relative to node `node`: rotation quaternion xyzw, position, scale (ModelInstance::GetSocketTransform).
    [Serializable] public class ModelSocketJson { public string name; public int node; public float[] pos, rot, scale; }
}
