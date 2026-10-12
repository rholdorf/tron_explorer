#!/bin/zsh
# Extract the Tron 2.0 .rez archives and export every world for the viewer.
set -e
cd "$(dirname "$0")"
GAME=${1:-$TRON_GAME_DIR}
[ -n "$GAME" ] && [ -d "$GAME" ] || { echo "usage: ./setup.sh <Tron 2.0 install dir> (or set TRON_GAME_DIR)"; exit 1; }
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip -q install numpy pillow; }
# Engine load order (launchcmds.txt + GOG patches): later archives override earlier ones.
for r in Engine.REZ Game.rez Sound.rez Game2.rez GameDLL.rez Gamep3.rez Gamep4.rez gamep5.rez gamep6.rez; do
  [ -f "$GAME/$r" ] && { echo -n "$r: "; .venv/bin/python -I tools/rez.py extract "$GAME/$r" extracted; }
done
.venv/bin/python -I tools/export_level.py extracted export
