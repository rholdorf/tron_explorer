"""The viewer's SoundButeFX repeat rule (TronViewer/.../SoundButeTimer.cs), compiled with .NET and run
frame by frame against sounds of a given length. Engine rule: SoundButeFX::Update (ltjs soundbutefx.cpp,
retail object.lto 0x1022c1d0); docs/research/ambient-sound.md §7 (branch research/ambient-sound): the
first sound at level start, the next at max(start of the last + U(MinDelay, MaxDelay), end of the last),
each a random PathN.
"""

import pytest

from conftest import cs_driver


# stdin: min max length dt duration files seed -> stdout: one "time file" line per play
DRIVER = r"""
using System;
using System.Globalization;
static class Driver
{
    static void Main()
    {
        var inv = CultureInfo.InvariantCulture;
        var a = Console.ReadLine().Split(' ');
        Func<int, float> F = i => float.Parse(a[i], inv);
        var timer = new Tron.SoundButeTimer(F(0), F(1), new Random((int)F(6)));
        float length = F(2), dt = F(3), end = -1;
        for (int frame = 0; frame * dt <= F(4); frame++)
        {
            float t = frame * dt;
            int file = timer.Next(t, t < end, (int)F(5));
            if (file < 0) continue;
            end = t + length;
            Console.WriteLine(t.ToString("R", inv) + " " + file);
        }
    }
}
"""


@pytest.fixture(scope="module")
def plays(tmp_path_factory):
    run_driver = cs_driver(tmp_path_factory, "soundbutetimer", DRIVER, "SoundButeTimer.cs")

    def run(min_delay, max_delay, length, duration, files=3, dt=0.25, seed=1):
        text = f"{min_delay} {max_delay} {length} {dt} {duration} {files} {seed}\n"
        out = run_driver(text)
        return [(float(t), int(f)) for t, f in (line.split() for line in out.splitlines())]
    return run


def test_the_first_sound_plays_at_level_start_then_every_delay_from_its_start(plays):
    # a 2 s sound with MinDelay = MaxDelay = 5 starts every 5 s
    assert [t for t, _ in plays(5, 5, 2, 20)] == [0, 5, 10, 15, 20]


def test_a_sound_longer_than_the_delay_is_waited_for(plays):
    # WaitUntilFinished: MinDelay = MaxDelay = 0 (m03-01 blips) plays back to back; 3 s sound, 1 s delay too
    assert [t for t, _ in plays(0, 0, 3, 12)] == [0, 3, 6, 9, 12]
    assert [t for t, _ in plays(1, 1, 3, 12)] == [0, 3, 6, 9, 12]


def test_delays_are_uniform_between_min_and_max_and_files_random(plays):
    p = plays(2, 4, 0.5, 2000, files=5, dt=0.25)
    gaps = [b - a for (a, _), (b, _) in zip(p, p[1:])]
    assert 2 <= min(gaps) < 2.3 and 3.7 < max(gaps) <= 4.25   # within a frame of [2, 4]
    assert 2.9 < sum(gaps) / len(gaps) < 3.25                   # mean 3 (+ half a frame)
    counts = [sum(1 for _, f in p if f == i) for i in range(5)]
    assert min(counts) > len(p) / 5 * 0.7
