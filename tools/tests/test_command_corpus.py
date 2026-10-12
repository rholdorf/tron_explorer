"""Every command string in the 38 single-player levels through the grammar (tools/commands.py), counted
the way docs/research/command-language.md ("Validation against the levels") counts them. The research's
numbers came from its own model of the tokenizer over the charting survey's extraction; these come from
the exporter's reading of the .dat files, so they agree where the corpus does (see each test).

The corpus: every non-empty string property the engine reads as a command (a name ending in Command / Cmd
with an optional number, not CustomCmd*; CommandObject events EventTnEm, the part after '|'; AI
Initial / ActivateOn / ActivateOff; ArchiveBin OnWithdrawN; Optimizer OnActivate / OnOptimize), and every
KeyFramer key command. "<none>" (the editor's empty value) and numbers aren't commands.
"""
import collections
import glob
import os
import re

import pytest

import commands

PROP = re.compile(r"(?i)((?<!custom)(command|cmd)\d*$|^EventT\d+E\d+$|^(Initial|ActivateOn|ActivateOff|"
                  r"OnWithdraw\d*|OnActivate|OnOptimize)$)")
AI_MIXED = {"Initial", "ActivateOn", "ActivateOff"}   # CAIHuman: split the AI's way (SendMixedTriggerMsgToObject)
# Words of a verb that are nested commands.
NESTED = {"DELAY": [2], "DELAYID": [3], "LOOP": [3], "LOOPID": [4], "REPEAT": [5], "REPEATID": [6], "RAND": [2, 3],
          **{f"RAND{n}": list(range(1, n + 1)) for n in range(2, 9)}}


def level_commands(w):
    """(class, property, command string) for every command string in a loaded level."""
    import keyframer
    out = []
    for o in w.objects:
        for k, v in o["props"].items():
            if not isinstance(v, str) or not PROP.search(k):
                continue
            if re.fullmatch(r"(?i)EventT\d+E\d+", k):
                v = v.split("|", 1)[1] if "|" in v else ""
            if v.strip() and v.strip() != "<none>" and not re.fullmatch(r"[\d.\s-]+", v):
                out.append((o["class"], k, v))
        if o["class"] == "KeyFramer":
            index = o["props"].get("KeyDataIndex", -1.0)
            if 0 <= index < len(w.blind):
                out += [("KeyFramer", "key", k["command"]) for k in keyframer.read_keys(w.blind[int(index)][1])
                        if k["command"].strip()]
    return out


@pytest.fixture(scope="module")
def corpus(extracted):
    import dat85
    out = []
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        name = os.path.basename(f)[:-4]
        out += [(name, *c) for c in level_commands(dat85.load(f))]
    return out


def mixed_parts(text):
    """ParseTriggerMsg (ltjs serverutilities.cpp): the AI's split of a mixed message, on ';' outside
    parentheses and quotes. Parts that are valid commands run as commands."""
    parts, start, depth, quote = [], 0, 0, False
    for i, c in enumerate(text):
        if c == "(" and not quote:
            depth += 1
        elif c == ")" and not quote and depth:
            depth -= 1
        elif c == '"':
            quote = not quote
        elif c == ";" and not quote and not depth:
            parts.append(text[start:i])
            start = i + 1
    return parts + [text[start:]]


def outcome(prop, text):
    if prop in AI_MIXED:
        return "ai"
    return "run" if commands.is_valid(text) else "dead"


def test_every_string_tokenizes_and_all_but_37_run(corpus):
    assert len(corpus) == 16418
    counts = collections.Counter(outcome(p, t) for _, _, p, t in corpus)
    # As in the research: 599 AI mixed messages, 37 never run (32 commented out, 5 Spawner addgoal).
    assert counts == {"run": 15782, "ai": 599, "dead": 37}


def test_the_strings_that_never_run_are_commented_out_or_spawner_goals(corpus):
    dead = [t for _, _, p, t in corpus if outcome(p, t) == "dead"]
    kinds = collections.Counter(
        "commented" if re.match(r"(?i)(\*|xmsg|COMMENTOUT\[|\\\\|\(FR\))", t) else
        "addgoal" if t.lower().startswith("addgoal") else t for t in dead)
    assert kinds == {"commented": 32, "addgoal": 5}


def test_executed_verbs_match_the_research(corpus):
    verbs = collections.Counter()

    def walk(text):
        for words in commands.statements(text):
            if commands.verb_count(words) is None:
                continue
            verb = words[0].upper()
            verbs[verb] += 1
            for i in NESTED.get(verb, []):
                if commands.is_valid(words[i]):
                    walk(words[i])
            if verb == "MSG" and commands.is_valid(words[2]):   # msg player (add inner 1)
                walk(words[2])

    for _, _, p, t in corpus:
        if outcome(p, t) == "run":
            walk(t)
        elif outcome(p, t) == "ai":
            for part in mixed_parts(t):
                if commands.is_valid(part):
                    walk(part)
    assert verbs == {"MSG": 27830, "DELAY": 3707, "ABORT": 105, "LOOPID": 84, "RAND3": 30, "RAND2": 20,
                     "DELAYID": 13, "RAND": 8, "ADD": 6, "SUB": 6, "LOOP": 2, "RAND4": 2, "RAND6": 1, "INT": 1,
                     "WHEN": 1}


def test_skipped_statements_and_separators_match_the_research(corpus):
    run = [t for _, _, p, t in corpus if outcome(p, t) == "run"]
    leftovers = sum(words == [")"] for t in run for words in commands.statements(t))
    line_breaks = sum(any(c in t for c in "\r\n\t") for t in run)
    assert (leftovers, line_breaks) == (48, 931)
