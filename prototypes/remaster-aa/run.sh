#!/bin/zsh
# run.sh: every -proto-aa variant: -frames captures and 3 m10-04 explosion benchmarks at native resolution
S=/private/tmp/claude-501/-Users-rui-src-pg-tron-explorer/96b3dc55-0e6c-4abb-a659-39d6209d8b0c/scratchpad
APP="/Users/rui/src/pg/tron_explorer/Build/TronExplorer.app/Contents/MacOS/Tron Explorer"
W=3024; H=1964
CMD=$(cat $S/explo_cmd.txt)
for v in ${=VARIANTS}; do
  mode=${v%%:*}; scale=${v#*:}; tag=$mode-$scale
  args=(-proto-aa $mode -proto-scale $scale -screen-width $W -screen-height $H -screen-fullscreen 1 -mute)
  for lv in "m01-01:3 8" "intro:20 40" "m10-04:3"; do
    l=${lv%%:*}; t=${lv#*:}
    timeout 300 "$APP" -level retailsingleplayer/$l -frames "$t" -out $S/aa/$tag/$l "${args[@]}" -logFile $S/aa/$tag-$l.log >/dev/null 2>&1
  done
  for i in 1 2 3; do
    timeout 120 "$APP" -level retailsingleplayer/m10-04 -benchmark 8 -benchat "-382 79 8378 0 15" -benchcmd "$CMD" "${args[@]}" -logFile $S/aa/bench.log >/dev/null 2>&1
    echo "$tag $(grep -o 'BENCH.*' $S/aa/bench.log)" >> $S/aa/bench.txt
  done
  grep -h PROTO-AA $S/aa/$tag-m01-01.log >> $S/aa/proto.txt
done
echo DONE
