#!/usr/bin/env bash
# Black-box smoke test of the built image: the container starts from its environment alone,
# is alive (/healthz), and says it isn't ready without Redis (/readyz). Placeholder secrets
# and an unreachable Redis: nothing here reaches a real service.
#
#   AICANSOLVEIT_IMAGE=aicansolveit:dev scripts/smoke.sh
set -euo pipefail

IMAGE="${AICANSOLVEIT_IMAGE:-aicansolveit:dev}"
NAME="aicansolveit-smoke-$$"
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
docker run -d --name "$NAME" -p 127.0.0.1:8000:8000 "${env_args[@]}" \
  -e SUPABASE_URL=https://supabase.invalid -e REDIS_URL=redis://redis.invalid:6379/0 \
  "$IMAGE" >/dev/null

for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz || true)
  [[ "$code" == 200 ]] && break
  sleep 1
done
[[ "$code" == 200 ]] || fail "/healthz returned ${code:-nothing} after 30 s"
pass "/healthz 200"

code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8000/readyz)
[[ "$code" == 503 ]] || fail "/readyz returned $code without Redis (want 503)"
pass "/readyz 503 without Redis"

[[ -z "$(docker exec "$NAME" sh -c 'ls -A /app/.env 2>/dev/null')" ]] || fail ".env is in the image"
pass "no .env in the image"

code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs)
[[ "$code" == 404 ]] || fail "/docs returned $code (API docs must be off outside debug)"
pass "/docs hidden"
echo "smoke test passed"
