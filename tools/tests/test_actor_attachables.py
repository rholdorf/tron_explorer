"""What `attach <position> <name>` hangs on a character (ltjs character.cpp ATTACH -> CAttachments::Attach ->
CreateAttachment): the exporter ships, per level, the model of every name its commands attach to a character
(placed, or a spawn name of a character template), so the viewer can build it when the message comes.
docs/research/cutscene-actors.md: m07-04's Kernel gets ICRegularDisc and DiscSmack in its hands; DiscSmack (a
melee weapon) has no hand-held model, so only the disc draws."""
import os
import types

import dat85
import export_level
import export_models


def level(*objects):
    return types.SimpleNamespace(objects=[{"class": c, "props": dict(p)} for c, p in objects], blind=[])


def test_attach_names_are_the_ones_sent_to_characters():
    w = level(("CAIHuman", {"Name": "Kernel"}),
              ("CAIHuman", {"Name": "cinTPLT", "Template": True}),
              ("Spawner", {"Name": "sp", "Target": "cinTPLT"}),
              ("Trigger", {"Name": "t1", "Command": "msg sp (spawn cin); msg Kernel (attach RightHand ICRegularDisc)"}),
              ("Trigger", {"Name": "t2", "Command": "msg cin (attach LeftHand DiscSmack); msg kernel (detach LeftHand)"}),
              ("Trigger", {"Name": "t3", "Command": "msg lift (attach ic01); msg KERNEL (attach RightHand icregulardisc)"}))
    assert export_level.attach_names(w) == ["DiscSmack", "ICRegularDisc"]


def test_m07_04_ships_the_kernels_disc(extracted):
    w = dat85.load(os.path.join(extracted, "worlds", "retailsingleplayer", "m07-04.dat"))
    resolver, styles, table = export_models.Resolver(extracted), export_models.Styles(extracted), []
    out = export_level.attachables(export_level.attach_names(w), resolver, styles, extracted, table)
    by_name = {a["name"]: a for a in out}
    assert export_level.attach_names(w) == ["DiscSmack", "ICRegularDisc"]
    assert sorted(by_name) == ["ICRegularDisc"]
    for name, a in by_name.items():
        assert a["file"].endswith(".ltb") and os.path.isfile(os.path.join(extracted, a["file"])), name
        assert a["skinned"] == 1 and a["pieces"] and all(0 <= p["style"] < len(table) for p in a["pieces"])
        assert len(a["dims"]) == 3 and a["visRadius"] > 0


def test_a_level_that_turns_a_talk_icon_on_ships_ai_talkicon(extracted):
    # Tron's client shows every talk icon (listen, say, ask) as the AI_TALKICON group on the character
    # (cshell.dll 0x10169720): menufx.fxf's AI_talkicon, the fx/models/talkicon.ltb model.
    import clientfx
    w = level(("CAIHuman", {"Name": "reg01"}),
              ("Trigger", {"Name": "t", "Command": "msg reg01 (sayicon 1 12026)"}))
    assert export_level.talk_icon_groups(w) == ["AI_TALKICON"]
    assert export_level.talk_icon_groups(level(("Trigger", {"Name": "t", "Command": "msg reg01 (sayicon 0)"}))) == []
    groups, missing = export_level.fx_groups([], clientfx.Library(extracted), ["AI_TALKICON"])
    assert [g["name"] for g in groups] == ["AI_talkicon"] and missing == []


def test_a_character_carries_its_skeletons_look_at_nodes(extracted):
    # modelbutes.txt: Male_Program_orange (m04-02's mp01, which `tracklookat`s the player) has Skeleton 0, whose
    # LookAtTrackingNodes is [TrackingNodes0]: the right eye (the left one cloning it) and the head.
    resolver = export_models.Resolver(extracted)
    obj = {"cls": "CAIHuman", "name": "mp01", "pos": [0, 0, 0], "rot": [0, 0, 0],
           "props": [{"k": "ModelTemplate", "t": "s", "s": "Male_Program_orange"}]}
    assert resolver.look_at_nodes(obj) == [
        {"name": "Face_REye", "clone": "Face_LEye", "axis": [0.0, 0.0, 1.0], "up": [0.0, 1.0, 0.0],
         "discomfort": [0.0, 0.0], "max": [30.0, 15.0], "maxVel": 180.0},
        {"name": "Head", "clone": "", "axis": None, "up": None, "discomfort": [25.0, 25.0], "max": [55.0, 45.0],
         "maxVel": 180.0}]


def test_animation_keys_attach_too(extracted):
    # CCharacter::HandleModelString `ATTACH <position> <name>` (three words; m10_pop.ltb's M10PopBloody puts a
    # Tablet in Popoff's left hand). The pool is what the character plays by name.
    styles = export_models.Styles(extracted)
    models = [{"file": "chars/models/civmale.ltb",
               "anims": [{"name": "M10PopBloody", "from": "chars/models/cinematic/mission10/m10_pop.ltb"},
                         {"name": "m11AlanPulls", "from": "chars/models/cinematic/mission11/m11_ralan.ltb"}]}]
    assert export_level.key_attach_names(models, styles, extracted) == ["Hard_Drive", "Tablet"]
    resolver = export_models.Resolver(extracted)
    assert export_level.attachables(["Tablet"], resolver, styles, extracted, [])[0]["name"] == "Tablet"


def test_a_name_that_draws_nothing_is_left_out(extracted):
    resolver, styles = export_models.Resolver(extracted), export_models.Styles(extracted)
    assert export_level.attachables(["NoSuchThing"], resolver, styles, extracted, []) == []
