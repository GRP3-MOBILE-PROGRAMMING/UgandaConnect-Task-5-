#!/usr/bin/env bash
# Runs INSIDE the ugandaconnect/jmeter container (started by the Jenkinsfile).
#   MODE=mock     start the bundled mock API, contract-check the plan, short smoke load
#   MODE=staging  full load test against TARGET_HOST
set -euo pipefail
cd /tests
rm -rf results/report results/results.jtl results/jmeter.log
mkdir -p results

MODE="${MODE:-mock}"
PROM_DELAY="${PROM_DELAY:-30}"   # keep :9270/metrics up so Prometheus scrapes the final numbers
export JVM_ARGS="${JVM_ARGS:-} -Djava.io.tmpdir=/tmp"
REPORT_TMP="-Jjmeter.reportgenerator.temp_dir=/tmp/jmeter-report-temp"   # writable as any user

if [ "$MODE" = "mock" ]; then
  echo ">>> Starting mock API"
  python3 mock-server/mock_server.py --port 8080 > results/mock.log 2>&1 &
  MOCK_PID=$!
  trap 'kill $MOCK_PID 2>/dev/null || true' EXIT
  for _ in $(seq 1 30); do curl -sf http://localhost:8080/api/v1/status >/dev/null && break; sleep 1; done

  echo ">>> Contract check: every request and assertion, once per persona"
  python3 scripts/dry_run.py UgandaConnect_LoadTest.jmx data http://localhost:8080 2

  echo ">>> JMeter smoke load (ramp-up + steady state)"
  jmeter -n -t UgandaConnect_LoadTest.jmx -q user.properties \
    -Jprotocol=http -Jhost=localhost -Jport=8080 \
    -Jtotal_users="${TOTAL_USERS:-20}" -Jrampup="${RAMPUP:-20}" -Jsteady="${STEADY:-60}" \
    -Jthink_time_ms=1000 -Jthink_dev_ms=300 -Jprometheus.delay="$PROM_DELAY" \
    -Jtest_name="jenkins-${BUILD_NUMBER:-local}" \
    "$REPORT_TMP" -l results/results.jtl -j results/jmeter.log -e -o results/report
else
  : "${TARGET_HOST:?TARGET_HOST is required for MODE=staging}"
  echo ">>> Pre-flight: ${TARGET_PROTOCOL:-https}://${TARGET_HOST}:${TARGET_PORT:-443}"
  echo ">>> JMeter load test"
  jmeter -n -t UgandaConnect_LoadTest.jmx -q user.properties \
    -Jprotocol="${TARGET_PROTOCOL:-https}" -Jhost="$TARGET_HOST" -Jport="${TARGET_PORT:-443}" \
    -Jtotal_users="${TOTAL_USERS:-500}" -Jrampup="${RAMPUP:-300}" -Jsteady="${STEADY:-1800}" \
    -Jthink_time_ms="${THINK_TIME_MS:-8000}" -Jthink_dev_ms=3000 -Jmix_uneb="${MIX_UNEB:-30}" \
    -Jprometheus.delay="$PROM_DELAY" -Jtest_name="jenkins-${BUILD_NUMBER:-local}" \
    "$REPORT_TMP" -l results/results.jtl -j results/jmeter.log -e -o results/report
fi
echo ">>> Done. Report: results/report/index.html"
