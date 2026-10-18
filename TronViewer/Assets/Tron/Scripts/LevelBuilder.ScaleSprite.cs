using UnityEngine;

namespace Tron
{
    // The level's ScaleSprite objects (ScaleSprite), drawn by SpriteDrawer. Each joins the command manager
    // with its GameBase handler (HIDDEN / VISIBLE / REMOVE on its FLAG_VISIBLE, made visible when StartOn) and
    // its own messages (ON / OFF, DAMAGE / DESTROY). It has a transform keyframers can move (the Ma3a flares
    // ride Ma3a's keyframers). Its colour takes the light grid's light at its place, sampled once. Templates
    // are never created.
    public partial class LevelBuilder
    {
        SpriteDrawer spriteDrawer;

        // The level's one sprite drawer (ScaleSprites and Sprite effects).
        SpriteDrawer Sprites()
        {
            if (spriteDrawer) return spriteDrawer;
            spriteDrawer = Root.AddComponent<SpriteDrawer>();
            spriteDrawer.Shader = EffectShader;
            return spriteDrawer;
        }

        void BuildScaleSprites()
        {
            SpriteDrawer drawer = null;
            GameObject parent = null;
            for (int i = 0; i < Data.objects.Length; i++)
            {
                var o = Data.objects[i];
                if (o.cls != "ScaleSprite" || o.Bool("Template")) continue;
                if (!drawer)
                {
                    drawer = Sprites();
                    parent = new GameObject("ScaleSprites");
                    parent.transform.SetParent(Root.transform, false);
                }
                var go = new GameObject(o.name);
                go.transform.SetParent(parent.transform, false);
                go.transform.localPosition = o.Position;
                var rot = LTQuat.FromEuler(o.rot[0], o.rot[1], o.rot[2]);
                go.transform.localRotation = new Quaternion(rot.x, rot.y, rot.z, rot.w);
                var c = o.Vec("Color", new Vector3(255, 255, 255));
                var p = new ScaleSprite.Props
                {
                    File = o.Str("Filename"), Damaged = o.Str("DamagedFilename"), Destroyed = o.Str("DestroyedFilename"),
                    ScaleX = o.Num("ScaleX", 1), ScaleY = o.Num("ScaleY", 1), Alpha = o.Num("Alpha", 1),
                    Color = new LTVec(c.x, c.y, c.z),
                    Additive = o.Bool("Additive"), Multiply = o.Bool("Multiply"), Rotatable = o.Bool("Rotatable"),
                    FlushWithWorld = o.Bool("FlushWithWorld"), Glow = o.Bool("Glow"), ZBias = o.Bool("ZBias"),
                    StartOn = o.Bool("StartOn", true),
                    CreateSprite = o.Bool("CreateSprite"), FlareFile = o.Str("SpriteFile"),
                    FlareAdditive = o.Bool("SpriteAdditive", true), Offset = o.Num("SpriteOffset"),
                    MinAngle = o.Num("MinAngle", 90), MinAlpha = o.Num("MinSpriteAlpha"), MaxAlpha = o.Num("MaxSpriteAlpha", 1),
                    MinScale = o.Num("MinSpriteScale", 1), MaxScale = o.Num("MaxSpriteScale", 1),
                };
                var light = lighting != null ? lighting.SampleGrid(o.Position) : Vector3.zero;
                var flags = JoinFlags(i, p.StartOn ? StartFlags.Visible : StartFlags.None, null, null);
                var s = new ScaleSprite(p, o.LTPosition, rot, new LTVec(light.x, light.y, light.z), flags);
                s.RemoveObject = () => flags.OnMessage(new Message(new[] { "REMOVE" }, -1));
                Commands.Handle(i, s.OnMessage);
                drawer.Add(s, go.transform);
                pointObjects[i] = go.transform;
            }
        }
    }
}
