"""The dialogues a level plays (docs/research/dialogue.md, branch research/dialogue; ltjs dialogue.cpp, Tron's
object.lto and cshell.dll), as level.json's "dialogues": each Dialogue object's commands and its lines.

A line is slot N's "<id> <speaker>" with DelayN (the wait before it, seconds) and StartDialogueCommandN.
Lines run from slot 1 to the first empty slot. The voice is voice/<id>.wav (GetSoundFilenameFromId with
[Paths] Dialogue = "Voice\\"); ids under 1000 (00000) name no file. A line lasts as long as its voice, so each
line carries the file's duration, 0 when there's no file to play: the game ends such a line at once. The
subtitle is the game string with the line's id (hud/strings.json).
"""
import functools
import os

import butes
import sounds

SLOTS = 20
BASE_SOUND_ID = 1000   # SMGR_BASE_SOUND_ID: lower ids give no file name


def voice_file(sound_id):
    """The voice file a dialogue id plays, "" for ids under 1000."""
    return f"voice/{sound_id}.wav" if sound_id >= BASE_SOUND_ID else ""


def _props(o):
    return {p["k"]: (p["s"] if p["t"] == "s" else p["v"][0]) for p in o["props"]}


def _line(text, delay, command, extracted):
    sound, speaker = text.split()
    sound_id = int(sound)
    voice = voice_file(sound_id)
    duration = 0.0
    if voice and os.path.isfile(os.path.join(extracted, voice)):
        duration = sounds.wav_duration(os.path.join(extracted, voice))
    else:
        voice = ""
    return {"id": sound_id, "speaker": speaker, "delay": float(delay), "command": command,
            "voice": voice, "duration": duration}


CHARACTER_SOUND_RADIUS = 1000.0   # CCharacter's, kept when an AI template says 0 (ltjs ai.cpp)


@functools.lru_cache(maxsize=None)
def ai_template_sound_radius(extracted):
    """The SoundRadius of the AIs' attribute templates (aibutes.txt). All 21 of Tron's say 1500; an AI's
    template comes from its model, so the first one stands for them all."""
    sections = butes.load(os.path.join(extracted, "attributes", "aibutes.txt"))
    radius = float(sections.get("AttributeTemplate0", {}).get("soundradius", 0))
    return radius if radius > 0 else CHARACTER_SOUND_RADIUS


def speakers(objects, extracted):
    """The objects a dialogue line can name besides the player, in object order: the AIs (CAIHuman) and
    Speakers, spawn templates included (template). radius: how far the voice carries (its outer radius; the
    inner is 25% of it, subtitles show within 77%): a Speaker's SoundRadius, an AI's SoundRadius override
    when set (a string prop, read after the template) else its template's. cinematic: IsCinematicAI, the
    AIs still heard while a scene camera is on."""
    out = []
    for o in objects:
        if o["cls"] not in ("CAIHuman", "Speaker"):
            continue
        p = _props(o)
        radius = p.get("SoundRadius", "")
        if o["cls"] == "CAIHuman":
            radius = float(radius) if str(radius).strip() else ai_template_sound_radius(extracted)
        out.append({"name": o["name"], "cls": o["cls"], "radius": float(radius),
                    "cinematic": bool(p.get("IsCinematicAI", 0)), "template": bool(p.get("Template", 0))})
    return out


def voices(level_dialogues):
    """The voice files the dialogues play, each once, in the order first spoken (the cut lines, which have
    no file, aren't among them)."""
    return list(dict.fromkeys(l["voice"] for d in level_dialogues for l in d["lines"] if l["voice"]))


def dialogues(objects, extracted):
    """The level's Dialogue objects (level.json form), in object order."""
    out = []
    for o in objects:
        if o["cls"] != "Dialogue":
            continue
        p = _props(o)
        lines = []
        for n in range(1, SLOTS + 1):
            text = p.get(f"Dialogue{n}", "").strip()
            if not text:
                break
            lines.append(_line(text, p.get(f"Delay{n}", 0.0), p.get(f"StartDialogueCommand{n}", ""), extracted))
        out.append({"name": o["name"], "startCommand": p.get("StartCommand", ""),
                    "finishedCommand": p.get("FinishedCommand", ""), "cleanUpCommand": p.get("CleanUpCommand", ""),
                    "removeWhenComplete": bool(p.get("RemoveWhenComplete", 1)),
                    "useAIState": bool(p.get("UseAIState", 1)), "lines": lines})
    return out
