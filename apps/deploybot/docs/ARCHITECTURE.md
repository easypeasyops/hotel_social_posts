# deploybot architecture

deploybot answers the `/aipostit` slash command in Slack's #aipostit-deploys. It is the second
phase of Slack deploys (the first posts each release and deploy step through an incoming
webhook: aipostit's `docs/ARCHITECTURE.md`, Release and deploy). It reports what staging and
prod run, and runs aipostit's release steps by starting this repo's workflows, which open the
PRs as they do from Actions:

| Command | Workflow | What follows |
|---|---|---|
| `status` | none | which release staging and prod run (below) |
| `release patch\|minor` | `bump.yml` | the bump PR, auto-merged once `ci` is green; the release then reaches staging |
| `promote` | `promote.yml` | the PR giving prod staging's digest, which waits for a person |
| `rollback staging\|prod` | `rollback.yml` | the PR giving that env the release before the one it runs; staging's merges itself, prod's waits for a person |

## Shape

- **Socket Mode.** The cluster runs on a laptop, so Slack can't reach it. The bot opens an
  outbound WebSocket to Slack instead (`slack_bolt`'s `SocketModeHandler`, the app-level token
  `SLACK_APP_TOKEN`). Nothing connects to it but the kubelet's probes on port 8000
  (`app/health.py`): `/healthz` while the process runs, `/readyz` while the Slack connection
  is up. The platform's service chart probes every app there; no Gateway route.
- **A separate app, not part of aipostit's release.** A tool that rolls aipostit back must not
  be rolled back with it, and it has no use for aipostit's keys (Supabase, Anthropic, Buffer).
  It has its own image (`release.yml` from tags `deploybot/vX.Y.Z`), namespace and store.
- **Code:** `app/main.py` connects and hands each command to `app/commands.py`, which decides
  who may run it and what the reply says, without Slack (tested on its own). `app/github.py`
  is the GitHub client; `app/config.py` the settings.

## Who may run what

A command counts only from our workspace (`SLACK_TEAM_ID`) in #aipostit-deploys
(`SLACK_CHANNEL_ID`), so everyone there sees every action. Anywhere else the person gets a
private "works only in #aipostit-deploys". `status` is for anyone in the channel. `release`,
`promote` and `rollback` are only for the Slack user IDs in `ALLOWED_USERS`; anyone else is
refused privately and nothing starts. When one starts, the reply goes to the channel and names
who asked; the workflow gets their Slack name as `requested_by` (their user ID when the name
holds characters the workflows refuse), which the PR then shows. Anything the bot doesn't
know gets the help, privately. There is no confirmation step: every command only opens a PR
or reads, and a prod PR still needs a review in GitHub.

## GitHub: its own App, least privilege

deploybot is the GitHub App **deploybot** (not the release app), installed on this repository
only, with repository permissions **Contents: read** and **Actions: read and write**, and
nothing else. For each call it signs a JWT (RS256, its client ID as issuer, under 10 minutes)
and asks for an installation token (1 hour, never stored) scoped to this repository and to the
permissions that call needs: `status` asks for Contents: read only, a command for Actions:
write only. The client starts only `bump.yml`, `promote.yml` and `rollback.yml`, on `main`,
and refuses any other before asking for a token. Actions write would also let a stolen key
re-run or cancel runs or start another manual workflow; none of ours merges into prod.
Without Contents write or Pull requests it can't push, open, approve or merge anything: every
deploy PR is opened by a workflow with the release app's token, and prod's still waits for a
person.

## status

Reads `apps/aipostit/deploy/envs/staging.yaml` and `prod.yaml` on `main` and reports the
version on each one's digest line (the line `.github/scripts/deploy-pr.sh` writes), or a short
digest when a hand edit left no version. That is what main says Argo CD deploys, not what the
pods run this minute: the bot has no access to the cluster's API.
