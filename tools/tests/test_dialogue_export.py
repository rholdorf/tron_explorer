"""What the exporter gives the viewer for dialogues (ticket #73): each Dialogue object's lines and commands
in level.json, the speakers' sound radii, the voice files in <export>/sounds/voice/ and the subtitle layout
in <export>/hud/subtitles.json. Rules: docs/research/dialogue.md (branch research/dialogue; ltjs
dialogue.cpp, Tron's object.lto and cshell.dll).
"""
import json
import os
import wave

import pytest

import dialogue
import hudtext
import sounds


def prop(k, t, v):
    if t == "s":
        return {"k": k, "t": "s", "s": v, "v": []}
    return {"k": k, "t": t, "s": "", "v": [float(v)]}


def dialogue_obj(name, lines, **props):
    """A Dialogue as level.json writes it: every slot 1..20, the unused ones empty."""
    p = [prop("StartCommand", "s", props.get("StartCommand", "")),
         prop("FinishedCommand", "s", props.get("FinishedCommand", "")),
         prop("CleanUpCommand", "s", props.get("CleanUpCommand", "")),
         prop("UseAIState", "b", props.get("UseAIState", 1)),
         prop("RemoveWhenComplete", "b", props.get("RemoveWhenComplete", 1))]
    for n in range(1, 21):
        line, delay, cmd = lines[n - 1] if n <= len(lines) else ("", 0, "")
        p += [prop(f"Delay{n}", "n", delay), prop(f"Dialogue{n}", "s", line),
              prop(f"StartDialogueCommand{n}", "s", cmd)]
    return {"cls": "Dialogue", "name": name, "pos": [0, 0, 0], "rot": [0, 0, 0], "props": p}


# Durations: the fact chunk's sample count over the rate (91008 and 231552 samples at 44100 Hz), as macOS
# afinfo also estimates them (2.063673 s, 5.250612 s).
def test_a_dialogue_lists_its_lines_in_slot_order_with_their_delays_and_commands(extracted):
    o = dialogue_obj("12042_Dialogue", [("12042 Player", 0.5, ""), ("12043 12042_TP", 0, "msg cam ON")],
                     CleanUpCommand="msg 12042_TP (talklock 0)", RemoveWhenComplete=0)
    assert dialogue.dialogues([o], extracted) == [{
        "name": "12042_Dialogue", "startCommand": "", "finishedCommand": "",
        "cleanUpCommand": "msg 12042_TP (talklock 0)", "removeWhenComplete": False, "useAIState": True,
        "lines": [
            {"id": 12042, "speaker": "Player", "delay": 0.5, "command": "",
             "voice": "voice/12042.wav", "duration": pytest.approx(2.0637, abs=1e-4)},
            {"id": 12043, "speaker": "12042_TP", "delay": 0.0, "command": "msg cam ON",
             "voice": "voice/12043.wav", "duration": pytest.approx(5.2506, abs=1e-4)},
        ]}]


def test_00000_and_a_cut_line_have_no_voice_and_last_no_time(extracted):
    # ids under 1000 name no file; 12026 has a .lip but no .wav (a cut line)
    o = dialogue_obj("d", [("00000 player", 1.0, "msg cam ON"), ("12026 Byte", 0, "")])
    lines = dialogue.dialogues([o], extracted)[0]["lines"]
    assert [(l["id"], l["voice"], l["duration"]) for l in lines] == [(0, "", 0.0), (12026, "", 0.0)]
    assert (lines[0]["delay"], lines[0]["command"]) == (1.0, "msg cam ON")


def test_lines_end_at_the_first_empty_slot():
    o = dialogue_obj("d", [("00000 player", 0, ""), ("", 0, ""), ("00000 player", 0, "")])
    assert len(dialogue.dialogues([o], "/nonexistent")[0]["lines"]) == 1


def speaker_obj(cls, name, **props):
    return {"cls": cls, "name": name, "pos": [0, 0, 0], "rot": [0, 0, 0],
            "props": [prop(k, t, v) for k, (t, v) in props.items()]}


