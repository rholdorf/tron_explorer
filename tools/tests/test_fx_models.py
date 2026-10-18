"""Effect models' looks (ticket #62): each LTBModel key carries its pieces' styles, its clip and its lighting
inputs (export_level.fx_models), and the render styles effect models use compile: wireframe passes,
a third texture, DOTPRODUCT3 and an opaque glow pass followed by another (pv_meshglow)."""
import pytest

import clientfx
import export_level
import export_models
import renderstyle

ONE, ZERO, SRC_ALPHA = 1, 0, 5


@pytest.fixture(scope="module")
def styles(extracted):
    return export_models.Styles(extracted)


def test_wireframe_styles_draw_lines(styles):
    (d,) = styles.compile("rs/additive_wireframe.ltb")["draws"]
    assert d["wire"] == 1 and list(d["blend"]) == [SRC_ALPHA, ONE] and len(d["glow"]) == 1   # its own glow
    # supercycle_base_wire_m204: a wire pass, then a filled one: two draws, not folded
    d0, d1, *_ = styles.compile("props/rs/supercycle_base_wire_m204.ltb")["draws"]
    assert (d0["wire"], d1["wire"]) == (1, 0)


def test_a_stage_can_read_the_third_texture(styles):
    d0 = styles.compile("weapons/rod/rs/pv_prod.ltb")["draws"][0]
    assert d0["passes"][0]["stages"][8:12] == [renderstyle.OP_BLEND_TF_A, 2, 0, 3]   # stage 1: texture 3


def test_an_opaque_glow_pass_and_another_are_two_glow_draws(styles):
    draws = styles.compile("weapons/mesh/rs/pv_blaster_base.ltb")["draws"]
    glows = [d for d in draws if d["glow"]]
    assert len(glows) == 2
    assert list(glows[1]["blend"]) == [SRC_ALPHA, ONE] and glows[1]["passes"] == []
    assert glows[1]["glow"][0]["stages"][0] == renderstyle.OP_DOT3


def test_model_keys_carry_their_look(extracted, styles):
    objects = [{"cls": "SpecialFX", "props": [{"k": "FxName", "t": "s", "s": "WORLDS_WallDisplay_Debris"}]},
               {"cls": "SpecialFX", "props": [{"k": "FxName", "t": "s", "s": "DISC_trail_Trailer"}]}]
    groups, _ = export_level.fx_groups(objects, clientfx.Library(extracted))
    table = []
    export_level.fx_models(groups, styles, extracted, table)
    keys = {g["name"]: [k for k in g["fx"] if k["type"] == "LTBModel"] for g in groups}
    plane = keys["WORLDS_WallDisplay_Debris"][0]
    (piece,) = plane["pieces"]
    assert table[piece["style"]]["name"] == "rs/alpha_additive_noculling_readz.ltb"
    assert piece["tex"] == ["fx/tex/white.dtx"]
    assert plane["anim"] == "Base"   # no AniName: animation 0
    assert plane["visRadius"] > 0 and len(plane["dims"]) == 3
    # AniName the model lacks (DiscThrow): GetAnimIndex fails, the model keeps animation 0
    (trailer,) = keys["DISC_trail_Trailer"]
    assert trailer["anim"] == styles.model(clientfx.prop(trailer, "Model")).anims[0].name
