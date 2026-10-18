"""Every command string in the 38 single-player levels through the grammar (tools/commands.py), counted
the way docs/research/command-language.md ("Validation against the levels") counts them. The research's
numbers came from its own model of the tokenizer over the charting survey's extraction; these come from
the exporter's reading of the .dat files, so they agree where the corpus does (see each test).

The corpus: conftest.py's `corpus`.
"""
import collections
import re

import commands


def outcome(prop, text):
    if prop in commands.AI_MIXED:
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
    verbs = collections.Counter(words[0].upper() for _, _, p, t in corpus for words in commands.executed(p, t))
    assert verbs == {"MSG": 27830, "DELAY": 3707, "ABORT": 105, "LOOPID": 84, "RAND3": 30, "RAND2": 20,
                     "DELAYID": 13, "RAND": 8, "ADD": 6, "SUB": 6, "LOOP": 2, "RAND4": 2, "RAND6": 1, "INT": 1,
                     "WHEN": 1}


def test_skipped_statements_and_separators_match_the_research(corpus):
    run = [t for _, _, p, t in corpus if outcome(p, t) == "run"]
    leftovers = sum(words == [")"] for t in run for words in commands.statements(t))
    line_breaks = sum(any(c in t for c in "\r\n\t") for t in run)
    assert (leftovers, line_breaks) == (48, 931)
