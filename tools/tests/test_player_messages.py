"""The player's messages the viewer keeps (TronViewer/.../PlayerMessages.cs): teleport, screen fades, the
render-variable table with its ramps and sines, and the WorldProperties fog messages. Compiled with Mono
next to Commands.cs and driven through the command manager, as a level's commands reach them. Rules:
docs/research/player-messages.md (branch research/player-messages; ltjs playerobj.cpp, interfacemgr.cpp,
wavefn.cpp, worldproperties.cpp, gameclientshell.cpp; Tron's object.lto / cshell.dll for the ramps and
sines). Expected values are worked by hand from those rules.

Driver lines (tab-separated):
  run <command>        run a command string (no sender)
  tick <seconds>       one frame: pending commands, then the render variables and the fade
  var <name>           print "var <name> <value>"
  drop <y> <floor y>   print "drop <y>", where a player (half-height 53) at y stands after a teleport
  alpha                print "alpha <fade alpha>"
  report               print the unhandled counts: "unhandled <verb> <class> <word> <count>"
The level: the player ("player"), a WorldProperties named "WorldProperties0" seeded with FogR/G/B 10 20 30,
FogNearZ 100, FogFarZ 1000, FarZ 5000; teleport points "tp1" and "TP2" (the teleport callback prints
"teleport <name>" and accepts only names starting with "tp", in any case).
"""
import os
import shutil
import subprocess

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")

