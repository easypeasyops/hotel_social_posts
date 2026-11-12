# deploybot runbook

What deploybot is and why it is shaped this way: `docs/ARCHITECTURE.md`.

## Use it

In #aipostit-deploys: `/aipostit` answers with its help, privately. Its commands come in the
next versions.

## Settings

| Variable | What | Secret |
|---|---|---|
| `SLACK_APP_TOKEN` | app-level token `xapp-…` with `connections:write` (Socket Mode) | yes |
| `SLACK_BOT_TOKEN` | the bot token `xoxb-…` | yes |
| `SLACK_TEAM_ID` | our workspace's ID (`T…`) | no |
| `SLACK_CHANNEL_ID` | #aipostit-deploys' ID (`C…`) | no |

Every one is required: the bot stops at start, naming the missing one. Secrets
never go into git: locally a `.env` (ignored), in the cluster the platform's `deploybot` store.

## Set up once

1. **Slack app.** At api.slack.com/apps, create the app in our workspace with **Socket Mode**
   on, an app-level token with `connections:write`, the slash command `/aipostit`, and the
   bot scope `commands`. Install it, then copy the bot token. Replies go through each
   command's response URL, so the bot needs no `chat:write`.
2. Put the two tokens in the platform's `deploybot` store, and the IDs in its deploy values.

## Run it locally

```sh
cd apps/deploybot
uv sync
set -a; source .env; set +a   # the settings above
uv run python -m app.main
```

It logs `⚡️ Bolt app is running!` once connected. Each command logs who ran it.

## Release it

The same pipeline as aipostit's: bump `version` in `pyproject.toml` (and `uv.lock`) and merge;
`tag-release.yml` tags `deploybot/vX.Y.Z` and `release.yml` builds, scans, signs and publishes
`ghcr.io/easypeasyops/hotel_social_posts/deploybot`. deploybot has no staging, so no deploy PR
follows. The first release creates its GHCR package as private: make it public, as aipostit's.

## When it doesn't answer

- Slack says "dispatch_failed" or the command times out: the bot isn't connected. Check its
  logs for the Socket Mode connection; a revoked app token fails there.
