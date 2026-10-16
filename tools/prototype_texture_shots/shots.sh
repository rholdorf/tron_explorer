#!/bin/zsh
# PROTOTYPE: render each texture pose of the contact sheet in the Editor (Play mode, level loaded).
# Usage: shots.sh <poses.json> <out dir>
set -e; D=${0:A:h}
cd /Users/rui/src/pg/tron_explorer
export UNITY_PROJECT_PATH=$PWD/TronViewer
poses=$1; out=$2; mkdir -p $out
tmp=$(mktemp -d)
n=$(.venv/bin/python -I -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" $poses)
cap() {
  unity command capture_game_view --no-banner --format json 2>/dev/null | .venv/bin/python -I -c "
import json,sys,base64
d=json.load(sys.stdin); open(sys.argv[1],'wb').write(base64.b64decode(d['data']['result']['base64']))" $tmp/$1.png
}
hl() {
  code=$(sed -e "s|ON|$1|" -e "s|KEY|$tex|" $D/hl.cs)
  unity command eval "$code" --no-banner --format json | .venv/bin/python -I -c "import json,sys; print(json.load(sys.stdin)['data']['result']['result'], end=' ')" 2>/dev/null || true
}
for i in $(seq 0 $((n-1))); do
  read tx ty tz ex ey ez tex <<<$(.venv/bin/python -I -c "
import json,sys
p=json.load(open(sys.argv[1]))[int(sys.argv[2])]
print(*p['target'], *p['eye'], p['texture'].replace(chr(92), '/'))" $poses $i)
  # Pull the eye in to just before the first surface between the target and it (MeshColliders), aim it at
  # the target, and place the body so the camera lands on the eye.
  unity command eval "var p = UnityEngine.Object.FindFirstObjectByType<Tron.PlayerController>(); p.Noclip = true;
var t = new UnityEngine.Vector3(${tx}f,${ty}f,${tz}f); var e = new UnityEngine.Vector3(${ex}f,${ey}f,${ez}f);
var d = (e - t).normalized; float L = (e - t).magnitude; UnityEngine.RaycastHit hit;
if (UnityEngine.Physics.Raycast(t + d * 0.05f, d, out hit, L - 0.05f, ~0, UnityEngine.QueryTriggerInteraction.Ignore))
  e = t + d * UnityEngine.Mathf.Max(0.4f, hit.distance - 0.1f);
var f = t - e;
p.transform.position = e - p.Cam.transform.localPosition;
p.SetView(UnityEngine.Mathf.Atan2(f.x, f.z) * UnityEngine.Mathf.Rad2Deg, -UnityEngine.Mathf.Asin(f.normalized.y) * UnityEngine.Mathf.Rad2Deg);
return 1;" --no-banner >/dev/null
  sleep 0.5; cap a
  # Same frame with the texture's materials white and fullbright: the difference marks where it is.
  hl true; sleep 0.3; cap b; hl false
  .venv/bin/python -I $D/mark.py $tmp/a.png $tmp/b.png $out/$(printf %03d $i).jpg
  echo -n "$i "
done
echo
