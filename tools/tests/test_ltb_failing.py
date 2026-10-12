"""The .ltb files that used to fail to load (ticket #6)."""
import os

import pytest

import export_models
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


def test_seeker_exports_every_piece(extracted, tmp_path):
    meta = export_models.export_model(extracted, "chars/models/seeker.ltb", str(tmp_path))
    assert len(meta["pieces"]) == 14
    assert (tmp_path / "models/chars/models/seeker.ltb.bin").stat().st_size > 0


@pytest.mark.parametrize("rel,why", ENGINE_REJECTS)
def test_models_the_engine_rejects_raise_unsupported(extracted, rel, why):
    with pytest.raises(ltb.Unsupported, match=why):
        load(extracted, rel)


def test_every_model_file_loads_or_is_one_the_engine_rejects(extracted):
    rejected = []
    for root, _dirs, files in os.walk(extracted):
        for f in files:
            path = os.path.join(root, f)
            if not f.lower().endswith(".ltb"):
                continue
            with open(path, "rb") as fh:
                head = fh.read(4)
            if head[0] != 1 or head[2] != 9:  # render styles (type 5) and non-D3D files
                continue
            try:
                ltb.load(path)
            except ltb.Unsupported:
                rejected.append(os.path.relpath(path, extracted))
    assert sorted(rejected) == sorted(rel for rel, _why in ENGINE_REJECTS)
