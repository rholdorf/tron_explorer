"""The viewer's carry of a player standing on a moving world model (TronViewer/.../Riding.cs), compiled with
Mono and checked against the engine's rule (ltjs moveobject.cpp): MoveObject offsets everything standing on
the object by the object's move; RotateWorldModel turns their positions about the world model's position
by the rotation from the old one to the new one (backRot = old transposed, forwardRot = new). Only the
position: the carried object's own rotation is left alone. Expected values are worked by hand.

Driver lines: carry <rider xyz> <from xyz> <from pitch yaw roll> <to xyz> <to pitch yaw roll> (radians)
"""
import math
import os
import shutil
import subprocess

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")

DRIVER = r"""
using System;
using System.Globalization;
using Tron;
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
            Func<int, LTVec> V = i => new LTVec(F(i), F(i + 1), F(i + 2));
            Func<int, LTQuat> Q = i => LTQuat.FromEuler(F(i), F(i + 1), F(i + 2));
            var p = Riding.Carry(V(1), V(4), Q(7), V(10), Q(13));
            Console.WriteLine(string.Join(" ", new[] { p.x, p.y, p.z }.Select(v => ((double)v).ToString("R", inv))));
        }
    }
}
""".replace("using Tron;", "using System.Linq;\nusing Tron;")


@pytest.fixture(scope="module")
def carry(tmp_path_factory):
    mcs, mono = shutil.which("mcs"), shutil.which("mono")
    if not mcs or not mono:
        pytest.skip("Mono (mcs, mono) not installed")
    d = tmp_path_factory.mktemp("riding")
    (d / "Driver.cs").write_text(DRIVER)
    exe = str(d / "driver.exe")
    r = subprocess.run([mcs, "-langversion:latest", "-out:" + exe, str(d / "Driver.cs"),
                        os.path.join(SCRIPTS, "Riding.cs"), os.path.join(SCRIPTS, "KeyframerMotion.cs")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

    def run(rider, frm, frm_pyr, to, to_pyr):
        text = " ".join(str(x) for x in ("carry", *rider, *frm, *frm_pyr, *to, *to_pyr)) + "\n"
        out = subprocess.run([mono, exe], input=text, capture_output=True, text=True, check=True).stdout
        return [float(x) for x in out.split()]
    return run


def close(a, b):
    return all(abs(x - y) < 1e-3 for x, y in zip(a, b))


def test_a_platform_that_moves_carries_the_rider_by_the_same_offset(carry):
    assert close(carry((10, 50, 20), (0, 0, 0), (0, 0, 0), (5, -3, 7), (0, 0, 0)), (15, 47, 27))


def test_a_platform_that_turns_swings_the_rider_about_its_position(carry):
    # Yaw +90 degrees takes +X to -Z: the offset (50, 40, 0) from (100, 0, 0) becomes (0, 40, -50).
    assert close(carry((150, 40, 0), (100, 0, 0), (0, 0, 0), (100, 0, 0), (0, math.pi / 2, 0)), (100, 40, -50))


def test_only_the_turn_since_the_last_pose_counts_not_the_platforms_whole_rotation(carry):
    # From yaw 90 to yaw 180 is the same quarter turn as from 0 to 90.
    assert close(carry((150, 40, 0), (100, 0, 0), (0, math.pi / 2, 0), (100, 0, 0), (0, math.pi, 0)), (100, 40, -50))


def test_a_platform_that_moves_and_turns_carries_the_rider_with_both(carry):
    assert close(carry((150, 40, 0), (100, 0, 0), (0, 0, 0), (110, 5, 0), (0, math.pi / 2, 0)), (110, 45, -50))


def test_a_pitching_platform_swings_the_rider_up_and_down(carry):
    # Pitch +90 degrees (LTRotation's matrix) takes +Z to -Y: (0, 10, 30) from the origin becomes (0, -30, 10).
    assert close(carry((0, 10, 30), (0, 0, 0), (0, 0, 0), (0, 0, 0), (math.pi / 2, 0, 0)), (0, -30, 10))
