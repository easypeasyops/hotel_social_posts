#!/usr/bin/env bash
# Posts <text> (Slack mrkdwn) to #aipostit-deploys through the incoming webhook in
# SLACK_DEPLOYS_WEBHOOK_URL. A missing webhook or a failed post only warns: Slack must never
# fail a release or a deploy.
#
# Usage: slack-notify.sh <text>
set -euo pipefail

if [[ -z "${SLACK_DEPLOYS_WEBHOOK_URL:-}" ]]; then
  echo "::warning::SLACK_DEPLOYS_WEBHOOK_URL is not set: nothing posted to Slack"
  exit 0
fi
jq -n --arg text "$1" '{text: $text}' |
  curl -fsS --max-time 10 -H 'Content-Type: application/json' --data @- "$SLACK_DEPLOYS_WEBHOOK_URL" >/dev/null ||
  echo "::warning::the Slack post failed"
