# deploybot runbook

What deploybot is and why it is shaped this way: `docs/ARCHITECTURE.md`.

## Use it

In #aipostit-deploys:

- `/aipostit status`: which release staging and prod run (the digests on main). Anyone.
- `/aipostit release patch` (or `minor`): starts **Bump version**. Its PR merges once `ci` is
  green and the release goes to staging on its own, so apply a migration it needs first.
- `/aipostit promote`: starts **Promote to prod**. Review and merge its PR in GitHub.
- `/aipostit rollback staging` (or `prod`): starts **Roll back**. Staging's PR merges itself;
  review and merge prod's in GitHub. Again goes back one more release.

The last three are for the users in `ALLOWED_USERS` only. Each reply links to the workflow's
runs; the PR and the deploy are then posted to the channel as from Actions. `/aipostit` alone,
or anything it doesn't know, shows the help privately.

## Settings

| Variable | What | Secret |
|---|---|---|
| `SLACK_APP_TOKEN` | app-level token `xapp-…` with `connections:write` (Socket Mode) | yes |
| `SLACK_BOT_TOKEN` | the bot token `xoxb-…` | yes |
| `GITHUB_APP_PRIVATE_KEY_BASE64` | the deploybot GitHub App's private key, base64 on one line (below) | yes |
| `GITHUB_APP_CLIENT_ID` | that App's client ID | no |
| `GITHUB_APP_INSTALLATION_ID` | its installation on `hotel_social_posts` | no |
| `SLACK_TEAM_ID` | our workspace's ID (`T…`) | no |
| `SLACK_CHANNEL_ID` | #aipostit-deploys' ID (`C…`) | no |
| `ALLOWED_USERS` | comma-separated Slack user IDs (`U…`) that may release, promote and roll back; empty: no one | no |
| `GITHUB_REPOSITORY` | optional, `easypeasyops/hotel_social_posts` by default | no |

Every one but the last is required: the bot stops at start, naming the missing one. Secrets
never go into git: locally a `.env` (ignored), in the cluster the platform's `deploybot` store.

## Set up once

1. **GitHub App.** In the easypeasyops organization (Settings → Developer settings → GitHub
   Apps), create **deploybot**: no webhook, repository permissions **Contents: read** and
   **Actions: read and write**, nothing else, installable only on this account. Install it on
   `hotel_social_posts` only. Note its client ID and the installation ID (the number at the
   end of the installation's settings URL), and generate a private key. Keep it outside the
   repo, readable only by you, and put it in `.env` base64-encoded on one line (the store's
   loader reads one line a key):
   `base64 -i ~/.secrets/deploybot.pem | tr -d '\n'`.
2. **Slack app.** At api.slack.com/apps, create the app in our workspace with **Socket Mode**
   on, an app-level token with `connections:write`, the slash command `/aipostit`, and the
   bot scope `commands`. Install it, then copy the bot token. Replies go through each
   command's response URL, so the bot needs no `chat:write`.
3. Put the three secrets in the platform's `deploybot` store, and the IDs in its deploy values.

## Run it locally

```sh
cd apps/deploybot
uv sync
set -a; source .env; set +a   # the settings above
uv run python -m app.main
```

It logs `⚡️ Bolt app is running!` once connected. Each command logs who ran it.
`curl localhost:8000/readyz` answers `ok` while the Slack connection is up (503 when not).

## Release it

The same pipeline as aipostit's: bump `version` in `pyproject.toml` (and `uv.lock`) and merge;
`tag-release.yml` tags `deploybot/vX.Y.Z` and `release.yml` builds, scans, signs and publishes
`ghcr.io/easypeasyops/hotel_social_posts/deploybot`. deploybot has no staging, so no deploy PR
follows. The first release creates its GHCR package as private: make it public, as aipostit's.

## When it doesn't answer

- Slack says "dispatch_failed" or the command times out: the bot isn't connected. Its pod is
  then not Ready (`/readyz` answers 503). Check its logs for the Socket Mode connection; a
  revoked app token fails there. A revoked bot token stops it at start, before the probes.
- "I couldn't read the deploy files from GitHub" or "GitHub didn't start …": the GitHub App's
  key, client ID or installation ID is wrong, the App lost its installation, or (for a start)
  it lacks Actions: write. The log has GitHub's answer.
- "You can't run …": the person's Slack user ID isn't in `ALLOWED_USERS` (their profile →
  ⋮ → Copy member ID). Add it in the deploy values and merge.
