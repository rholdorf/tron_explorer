#!/bin/zsh
# run.sh: every -proto-ssao variant at native resolution: stills, a 24-frame motion sequence, 3 m10-04 explosion benchmarks
S=${S:?scratchpad}
G=$S/ssao
APP="/Users/rui/src/pg/tron_explorer/Build/TronExplorer.app/Contents/MacOS/Tron Explorer"
CMD=$(cat $S/explo_cmd.txt)
REM=(-proto-aa msaa4 -proto-glow 512 -proto-glow-mode resample)
mkdir -p $G
for v in ${=VARIANTS}; do
  tag=${v%%:*}; spec=${v#*:}
  args=(-screen-width 3024 -screen-height 1964 -screen-fullscreen 1 -mute)
  [[ $spec != off ]] && args+=(-proto-ssao $spec)
  if [[ $tag != bench-* ]]; then
    for lv in "m01-01:3" "intro:20 40" "m10-04:3" "m02-04:3" "m05-01:3"; do
      l=${lv%%:*}; t=${lv#*:}
      timeout 300 "$APP" -level retailsingleplayer/$l -frames "$t" -out $G/$tag/$l "${args[@]}" -logFile $G/$tag-$l.log >/dev/null 2>&1
    done
    timeout 300 "$APP" -level retailsingleplayer/intro -frames 21 -proto-seq "21 24" -out $G/$tag/seq-intro "${args[@]}" -logFile $G/$tag-seq.log >/dev/null 2>&1
  else
    args+=($REM)   # bench-*: the cost on top of MSAA 4x and the 512² glow
  fi
  for i in 1 2 3; do
    timeout 120 "$APP" -level retailsingleplayer/m10-04 -benchmark 8 -benchat "-382 79 8378 0 15" -benchcmd "$CMD" "${args[@]}" -logFile $G/bench.log >/dev/null 2>&1
    echo "$tag $(grep -o 'BENCH.*' $G/bench.log)" >> $G/bench.txt
  done
done
echo DONE
