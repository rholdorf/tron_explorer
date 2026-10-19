using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Tron
{
    // Font 0 of the game's HUD (Tw Cen MT), from the atlas tools/hudtext.py renders into <export>/hud/, drawn
    // as GL quads in OnGUI's repaint, over the screen fade like the rest of the HUD.
    //
    // Positions and sizes are in the game's 640 x 480 layout units, mapped to a centred 4:3 area as tall as
    // the screen (narrower screens: as wide as the screen).
    //
    // Sizes, measured on the reference video (reference/video/1-2.mp4: a transmission at 741 s, a mission text
    // at 282.5 s): at a char height of 14 the em is 9.83 units (cap height 6.45, Tw Cen MT's caps being 0.656
    // em), the baseline 10.1 units below the line's top, and the letter spacing about 0.33 units. That is the
    // .ffa's PointSize 20 page (a 26.7 px em at 96 dpi) scaled to the em, with its SpacingHorizontal 1 and
    // SpacingVertical 3 page pixels: 0.37 units between letters, a line pitch of 15.1 (15.3 measured).
    public sealed class HudFont
    {
        [Serializable] class GlyphJson { public int c, x, y, w, h, ox, oy; public float adv; }
        [Serializable] class FontJson { public float size, ascent; public int width, height; public GlyphJson[] glyphs; }

        const float EmPerCharHeight = 9.83f / 14, BaselinePerCharHeight = 10.1f / 14;
        const float PageEm = 20 * 96 / 72f, SpacingHorizontal = 1, SpacingVertical = 3;
        // The drop shadow under the text: black, offset (+2, +2) pixels of the game's screen; here 1 unit.
        const float ShadowOffset = 1;

        readonly Dictionary<char, GlyphJson> glyphs = new Dictionary<char, GlyphJson>();
        readonly FontJson meta;
        readonly Texture2D atlas;
        readonly Material material;

        HudFont(FontJson meta, Texture2D atlas, Shader shader)
        {
            this.meta = meta;
            this.atlas = atlas;
            foreach (var g in meta.glyphs) glyphs[(char)g.c] = g;
            material = new Material(shader) { mainTexture = atlas, hideFlags = HideFlags.DontSave };
        }

        // The font in <export>/hud, drawn with shader (Tron/HudText), or null (logged) without it.
        public static HudFont Load(string exportRoot, Shader shader)
        {
            try
            {
                var dir = Path.Combine(exportRoot ?? "", "hud");
                var meta = JsonUtility.FromJson<FontJson>(File.ReadAllText(Path.Combine(dir, "font.json")));
                var atlas = new Texture2D(2, 2, TextureFormat.RGBA32, true) { hideFlags = HideFlags.DontSave };
                atlas.LoadImage(File.ReadAllBytes(Path.Combine(dir, "font.png")));
                atlas.filterMode = FilterMode.Trilinear;
                atlas.wrapMode = TextureWrapMode.Clamp;
                return new HudFont(meta, atlas, shader);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"HUD font not loaded ({e.Message}); run tools/export_level.py");
                return null;
            }
        }

        // ---- Layout ----

        // Pixels per layout unit and the 4:3 area's top-left corner on the screen.
        float unit, left, top;

        // Call once per repaint before drawing.
        public void Begin(float screenWidth, float screenHeight)
        {
            unit = Mathf.Min(screenHeight / 480, screenWidth / 640);
            left = (screenWidth - 640 * unit) / 2;
            top = (screenHeight - 480 * unit) / 2;
            material.SetPass(0);
            GL.PushMatrix();
            GL.LoadPixelMatrix(0, screenWidth, screenHeight, 0);
            GL.LoadIdentity();   // not OnGUI's GUI.matrix
            GL.Begin(GL.QUADS);
        }

        public void End()
        {
            GL.End();
            GL.PopMatrix();
        }

        // Atlas pixels to layout units at a char height, and the game's page pixels to layout units.
        float Scale(float charHeight) => charHeight * EmPerCharHeight / meta.size;
        static float PagePixel(float charHeight) => charHeight * EmPerCharHeight / PageEm;
        public float LineHeight(float charHeight) => charHeight + SpacingVertical * PagePixel(charHeight);
        // The height of a block of lines: the last line counts its char height only.
        public float BlockHeight(int lines, float charHeight) => lines == 0 ? 0 : (lines - 1) * LineHeight(charHeight) + charHeight;
        float Advance(char c, float scale) =>
            glyphs.TryGetValue(c, out var g) ? (g.adv + SpacingHorizontal * meta.size / PageEm) * scale : 0;

        // Splits characters into lines: at each new HudChar.Line, and (wrapWidth > 0) before a word that would
        // pass wrapWidth units.
        public List<List<HudChar>> Lines(IList<HudChar> chars, float charHeight, float wrapWidth = 0)
        {
            float scale = Scale(charHeight);
            var lines = new List<List<HudChar>>();
            List<HudChar> cur = null;
            int line = -1;
            float width = 0;
            for (int i = 0; i < chars.Count; i++)
            {
                var c = chars[i];
                if (cur == null || c.Line != line)
                {
                    // Blank lines keep their place.
                    for (int k = cur == null ? 0 : line + 1; k < c.Line; k++) lines.Add(new List<HudChar>());
                    cur = new List<HudChar>();
                    lines.Add(cur);
                    line = c.Line;
                    width = 0;
                }
                if (wrapWidth > 0 && c.C != ' ' && (i == 0 || chars[i - 1].C == ' ' || chars[i - 1].Line != c.Line))
                {
                    float word = 0;
                    for (int j = i; j < chars.Count && chars[j].C != ' ' && chars[j].Line == c.Line; j++) word += Advance(chars[j].C, scale);
                    if (width > 0 && width + word > wrapWidth)
                    {
                        while (cur.Count > 0 && cur[cur.Count - 1].C == ' ') cur.RemoveAt(cur.Count - 1);
                        cur = new List<HudChar>();
                        lines.Add(cur);
                        width = 0;
                    }
                }
                cur.Add(c);
                width += Advance(c.C, scale);
            }
            return lines;
        }

        public float Width(List<HudChar> line, float charHeight)
        {
            float scale = Scale(charHeight), w = 0;
            foreach (var c in line) w += Advance(c.C, scale);
            return w;
        }

        // Draws lines from (x, y) (layout units, top-left of the first line); centred: each line centred on x.
        // count: how many characters to draw, in order. Shadow first (black, shadowAlpha × alpha), then the
        // characters in their colours at alpha.
        public void Draw(List<List<HudChar>> lines, float x, float y, float charHeight, float alpha,
                         bool centred = false, int count = int.MaxValue, float shadowAlpha = 1)
        {
            if (alpha <= 0) return;
            if (shadowAlpha > 0) DrawPass(lines, x + ShadowOffset, y + ShadowOffset, charHeight, new Color(0, 0, 0, alpha * shadowAlpha), centred, count, true);
            DrawPass(lines, x, y, charHeight, new Color(1, 1, 1, alpha), centred, count, false);
        }

        // One line in a single colour (the use prompt).
        public void DrawText(string text, float x, float y, float charHeight, Color color, bool centred)
        {
            var chars = new List<HudChar>();
            foreach (var c in text) chars.Add(new HudChar { C = c, Rgb = (int)(color.r * 255) << 16 | (int)(color.g * 255) << 8 | (int)(color.b * 255) });
            DrawPass(Lines(chars, charHeight), x, y, charHeight, new Color(1, 1, 1, color.a), centred, int.MaxValue, false);
        }

        void DrawPass(List<List<HudChar>> lines, float x, float y, float charHeight, Color tint, bool centred, int count, bool shadow)
        {
            float scale = Scale(charHeight), lineHeight = LineHeight(charHeight), baseline = BaselinePerCharHeight * charHeight;
            float iw = 1f / meta.width, ih = 1f / meta.height;
            int drawn = 0;
            for (int l = 0; l < lines.Count && drawn < count; l++, y += lineHeight)
            {
                float pen = centred ? x - Width(lines[l], charHeight) / 2 : x;
                foreach (var c in lines[l])
                {
                    if (drawn++ >= count) break;
                    if (!glyphs.TryGetValue(c.C, out var g)) continue;
                    if (g.w > 0 && g.h > 0)
                    {
                        var col = shadow ? tint : new Color(((c.Rgb >> 16) & 255) / 255f, ((c.Rgb >> 8) & 255) / 255f, (c.Rgb & 255) / 255f, tint.a);
                        GL.Color(col);
                        float x0 = left + (pen + g.ox * scale) * unit, y0 = top + (y + baseline + (g.oy - meta.ascent) * scale) * unit;
                        float x1 = x0 + g.w * scale * unit, y1 = y0 + g.h * scale * unit;
                        float u0 = g.x * iw, u1 = (g.x + g.w) * iw, v0 = 1 - g.y * ih, v1 = 1 - (g.y + g.h) * ih;
                        GL.TexCoord2(u0, v0); GL.Vertex3(x0, y0, 0);
                        GL.TexCoord2(u1, v0); GL.Vertex3(x1, y0, 0);
                        GL.TexCoord2(u1, v1); GL.Vertex3(x1, y1, 0);
                        GL.TexCoord2(u0, v1); GL.Vertex3(x0, y1, 0);
                    }
                    pen += Advance(c.C, scale);
                }
            }
        }
    }
}
