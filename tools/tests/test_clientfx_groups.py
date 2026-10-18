"""Effect groups (ticket #58, docs/research/clientfx-groups.md): both .fxf formats, the game's lookup,
and what the levels' SpecialFX reach."""
import glob
import os

import pytest

import clientfx
import dat85
import export_level


@pytest.fixture(scope="module")
def library(extracted):
    return clientfx.Library(extracted)


@pytest.fixture(scope="module")
def specialfx(extracted):
    """(level, props) of every SpecialFX in the 38 single-player levels."""
    out = []
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        out += [(os.path.basename(f)[:-4], o["props"]) for o in dat85.load(f).objects if o["class"] == "SpecialFX"]
    return out


def test_every_fxf_file_reads_to_its_end(extracted):
    """read_binary raises if bytes are left over; the text file is the only one starting with Groups:."""
    counts = {os.path.basename(f): len(clientfx.read_fxf(f))
              for f in sorted(glob.glob(os.path.join(extracted, "clientfx", "*.fxf")))}
    assert counts == {"characterfx.fxf": 110, "clientfx.fxf": 0, "damagefx.fxf": 9, "derezfx.fxf": 233,
                      "empty.fxf": 0, "m0902.fxf": 4, "menufx.fxf": 77, "test.fxf": 47, "thornfx.fxf": 9,
                      "weaponfx.fxf": 176, "worldfx.fxf": 219}


def test_a_binary_key_reads_as_the_research_note_gives_it(extracted):
    g = clientfx.read_fxf(os.path.join(extracted, "clientfx", "m0902.fxf"))[0]
    k = g["keys"][0]
    assert (g["name"], g["phase"], len(g["keys"])) == ("m0902_TubeEnergyOut", 10000, 1)
    assert (k["type"], k["id"], k["start"], k["end"], k["repeat"], len(k["props"])) == \
        ("ParticleSystem", 1, 0.0, 10.0, 1, 47)
    assert k["props"][0][:2] == ("UpdatePos", clientfx.COMBO) and k["props"][0][2].startswith("0,Fixed,Follow")


def test_lookup_ignores_case_and_the_first_file_wins(library):
    assert library.find("pda_BRACKETS")["name"] == "PDA_brackets"
    assert library.source["zzz_empty"] == "damagefx.fxf"


def test_every_specialfx_name_finds_a_group(library, specialfx):
    groups, missing = library.reached(p.get("FxName", "") for _, p in specialfx)
    assert missing == ["<none>", "M02_04JetCycleDerez"]    # the second is a CreateFX target the game lacks too
    assert len(groups) == 126


def test_the_levels_reach_only_types_the_dll_has(library, specialfx):
    groups, _ = library.reached(p.get("FxName", "") for _, p in specialfx)
    types = {k["type"] for g in groups for k in g["keys"]}
    assert types <= clientfx.TYPES
    assert types - {"ParticleSystem", "Sprite", "LTBModel", "PlaySound", "LTBBouncyChunk", "LightningFX",
                    "PolyTrail", "CreateFX"} == {"CamJitter", "DynaLight", "SpriteSystem", "Null"}


def test_only_templates_have_a_target_object(specialfx):
    """The 6 SpecialFX aimed at an object are m05-01's spawned hitchfx: every placed effect stands on its
    own object."""
    targeted = sorted((lv, p["Name"]) for lv, p in specialfx if p.get("TargetObject"))
    assert targeted == [("m05-01", f"hitchfx0{i}") for i in range(1, 7)]
    assert all(p.get("Template") for lv, p in specialfx if p.get("TargetObject"))


def test_keys_off_at_detail_high_are_not_exported(library, specialfx):
    groups, _ = library.reached(p.get("FxName", "") for _, p in specialfx)
    assert sum(len(g["keys"]) for g in groups) - sum(len(clientfx.export_group(g)["fx"]) for g in groups) == 3


def test_an_exported_key_clamps_to_the_phase_and_parses_its_props(library):
    g = clientfx.export_group(library.find("m0501_Debris"))
    assert g["phase"] == 0.75
    assert all(0 <= k["start"] <= k["end"] <= g["phase"] for k in g["fx"])
    sound = next(k for k in g["fx"] if k["type"] == "PlaySound")
    assert sound["end"] == 0.75                               # 3.0 s in the file
    chunk = next(k for k in g["fx"] if k["type"] == "LTBBouncyChunk")
    assert clientfx.prop(chunk, "Model").startswith("fx/models/debris/m0501/")
    assert clientfx.prop(chunk, "Skin") == ""                       # dtx|... is unset
    assert chunk["ck"][0] == 0.0 and chunk["sk"][-2] == 1.0


def test_ck_alpha_stays_a_transparency(library):
    """PDA_brackets' model is opaque with A = 0 on both keys: drawn alpha = 1 - a."""
    model = next(k for k in clientfx.export_group(library.find("PDA_brackets"))["fx"] if k["type"] == "LTBModel")
    assert model["ck"][4::5] == [0.0, 0.0]


def test_a_linked_key_comes_after_the_key_it_follows(library, specialfx):
    groups, _ = library.reached(p.get("FxName", "") for _, p in specialfx)
    for g in map(clientfx.export_group, groups):
        seen = set()
        for k in g["fx"]:
            ids = {x["id"] for x in g["fx"]}
            assert k["link"] not in ids or k["link"] in seen, (g["name"], k["label"])
            seen.add(k["id"])


def test_a_level_exports_its_groups_and_the_groups_they_start(library):
    objects = [{"cls": "SpecialFX", "props": [{"k": "FxName", "t": "s", "s": "m02_01supercyclecrash"}]},
               {"cls": "SpecialFX", "props": [{"k": "FxName", "t": "s", "s": "<none>"}]}]
    groups, missing = export_level.fx_groups(objects, library)
    names = [g["name"] for g in groups]
    assert names[0] == "M02_01SuperCycleCrash"
    assert {"m02_01SupercycleChunks", "m02_01SupercycleLightning"} <= set(names)   # CreateFX, then its splat
    assert missing == []
    models, sounds = clientfx.assets(groups)
    assert models and all(not m.startswith("ltb|") for m in models)


def test_level_json_carries_its_effect_groups(extracted, tmp_path):
    import json
    import export_models
    name = "retailsingleplayer/m02-01"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] == export_level.FORMAT_VERSION == 22
    names = {g["name"].lower() for g in meta["fxGroups"]}
    fx_names = {p["s"].lower() for o in meta["objects"] if o["cls"] == "SpecialFX" for p in o["props"]
                if p["k"] == "FxName" and p["s"] != "<none>"}
    assert fx_names <= names
    assert meta["fxMissing"] == ["M02_04JetCycleDerez"]
