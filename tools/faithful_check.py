"""Faithful-mode reference captures: the player build's -shots and -frames over a fixed set of levels, and an
exact pixel comparison of two capture sets. Remaster mode (#91) must leave faithful mode pixel-identical; take a
reference before a change and compare after it (#92).

    .venv/bin/python -I tools/faithful_check.py capture reference/faithful/<label>
    .venv/bin/python -I tools/faithful_check.py compare reference/faithful/<before> reference/faithful/<after>

Captures run in fixed 60 Hz game time with seeded randoms, so two runs of the same build are identical. They
are game imagery: keep them under reference/ (gitignored). Needs the player build at Build/TronExplorer.app and
mus-y-sinak beside this repo for the reference-panel poses.
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "Build/TronExplorer.app/Contents/MacOS/Tron Explorer"
PANEL = ROOT.parent / "mus-y-sinak/docs/reference-panel.json"

# What remaster touches: world edges and floors at grazing angles (m01-01's panel), scene cameras, characters,
# subtitles and the digitization (intro), an opening scene with effects (m10-04), the heaviest level (m02-04).
FRAMES = [
    ("retailsingleplayer/intro", "5 20 40"),
    ("retailsingleplayer/m10-04", "3 10"),
    ("retailsingleplayer/m01-01", "3 8"),
    ("retailsingleplayer/m02-04", "3"),
]
SHOTS = "retailsingleplayer/m01-01"


def run(out, *args):
    out.mkdir(parents=True, exist_ok=True)
    log = out / "player.log"
    subprocess.run([str(APP), *args, "-out", str(out), "-mute", "-screen-fullscreen", "0", "-logFile", str(log)],
                   check=True, timeout=600, stdout=subprocess.DEVNULL)
    if not any(line.startswith(("FRAMES", "SHOTS")) for line in log.read_text(errors="replace").splitlines()):
        sys.exit(f"{out}: the player didn't finish; see {log}")


def capture(dest):
    dest = Path(dest).resolve()  # the player resolves relative paths against its own directory
    run(dest / "shots", "-level", SHOTS, "-shots", str(PANEL), "-screen-width", "1706", "-screen-height", "772")
    for level, times in FRAMES:
        run(dest / level.split("/")[-1], "-level", level, "-frames", times,
            "-screen-width", "1920", "-screen-height", "1080")
    print(f"{len(list(dest.rglob('*.png')))} captures in {dest}")


def compare(a, b):
    a, b = Path(a), Path(b)
    differ = 0
    pngs = sorted(p.relative_to(a) for p in a.rglob("*.png"))
    for rel in pngs:
        if not (b / rel).exists():
            print(f"{rel}: missing in {b}")
            differ += 1
            continue
        x, y = Image.open(a / rel).convert("RGBA"), Image.open(b / rel).convert("RGBA")
        box = ImageChops.difference(x, y).getbbox() if x.size == y.size else (0, 0, *y.size)
        if box:
            print(f"{rel}: differs in {box}")
            differ += 1
    print("IDENTICAL" if not differ else f"{differ} of {len(pngs)} captures differ")
    return 1 if differ else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "capture":
        capture(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "compare":
        sys.exit(compare(sys.argv[2], sys.argv[3]))
    else:
        sys.exit(__doc__)
