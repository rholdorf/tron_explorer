"""Dual-texture sections (shaders 8 and 9) with an empty second texture (ticket #18).

The engine draws them as plain texture sections: the dual-texture shader refuses a section without
its second texture and AllocShader falls back to Gouraud_Texture (8) or Lightmap_Texture (9),
which ignore the base texture's EnvMap/DetailTex (docs/research/dual-texture.md).
"""
import glob
import os

import pytest

import dat85
import export_level


def section(shader, tex2=""):
    s = dat85.RenderSection()
    s.textures = ["tex\\prototype\\m01\\geoff\\serverp\\walls\\m01p_w17.dtx", tex2]
    s.shader, s.effect = shader, ""
    return s


@pytest.mark.parametrize("shader", [8, 9])
def test_a_dual_texture_section_without_a_second_texture_exports_as_a_material(shader):
    w = export_level.Writer()
    m = w.materials[w.material(section(shader))]
    assert (m["shader"], m["tex2"]) == (shader, "")


@pytest.mark.parametrize("shader", [8, 9])
def test_a_real_second_texture_fails_the_export(shader):
    with pytest.raises(ValueError, match="second texture"):
        export_level.Writer().material(section(shader, "tex\\env\\env003.dtx"))


def test_no_retail_world_has_a_dual_texture_section_with_a_second_texture(extracted):
    """Pins the data the viewer relies on: all dual-texture sections are in intro and m01-01, all
    shader 8, none with a second texture."""
    found = {}
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "**", "*.dat"), recursive=True)):
        w = dat85.load(f)
        for rw in [w.render] + list(w.render.world_models):
            for b in rw.blocks:
                for s in b.sections:
                    if s.shader in export_level.DUAL_TEXTURE_SHADERS:
                        found.setdefault(os.path.basename(f), set()).add((s.shader, s.textures[1]))
    assert found == {"intro.dat": {(8, "")}, "m01-01.dat": {(8, "")}}
