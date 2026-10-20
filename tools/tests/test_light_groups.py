"""Light groups kept apart (#88): their per-vertex intensities and lightmap patches, added back at their
DAT colour the way CD3D_RenderBlock adds them (truncated colour x intensity, clamped at 255 after each
group), give what apply_vertex_light_groups / section_lightmap bake in."""
import numpy as np

import export_level


def lit_blocks(w):
    def walk(rw):
        for b in rw.blocks:
            if b.light_groups:
                yield b
        for sub in rw.world_models:
            yield from walk(sub)
    return list(walk(w.render))


def add_groups(base, groups, intensities):
    acc = base.astype(np.int64)
    for lg, vals in zip(groups, intensities):
        add = (np.array(lg.color, np.float32) * vals.astype(np.float32)[..., None]).astype(np.uint32)
        acc = np.minimum(acc + add, 255)
    return acc


def test_vertex_intensities_add_back_to_the_baked_vertex_colours(world):
    w = world("retailsingleplayer/intro")
    blocks = lit_blocks(w)
    assert blocks
    for b in blocks:
        c = b.verts["color"]
        base = np.stack([(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF], 1)
        vals = [export_level.vertex_light_group_intensities(lg, len(c)) for lg in b.light_groups]
        baked = export_level.apply_vertex_light_groups(c, b.light_groups)
        expect = np.stack([(baked >> 16) & 0xFF, (baked >> 8) & 0xFF, baked & 0xFF], 1)
        assert (add_groups(base, b.light_groups, vals) == expect).all()


def test_lightmap_patches_add_back_to_the_baked_lightmaps(world):
    w = world("retailsingleplayer/intro")   # with m07-01cin, the only levels with lightmapped groups
    checked = 0
    for b in lit_blocks(w):
        for si, s in enumerate(b.sections):
            if s.shader != export_level.LIGHTMAP_SHADER or not s.lm_data:
                continue
            subs = [lg.section_lms[si] if si < len(lg.section_lms) else [] for lg in b.light_groups]
            if not any(subs):
                continue
            base = export_level.section_lightmap(s, [], [])
            acc = base.astype(np.int64)
            for lg, patches in zip(b.light_groups, subs):
                col = np.array(lg.color, np.float32)
                for left, top, pw, ph, data in patches:
                    vals = export_level.lightmap_patch_intensities(left, top, pw, ph, data)
                    add = (col * vals.astype(np.float32)[..., None]).astype(np.uint32)
                    region = acc[top:top + ph, left:left + pw]
                    acc[top:top + ph, left:left + pw] = np.minimum(region + add, 255)
            assert (acc == export_level.section_lightmap(s, subs, b.light_groups)).all()
            checked += 1
    assert checked > 0
