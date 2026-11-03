#!/usr/bin/env bash
# Does this CI run need the full checks? Writes `full=true|false` to $GITHUB_OUTPUT.
#
# A pull request that changes only Markdown skips the work in every CI job. The jobs still
# run and report success: `ci` needs them, and a workflow-level `paths` filter would leave
# the required check waiting forever. Pushes to main always run everything.
#
# Needs the PR merge commit and its first parent (actions/checkout fetch-depth: 2 or more).
set -euo pipefail

out="${GITHUB_OUTPUT:-/dev/stdout}"
if [[ "${GITHUB_EVENT_NAME:-}" != pull_request ]]; then
  echo "full=true" >>"$out"
  exit 0
fi
changed=$(git diff --name-only HEAD^1 HEAD)
echo "$changed"
if grep -qvE '\.md$' <<<"$changed"; then
  echo "full=true" >>"$out"
else
  echo "full=false" >>"$out"
  echo "::notice::Docs-only change: checks skipped (scripts/ci-scope.sh)"
fi
