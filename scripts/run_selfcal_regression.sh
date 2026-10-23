#!/usr/bin/env sh
# TeamTrack regression for one perception configuration (generalisation session, 23 Oct).
# Usage: sh scripts/run_selfcal_regression.sh <tag> [KEY=VALUE ...]
#   e.g. sh scripts/run_selfcal_regression.sh static perception.self_calibration.static_objects=true
# Writes outputs/eval_tracking_top_<tag>.json, outputs/eval_second_set_tracking_top_<tag>.json,
# outputs/match_state_top_{,eval2_}4fps_<tag>.json, outputs/eval_real_<tag>.json and
# outputs/eval_second_set_real_<tag>.json (official files are never overwritten).
set -e
TAG="$1"; shift
PY="${PY:-.venv/Scripts/python.exe}"
CFG=""
for kv in "$@"; do CFG="$CFG --cfg $kv"; done
$PY scripts/eval_tracking.py --view top --track-fps 4 --whole-source --save --tag "_$TAG" $CFG \
    > "outputs/selfcal_${TAG}_eval.log" 2>&1
$PY scripts/eval_tracking.py --view top --set eval2 --track-fps 4 --whole-source --save \
    --tag "_$TAG" $CFG > "outputs/selfcal_${TAG}_eval2.log" 2>&1
$PY scripts/eval_real.py --view top --pipeline "outputs/match_state_top_4fps_$TAG.json" \
    --tag "$TAG" >> "outputs/selfcal_${TAG}_eval.log" 2>&1
$PY scripts/eval_real.py --view top --set eval2 \
    --pipeline "outputs/match_state_top_eval2_4fps_$TAG.json" --tag "$TAG" \
    >> "outputs/selfcal_${TAG}_eval2.log" 2>&1
echo "done $TAG"