DRIVER = r"""
using System;
using System.Collections.Generic;
using System.Globalization;
using Tron;
static class Driver
{
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var mgr = new CommandMgr(() => 0.0);
        var world = new Dictionary<string, float>
        {
            { "FogR", 10 }, { "FogG", 20 }, { "FogB", 30 }, { "FogNearZ", 100 }, { "FogFarZ", 1000 }, { "FarZ", 5000 },
        };
        var vars = new RenderVars(world);
        var fade = new ScreenFade();
        int wp = mgr.Join("WorldProperties0", "WorldProperties");
        PlayerMessages.HandleWorldProperties(mgr, wp, vars);
        int player = mgr.Join("player", "Player");
        PlayerMessages.Handle(mgr, player, vars, fade, name =>
        {
            Console.WriteLine("teleport\t" + name);
            return name.StartsWith("tp", StringComparison.OrdinalIgnoreCase);
        });
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
                    mgr.Update(dt);
                    vars.Update(dt);
                    fade.Update(dt);
                    break;
                }
                case "var": Console.WriteLine("var\t" + a[1] + "\t" + vars[a[1]].ToString("0.####", inv)); break;
                case "drop":
                    Console.WriteLine("drop\t" + PlayerMessages.DropToFloor(float.Parse(a[1], inv), float.Parse(a[2], inv), 53).ToString("0.####", inv));
                    break;
                case "alpha": Console.WriteLine("alpha\t" + fade.Alpha.ToString("0.####", inv)); break;
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
    mcs, mono = shutil.which("mcs"), shutil.which("mono")
    if not mcs or not mono:
        pytest.skip("Mono (mcs, mono) not installed")
    d = tmp_path_factory.mktemp("player_messages")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs"),
                        os.path.join(SCRIPTS, "Commands.cs"), os.path.join(SCRIPTS, "PlayerMessages.cs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def run(lines):
        text = "".join("\t".join(map(str, line)) + "\n" for line in lines)
        out = subprocess.run([mono, exe], input=text, capture_output=True, text=True, check=True).stdout
        return [tuple(x.split("\t")) for x in out.splitlines()]
    return run


def values(out, kind):
    return [float(o[-1]) for o in out if o[0] == kind]


# ---- Teleport ----

def test_teleport_asks_for_the_named_point(driver):
    out = driver([("run", "msg player (teleport TP2)")])
    assert out == [("teleport", "TP2")]


def test_a_teleport_to_something_that_isnt_a_teleport_point_is_counted(driver):
    out = driver([("run", "msg player (teleport DS1.EndTP)"), ("report",)])
    assert out == [("teleport", "DS1.EndTP"), ("unhandled", "MSG", "Player", "TELEPORT", "1")]


def test_a_teleported_player_drops_onto_the_floor_below_but_never_rises(driver):
    # MoveObjectToFloor: if the floor is farther than the half-height, stand 0.1 above half-height over it.
    out = driver([("drop", 500, 0), ("drop", 40, 0), ("drop", 53, 0)])
    assert values(out, "drop") == pytest.approx([53.1, 40, 53])


# ---- Fades ----
# alpha = 1 - SlowOn(1 - p), p = elapsed/total for a fade-out, remaining/total for a fade-in;
# SlowOn(v) = v < 0.5 ? (1 - cos(pi v)) / 2 : v. So SlowOn(0.25) = 0.146447, SlowOn(0.75) = 0.75.

def test_a_fade_out_eases_to_black_and_stays_black(driver):
    out = driver([("alpha",), ("run", "msg player (fadeout 1)"), ("alpha",),
                  ("tick", 0.25), ("alpha",), ("tick", 0.25), ("alpha",), ("tick", 0.25), ("alpha",),
                  ("tick", 0.25), ("alpha",), ("tick", 5), ("alpha",)])
    assert values(out, "alpha") == pytest.approx([0, 0, 0.25, 0.5, 0.853553, 1, 1], abs=1e-4)


def test_a_fade_in_eases_from_black_and_replaces_the_fade_out(driver):
    out = driver([("run", "msg player (fadeout .5)"), ("tick", 0.25),
                  ("run", "msg player (fadein 1 1)"), ("alpha",), ("tick", 0.25), ("alpha",),
                  ("tick", 0.5), ("alpha",), ("tick", 0.25), ("alpha",), ("tick", 1), ("alpha",)])
    assert values(out, "alpha") == pytest.approx([1, 0.853553, 0.25, 0, 0], abs=1e-4)


def test_a_fade_shorter_than_a_tenth_of_a_second_and_fadein_5_are_not_fades(driver):
    out = driver([("run", "msg player (fadeout 0.05); msg player fadein.5"), ("tick", 1), ("alpha",), ("report",)])
    assert out == [("alpha", "0"), ("unhandled", "MSG", "Player", "FADEIN.5", "1"),
                   ("unhandled", "MSG", "Player", "FADEOUT", "1")]


# ---- Ramps and sines ----

def test_a_ramp_moves_a_variable_linearly_then_holds_its_end(driver):
    # FogB is an int: written as "%4.2f", read back truncated.
    out = driver([("run", "msg player (rampconsolevar fogb 255 128 1)"), ("var", "FogB"),
                  ("tick", 0.25), ("var", "FogB"), ("tick", 0.75), ("var", "FogB"), ("tick", 1), ("var", "FogB")])
    assert values(out, "var") == [30, 223, 128, 128]


def test_a_ramp_without_a_start_begins_at_the_current_value_rounded_to_two_decimals(driver):
    out = driver([("run", "msg player (rampconsolevar FogNearZ 101 3)"), ("tick", 1), ("var", "fognearz"),
                  ("run", "msg player (rampconsolevar fognearz 300.33 2)"), ("tick", 1), ("var", "fognearz")])
    assert values(out, "var") == [100.33, 200.33]


def test_a_variable_the_client_doesnt_have_is_ignored_and_a_bad_ramp_is_refused(driver):
    out = driver([("run", "msg player (rampconsolevar fogb128 0 128 1); msg player (rampconsolevar fogr 5)"),
                  ("tick", 1), ("var", "fogb128"), ("var", "fogr"), ("report",)])
    assert out == [("var", "fogb128", "0"), ("var", "fogr", "10"),
                   ("unhandled", "MSG", "Player", "RAMPCONSOLEVAR", "1")]


def test_a_sine_swings_about_min_plus_half_max_until_stopped(driver):
    # Tron's cshell.dll: center = min + max/2 = 3500, amplitude = (max - min)/2 = 500.
    out = driver([("run", "msg player (sinconsolevar fogfarz 2000 3000 4)"),
                  ("tick", 1), ("var", "fogfarz"), ("tick", 1), ("var", "fogfarz"), ("tick", 1), ("var", "fogfarz"),
                  ("run", "msg player (sinconsolevar fogfarz off)"), ("tick", 1), ("var", "fogfarz")])
    assert values(out, "var") == pytest.approx([4000, 3500, 3000, 3000], abs=0.01)


def test_revert_puts_back_the_value_from_before_the_sine(driver):
    out = driver([("run", "msg player (sinconsolevar fogr 0 100 4)"), ("tick", 1), ("var", "fogr"),
                  ("run", "msg player (sinconsolevar fogr revert)"), ("var", "fogr"), ("tick", 1), ("var", "fogr")])
    assert values(out, "var") == [100, 10, 10]


def test_a_sine_replaces_a_ramp_on_the_same_variable(driver):
    out = driver([("run", "msg player (rampconsolevar fogg 20 220 1)"), ("tick", 0.5),
                  ("run", "msg player (sinconsolevar fogg 0 100 4)"), ("tick", 1), ("var", "fogg"),
                  ("tick", 2), ("var", "fogg")])
    assert values(out, "var") == [100, 0]


# ---- WorldProperties ----

def test_fogcolor_sets_the_fog_color_in_any_case_of_the_name(driver):
    out = driver([("run", "msg worldproperties0 (FOGCOLOR 1 2 3)"), ("var", "fogr"), ("var", "fogg"), ("var", "fogb")])
    assert values(out, "var") == [1, 2, 3]


def test_a_worldproperties_message_copies_every_world_variable_again_wiping_a_ramp_that_keeps_running(driver):
    out = driver([("run", "msg player (rampconsolevar fognearz 300 2)"), ("tick", 1), ("var", "fognearz"),
                  ("run", "msg WorldProperties0 (fogfarz 900)"), ("var", "fognearz"), ("var", "fogfarz"),
                  ("tick", 0.5), ("var", "fognearz")])
    assert values(out, "var") == [200, 100, 900, 250]


def test_glow_fog_and_fog_enable_messages_set_their_variables(driver):
    out = driver([("run", "msg WorldProperties0 (screenglowfogenable 1); msg WorldProperties0 (screenglowfognearz 650);"
                          " msg WorldProperties0 (screenglowfogfarz 2000); msg WorldProperties0 (fogenable 0);"
                          " msg WorldProperties0 (fognearz 5)"),
                  ("var", "ScreenGlowFogEnable"), ("var", "ScreenGlowFogNearZ"), ("var", "ScreenGlowFogFarZ"),
                  ("var", "FogEnable"), ("var", "FogNearZ")])
    assert values(out, "var") == [1, 650, 2000, 0, 5]


def test_farz_is_not_a_worldproperties_message(driver):
    out = driver([("run", "msg WorldProperties0 (farz 100)"), ("var", "farz"), ("report",)])
    assert out == [("var", "farz", "5000"), ("unhandled", "MSG", "WorldProperties", "FARZ", "1")]
