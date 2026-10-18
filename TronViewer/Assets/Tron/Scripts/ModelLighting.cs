using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tron
{
    // Per-instance model lighting as the LithTech D3D renderer sets it up (ModelDraw::SetupModelLight,
    // setupmodel.cpp): an ambient term from the light grid plus up to MaxLights device lights from the sun,
    // the dynamic lights (DynaLight effects: D3D point lights) and the static object lights, the rest folded
    // into ambient. Port of tools/modellight.py (model_lighting), which is the tested reference for all but
    // the dynamic lights (FxDynaLight.Sample). All values in LT space, colors 0-255.
    public class ModelLighting
    {
        // A dynamic light this frame: where it is, its radius and color (0-255).
        public struct DynamicLight
        {
            public Vector3 Pos, Color;
            public float Radius;
        }

        // The level's dynamic lights now (DynamicLights fills it every frame).
        public readonly List<DynamicLight> Dynamic = new List<DynamicLight>();

        public const int MaxLights = 4;   // MaxModelLights console variable default
        const float DirectionalCosFov = 0.98f;   // retail StaticLightCB, [0x58d9e4]
        // A static light with cosFov above it is a spot, else omni (world_shared_bsp.cpp static lights;
        // modellight.SPOT_COS_FOV).
        const float SpotCosFov = -0.99f;


        readonly byte[] grid;   // dims x*y*z RGB, x fastest (level.bin after the lightmap atlas)
        readonly Vector3 origin, cell;
        readonly int dx, dy, dz;
        readonly StaticLightJson[] lights;
        readonly SunJson sun;
        readonly bool ltjsGridOrder;

        // ltjsGridOrder: CLightTable::GetLightVal as ltjs reads, Y lerps from the y+1 node to the y node
        // (modellight.sample_grid's ltjs_order). Off = textbook order, which fits the baked vertex colors
        // better (docs/research/light-grid.md §2.1).
        public ModelLighting(LevelJson data, byte[] grid, bool ltjsGridOrder)
        {
            this.ltjsGridOrder = ltjsGridOrder;
            var g = data.lightGrid;
            this.grid = grid;
            origin = V(g.origin);
            cell = V(g.cell);
            dx = g.dims[0]; dy = g.dims[1]; dz = g.dims[2];
            lights = data.lights ?? Array.Empty<StaticLightJson>();
            sun = data.sun;
        }

        static Vector3 V(float[] v) => new Vector3(v[0], v[1], v[2]);

        Vector3 Node(int x, int y, int z)
        {
            int i = ((z * dy + y) * dx + x) * 3;
            return new Vector3(grid[i], grid[i + 1], grid[i + 2]);
        }

        // CLightTable::GetLightVal: trilinear sample, clamped and truncated to 0-255 per channel.
        public Vector3 SampleGrid(Vector3 pos)
        {
            var f = new Vector3((pos.x - origin.x) / cell.x, (pos.y - origin.y) / cell.y, (pos.z - origin.z) / cell.z);
            int cx = Mathf.Clamp((int)f.x, -1, dx - 1), cy = Mathf.Clamp((int)f.y, -1, dy - 1), cz = Mathf.Clamp((int)f.z, -1, dz - 1);
            int ox = cx == -1 || cx == dx - 1 ? 0 : 1, oy = cy == -1 || cy == dy - 1 ? 0 : 1, oz = cz == -1 || cz == dz - 1 ? 0 : 1;
            int x = Math.Max(cx, 0), y = Math.Max(cy, 0), z = Math.Max(cz, 0);
            float tx = f.x - Mathf.Floor(f.x), ty = f.y - Mathf.Floor(f.y), tz = f.z - Mathf.Floor(f.z);
            Vector3 YLerp(int nx, int nz)
            {
                Vector3 lo = Node(nx, y, nz), hi = Node(nx, y + oy, nz);
                return ltjsGridOrder ? Vector3.LerpUnclamped(hi, lo, ty) : Vector3.LerpUnclamped(lo, hi, ty);
            }
            var near = Vector3.LerpUnclamped(YLerp(x, z), YLerp(x + ox, z), tx);
            var far = Vector3.LerpUnclamped(YLerp(x, z + oz), YLerp(x + ox, z + oz), tx);
            var v = Vector3.LerpUnclamped(near, far, tz);
            return new Vector3((int)Mathf.Clamp(v.x, 0, 255), (int)Mathf.Clamp(v.y, 0, 255), (int)Mathf.Clamp(v.z, 0, 255));
        }

        // CRenderLight::GetLightSample of a static light (point or spot).
        static Vector3 Sample(StaticLightJson lt, Vector3 pos)
        {
            var v = pos - V(lt.pos);
            float d2 = v.sqrMagnitude, r = lt.radius;
            if (d2 >= r * r) return Vector3.zero;
            float d = Mathf.Sqrt(d2), k;
            if (string.Equals(lt.att, "Quartic", StringComparison.OrdinalIgnoreCase)) { k = 1 - d2 / (r * r); k *= k; }
            else if (string.Equals(lt.att, "Linear", StringComparison.OrdinalIgnoreCase)) k = 1 - d / r;
            else k = 1 / (lt.attCoefs[0] + lt.attCoefs[1] * d + lt.attCoefs[2] * d2);
            if (lt.cosFov > SpotCosFov)
            {
                if (d == 0) return Vector3.zero;
                float dot = Vector3.Dot(v, V(lt.dir)) / d;
                if (dot <= lt.cosFov) return Vector3.zero;
                k *= (dot - lt.cosFov) / (1 - lt.cosFov);
            }
            return V(lt.color) * k;
        }

        // A light in the relevant light list: a directional light (light == null and not point: the sun or a
        // narrow static spot; color already scaled), a dynamic point light, or a sampled static light, whose
        // color the list scales by keep = 1 - ConvertToAmbient.
        struct Slot
        {
            public float score, keep;
            public StaticLightJson light;
            public bool point;
            public DynamicLight dyn;
            public Vector3 dir, color;
        }

        static Vector3 V(LTVec v) => new Vector3(v.x, v.y, v.z);
        static LTVec L(Vector3 v) => new LTVec(v.x, v.y, v.z);

        static Vector3 PointSample(DynamicLight d, Vector3 pos) => V(FxDynaLight.Sample(L(d.Pos), d.Radius, L(d.Color), L(pos)));

        // Whether a dynamic light can reach a model there (its radius and the model's VisRadius overlap): the
        // others light it as if there were none.
        public bool Touches(Vector3 pos, float visRadius)
        {
            foreach (var d in Dynamic)
                if ((d.Pos - pos).sqrMagnitude < (d.Radius + visRadius) * (d.Radius + visRadius)) return true;
            return false;
        }

        // Ambient (0-255, the D3D ambient light) and up to MaxLights device lights for an instance:
        // dirs[i].xyz = unit direction the light travels, colors[i].rgb = 0-255 (zero when unused); a point
        // light has dirs[i] = (its place in the world (Unity units), 1) and colors[i].w = its range there.
        public Vector3 Compute(Vector3 pos, Vector3 dims, float visRadius, float sunAmount, Vector4[] dirs, Vector4[] colors)
        {
            var ambient = Vector3.zero;
            var slots = new List<Slot>(MaxLights);

            // CRelevantLightList::InsertLight
            void Insert(Slot s, Vector3 sample, float toAmbient)
            {
                s.score = Mathf.Max(sample.x, Mathf.Max(sample.y, sample.z)) * (1 - toAmbient);
                int i = 0;
                while (i < slots.Count && !(s.score > slots[i].score)) i++;
                if (i >= MaxLights) { ambient += sample; return; }
                if (slots.Count >= MaxLights)
                {
                    var last = slots[slots.Count - 1];
                    ambient += last.point ? PointSample(last.dyn, pos)
                             : last.light == null ? last.color : Sample(last.light, pos) * last.keep;
                    slots.RemoveAt(slots.Count - 1);
                }
                s.keep = 1 - toAmbient;
                s.color *= s.keep;
                slots.Insert(i, s);
                ambient += toAmbient * sample;
            }

            if (sun != null && sun.color != null && (sun.color[0] != 0 || sun.color[1] != 0 || sun.color[2] != 0))
            {
                var c = V(sun.color) * sunAmount;
                Insert(new Slot { dir = V(sun.dir), color = c }, c, sun.toAmbient);
            }
            ambient += SampleGrid(pos);
            foreach (var d in Dynamic) Insert(new Slot { point = true, dyn = d, color = d.Color }, PointSample(d, pos), 0);
            foreach (var lt in lights)
            {
                // FindObjectsInBox2: the light's box (pos +- radius) touches the model's (pos +- VisRadius).
                var lp = V(lt.pos);
                float reach = lt.radius + visRadius;
                if (Mathf.Abs(lp.x - pos.x) > reach || Mathf.Abs(lp.y - pos.y) > reach || Mathf.Abs(lp.z - pos.z) > reach) continue;
                if (lt.color[0] < 1 && lt.color[1] < 1 && lt.color[2] < 1) continue;   // StaticLightCB early out
                // Retail Lithtech.exe StaticLightCB (0x54f2cb), not in ltjs: a spot narrower than
                // DirectionalCosFov is set up as a directional light along its direction, at full color.
                if (lt.cosFov > DirectionalCosFov) Insert(new Slot { dir = V(lt.dir), color = V(lt.color) }, V(lt.color), lt.toAmbient);
                else Insert(new Slot { light = lt, color = V(lt.color) }, Sample(lt, pos), lt.toAmbient);
            }

            int n = 0;
            foreach (var s in slots)
            {
                Vector3 dir, color;
                if (s.point)
                {
                    // CreatePointLightD3D: a device point light, attenuation 1, 0, 19 / radius^2 (the shader).
                    if (s.color.x <= 0 && s.color.y <= 0 && s.color.z <= 0) continue;
                    var p = s.dyn.Pos * LT.Scale;
                    dirs[n] = new Vector4(p.x, p.y, p.z, 1);
                    colors[n] = new Vector4(s.color.x, s.color.y, s.color.z, s.dyn.Radius * LT.Scale);
                    n++;
                    continue;
                }
                if (s.light == null) { dir = s.dir; color = s.color; }
                else DeviceLight(s.light, s.keep, pos, dims, out dir, out color);
                if (color.x <= 0 && color.y <= 0 && color.z <= 0) continue;
                dirs[n] = dir.normalized;
                colors[n] = color;
                n++;
            }
            for (; n < dirs.Length; n++) { dirs[n] = Vector4.zero; colors[n] = Vector4.zero; }
            // CDeviceLightList::SetAmbientColor: clamp to 255 and truncate.
            return new Vector3((int)Mathf.Min(255, ambient.x), (int)Mathf.Min(255, ambient.y), (int)Mathf.Min(255, ambient.z));
        }

        // The device lights' colors from 0-255 to 0-1 (a point light's range stays).
        public static void ToUnit(Vector4[] colors)
        {
            for (int i = 0; i < colors.Length; i++)
                colors[i] = new Vector4(colors[i].x / 255f, colors[i].y / 255f, colors[i].z / 255f, colors[i].w);
        }

        // CRenderLight::CreateDeviceLight: quartic/linear points become a directional light sampled at the
        // model (CreateSampledDirLight), spots the brightest of the center and the 8 dims-box corners
        // (CreateMultiSampledDirLight). D3D-attenuation points stay point lights in the engine; no retail
        // static light uses them, so they're sampled the same way.
        static void DeviceLight(StaticLightJson lt, float keep, Vector3 pos, Vector3 dims, out Vector3 dir, out Vector3 color)
        {
            color = Sample(lt, pos);
            if (lt.cosFov > SpotCosFov)
            {
                float best = color.sqrMagnitude;
                for (int sx = -1; sx <= 1; sx += 2)
                for (int sy = -1; sy <= 1; sy += 2)
                for (int sz = -1; sz <= 1; sz += 2)
                {
                    var c = Sample(lt, pos + Vector3.Scale(dims, new Vector3(sx, sy, sz)));
                    if (c.sqrMagnitude > best) { best = c.sqrMagnitude; color = c; }
                }
            }
            color *= keep;
            dir = pos - V(lt.pos);
        }
    }
}
