#!/usr/bin/env bash
# Opens the PR that deploys <app> v<version> (image digest <digest>) to <env>: it sets
# image.digest in apps/<app>/deploy/envs/<env>.yaml on a new branch. Argo CD deploys it once
# the PR is merged. A staging PR merges itself when `ci` is green; a prod PR waits for you.
#
# Usage: deploy-pr.sh <app> <env> <digest> <version>
# With ROLLBACK=1 the PR rolls <env> back to that earlier release (rollback.yml), and
# REQUESTED_BY, when set, names who asked for it in the PR (the Slack bot fills it in).
# Run from a checkout of main. Needs GH_TOKEN, the release app's token: a PR opened with the
# workflow's own GITHUB_TOKEN would never start CI, so `ci` would never report.
set -euo pipefail

app=$1 env=$2 digest=$3 version=$4
file="apps/$app/deploy/envs/$env.yaml"
repo=$GITHUB_REPOSITORY
rollback=${ROLLBACK:-} requested_by=${REQUESTED_BY:-}

[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "::error::$digest is not an image digest"; exit 1; }
[[ "$requested_by" =~ ^[A-Za-z0-9._\ -]{0,80}$ ]] || { echo "::error::requested_by is not a name"; exit 1; }
[[ $(grep -c '^  digest: ' "$file") == 1 ]] || { echo "::error::$file needs exactly one image digest line"; exit 1; }
if grep -q "^  digest: \"$digest\"" "$file"; then
  echo "::notice::$app $env already runs $digest"
  exit 0
fi

note="$app v$version"
title="deploy: $app $env runs v$version"
branch="deploy/$app-$env-v$version"
what="This sets \`image.digest\` in \`$file\` to \`$digest\` ($app v$version)."
if [[ -n "$rollback" ]]; then
  # The release's own deploy branch may still exist, and a rollback reads differently.
  note="$note, rolled back"
  title="deploy: $app $env rolls back to v$version"
  branch="rollback/$app-$env-v$version"
  what="This rolls $env back to $app v$version, the release before the one it ran: \`image.digest\` in \`$file\` becomes \`$digest\`."
elif [[ "$env" == prod ]]; then
  note="$note, as staging"
  title="$title, the digest staging runs"
fi
sed -i "s|^  digest: .*|  digest: \"$digest\" # $note|" "$file"

# The commit is made through the API, so GitHub signs it as the app.
gh api "repos/$repo/git/refs" -f ref="refs/heads/$branch" -f sha="$(git rev-parse HEAD)" >/dev/null
gh api -X PUT "repos/$repo/contents/$file" -f branch="$branch" -f message="$title" \
  -f sha="$(git rev-parse "HEAD:$file")" -f content="$(base64 -w0 "$file")" >/dev/null

body="**Repo:** hotel_social_posts · **Stack:** the $env deploy of $app **$version** (tag \`$app/v$version\`) · **Waits on:** nothing. The release workflow built, scanned and signed the image.

$what Argo CD deploys it once this is merged.${requested_by:+

Requested by $requested_by.}

Opened by \`.github/scripts/deploy-pr.sh\`."
gh pr create --repo "$repo" --base main --head "$branch" --title "$title" --body "$body"
if [[ "$env" == staging ]]; then
  gh pr merge "$branch" --repo "$repo" --auto --squash
fi
