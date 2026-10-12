"""The .ltb files that used to fail to load (ticket #6)."""
import os

import pytest

import ltb


def load(extracted, rel):
    return ltb.load(os.path.join(extracted, rel))


# v23 models with oriented bounding boxes: (file, pieces, first piece, nodes, first animation)
OBB_MODELS = [
    ("chars/models/seeker.ltb", 14, "RightSheild", 29, "base"),
    ("chars/models/cinematic/mission02/m0204_jet.ltb", 10, "Hair", 35, "M02JetSCDerez"),
    ("weapons/mesh/models_pv/pv_energyclaw.ltb", 23, "d_Arm", 79, "Select"),
]


@pytest.mark.parametrize("rel,n_pieces,first,n_nodes,anim", OBB_MODELS)
def test_models_with_obbs_load(extracted, rel, n_pieces, first, n_nodes, anim):
    m = load(extracted, rel)
    assert len(m.pieces) == n_pieces
    assert m.pieces[0].name == first
    assert len(m.nodes) == n_nodes
    # the reader lands on the animation section: count, dims, then the first animation's name
    r = ltb.Reader(m.data, m.anims_offset)
    assert r.u32() > 0
    r.p += 12
    assert r.str() == anim


# Files the engine itself refuses (no level or FX references them; each has a v23 sibling that is used).
ENGINE_REJECTS = [
    ("fx/models/pda_towertrails.ltb", "version 18"),
    ("fx/models/lightcyclerezin_cube.ltb", "version 21"),
    ("weapons/rod/fx/pv_model/pv_snipertube.ltb", "version 22"),
    ("weapons/rod/fx/pv_model/snipertube2.ltb", "version 22"),
    ("fx/models/rectorscript_shards.ltb", "0 bones per triangle"),
]


@pytest.mark.parametrize("rel,why", ENGINE_REJECTS)
def test_models_the_engine_rejects_raise_unsupported(extracted, rel, why):
    with pytest.raises(ltb.Unsupported, match=why):
        load(extracted, rel)
