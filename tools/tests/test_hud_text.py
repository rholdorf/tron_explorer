"""The HUD text (ticket #52): MISSIONTEXT's typed block and TRANSMISSION's announcement queue
(TronViewer/.../HudText.cs, compiled with .NET next to Commands.cs and driven through the command manager),
and what tools/hudtext.py exports for them. Rules: docs/research/mission-text.md (branch
research/mission-text; ltjs timedtext.cpp, hudmessagequeue.cpp; Tron's cshell.dll and Lithtech.exe).
Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  run <command>    run a command string
  tick <seconds>   one frame: pending commands, then the mission text and the queue
  mission          print "mission <active> <visible> <alpha> <text shown>"
  queue            print "queue <alpha> <text>" for each visible transmission, oldest first
  report           print the unhandled counts: "unhandled <verb> <class> <word> <count>"
Strings: 1 "AB\\nC", 2 "<color 1 2 3>X<Y", 3 "MESSAGE:<color 165 223 255> Hi"; the others are missing.
Sounds print "sound type on|off", "sound scroll", "sound transmission" when asked for.
"""

import json
import os
import sys

import pytest

from conftest import cs_driver

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hudtext  # noqa: E402


DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Tron;
static class Driver
{
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var mgr = new CommandMgr(() => 0.0);
        var strings = new Dictionary<int, string> { { 1, "AB\nC" }, { 2, "<color 1 2 3>X<Y" }, { 3, "MESSAGE:<color 165 223 255> Hi" } };
        var mission = new MissionText();
        mission.TypeSound = on => Console.WriteLine("sound\ttype " + (on ? "on" : "off"));
        mission.ScrollSound = () => Console.WriteLine("sound\tscroll");
        var queue = new TransmissionQueue();
        int player = mgr.Join("player", "Player");
        HudMessages.Handle(mgr, player, id => strings.TryGetValue(id, out var s) ? s : null, mission, queue,
                           () => Console.WriteLine("sound\ttransmission"));
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split('\t');
            switch (a[0])
            {
                case "run": mgr.Run(a[1]); break;
                case "tick":
                {
                    float dt = float.Parse(a[1], inv);
                    mgr.BeginFrame(dt); mgr.Update();
                    mission.Update(dt);
                    queue.Update(dt);
                    break;
                }
                case "mission":
                    Console.WriteLine("mission\t" + mission.Active + "\t" + mission.Visible + "\t" + mission.Alpha.ToString("0.####", inv) + "\t" +
                                      string.Concat(mission.Chars.Take(mission.Visible).Select(c => c.C)));
                    break;
                case "colors":
                    Console.WriteLine("colors\t" + string.Join(" ", mission.Chars.Select(c => c.C + ":" + c.Line + ":" + c.Rgb.ToString("X6"))));
                    break;
                case "queue":
                    foreach (var e in queue.Entries.Where(e => e.Visible))
                        Console.WriteLine("queue\t" + e.Alpha.ToString("0.####", inv) + "\t" + string.Concat(e.Chars.Select(c => c.C)));
                    break;
                case "report":
                    foreach (var u in mgr.Unhandled)
                        Console.WriteLine("unhandled\t" + u.Verb + "\t" + u.Class + "\t" + u.Word + "\t" + u.Count);
                    break;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    run_driver = cs_driver(tmp_path_factory, "hud_text", DRIVER, "Commands.cs", "HudText.cs")

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        out = run_driver(text)
        return [tuple(x.split("\t")) for x in out.splitlines()]
    return run


def missions(out):
    return [(o[1], int(o[2]), float(o[3]), o[4] if len(o) > 4 else "") for o in out if o[0] == "mission"]


# ---- Mission text ----
# "AB\nC": A at 0, B at 0.015; C is on a new line: the scroll waits 0.25 from 0.03, so C at 0.28; the last
# letter's slot ends at 0.295, then 3 s hold and a 2 s linear fade: alpha 0.5 at 4.295, gone at 5.295.

def test_letters_type_one_every_15_ms_and_a_new_line_waits_a_quarter_second(driver):
    out = driver([("run", "msg player (missiontext 1)"), ("mission",), ("tick", 0.016), ("mission",),
                  ("tick", 0.2), ("mission",), ("tick", 0.07), ("mission",)])
    assert missions(out) == [("True", 1, 1, "A"), ("True", 2, 1, "AB"), ("True", 2, 1, "AB"), ("True", 3, 1, "ABC")]


def test_the_type_sound_loops_while_typing_and_stops_for_the_scroll_and_at_the_end(driver):
    out = driver([("run", "msg player (missiontext 1)"), ("tick", 0.1), ("tick", 0.2), ("tick", 0.1)])
    assert [o[1] for o in out if o[0] == "sound"] == ["type on", "type off", "scroll", "type on", "type off"]


def test_the_block_holds_3_s_after_the_last_letter_then_fades_over_2_s(driver):
    out = driver([("run", "msg player (missiontext 1)"), ("tick", 0.3), ("tick", 2.9), ("mission",),
                  ("tick", 1.095), ("mission",), ("tick", 1.1), ("mission",)])
    m = missions(out)
    assert m[0][2] == pytest.approx(1)
    assert m[1][2] == pytest.approx(0.5, abs=1e-3)
    assert m[2][0] == "False"


def test_a_new_mission_text_replaces_the_current_one_at_once(driver):
    out = driver([("run", "msg player (missiontext 1)"), ("tick", 0.3), ("run", "msg player (missiontext 2)"),
                  ("mission",), ("tick", 1), ("mission",)])
    assert missions(out) == [("True", 1, 1, "X"), ("True", 3, 1, "X<Y")]


def test_colour_tags_recolour_what_follows_and_other_brackets_are_text(driver):
    out = driver([("run", "msg player (missiontext 1)"), ("colors",), ("run", "msg player (missiontext 2)"), ("colors",)])
    colors = [o[1] for o in out if o[0] == "colors"]
    assert colors == ["A:0:FF9B00 B:0:FF9B00 C:1:FF9B00", "X:0:010203 <:0:010203 Y:0:010203"]


def test_missiontext_0_clears_and_a_missing_string_shows_nothing_and_is_counted(driver):
    out = driver([("run", "msg player (missiontext 1)"), ("tick", 0.1), ("run", "msg player (missiontext 0)"), ("mission",),
                  ("run", "msg player (missiontext 1)"), ("tick", 0.1), ("run", "msg player (missiontext 6130)"),
                  ("mission",), ("report",)])
    assert missions(out) == [("False", 0, 0, ""), ("True", 0, 1, "")]
    assert ("unhandled", "MISSINGSTRING", "Player", "MISSIONTEXT", "1") in out


# ---- Transmissions ----
# Alpha: t/1 over the first second, 1 until 5, then 1 - (t - 5)/0.5; hidden at 5.5.

def test_a_transmission_fades_in_holds_and_fades_out_with_its_sound(driver):
    out = driver([("run", "msg player (transmission 3)"), ("tick", 0.5), ("queue",), ("tick", 2), ("queue",),
                  ("tick", 2.75), ("queue",), ("tick", 0.5), ("queue",)])
    assert out[0] == ("sound", "transmission")
    assert [(float(o[1]), o[2]) for o in out if o[0] == "queue"] == [
        (0.5, "MESSAGE: Hi"), (1, "MESSAGE: Hi"), (0.5, "MESSAGE: Hi")]


def test_a_third_transmission_takes_the_oldest_slot_at_once(driver):
    out = driver([("run", "msg player (transmission 1)"), ("tick", 0.1), ("run", "msg player (transmission 2)"),
                  ("tick", 0.1), ("run", "msg player (transmission 3)"), ("queue",)])
    assert [o[2] for o in out if o[0] == "queue"] == ["X<Y", "MESSAGE: Hi"]


def test_a_missing_transmission_takes_a_slot_and_plays_its_sound(driver):
    out = driver([("run", "msg player (transmission 5355)"), ("queue",), ("report",)])
    assert out == [("sound", "transmission"), ("queue", "0", ""),
                   ("unhandled", "MISSINGSTRING", "Player", "TRANSMISSION", "1")]


# ---- Export ----

@pytest.fixture(scope="module")
def hud(extracted, tmp_path_factory):
    out = tmp_path_factory.mktemp("hud")
    strings, glyphs, files = hudtext.export_hud(extracted, str(out))
    return out, strings, glyphs, files


def test_the_string_table_has_every_string_but_the_three_missing_ids(hud):
    out, strings, _, _ = hud
    assert len(strings) == 5001 and min(strings) == 2 and max(strings) == 22511
    assert not {6130, 5355, 5316} & set(strings)
    assert strings[5430] == "MESSAGE:<color 165 223 255> Combat disc training complete."
    data = json.loads((out / "hud" / "strings.json").read_text(encoding="utf-8"))
    assert dict(zip(data["ids"], data["texts"])) == strings


def test_the_font_has_a_glyph_for_every_character_the_strings_use(hud):
    _, strings, glyphs, _ = hud
    have = {g["c"] for g in glyphs}
    used = {ord(c) for s in strings.values() for c in s if c != "\n"}
    assert used <= have


def test_the_hud_sounds_are_exported(hud):
    out, _, _, files = hud
    assert files == ["interface/snd/type.wav", "interface/snd/enter.wav", "interface/snd/msgfadeout.wav"]
    assert all((out / "sounds" / f).is_file() for f in files)


def test_the_io_camera_and_its_frame_are_exported_as_layout_txt_has_them(hud):
    # layout.txt [Miscellaneous] IOCameraRect / FOVX / FOVY (the live line, not the commented-out older rect) and
    # [IONodeCam], named as the viewer's IOCamLayout reads them.
    out, _, _, _ = hud
    assert json.loads((out / "hud" / "iocam.json").read_text()) == {
        "rect": [252, 105, 389, 278], "fovX": 70.0, "fovY": 60.0, "center": [320, 357],
        "piece1Tex": "interface/hud/ionode_hud.dtx", "piece1MinAlpha": 0.27, "piece1MaxAlpha": 0.36,
        "piece1Period": 3.0, "piece1Radius": 256.0,
        "piece2Tex": "interface/hud/ionode_static.dtx", "piece2MinInterval": 0.01, "piece2MaxInterval": 0.25,
        "piece2MinRadius": 248.0, "piece2MaxRadius": 264.0, "piece2MinFlickers": 12, "piece2MaxFlickers": 22,
        "piece2FlickerTime": 0.04}
