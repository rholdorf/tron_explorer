"""Two-pass render styles (ticket #11): a second pass that needs the framebuffer is its own draw,
with its own blend/Z/cull/alpha test, drawn after the first; the glow goes on a draw that can carry it."""
import pytest

import export_models

# Unity BlendMode / CullMode / CompareFunction codes
ONE, ZERO, DST_COLOR, SRC_COLOR, ONE_MINUS_SRC_COLOR, SRC_ALPHA, ONE_MINUS_SRC_ALPHA = 1, 0, 2, 3, 6, 5, 10
CULL_OFF, CULL_FRONT, CULL_BACK = 0, 1, 2
LESS, LEQUAL, GREATER = 2, 4, 5


@pytest.fixture(scope="module")
def styles(extracted):
    return export_models.Styles(extracted)


def state(d):
    return list(d["blend"]), d["zwrite"], d["ztest"], d["cull"]


def test_mul_srccol_dstcol_cloak_draws_its_opaque_pass_second(styles):
    for rel in ("chars/rs/rector_cloak.ltb", "chars/rs/thorn_body.ltb"):
        c = styles.compile(rel)
        cull = CULL_OFF if "rector" in rel else CULL_BACK
        d0, d1 = c["draws"]
        assert state(d0) == ([SRC_COLOR, DST_COLOR], 1, LEQUAL, cull)
        assert state(d1) == ([ONE, ZERO], 1, LEQUAL, cull)
        assert len(d0["passes"]) == len(d1["passes"]) == 1
        assert d0["passes"][0]["alphaTest"][0] == 0
        assert d1["passes"][0]["alphaTest"] == [LEQUAL, 128 / 255]
        assert d1["passes"][0]["stages"][8:12] == [6, 2, 0, 2]          # TEX2 env MODULATETFACTOR(TEX, CUR)
        assert d1["passes"][0]["blendOver"] == 0
        # The glow style is opaque (premultiplied), so it rides on the opaque second draw.
        assert d0["glow"] == [] and len(d1["glow"]) == 1 and d1["glow"][0]["blendOver"] == 1


def test_thorn_corruption_second_draw_is_blended_no_zwrite_front_culled(styles):
    c = styles.compile("chars/rs/thorn_corruption.ltb")
    d0, d1, g = c["draws"]
    assert state(d0) == ([SRC_COLOR, ONE_MINUS_SRC_COLOR], 1, LEQUAL, CULL_BACK)
    assert state(d1) == ([SRC_ALPHA, ONE_MINUS_SRC_ALPHA], 0, LEQUAL, CULL_FRONT)
    assert d1["passes"][0]["stages"][:4] == [2, 2, 1, 0]               # SELECTARG2(DIF), no texture
    # Neither draw is opaque: the glow (Glow_Jet_RS, the first loadable mapping) gets a glow-only draw.
    assert d0["glow"] == [] and d1["glow"] == []
    assert g["passes"] == [] and state(g) == ([ONE, ZERO], 1, LEQUAL, CULL_BACK) and len(g["glow"]) == 1


def test_alpha_transparent_splits_opaque_and_blended_texels(styles):
    d0, d1 = styles.compile("rs/alpha_transparent.ltb")["draws"]
    assert state(d0) == ([ONE, ZERO], 1, LEQUAL, CULL_OFF)
    assert state(d1) == ([SRC_ALPHA, ONE_MINUS_SRC_ALPHA], 0, LEQUAL, CULL_OFF)
    assert d0["passes"][0]["alphaTest"] == [GREATER, 250 / 255]
    assert d1["passes"][0]["alphaTest"] == [LESS, 251 / 255]
    assert len(d0["glow"]) == 1 and d1["glow"] == []                 # GlowDefaultRS (black) on the opaque draw


def test_seeker_adds_its_second_pass_on_the_complement(styles):
    d0, d1 = styles.compile("chars/rs/seeker.ltb")["draws"]
    assert state(d0) == ([ONE, ZERO], 1, LEQUAL, CULL_OFF)
    assert state(d1) == ([SRC_COLOR, ONE], 1, LEQUAL, CULL_BACK)
    assert d0["passes"][0]["alphaTest"] == [LEQUAL, 128 / 255]
    assert d1["passes"][0]["alphaTest"] == [7, 128 / 255]             # GREATEREQUAL
    assert len(d0["glow"]) == 1 and d1["glow"] == []


def test_two_pass_glow_style_folds_into_one_premultiplied_glow_only_draw(styles):
    """Thorn's cloak glows with GLow_ThornCloak_RS: two alpha-blended passes (black at TF alpha 0x80,
    then the texture over it), folded into Blend One OneMinusSrcAlpha on a draw of its own."""
    d0, g = styles.compile("chars/rs/thorn_cloak.ltb")["draws"]
    assert state(d0) == ([ONE, ZERO], 1, LEQUAL, CULL_BACK) and d0["glow"] == []
    assert g["passes"] == [] and state(g) == ([ONE, ONE_MINUS_SRC_ALPHA], 1, LEQUAL, CULL_BACK)
    g0, g1 = g["glow"]
    assert g0["blendOver"] == 2 and g0["tfactor"][3] == 0x80 / 255 and g0["stages"][:3] == [1, 3, 1]
    assert g1["stages"][:4] == [3, 1, 2, 1]                          # MODULATE(DIF, TEX1)


def test_foldable_styles_stay_one_draw(styles):
    (d,) = styles.compile("chars/rs/jet_rs.ltb")["draws"]
    assert len(d["passes"]) == 2 and d["passes"][1]["blendOver"] == 1 and len(d["glow"]) == 1
    (d,) = styles.compile("chars/rs/kernel_shell.ltb")["draws"]   # glow over the model's own state, as before
    assert len(d["passes"]) == 1 and len(d["glow"]) == 1
    (d,) = styles.compile("")["draws"]
    assert state(d) == ([ONE, ZERO], 1, LEQUAL, CULL_BACK)


def test_every_level_style_compiles(styles, extracted):
    """No style is drawn with fewer passes than the game: there is no pass-0-only list any more."""
    assert not hasattr(export_models, "PASS0_ONLY") and not hasattr(export_models, "GLOW_DEFAULT_INSTEAD")
