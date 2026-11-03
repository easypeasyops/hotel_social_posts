#!/usr/bin/env bash
# Black-box smoke test of the built image: the container starts from its environment alone
# and answers its health check. Placeholder secrets: nothing here reaches a real provider.
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
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health || true)
  [[ "$code" == 200 ]] && break
  sleep 1
done
[[ "$code" == 200 ]] || fail "/health returned ${code:-nothing} after 30 s"
pass "/health 200"

[[ -z "$(docker exec "$NAME" sh -c 'ls -A /app/.env 2>/dev/null')" ]] || fail ".env is in the image"
pass "no .env in the image"

code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs)
[[ "$code" == 404 ]] || fail "/docs returned $code (API docs must be off outside debug)"
pass "/docs hidden"
echo "smoke test passed"
