"""Glow occlusion by blended model styles (ticket #17): in the glow pass the engine swaps each piece's
render style for its [GlowRSMap] style, states included (CRenderModelPieceList::RemapRenderStyles), so a
blended piece draws its glow style opaque with Z (black when unmapped) and occludes the glow behind it."""
import pytest

import export_models

ONE, ZERO, SRC_ALPHA, ONE_MINUS_SRC_ALPHA = 1, 0, 5, 10
CULL_BACK, LEQUAL = 2, 4


@pytest.fixture(scope="module")
def styles(extracted):
    return export_models.Styles(extracted)


def state(d):
    return list(d["blend"]), d["zwrite"], d["ztest"], d["cull"]


def test_unmapped_additive_style_draws_opaque_black_into_the_glow(styles):
    d0, g = styles.compile("rs/alpha_additive_fullbright.ltb")["draws"]
    assert state(d0) == ([SRC_ALPHA, ONE], 0, LEQUAL, CULL_BACK) and d0["glow"] == []
    assert g["passes"] == [] and state(g) == ([ONE, ZERO], 1, LEQUAL, CULL_BACK)
    (black,) = g["glow"]
    assert black["stages"][:2] == [1, 3] and black["tfactor"][:3] == [0, 0, 0]   # SELECTARG1(TFACTOR) black


def test_mapped_alpha_style_draws_its_glow_style_opaque(styles):
    """alpha_fullbright maps to GLow_Jet_RS (MUL_SRCALPHA_ZERO, premultiplied): opaque, with Z."""
    d0, g = styles.compile("rs/alpha_fullbright.ltb")["draws"]
    assert state(d0)[0] == [SRC_ALPHA, ONE_MINUS_SRC_ALPHA] and d0["glow"] == []
    assert g["passes"] == [] and state(g) == ([ONE, ZERO], 1, LEQUAL, CULL_BACK)
    assert len(g["glow"]) == 1 and g["glow"][0]["blendOver"] == 1


def test_self_mapped_additive_style_keeps_its_own_blend_in_the_glow(styles):
    (d,) = styles.compile("rs/alpha_additive_wglow.ltb")["draws"]
    assert state(d)[0] == [SRC_ALPHA, ONE] and len(d["glow"]) == 1


def draw(blend, zwrite, ztest=LEQUAL, cull=CULL_BACK):
    return {"blend": blend, "zwrite": zwrite, "ztest": ztest, "cull": cull, "passes": [{}], "glow": []}


@pytest.mark.parametrize("glow_state", [
    {"zwrite": 0},                  # an opaque glow style that doesn't write Z
    {"blend": (SRC_ALPHA, ONE)},    # a blended one
])
def test_one_pass_glow_rides_only_when_it_is_opaque_with_z(glow_state):
    """The glow pass draws with the glow style's state, so it rides on the opaque Z-writing draw only
    when it writes opaque with Z too; otherwise it is a draw of its own."""
    d = draw((ONE, ZERO), 1)
    g = dict(draw((ONE, ZERO), 1), passes=[{"glow": True}], **glow_state)
    draws = [d]
    export_models.place_glow(draws, g)
    assert d["glow"] == [] and len(draws) == 2
    assert state(draws[1]) == state(g) and draws[1]["passes"] == [] and draws[1]["glow"] == [{"glow": True}]


def test_opaque_z_writing_one_pass_glow_rides_on_the_opaque_draw():
    d = draw((ONE, ZERO), 1, cull=0)   # the cull stays the draw's, as before
    draws = [d]
    export_models.place_glow(draws, dict(draw((ONE, ZERO), 1), passes=[{"glow": True}]))
    assert draws == [d] and d["glow"] == [{"glow": True}]
