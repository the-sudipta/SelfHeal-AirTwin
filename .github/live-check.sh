#!/usr/bin/env bash
# Smoke test of a running live twin: wait until it streams live ticks, then check the API,
# the web twin page and one command. Usage: live-check.sh <port>
set -euo pipefail

port="$1"
base="http://localhost:${port}"
phase=""
for _ in $(seq 1 120); do
  phase=$(curl -fsS "${base}/api/health" | python3 -c "import json, sys; print(json.load(sys.stdin)['phase'])" || true)
  if [ "${phase}" = "running" ] || [ "${phase}" = "failed" ]; then
    break
  fi
  sleep 5
done
echo "phase: ${phase}"
test "${phase}" = "running"

curl -fsS "${base}/api/state" | python3 -c "
import json, sys
state = json.load(sys.stdin)
sensors = state['frame']['sensors']
assert len(sensors) == 12, len(sensors)
assert all(s['expected'] is not None for s in sensors if s['raw'] is not None)
print('hour', state['status']['hour'], 'time', state['status']['time'])
"
curl -fsS "${base}/" | grep -q "SelfHeal-Air"
curl -fsS "${base}/js/main.js" > /dev/null
curl -fsS -X POST "${base}/api/sensors/Dongsi:pm25/inject" | grep -q '"kind":"inject"'
curl -fsS "${base}/api/state" | grep -q '"injections":\[{"sensor":"Dongsi:pm25"'
echo "live twin OK on port ${port}"