def test_speakers_hear_out_to_their_sound_radius(extracted):
    # An AI's SoundRadius override (a string prop) wins over its attribute template's (1500 in all 21 of
    # Tron's); a Speaker has its own; IsCinematicAI lets an AI be heard while a scene camera is on.
    objects = [speaker_obj("CAIHuman", "12042_TP", SoundRadius=("s", "2048"), IsCinematicAI=("b", 0), Template=("b", 0)),
               speaker_obj("CAIHuman", "alanactor", SoundRadius=("s", ""), IsCinematicAI=("b", 1), Template=("b", 1)),
               speaker_obj("Speaker", "Speaker0", SoundRadius=("n", 30000), Template=("b", 0)),
               speaker_obj("Prop", "box", SoundRadius=("n", 5))]
    assert dialogue.speakers(objects, extracted) == [
        {"name": "12042_TP", "cls": "CAIHuman", "radius": 2048.0, "cinematic": False, "template": False},
        {"name": "alanactor", "cls": "CAIHuman", "radius": 1500.0, "cinematic": True, "template": True},
        {"name": "Speaker0", "cls": "Speaker", "radius": 30000.0, "cinematic": False, "template": False}]


def test_the_voices_a_level_speaks_export_with_its_sounds_as_16_bit_pcm(extracted, tmp_path):
    o = dialogue_obj("d", [("12042 Player", 0, ""), ("00000 player", 0, ""), ("12026 Byte", 0, ""),
                           ("12042 Player", 0, "")])
    voices = dialogue.voices(dialogue.dialogues([o], extracted))
    assert voices == ["voice/12042.wav"]
    exported, missing = sounds.export_sounds(extracted, {"intro": []}, str(tmp_path), {"intro": voices})
    assert (exported, missing) == (["voice/12042.wav"], {})
    with wave.open(os.path.join(str(tmp_path), "sounds", "voice", "12042.wav")) as w:
        assert (w.getcomptype(), w.getsampwidth(), w.getnchannels(), w.getframerate(), w.getnframes()) == \
            ("NONE", 2, 1, 44100, 91008)


def test_a_short_voice_macos_cannot_open_as_a_wave_file_still_decodes_to_its_fact_length(extracted, tmp_path):
    # 10001.wav: 21 MP3 frames (4368 bytes), fact = 24192 samples; afconvert and afinfo refuse the RIFF file
    # (144 voices are like it) but read its MP3 stream
    out = sounds.export_file(extracted, "voice/10001.wav", str(tmp_path))
    with wave.open(out) as w:
        assert (w.getsampwidth(), w.getnchannels(), w.getframerate(), w.getnframes()) == (2, 1, 44100, 24192)


def test_a_float_wave_file_still_converts_whole(extracted, tmp_path):
    # chars/snd/derez/civ.wav: 32-bit float PCM (format 3), 41536 samples, no MP3 stream to cut out
    out = sounds.export_file(extracted, "chars/snd/derez/civ.wav", str(tmp_path))
    with wave.open(out) as w:
        assert (w.getsampwidth(), w.getnframes()) == (2, 41536)


def test_level_json_carries_its_dialogues_and_speakers(extracted, tmp_path):
    import export_level
    import export_models
    name = "retailsingleplayer/intro"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    assert meta["version"] == export_level.FORMAT_VERSION == 24
    d = {x["name"]: x for x in meta["dialogues"]}
    assert len(d) == 63
    assert [(l["id"], l["speaker"]) for l in d["12042_Dialogue"]["lines"]] == [
        (12042, "Player"), (12043, "12042_TP"), (12044, "12042_TP"), (12045, "12042_TP"), (12046, "12042_TP"),
        (12047, "12042_TP")]
    assert d["NoDO"]["lines"] == []
    s = {x["name"]: x for x in meta["speakers"]}
    assert s["12042_TP"]["radius"] == 2048.0


def test_the_subtitle_layout_comes_from_layout_txt(extracted, tmp_path):
    # [Subtitle]: font 0 (the HUD's Tw Cen MT, hud/font.json), 16 px white, 3 lines; FullScreenPos/Width in
    # play, Pos/Width while a scene camera is on; 640x480 layout units
    expected = {"font": 0, "fontSize": 16, "numLines": 3, "color": [255.0, 255.0, 255.0],
                "playPos": [200, 380], "playWidth": 256, "cinematicPos": [200, 408], "cinematicWidth": 256}
    assert hudtext.subtitle_layout(extracted) == expected
    hudtext.export_hud(extracted, str(tmp_path))
    with open(os.path.join(str(tmp_path), "hud", "subtitles.json")) as f:
        assert json.load(f) == expected
