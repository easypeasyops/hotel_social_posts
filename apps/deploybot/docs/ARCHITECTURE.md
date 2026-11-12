# deploybot architecture

deploybot answers the `/aipostit` slash command in Slack's #aipostit-deploys. It is the second
phase of Slack deploys (the first posts each release and deploy step through an incoming
webhook: aipostit's `docs/ARCHITECTURE.md`, Release and deploy). This version connects and
answers with its help; `status`, `release`, `promote` and `rollback` come next, the last three
by starting a workflow in this repo.

## Shape

- **Socket Mode.** The cluster runs on a laptop, so Slack can't reach it. The bot opens an
  outbound WebSocket to Slack instead (`slack_bolt`'s `SocketModeHandler`, the app-level token
  `SLACK_APP_TOKEN`) and serves nothing: no port, no Gateway route.
- **A separate app, not part of aipostit's release.** A tool that rolls aipostit back must not
  be rolled back with it, and it has no use for aipostit's keys (Supabase, Anthropic, Buffer).
  It has its own image (`release.yml` from tags `deploybot/vX.Y.Z`), namespace and store.
- **Code:** `app/main.py` connects and hands each command to `app/commands.py`, which decides
  who may run it and what the reply says, without Slack (tested on its own); `app/config.py`
  holds the settings.

## Who may run what

A command counts only from our workspace (`SLACK_TEAM_ID`) in #aipostit-deploys
(`SLACK_CHANNEL_ID`), so everyone there sees every action. Anywhere else the person gets a
private "works only in #aipostit-deploys". In the channel, for now, everyone gets the help,
privately.
