"""The viewer's ambient sound volume (TronViewer/.../AmbientVolume.cs), compiled with Mono and checked
against the engine's numbers in docs/research/ambient-sound.md (branch research/ambient-sound):
linear falloff in LT volume between the radii (Lithtech.exe 0x4815d2), then retail SndDrv.dll's
LT volume -> dB curve (0x10005470). AmbientVolume.cs uses only System, so it compiles outside Unity.
"""
import os
import shutil
import subprocess

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")

DRIVER = r"""
using System;
using System.Globalization;
static class Driver
{
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var a = line.Split(' ');
            Func<int, float> F = i => float.Parse(a[i], inv);
            double r = a[0] == "falloff" ? Tron.AmbientVolume.Falloff(F(1), F(2), F(3))
                     : a[0] == "db" ? Tron.AmbientVolume.Decibels((int)F(1), F(2), F(3))
                     : a[0] == "gain" ? Tron.AmbientVolume.Gain((int)F(1), F(2), F(3), F(4), F(5))
                     : Tron.AmbientVolume.UnityPriority((int)F(1));
            Console.WriteLine(r.ToString("R", inv));
        }
    }
}
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    mcs, mono = shutil.which("mcs"), shutil.which("mono")
    if not mcs or not mono:
        pytest.skip("Mono (mcs, mono) not installed")
    d = tmp_path_factory.mktemp("ambientvolume")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs"),
                        os.path.join(SCRIPTS, "AmbientVolume.cs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def call(*queries):
        text = "\n".join(" ".join(str(x) for x in q) for q in queries) + "\n"
        out = subprocess.run([mono, exe], input=text, capture_output=True, text=True, check=True).stdout
        return [float(x) for x in out.split()]
    return call


def test_falloff_is_full_inside_inner_zero_past_outer_and_linear_between(run):
    # f = 1 - (d - inner) / (outer + 0.01 - inner)
    assert run(("falloff", 0, 1500, 5500), ("falloff", 1500, 1500, 5500), ("falloff", 3500, 1500, 5500),
               ("falloff", 5500.01, 1500, 5500), ("falloff", 9000, 1500, 5500)) == \
        pytest.approx([1, 1, 0.5, 0, 0], abs=1e-5)


def test_inner_beyond_outer_plays_full_out_to_inner(run):
    # m02-01 gridamb_02: InnerRadius 18000 > OuterRadius 17000; the inner test comes first
    assert run(("falloff", 17500, 18000, 17000), ("falloff", 18500, 18000, 17000)) == [1, 0]


def test_lt_volume_to_db_follows_retail_snddrv(run):
    # research table, Volume 100, master 1: f = 1, .9 ... .1, 0
    fs = [1, .9, .8, .7, .6, .5, .4, .3, .2, .1]
    expected = [0, -1.0, -2.3, -3.9, -5.8, -8.7, -12.9, -19.1, -31.0, -59.0]
    assert run(*[("db", 100, f, 1) for f in fs]) == pytest.approx(expected, abs=0.06)


def test_game_default_volume_scales_before_the_curve(run):
    # SoundVolume 75 x defaultsoundmultiplier 0.75 = 0.5625: full volume is -6.8 dB, half falloff -21.1
    assert run(("db", 100, 1, 0.5625), ("db", 100, 0.5, 0.5625), ("db", 100, 0.2, 0.5625)) == \
        pytest.approx([-6.8, -21.1, -55.6], abs=0.06)


def test_a_volume_prop_below_100_goes_through_the_same_curve(run):
    # Volume 50 at f = 1 is LT volume 50, the same as Volume 100 halfway out
    [a, b] = run(("db", 50, 1, 1), ("db", 100, 0.5, 1))
    assert a == b


def test_gain_is_the_db_as_amplitude_and_silent_out_of_earshot(run):
    # gain(volume, inner, outer, distance, master): -8.7 dB = 0.367; past outer, or a Volume 0 sound, is silent
    [half, far, zero] = run(("gain", 100, 1500, 5500, 3500, 1), ("gain", 100, 1500, 5500, 6000, 1),
                            ("gain", 0, 1500, 5500, 0, 1))
    assert half == pytest.approx(10 ** (-8.72 / 20), abs=0.003)
    assert far == 0 and zero == 0


def test_engine_priority_maps_to_unity_priority_lower_is_more_important(run):
    assert run(("priority", 0), ("priority", 1), ("priority", 3)) == [128, 96, 32]


def test_inner_beyond_outer_is_still_silent_past_earshot(run):
    # research §1: no voice beyond 1.5 x OuterRadius (25500 here), even inside a larger InnerRadius
    [inside, beyond] = run(("gain", 100, 30000, 17000, 20000, 1), ("gain", 100, 30000, 17000, 26000, 1))
    assert inside > 0 and beyond == 0
