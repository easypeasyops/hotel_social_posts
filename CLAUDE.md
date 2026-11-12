# Working on hotel_social_posts

This repo holds the hotel social posts domain's apps under `apps/<app>/` (platform plan 3.5);
aipostit is `apps/aipostit/`, and deploybot, its `/aipostit` Slack command, is `apps/deploybot/`.
Run an app's commands from its folder. `.github/`,
`platform.lock` and this file are at the repo root.

## Docs are part of the change

Each app's `docs/ARCHITECTURE.md` (how and why it works) and `docs/RUNBOOK.md` (how to
operate it) must stay true: a PR that changes behaviour they describe updates them in the
same PR.

## Conventions

- `uv run pytest`; CI enforces the coverage minimum in `.github/workflows/ci.yml`, raised as
  tests are added, up to the platform's 90.
- Dependencies live in `pyproject.toml` and `uv.lock`: change them together.
- Secrets never go into git. An app reads its keys from the environment: locally a `.env`
  (ignored by git and by `.dockerignore`), in the cluster the platform's secret store.
- The platform (reusable workflows, chart, policies) lives in easypeasyops/platform; this
  repo uses it at the commit `platform.lock` names, and `ci.yml` pins the same SHA. Move
  both in a PR of their own.

## Pull requests opened by Claude

- **No tool attribution in PR descriptions** (Emrah, 2026-10-29): no "Generated with/by
  Claude Code" line, no claude.ai session link, no `---` separator for one. The description
  ends with its last point. (The session's GitHub connection may append its own footer when
  it writes a PR; that one is outside the session's control.)
- Each description starts with its repo, its place in the stack and what it waits on.
- **One problem per PR, small enough to review in one sitting**: aim for about 200 changed
  lines (a sweet spot, not a hard limit). Generated or mechanical changes (`uv.lock`, a
  formatter's output) don't count, but say so in the description.
- A bigger change goes in as a stack, each PR leaving `main` working and CI green on its own.
- A refactor and a behaviour change never share a PR.
- **Auto-merge everything but production** (Emrah, 2026-11-08): turn on auto-merge (squash)
  when opening a PR, code, CI and docs alike; it merges once CI is green, and a release
  still reaches staging the usual way (bump → tag → staging). Production needs Emrah's
  approval, so never auto-merge a PR that changes an `apps/<app>/deploy/envs/prod.yaml`
  (prod's image, settings or alert rules). PRs in easypeasyops/platform reach prod as soon
  as they merge: Emrah merges those too.
