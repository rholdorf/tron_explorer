"""BinaryBit and SecRezzer state machines (ticket #53; TronViewer/.../StateModels.cs, compiled with .NET next
to Commands.cs). Rules: docs/research/secrezzer-binarybit.md (branch research/secrezzer-binarybit; Tron's
object.lto). Each test drives one model through a fake host that prints what the model asks for.

Driver lines (tab-separated):
  new bit <energy> <startOnInSocket 0/1> <locked 0/1>   a BinaryBit with PowerUpCommand "pu", TurnOn "on", TurnOff "off"
  new rezzer                                             a SecRezzer
  start | end                                            Start / the playing clip ends
  msg <words> <fromPlayer 0/1>                           a message; prints "handled 0/1" when not handled
  key <statement>                                        a model string key
  state                                                  prints "state <Current> <CanUse> <Prompt>"
Host output: "play <clip> <loop>", "look <name>", "run <command>", "count <word>".
"""

import pytest

from conftest import cs_driver


DRIVER = r"""
using System;
using Tron;
class Host : IStateModelHost
{
    public void Play(string clip, bool loop) => Console.WriteLine("play\t" + clip + "\t" + (loop ? 1 : 0));
    public void SetLook(string look) => Console.WriteLine("look\t" + look);
    public void Run(string command) => Console.WriteLine("run\t" + command);
    public void Count(string word) => Console.WriteLine("count\t" + word);
}
static class Driver
{
    static void Main()
    {
        var host = new Host();
        IStateModel model = null;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "new":
                    model = a[1] == "bit"
                        ? new BinaryBit(host, float.Parse(a[2]), a[3] == "1", a[4] == "1", "pu", "on", "off")
                        : (IStateModel)new SecRezzer(host);
                    break;
                case "start": model.Start(); break;
                case "end": model.OnClipEnd(); break;
                case "key": model.OnKey(a[1]); break;
                case "msg":
                    if (!model.OnMessage(new Message(a[1].Split(' '), 0), a[2] == "1")) Console.WriteLine("handled\t0");
                    break;
                case "state":
                    var cur = model is BinaryBit b ? b.Current.ToString() : ((SecRezzer)model).Current.ToString();
                    Console.WriteLine("state\t" + cur + "\t" + (model.CanUse ? 1 : 0) + "\t" + model.Prompt);
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    run_driver = cs_driver(tmp_path_factory, "state_models", DRIVER, "Commands.cs", "StateModels.cs")

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        return [tuple(x.split("\t")) for x in run_driver(text).splitlines()]
    return run


# ---- BinaryBit ----

def test_a_bit_that_needs_energy_spawns_powered_down_in_its_idle_look(driver):
    out = driver([("new", "bit", 10, 1, 0), ("start",), ("state",)])
    assert out == [("look", "idle"), ("play", "PoweredDown", "0"), ("state", "PoweredDown", "1", "None")]


def test_a_bit_without_energy_lands_on_yes_or_no_at_once(driver):
    out = driver([("new", "bit", 0, 1, 0), ("start",), ("state",), ("new", "bit", 0, 0, 0), ("start",), ("state",)])
    assert out == [("look", "idle"), ("play", "PoweredDown", "0"), ("look", "yes"), ("state", "Yes", "1", "On"),
                   ("look", "idle"), ("play", "PoweredDown", "0"), ("look", "no"), ("state", "No", "1", "Off")]


def test_use_powers_a_bit_up_and_atsocket_lands_it(driver):
    # The energy transfer is granted; the trail is a ClientFX the viewer skips.
    out = driver([("new", "bit", 10, 0, 0), ("start",), ("msg", "ACTIVATE", 1), ("state",),
                  ("msg", "ACTIVATE", 1), ("msg", "ATSOCKET", 0), ("state",)])
    assert out[2:] == [("count", "BinaryBit_Trail"), ("run", "pu"), ("play", "Idle", "1"),
                       ("state", "Flying", "0", "None"), ("look", "no"), ("state", "No", "1", "Off")]


def test_a_flip_plays_its_clip_swaps_the_look_on_the_key_then_runs_its_command(driver):
    out = driver([("new", "bit", 0, 1, 0), ("start",), ("msg", "ACTIVATE", 1), ("state",),
                  ("key", r"RS 0 props\rs\BinaryBit_No.ltb"), ("end",), ("state",),
                  ("msg", "ACTIVATE", 1), ("key", r"RS 0 props\rs\BinaryBit_Yes.ltb"), ("end",)])
    assert out[3:] == [("play", "No", "0"), ("state", "No", "0", "Off"),
                       ("look", "no"), ("run", "off"), ("play", "Idle", "1"), ("state", "No", "1", "Off"),
                       ("play", "Yes", "0"), ("look", "yes"), ("run", "on"), ("play", "Idle", "1")]


def test_a_locked_bit_ignores_use_until_unlocked(driver):
    out = driver([("new", "bit", 0, 1, 1), ("start",), ("state",), ("msg", "ACTIVATE", 1),
                  ("msg", "UNLOCK", 0), ("state",), ("msg", "LOCK", 0), ("state",)])
    assert out[3:] == [("state", "Yes", "0", "On"), ("state", "Yes", "1", "On"), ("state", "Yes", "0", "On")]


def test_other_words_are_left_to_the_object_and_the_report(driver):
    out = driver([("new", "bit", 0, 1, 0), ("start",), ("msg", "INFOSTRING 5", 0), ("msg", "REMOVE", 0)])
    assert out[3:] == [("handled", "0"), ("handled", "0")]


# ---- SecRezzer ----

def test_a_rezzer_spawns_open_and_the_players_use_folds_it_shut(driver):
    out = driver([("new", "rezzer"), ("start",), ("state",), ("msg", "ACTIVATE", 1), ("state",), ("end",),
                  ("state",), ("msg", "ACTIVATE", 1)])
    assert out == [("look", "idle"), ("play", "Idle", "0"), ("state", "Idle", "1", "On"),
                   ("look", "off"), ("play", "Disable", "0"), ("state", "Disabling", "0", "Off"),
                   ("play", "Disabled", "0"), ("state", "Disabled", "0", "Off")]


def test_only_the_player_disables_a_rezzer_and_its_ai_words_stay_unhandled(driver):
    out = driver([("new", "rezzer"), ("start",), ("msg", "ACTIVATE", 0), ("state",), ("msg", "ON", 0)])
    assert out[2:] == [("state", "Idle", "1", "On"), ("handled", "0")]


# ---- Export ----

def test_binarybit_yes_and_no_scale_the_pyramid_and_the_spike_with_their_keys(extracted, tmp_path):
    import export_models
    meta = export_models.export_model(extracted, "props/models/binarybit.ltb", str(tmp_path), ["Yes", "No", "Idle"])
    anims = {a["name"]: a for a in meta["anims"]}
    nodes = [n["name"] for n in meta["nodes"]]
    assert [nodes[anims["Yes"]["scales"][0]], anims["Yes"]["scales"][2]] == ["d_Pyramid", 21]
    assert [nodes[anims["No"]["scales"][0]], anims["No"]["scales"][2]] == ["d_NewSpike", 21]
    assert anims["Idle"]["scales"] == []
    assert anims["Yes"]["cmds"] == [{"t": 0.0, "s": "bute_sound_key bb_yes"},
                                    {"t": 0.3, "s": r"RS 0 props\rs\BinaryBit_Yes.ltb"}]


def test_a_level_carries_its_state_models_looks_clips_and_their_sounds(extracted, tmp_path):
    import json
    import os
    import export_level
    import export_models
    name = "retailsingleplayer/m04-03"
    export_level.export(os.path.join(extracted, "worlds", name + ".dat"), str(tmp_path), name,
                        export_models.Resolver(extracted), export_models.Styles(extracted), extracted)
    meta = json.loads((tmp_path / "level.json").read_text())
    by_cls = {}
    for m in meta["models"]:
        if "looks" in m:
            by_cls.setdefault(meta["objects"][m["obj"]]["cls"], []).append(m)
    assert {k: len(v) for k, v in by_cls.items()} == {"BinaryBit": 4, "SecRezzer": 3}
    bit, rezzer = by_cls["BinaryBit"][0], by_cls["SecRezzer"][0]
    assert bit["skinned"] == 1 and bit["clips"] == ["PoweredDown", "Idle", "Yes", "No"]
    styles = [s["name"] for s in meta["renderStyles"]]
    # Only the byte (render style slot 0) changes between the bit's looks.
    assert [[styles[p["style"]] for p in look["pieces"]][-1] for look in bit["looks"]] == [
        "props/rs/binarybit_idle.ltb", "props/rs/binarybit_yes.ltb", "props/rs/binarybit_no.ltb"]
    assert [(look["name"], look["pieces"][0]["tex"][0]) for look in rezzer["looks"]] == [
        ("idle", "props/skins/secrezzer.dtx"), ("off", "props/skins/secrezzer_off.dtx"),
        ("on", "props/skins/secrezzer_on.dtx"), ("spawn", "props/skins/secrezzer_spawn.dtx")]
    assert [(b["name"], b["files"]) for b in meta["buteSounds"]] == [
        ("bb_yes", ["props/snd/bbit/yes_01.wav"]), ("bb_no", ["props/snd/bbit/no_01.wav"]),
        ("secrez_shutdown", ["props/snd/secrez_shutdown.wav"])]
