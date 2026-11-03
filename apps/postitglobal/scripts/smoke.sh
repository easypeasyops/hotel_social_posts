#!/usr/bin/env bash
# Black-box smoke test of the built image: the container starts from its environment alone,
# is alive (/healthz), and says it isn't ready without Redis (/readyz). Placeholder secrets
# and an unreachable Redis: nothing here reaches a real service.
#
#   POSTITGLOBAL_IMAGE=postitglobal:dev scripts/smoke.sh
set -euo pipefail

IMAGE="${POSTITGLOBAL_IMAGE:-postitglobal:dev}"
NAME="postitglobal-smoke-$$"
fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "ok   $*"; }
cleanup() {
  status=$?
  [[ $status -eq 0 ]] || { echo "--- container logs ---"; docker logs "$NAME" 2>&1 | tail -50 || true; }
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

env_args=()
for var in SECRET_KEY SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY ANTHROPIC_API_KEY \
  DEEPL_API_KEY BUFFER_ACCESS_TOKEN CRON_SECRET; do
  env_args+=(-e "$var=smoke-placeholder")
done
docker run -d --name "$NAME" -p 127.0.0.1:8000:8000 -p 127.0.0.1:9100:9100 "${env_args[@]}" \
  -e SUPABASE_URL=https://supabase.invalid -e REDIS_URL=redis://redis.invalid:6379/0 \
  "$IMAGE" >/dev/null

for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz || true)
  [[ "$code" == 200 ]] && break
  sleep 1
done
[[ "$code" == 200 ]] || fail "/healthz returned ${code:-nothing} after 30 s"
pass "/healthz 200"

uid=$(docker exec "$NAME" id -u)
[[ "$uid" != 0 ]] || fail "the app runs as root"
pass "runs as non-root (uid $uid)"

code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8000/readyz)
[[ "$code" == 503 ]] || fail "/readyz returned $code without Redis (want 503)"
pass "/readyz 503 without Redis"

[[ -z "$(docker exec "$NAME" sh -c 'ls -A /app/.env 2>/dev/null')" ]] || fail ".env is in the image"
pass "no .env in the image"

code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs)
[[ "$code" == 404 ]] || fail "/docs returned $code (API docs must be off outside debug)"
pass "/docs hidden"

# Logs: every stdout line is JSON (stderr aside), the /docs request among them as an
# access line with its status.
docker logs "$NAME" 2>/dev/null | python3 -c '
import json, sys
lines = [json.loads(line) for line in sys.stdin if line.strip()]
assert any(e.get("logger") == "postitglobal.access" and e.get("status") == 404 for e in lines), lines
' || fail "stdout is not JSON log lines with an access line"
pass "JSON logs on stdout"

# Metrics on their own port, with the /docs request counted by route template.
metrics=$(curl -s http://127.0.0.1:9100/metrics) # captured: grep -q would SIGPIPE curl
grep -q 'http_requests_total{method="GET",route="unmatched",status="404"}' <<<"$metrics" \
  || fail "no request metrics on :9100"
pass "metrics on :9100"

# SIGTERM (what Kubernetes sends) stops it cleanly: uvicorn is PID 1, not behind a shell.
docker stop -t 25 "$NAME" >/dev/null
code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
[[ "$code" == 0 ]] || fail "exited $code on SIGTERM (want 0)"
pass "clean exit on SIGTERM"

echo "smoke test passed"
