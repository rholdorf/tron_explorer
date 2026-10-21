#!/bin/zsh
# run.sh: every -proto-glow variant at native resolution: stills, 24-frame motion sequences, 3 m10-04 explosion benchmarks
S=/private/tmp/claude-501/-Users-rui-src-pg-tron-explorer/96b3dc55-0e6c-4abb-a659-39d6209d8b0c/scratchpad
G=$S/glow
APP="/Users/rui/src/pg/tron_explorer/Build/TronExplorer.app/Contents/MacOS/Tron Explorer"
CMD=$(cat $S/explo_cmd.txt)
for v in ${=VARIANTS}; do
  size=${v%%:*}; mode=${v#*:}; tag=$size-$mode
  args=(-screen-width 3024 -screen-height 1964 -screen-fullscreen 1 -mute)
  [[ $size != 0 ]] && args+=(-proto-glow $size -proto-glow-mode $mode)
  for lv in "m01-01:3" "intro:20 40" "m10-04:3"; do
    l=${lv%%:*}; t=${lv#*:}
    timeout 300 "$APP" -level retailsingleplayer/$l -frames "$t" -out $G/$tag/$l "${args[@]}" -logFile $G/$tag-$l.log >/dev/null 2>&1
  done
  for lv in "intro:21:21.1" "m10-04:4:4.1"; do
    l=${lv%%:*}; r=${lv#*:}; t=${r%%:*}; s0=${r#*:}
    timeout 300 "$APP" -level retailsingleplayer/$l -frames "$t" -proto-seq "$s0 24" -out $G/$tag/seq-$l "${args[@]}" -logFile $G/$tag-seq-$l.log >/dev/null 2>&1
  done
  for i in 1 2 3; do
    timeout 120 "$APP" -level retailsingleplayer/m10-04 -benchmark 8 -benchat "-382 79 8378 0 15" -benchcmd "$CMD" "${args[@]}" -logFile $G/bench.log >/dev/null 2>&1
    echo "$tag $(grep -o 'BENCH.*' $G/bench.log)" >> $G/bench.txt
  done
done
echo DONE
