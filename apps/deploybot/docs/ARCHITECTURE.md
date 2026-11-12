# deploybot architecture

deploybot answers the `/aipostit` slash command in Slack's #aipostit-deploys. It is the second
phase of Slack deploys (the first posts each release and deploy step through an incoming
webhook: aipostit's `docs/ARCHITECTURE.md`, Release and deploy). This version knows `status`;
`release`, `promote` and `rollback` come next, each by starting a workflow in this repo.

## Shape

- **Socket Mode.** The cluster runs on a laptop, so Slack can't reach it. The bot opens an
  outbound WebSocket to Slack instead (`slack_bolt`'s `SocketModeHandler`, the app-level token
  `SLACK_APP_TOKEN`) and serves nothing: no port, no Gateway route.
- **A separate app, not part of aipostit's release.** A tool that rolls aipostit back must not
  be rolled back with it, and it has no use for aipostit's keys (Supabase, Anthropic, Buffer).
  It has its own image (`release.yml` from tags `deploybot/vX.Y.Z`), namespace and store.
- **Code:** `app/main.py` connects and hands each command to `app/commands.py`, which decides
  who may run it and what the reply says, without Slack (tested on its own). `app/github.py`
  is the GitHub client; `app/config.py` the settings.

## Who may run what

A command counts only from our workspace (`SLACK_TEAM_ID`) in #aipostit-deploys
(`SLACK_CHANNEL_ID`), so everyone there sees every action. Anywhere else the person gets a
private "works only in #aipostit-deploys". `status` is for anyone in the channel and its reply
goes to the channel. Anything else gets the help, privately.

## GitHub: its own App, least privilege

deploybot is the GitHub App **deploybot** (not the release app), installed on this repository
only, with repository permissions **Contents: read** and **Actions: read and write**, and
nothing else. For each call it signs a JWT (RS256, its client ID as issuer, under 10 minutes)
and asks for an installation token (1 hour, never stored) scoped to this repository and to the
permissions that call needs: `status` asks for Contents: read only. Without Contents write or
Pull requests it can't push, open, approve or merge anything: every deploy PR is opened by a
workflow with the release app's token, and prod's still waits for a person.

## status

Reads `apps/aipostit/deploy/envs/staging.yaml` and `prod.yaml` on `main` and reports the
version on each one's digest line (the line `.github/scripts/deploy-pr.sh` writes), or a short
digest when a hand edit left no version. That is what main says Argo CD deploys, not what the
pods run this minute: the bot has no access to the cluster's API.
