"""Sound files in the export (ticket #23).

A sound name in a level (SoundFX Sound, SoundButeFX SoundBute, KeyFramer ActiveSound) is either a
soundbute from attributes/soundbutes.txt, which plays one of its PathN files, or a file path
(CGameSoundMgr FillPSIFromButeOrParams). The exporter copies every file the levels name into
<export>/sounds/<path>, as 16-bit PCM WAV: the PCM files as they are, the MP3-in-WAV ones decoded.
"""
import os
import wave

import sounds


def test_a_soundbute_name_plays_its_path_files(extracted):
    # m05-01's 1_light_snd_* SoundFX name the soundbute, not a file
    assert sounds.SoundButes(extracted).files("light_oneoffs") == [
        "snd/amb/1_light_01.wav", "snd/amb/1_light_02.wav", "snd/amb/1_light_03.wav", "snd/amb/1_light_04.wav"]


def test_any_other_name_is_a_file_path(extracted):
    assert sounds.SoundButes(extracted).files("Snd\\amb\\drone12.WAV") == ["snd/amb/drone12.wav"]


def obj(cls, **props):
    return {"cls": cls, "props": [{"k": k, "t": "s", "s": v, "v": []} for k, v in props.items()]}


def test_a_level_names_sounds_in_soundfx_soundbutefx_and_keyframers_whether_live_or_not():
    objects = [obj("SoundFX", Sound="Snd\\amb\\drone12.WAV"), obj("SoundButeFX", SoundBute="routerrands"),
               obj("KeyFramer", ActiveSound="snd\\lifts\\lift1.wav"), obj("KeyFramer", ActiveSound=""),
               obj("Prop", Sound="not a sound object")]
    assert sounds.sound_names(objects) == ["Snd\\amb\\drone12.WAV", "routerrands", "snd\\lifts\\lift1.wav"]


def test_a_pcm_file_is_copied_as_it_is(extracted, tmp_path):
    out = sounds.export_file(extracted, "snd/amb/drone12.wav", str(tmp_path))
    assert out == os.path.join(str(tmp_path), "sounds", "snd", "amb", "drone12.wav")
    with open(out, "rb") as a, open(os.path.join(extracted, "snd", "amb", "drone12.wav"), "rb") as b:
        assert a.read() == b.read()


def test_an_mp3_in_wav_file_is_decoded_to_16_bit_pcm_of_its_fact_length(extracted, tmp_path):
    # pistonexplde.wav: codec 0x55, mono 44100 Hz, fact chunk = 819072 samples
    out = sounds.export_file(extracted, "snd/event/pistonexplde.wav", str(tmp_path))
    with wave.open(out) as w:
        assert (w.getcomptype(), w.getsampwidth(), w.getnchannels(), w.getframerate(), w.getnframes()) == \
            ("NONE", 2, 1, 44100, 819072)


def test_exporting_the_levels_sounds_writes_every_file_they_name_and_reports_the_missing_ones(extracted, tmp_path):
    levels = {"m05-01": [obj("SoundFX", Sound="light_oneoffs"), obj("SoundFX", Sound="Snd\\amb\\drone08.WAV")],
              "m06-02": [obj("SoundFX", Sound="Snd\\amb\\drone08.WAV")]}
    exported, missing = sounds.export_sounds(extracted, levels, str(tmp_path))
    assert exported == ["snd/amb/1_light_01.wav", "snd/amb/1_light_02.wav", "snd/amb/1_light_03.wav",
                        "snd/amb/1_light_04.wav"]
    assert all(os.path.isfile(os.path.join(str(tmp_path), "sounds", f)) for f in exported)
    assert missing == {"snd/amb/drone08.wav": ["m05-01", "m06-02"]}


def test_a_missing_file_exports_nothing(extracted, tmp_path):
    assert sounds.export_file(extracted, "snd/amb/drone08.wav", str(tmp_path)) is None
    assert not os.path.exists(os.path.join(str(tmp_path), "sounds", "snd", "amb", "drone08.wav"))


def test_doors_switches_and_moving_world_models_name_the_sounds_of_their_states():
    # ActiveWorldModel ReadProps (generic names) and Door ReadProps (door names), plus LockedSound
    objects = [obj("SlidingDoor", OpeningSound="snd\\doors\\Door1.WAV", OpenSound="", ClosingSound="snd\\doors\\Door2.WAV",
                   ClosedSound="snd\\lifts\\lift_02_sp.wav", LockedSound="snd\\switch\\lock_1.wav"),
               obj("SlidingSwitch", PowerOnSound="snd\\switch\\keypad_02.WAV", OnSound="snd\\event\\surgefuseblow.wav",
                   PowerOffSound="", OffSound=""),
               obj("RotatingWorldModel", PowerOffSound="snd\\a.wav"), obj("RotatingDoor", ClosedSound="snd\\b.wav")]
    assert sounds.sound_names(objects) == [
        "snd\\doors\\Door1.WAV", "snd\\doors\\Door2.WAV", "snd\\lifts\\lift_02_sp.wav", "snd\\switch\\lock_1.wav",
        "snd\\switch\\keypad_02.WAV", "snd\\event\\surgefuseblow.wav", "snd\\a.wav", "snd\\b.wav"]
