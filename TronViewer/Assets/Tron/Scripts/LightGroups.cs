using System;
using System.Collections.Generic;

// Light groups: switchable lights baked apart from the rest of the level's lighting (tools/export_level.py
// Writer.light_groups). Plain C#, no Unity, so tools/tests/test_light_groups_runtime.py compiles it with .NET;
// LevelBuilder.LightGroups.cs adds each group to the world's vertex colours and lightmaps, and ModelLighting
// to the light grid and the static lights.
namespace Tron
{
    // The level's light groups and their live colours (CWorldClientBSP / CLTClient::SetLightGroupColor): each
    // starts at its colour in the DAT; a LightGroup object sets it at its first update and after each message.
    // Groups are found by name in any case (st_GetHashCode_ic). A colour that doesn't change (within 0.0001
    // per channel) changes nothing.
    public sealed class LightGroups
    {
        public sealed class Group
        {
            public readonly string Name;
            public readonly LTVec DatColor;
            public LTVec Color;

            internal Group(string name, LTVec datColor)
            {
                Name = name;
                DatColor = Color = datColor;
            }
        }

        readonly List<Group> groups = new List<Group>();
        readonly Dictionary<string, int> byName = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        // A group's colour changed (its index).
        public event Action<int> Changed;

        public int Count => groups.Count;
        public Group this[int i] => groups[i];

        public int Add(string name, LTVec datColor)
        {
            if (byName.TryGetValue(name, out int i)) return i;
            groups.Add(new Group(name, datColor));
            return byName[name] = groups.Count - 1;
        }

        // The group's index, -1 for a name the level has no group of.
        public int Find(string name) => !string.IsNullOrEmpty(name) && byName.TryGetValue(name, out int i) ? i : -1;

        public LTVec ColorOf(string name)
        {
            int i = Find(name);
            return i < 0 ? new LTVec(1, 1, 1) : groups[i].Color;
        }

        public void SetColor(int i, LTVec color)
        {
            if (i < 0 || i >= groups.Count) return;
            var g = groups[i];
            if (Math.Abs(g.Color.x - color.x) <= 0.0001f && Math.Abs(g.Color.y - color.y) <= 0.0001f &&
                Math.Abs(g.Color.z - color.z) <= 0.0001f) return;
            g.Color = color;
            Changed?.Invoke(i);
        }

        // A LightGroup object named `name` (StartOn, StartColor 0-255): it sets its group's colour now, as its
        // initial update does, and answers its messages.
        public LightGroupObject AddObject(string name, bool startOn, LTVec startColor)
        {
            var o = new LightGroupObject(this, Find(name), startOn, startColor / 255f);
            o.Send();
            return o;
        }

        // CD3D_RenderBlock adding a group to a vertex colour or a lightmap texel: per channel the colour times
        // the intensity, truncated, added and clamped at 255. Groups add in order, each clamped.
        public static byte Add(byte value, float color, byte intensity)
        {
            float add = color * intensity;
            int a = add >= 255 ? 255 : add <= 0 ? 0 : (int)add;
            int s = value + a;
            return (byte)(s > 255 ? 255 : s);
        }
    }

    // The LightGroup object (ltjs lightgroup.cpp): on or off and a colour (StartOn, StartColor / 255); it sends
    // its group the colour when on, black when off, at its first update and after every message (only these
    // change it; the others fall through to GameBase):
    //   ON, OFF, TOGGLE;
    //   COLOR <v>: grey v / 255; COLOR <r> <g> <b>: each / 255, a negative one keeps its channel; any other
    //     count of arguments leaves the colour.
    public sealed class LightGroupObject
    {
        readonly LightGroups groups;
        readonly int group;
        public bool On { get; private set; }
        public LTVec Color { get; private set; }

        internal LightGroupObject(LightGroups groups, int group, bool on, LTVec color)
        {
            this.groups = groups;
            this.group = group;
            On = on;
            Color = color;
        }

        internal void Send() => groups.SetColor(group, On ? Color : new LTVec(0, 0, 0));

        public bool OnMessage(Message m)
        {
            if (m.Is("TOGGLE")) On = !On;
            else if (m.Is("ON")) On = true;
            else if (m.Is("OFF")) On = false;
            else if (m.Is("COLOR") && m.ArgCount == 1)
            {
                float v = CommandMgr.Atof(m.Arg(0)) / 255f;
                Color = new LTVec(v, v, v);
            }
            else if (m.Is("COLOR") && m.ArgCount == 3)
            {
                float r = CommandMgr.Atof(m.Arg(0)) / 255f, g = CommandMgr.Atof(m.Arg(1)) / 255f, b = CommandMgr.Atof(m.Arg(2)) / 255f;
                Color = new LTVec(r < 0 ? Color.x : r, g < 0 ? Color.y : g, b < 0 ? Color.z : b);
            }
            else if (!m.Is("COLOR")) return false;
            Send();
            return true;
        }
    }
}
