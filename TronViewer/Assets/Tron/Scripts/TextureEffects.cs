using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace Tron
{
    // Texture effect groups (textureeffectgroups/*.tfg) and their compiled scripts (*.tfs), as run by
    // texturescriptmgr.cpp / texturescriptinterpreter.cpp / texturescriptinstance.cpp.
    //
    // .tfg: u32 version, u32 stageCount, then per stage: u32 type (0 disabled, 1 overridden, 2 evaluated),
    //       u32 channel; overridden: u32 stage it copies; evaluated: str16 script, u32 n, float defaults[n].
    // .tfs: u16 version, u32 skip + skip bytes, u32 input, u32 output, u32 dirty, u32 nConst,
    //       float const[nConst], u32 codeLen, then 4-byte ops (op, p1, p2, out) over a float register file.
    //
    // Each frame a script builds a 4x4 texture matrix that the shader applies to the stage's input
    // (uv, or camera/world-space position, normal or reflection vector); only the base texture and
    // env map channels exist in this renderer, which are the only ones the game data uses.
    public static class TextureEffects
    {
        public static string Root;

        // ETextureScriptChannel
        const int ChannelBase = 1, ChannelEnvMap = 3;

        // Register file layout (texturescriptdefs.h)
        const int VarStack = 0, VarMat = 16, VarUser = 32, VarTime = 38, VarElapsed = 39, VarConst = 40, NumVars = 75;
        const int NumUserVars = 6;

        class Script
        {
            public int input, output;   // TSINPUT_*, TSOUTPUT_*
            public float[] consts;
            public byte[] code;
        }

        class Stage
        {
            public int channel;
            public Script script;       // null for an overridden stage
            public int overrideOf = -1;
            public float[] user = new float[NumUserVars];
            public Matrix4x4 matrix = Matrix4x4.identity;
        }

        class Group
        {
            public string name;
            public Stage[] stages;
            public readonly List<Material> materials = new List<Material>();
        }

        static readonly Dictionary<string, Script> scripts = new Dictionary<string, Script>(StringComparer.OrdinalIgnoreCase);
        static readonly Dictionary<string, Group> groups = new Dictionary<string, Group>(StringComparer.OrdinalIgnoreCase);
        static readonly Dictionary<Material, Group> byMaterial = new Dictionary<Material, Group>();
        static readonly float[] vars = new float[NumVars];
        static float startTime, lastTime;

        static readonly int TexFxBase = Shader.PropertyToID("_TexFxBase");
        static readonly int TexFxEnv = Shader.PropertyToID("_TexFxEnv");
        static readonly int TexFxModes = Shader.PropertyToID("_TexFxModes");

        public static void Apply(Material m, string effect)
        {
            if (string.IsNullOrEmpty(effect)) return;
            var g = LoadGroup(effect);
            if (g == null) return;
            g.materials.Add(m);
            byMaterial[m] = g;
            SetModes(m, g);
        }

        // Materials cloned from an animated one (blend mode / sky variants) animate with it.
        public static void RegisterClone(Material source, Material clone)
        {
            if (!byMaterial.TryGetValue(source, out var g)) return;
            g.materials.Add(clone);
            byMaterial[clone] = g;
        }

        public static void Clear()
        {
            groups.Clear();
            byMaterial.Clear();
            startTime = lastTime = Time.time;
        }

        // CTextureScriptInstance::Evaluate: time accumulates from the first update.
        public static void Update()
        {
            float time = Time.time - startTime;
            float elapsed = time - lastTime;
            lastTime = time;
            foreach (var g in groups.Values)
            {
                if (g == null || g.materials.Count == 0) continue;
                foreach (var s in g.stages)
                    if (s != null && s.script != null) Evaluate(s, time, elapsed);
                Matrix4x4 baseM = Matrix4x4.identity, envM = Matrix4x4.identity;
                foreach (var s in g.stages)
                {
                    if (s == null) continue;
                    var m = s.overrideOf >= 0 && g.stages[s.overrideOf] != null ? g.stages[s.overrideOf].matrix : s.matrix;
                    if (s.channel == ChannelBase) baseM = m;
                    else if (s.channel == ChannelEnvMap) envM = m;
                }
                foreach (var mat in g.materials)
                {
                    if (!mat) continue;
                    mat.SetMatrix(TexFxBase, baseM);
                    mat.SetMatrix(TexFxEnv, envM);
                }
            }
        }

        // _TexFxModes = (base input + 1, base projection, env input + 1, env projection); input 0 = no script,
        // projection 0 = none, 3 = divide by z, 4 = divide by w (TSOUTPUT_3PROJ / TSOUTPUT_4PROJ).
        static void SetModes(Material m, Group g)
        {
            var modes = Vector4.zero;
            foreach (var s in g.stages)
            {
                if (s == null) continue;
                var src = s.overrideOf >= 0 && g.stages[s.overrideOf] != null ? g.stages[s.overrideOf] : s;
                if (src.script == null) continue;
                float proj = src.script.output == 2 ? 3 : src.script.output == 3 ? 4 : 0;
                if (s.channel == ChannelBase) { modes.x = src.script.input + 1; modes.y = proj; }
                else if (s.channel == ChannelEnvMap) { modes.z = src.script.input + 1; modes.w = proj; }
            }
            m.SetVector(TexFxModes, modes);
        }

        // texturescriptinterpreter.cpp: note the engine's "sin" returns cos and "cos" returns sin.
        static void Evaluate(Stage s, float time, float elapsed)
        {
            var sc = s.script;
            Array.Clear(vars, 0, VarUser);
            for (int i = 0; i < 16; i++) vars[VarMat + i] = i % 5 == 0 ? 1 : 0;
            Array.Copy(s.user, 0, vars, VarUser, NumUserVars);
            vars[VarTime] = time;
            vars[VarElapsed] = elapsed;
            Array.Copy(sc.consts, 0, vars, VarConst, Math.Min(sc.consts.Length, 32));
            var c = sc.code;
            for (int k = 0; k + 3 < c.Length; k += 4)
            {
                float a = vars[c[k + 1] % NumVars], b = vars[c[k + 2] % NumVars];
                float r;
                switch (c[k])
                {
                    case 0: r = a + b; break;
                    case 1: r = a - b; break;
                    case 2: r = a * b; break;
                    case 3: r = a / b; break;
                    case 4: r = a % b; break;                       // fmod
                    case 5:
                        switch (c[k + 1])
                        {
                            case 0: r = Mathf.Cos(b); break;        // TSFuncSin
                            case 1: r = Mathf.Sin(b); break;        // TSFuncCos
                            case 2: r = Mathf.Tan(b); break;
                            case 3: r = Mathf.Sin(b) >= 0 ? 1 : -1; break;
                            case 4: r = Mathf.Cos(b) >= 0 ? 1 : -1; break;
                            default: r = b * 0.017453292519f; break;
                        }
                        break;
                    case 6: r = -a; break;
                    case 7: r = a; break;
                    case 8: r = Mathf.Min(a, b); break;
                    default: r = Mathf.Max(a, b); break;
                }
                vars[c[k + 3] % NumVars] = r;
            }
            var mtx = new Matrix4x4();
            for (int i = 0; i < 16; i++) mtx[i / 4, i % 4] = vars[VarMat + i];
            s.matrix = mtx;
            Array.Copy(vars, VarUser, s.user, 0, NumUserVars);
        }

        static Group LoadGroup(string name)
        {
            if (groups.TryGetValue(name, out var cached)) return cached;
            Group g = null;
            var path = Path.Combine(Root, "textureeffectgroups", name.ToLowerInvariant());
            try
            {
                if (File.Exists(path))
                {
                    using var br = new BinaryReader(File.OpenRead(path));
                    br.ReadUInt32(); // version
                    int n = Math.Min((int)br.ReadUInt32(), 4);
                    g = new Group { name = name, stages = new Stage[n] };
                    for (int i = 0; i < n; i++)
                    {
                        int type = (int)br.ReadUInt32();
                        if (type == 0) continue;
                        var st = new Stage { channel = (int)br.ReadUInt32() };
                        if (type == 1) st.overrideOf = (int)br.ReadUInt32();
                        else
                        {
                            var scriptName = Encoding.ASCII.GetString(br.ReadBytes(br.ReadUInt16()));
                            int nd = (int)br.ReadUInt32();
                            for (int d = 0; d < nd; d++)
                            {
                                float f = br.ReadSingle();
                                if (d < NumUserVars) st.user[d] = f;
                            }
                            st.script = LoadScript(scriptName);
                            if (st.script == null) continue;
                        }
                        g.stages[i] = st;
                    }
                }
                else Debug.LogWarning($"Texture effect {name}: file not found");
            }
            catch (Exception e)
            {
                Debug.LogWarning($"Texture effect {name}: {e.Message}");
                g = null;
            }
            groups[name] = g;
            return g;
        }

        static Script LoadScript(string name)
        {
            var rel = DtxLoader.Normalize(name).TrimStart('/');
            if (scripts.TryGetValue(rel, out var cached)) return cached;
            Script s = null;
            var path = Path.Combine(Root, rel);
            if (File.Exists(path))
            {
                using var br = new BinaryReader(File.OpenRead(path));
                if (br.ReadUInt16() == 1)
                {
                    br.ReadBytes((int)br.ReadUInt32());
                    s = new Script { input = (int)br.ReadUInt32(), output = (int)br.ReadUInt32() };
                    br.ReadUInt32(); // dirty flags: every script in the game data updates every frame
                    s.consts = new float[br.ReadUInt32()];
                    for (int i = 0; i < s.consts.Length; i++) s.consts[i] = br.ReadSingle();
                    s.code = br.ReadBytes((int)br.ReadUInt32());
                }
            }
            if (s == null) Debug.LogWarning($"Texture script {name}: not found or unsupported");
            scripts[rel] = s;
            return s;
        }
    }

    // Per-frame driver: animated sprite (.spr) frames and texture effect scripts.
    public class SpriteAnimator : MonoBehaviour
    {
        struct Entry { public Material mat; public Texture2D[] frames; public float rate; }
        static readonly List<Entry> entries = new List<Entry>();

        public static void Register(Material m, Texture2D[] frames, float rate)
        {
            entries.Add(new Entry { mat = m, frames = frames, rate = rate > 0 ? rate : 10 });
        }

        public static void RegisterClone(Material source, Material clone)
        {
            for (int i = 0, n = entries.Count; i < n; i++)
                if (entries[i].mat == source) entries.Add(new Entry { mat = clone, frames = entries[i].frames, rate = entries[i].rate });
        }

        public static void Clear() => entries.Clear();

        void Update()
        {
            float t = Time.time;
            foreach (var e in entries)
                if (e.mat) e.mat.SetTexture("_MainTex", e.frames[(int)(t * e.rate) % e.frames.Length]);
            TextureEffects.Update();
        }
    }
}
