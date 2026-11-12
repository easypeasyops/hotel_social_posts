# Operations Runbook

## Scope

This runbook covers local startup, deployment checks, common incidents, and recovery for the current FastAPI/Celery application. It assumes access to the cluster (`kubectl`, Argo CD), the Supabase project and the provider dashboards. Never paste secrets into tickets, logs, or command output.

## Service topology

- **API:** FastAPI/Uvicorn web service. Liveness is `GET /healthz`, readiness `GET /readyz` (Redis answers).
- **Worker:** Celery process using the same application image, with its own command (the chart's `workers.worker`).
- **Redis:** Celery broker/result backend and operator session store.
- **Supabase:** Postgres, Auth, the private `hotel-assets` Storage bucket (uploads) and the public `published-media` bucket (images being posted).
- **External providers:** Anthropic, DeepL, and Buffer.
- **Cron:** the cluster's `generate-weekly`, `sync-buffer`, `purge-invites` and `purge-photos` CronJobs (below). Railway ran the app and its cron until plan 5.9.
- **In the cluster (from plan 5.9):** the same pieces from `deploy/` (ARCHITECTURE, In the cluster): API and worker Deployments, the Redis StatefulSet, the `generate-weekly` CronJob (Mondays 06:00 UTC, prod only: staging shares prod's Supabase). Run it now: `kubectl -n aipostit-prod create job generate-now --from=cronjob/aipostit-generate-weekly`; in staging, queue one hotel with `POST /internal/jobs/generate/<hotel_id>`. The `sync-buffer` CronJob (hourly at :15, prod only) marks drafts Buffer has sent `published` and those it couldn't send `failed`; run it now with `kubectl -n aipostit-prod create job sync-now --from=cronjob/aipostit-sync-buffer`. The `purge-invites` CronJob (daily at 03:45 UTC, prod only; one run covers staging's rows too) deletes staff invites that ended longer ago than their hotel keeps them (`python -m app.jobs.purge_invites`, in the Job's own pod, not through the worker); run it now with `kubectl -n aipostit-prod create job purge-now --from=cronjob/aipostit-purge-invites`, then `kubectl -n aipostit-prod logs job/purge-now` says `Purged N ended invites across M hotels`. The `purge-photos` CronJob (daily at 04:30 UTC, prod only) deletes the profile photos no one can see any more and the logos of deleted hotels (Security and data handling); run it now with `kubectl -n aipostit-prod create job purge-photos-now --from=cronjob/aipostit-purge-photos`. Its keys come from the platform's store: `platform/scripts/load-app-env.sh aipostit .env`. The cluster's copy (the ExternalSecret `aipostit-env`) refreshes only hourly, so make it copy now and check the key names before restarting, or the pods restart with the old keys:

```sh
kubectl -n aipostit-<env> annotate externalsecret aipostit-env force-sync=$(date +%s) --overwrite
kubectl -n aipostit-<env> get externalsecret aipostit-env   # STATUS SecretSynced, a fresh refresh
kubectl -n aipostit-<env> get secret aipostit-env -o json | jq '.data | keys'   # names only
kubectl -n aipostit-<env> rollout restart deployment
```

## Prerequisites and configuration

Before starting the app, provision Supabase and Redis, create the `hotel-assets` Storage bucket, apply the migrations in `supabase/migrations/` in order (`002` creates the public `published-media` bucket, `003` the `hotel_members` table for hotel staff, `004` its `role` column, `005` the assets' `thumbnail_path`, `006` the `staff_invites` table and `hotels.invite_retention_days`, `007` `hotels.logo_version`), and configure provider credentials.

Set the following environment variables in the local `.env`; in the cluster they come from the platform's store, loaded from that file (below):

```dotenv
SECRET_KEY=
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
ANTHROPIC_API_KEY=
DEEPL_API_KEY=
BUFFER_ACCESS_TOKEN=
CRON_SECRET=
REDIS_URL=redis://localhost:6379/0
SESSION_COOKIE_SECURE=true
PUBLIC_BASE_URL=http://localhost:8000
```

The blank values above are placeholders; supply secrets through your secret manager. `REDIS_URL` defaults to the local URL shown. `SESSION_COOKIE_SECURE=false` is required wherever the front door is plain HTTP: local development, and the kind cluster for now (both environments set it false in `deploy/envs/`). Keep it true wherever the front door is HTTPS. `CLAUDE_DRAFT_MODEL` and `CLAUDE_PREMIUM_MODEL` are optional. Keep the Supabase service-role key server-side only; it bypasses row-level security.

Create operator accounts through the Supabase Auth administration process. The application provides password sign-in (and Google, when enabled) plus a forgot-password flow, but does not provide sign-up or MFA. An account reaches the dashboard and the operator API only with the operator role, which you set by hand. Staging and prod share one Supabase project, so this covers both. In the Supabase **SQL editor**:

```sql
update auth.users
set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role": "operator"}'
where email in ('operator@example.com');
```

Remove the role with `raw_app_meta_data - 'role'`. The app reads the role from Supabase on every request, so either change applies at once with no new sign-in. Run the update for every existing operator **before** deploying a version with the role check: without it they get "This account doesn't have access to aipostit." To list the operators: `select email from auth.users where raw_app_meta_data->>'role' = 'operator';`. A new operator is asked for their full name the first time they open the dashboard; set it ahead with `raw_user_meta_data || '{"full_name": "Ad Soyad"}'` if you like.

Hotel staff are accounts without the operator role that belong to one hotel. They sign in at the same `/login` and land on `/hotel`, which shows their hotel's files (photos as thumbnails that open full size; files no draft has taken to Buffer can be renamed, recategorized or deleted), lets them upload more, and links to the drafts waiting for review (`/hotel/drafts`), which they can edit (text and photos), approve (published as from the dashboard), reject or delete. What they may do depends on their role in `hotel_members.role`: `hotel_admin` and `content_moderator` do all of that; a `content_creator` uploads and sees the files and drafts, without the buttons that change or decide them. Change a member's role with the role menu and **Change** next to their email in the hotel's "Hotel staff" section. A hotel's admins do the same themselves on `/hotel/staff` (**Ekip** on `/hotel`): invites (**Davet gönder**, the same form as the dashboard's), role changes and removal, for everyone but themselves. So the operator usually only invites the hotel's first admin. Hotel admins also keep the hotel's name, location, contact email, description and channels up to date on `/hotel/details` (**Otel bilgileri**); the slug, tier and Buffer profiles stay on the dashboard. Both that page and the dashboard's hotel edit form set how many days an ended invite (accepted, revoked or expired), with its email, is kept: 7 to 180, 90 by default. The daily `purge-invites` CronJob deletes the invites past it, never a pending one (Service topology above). To invite staff, open the hotel on the dashboard, enter the person's email, the role (hotel admin by default) and how many days the invite lasts (7 by default, 1 to 30), and use **Send invite**. The invite is recorded in `staff_invites` (so migration `006` must be applied first) and works once, only for that address. With SMTP set up it's emailed; either way the page says whether it went and offers **Copy invite link**, to send it yourself if the email wasn't sent. The page updates in place, without reloading. The person opens it, sets a password, and lands on `/hotel`. To see who you invited, look at **Invites** under the hotel's staff (**Davetler** on `/hotel/staff` for its admin): each invite's status (pending, accepted with its date, expired or revoked), "email not sent" on a pending one never emailed, and on a pending one **Copy invite link** (**Bağlantıyı kopyala**), to send it another way. On both pages the pending invites come first and the ended ones are folded under **Ended invites**. To revoke an invite, use **Revoke** on its row (**İptal et** on `/hotel/staff`; a hotel admin can revoke the operator's invites too): it stops working at once, and `/signup` calls its link invalid or expired. Invites made before they were recorded aren't listed and can't be revoked; they run out within 7 days. Links made before this (the older **Create staff invite link**, usable by several people) keep working until they expire, and only rotating `SECRET_KEY` revokes one early (which also ends every upload link). An email that already has an account can't sign up again; to add an existing account to a hotel, or to make staff by hand, create the user in Supabase **Authentication → Users → Add user** (with a password, auto-confirmed) if needed, then in the SQL editor:

```sql
insert into hotel_members (user_id, hotel_id, email, role)
select u.id, h.id, u.email, 'content_creator' from auth.users u, hotels h
where u.email = 'staff@example.com' and h.slug = 'the-hotel-slug';
```

The role is one of `hotel_admin`, `content_moderator` or `content_creator`; it applies on the person's next request. To change it without the dashboard:

```sql
update hotel_members set role = 'content_moderator'
where email = 'staff@example.com';
```

Staff roles need migration `004`. Run it in the SQL editor **before** deploying a version with roles (a version without the column refuses every staff page); it is safe for the version already running, whose new staff rows get the default `hotel_admin`. Every existing staff account becomes `hotel_admin`, which keeps what it can do today:

```sql
alter table hotel_members
  add column role text not null default 'hotel_admin'
  check (role in ('hotel_admin', 'content_moderator', 'content_creator'));
```

Photo thumbnails need migration `005`. Run it in the SQL editor **before** deploying a version that makes thumbnails (that version's worker fails every photo without the column); it is safe for the version already running, which doesn't select or write it:

```sql
alter table assets add column thumbnail_path text;
```

Photos uploaded before thumbnails existed (before 0.3.7) have none, so the pages load them full size. To make theirs, run the backfill task once from prod's worker (staging and prod share the Supabase project, so once covers both):

```bash
kubectl -n aipostit-prod exec deploy/aipostit-worker -- celery -A app.jobs.tasks.celery_app call tasks.backfill_thumbnails
```

It queues the task and prints its ID; the worker log then says `Made N thumbnails`. It only touches `ready` JPEGs and PNGs with no `thumbnail_path`, so running it again does only what's left. A photo it can't read is logged (`is not a photo Pillow can open`, or `Could not make a thumbnail`) and skipped: it stays `ready` and keeps showing full size.

Hotel logos need migration `007` (applied to the shared project on 2026-11-09). Run it in the SQL editor **before** merging the version bump of any release that sets logos (without the column, an upload fails and a hotel's pages can't record its logo); it is safe for the version already running, which neither selects nor writes it. Staging and prod share the project, so once covers both:

```sql
alter table hotels add column logo_version bigint;
```

Staff invite tracking needs migration `006` (applied to the shared project on 2026-11-09). Run `supabase/migrations/006_staff_invites.sql` in the SQL editor **before** merging the version bump of any release that reads or writes invites: staging and prod share the Supabase project, and a merged bump reaches staging on its own. It only adds a table and a column with a default, so it is safe for the version already running, which uses neither. The dashboard's **Send invite** and `/hotel/staff`'s **Davet gönder** write to `staff_invites`, so `006` must be applied before the release that contains it reaches staging; without it every invite fails.

To take someone's access away, use **Remove** next to their email in the hotel's "Hotel staff" section (or delete their `hotel_members` row). It takes effect on their next request. Their Supabase account stays, with no access; delete it in **Authentication → Users** if it shouldn't exist at all. Set `PUBLIC_BASE_URL` to the exact app origin used in browser (no trailing slash required).

In Supabase **Authentication → URL Configuration**, set the Site URL to the app origin and add the callback URL to the redirect allow list:

- Local: Site URL `http://localhost:8000`; redirect URL `http://localhost:8000/auth/callback`
- Deployed: use the HTTPS app origin and add `<PUBLIC_BASE_URL>/auth/callback`

Keep the Supabase password-recovery email template configured to redirect to the provided redirect URL. Supabase must allow the callback URL or it may fall back to the Site URL.

In Supabase **Authentication → Sign In / Providers**, keep **Allow new users to sign up** off. The app never needs Supabase to create users on its own, and Google sign-in relies on this setting to stay limited to existing accounts.

### Staff invite emails (Gmail SMTP)

With an SMTP password, the dashboard's **Send invite** and `/hotel/staff`'s **Davet gönder** also email the invite they record, which only that address can use. Without one, they still record the invite and show its link, marked "email not sent". The app sends through one Gmail account for now:

1. Use a Google account for aipostit with 2-Step Verification on. In [Google Account → Security → App passwords](https://myaccount.google.com/apppasswords), create an app password named aipostit.
2. In `.env`, set `SMTP_USERNAME=<the gmail address>` and `SMTP_PASSWORD=<the 16-character app password>`. `SMTP_HOST` and `SMTP_PORT` default to `smtp.gmail.com` and 587. Gmail sends as the account itself, so leave `MAIL_FROM` empty unless it's an alias verified in Gmail.
3. Restart the API and send an invite to yourself from a test hotel.

In the cluster the keys come from the platform's store like the others. That script replaces the whole store with the file's keys, so add `SMTP_USERNAME` and `SMTP_PASSWORD` to the same `.env` that holds all of aipostit's keys, then run `platform/scripts/load-app-env.sh aipostit ../hotel_social_posts/apps/aipostit/.env` from the platform checkout and check that the printed key list includes both. Make the cluster copy them now (the `force-sync` annotation in "Service topology" above) and check `aipostit-env` lists both before going on. Then set `config.inviteEmail: "true"` in the environment's `deploy/envs/` values, which hands the two keys to the pods; the network policy already allows port 587 out. Never set it before the keys are in the store: a pod whose env names a missing key doesn't start. Gmail allows about 500 recipients a day and may file the first emails as spam: tell the recipient to look there. If a send fails, the invite stays recorded as "email not sent" with its link on the page, and the API log has the SMTP error ("The staff invite email could not be sent"); an `SMTPAuthenticationError` means the app password was revoked or mistyped.

### Google sign-in

The **Continue with Google** button shows only when `GOOGLE_SIGN_IN=true` (deploy value `config.googleSignIn`, per environment in `deploy/envs/`). Set it up once; staging and prod share the Supabase project, so they share the provider:

1. In [Google Cloud console](https://console.cloud.google.com/) → **APIs & Services → OAuth consent screen**: user type External, app name aipostit, your support email. Scopes: `openid`, `email`, `profile` only. Publish the app (in Testing, only listed test users can sign in).
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type Web application. Under **Authorized redirect URIs** add Supabase's callback, shown on the Supabase Google provider page: `https://<project-ref>.supabase.co/auth/v1/callback`. Google sends people back to Supabase, not to the app, so no app URL goes here.
3. In Supabase **Authentication → Sign In / Providers → Google**: enable it and paste the client ID and client secret. Keep the secret out of git; it lives only in Supabase.
4. In Supabase **Authentication → URL Configuration → Redirect URLs**, add each origin's Google callback next to `/auth/callback`:
   - Local: `http://localhost:8000/auth/callback/google`
   - Staging: `http://staging.aipostit.localhost:8080/auth/callback/google`
   - Prod: `http://aipostit.localhost:8080/auth/callback/google` (the HTTPS origin once prod has one)
5. Set `GOOGLE_SIGN_IN=true` (`.env` locally; `config.googleSignIn: "true"` in the environment's values) and redeploy.

Check it: an operator whose account email is the Google address signs in and lands on the hotel list. A Google address without an account sees "There's no aipostit account for that Google address", and no user appears in Supabase **Authentication → Users**. To turn it off, set `GOOGLE_SIGN_IN=false`; Google identities already linked stay in Supabase, harmlessly.

## Local startup

From the project root:

```sh
docker compose up --build
```

This starts the API, worker, and Redis. The API listens on port `8000`; its code reloads as the source directory is mounted. Confirm basic process liveness:

```sh
curl --fail http://localhost:8000/healthz
curl --fail http://localhost:8000/readyz   # 503 until Redis answers
```

Expected response:

```json
{"status":"ok"}
```

This check does **not** verify Supabase, Redis, or provider connectivity. In local debug mode, `/docs` is available only if `DEBUG=true`. To stop local services, use `Ctrl+C` in the compose session.

Open `http://localhost:8000/login` to sign in with a provisioned Supabase Auth operator account using a password or, with `GOOGLE_SIGN_IN=true`, Google. Use **Forgot password?** (`/forgot-password`) to request a reset email; the recovery link opens a password form valid for 15 minutes. The application stores browser and recovery sessions in Redis, so local auth requires the compose Redis service. From the hotel dashboard, create or edit a hotel and generate its 24-hour upload link. For local HTTP, configure `SESSION_COOKIE_SECURE=false` in `.env` and restart the API.

## Development checks

Dependencies are in `pyproject.toml`, pinned with hashes in `uv.lock`; the Docker image installs exactly the lock. From `apps/aipostit/`, with [uv](https://docs.astral.sh/uv/):

| Step | Command |
| --- | --- |
| Install exactly the locked dependencies | `uv sync --locked` |
| Format and lint | `uv run ruff format .` and `uv run ruff check .` |
| Type check | `uv run mypy app tests` |
| Tests (no `.env` needed: they use placeholders) | `uv run pytest` |
| The image, black-box (non-root, probes, JSON logs, metrics, clean SIGTERM exit) | `docker build -t aipostit:dev . && scripts/smoke.sh` |

Change a dependency with `uv add <package>==<version>` (or edit `pyproject.toml`, then `uv lock`) and commit both files. CI runs the same commands on every pull request (`.github/workflows/ci.yml` at the repo root, through the platform's reusable workflows); a pull request is ready to merge when its `ci` check is green. Code that came in with the import still has inline `noqa` markers and modules listed under mypy's overrides in `pyproject.toml`: they come off as the code is fixed and typed.

## Cut a release

A release is an image built, scanned and signed by `.github/workflows/release.yml` from a tag `aipostit/vX.Y.Z` that matches `version` in `apps/aipostit/pyproject.toml`. Only such images run in the cluster: the platform's admission policy and deploy gate require this workflow's provenance at this app's tag.

1. Bump `version` in `pyproject.toml` (and the same line in `uv.lock`), in the feature's PR or one of its own, and merge it. For a bump on its own: `/aipostit release patch` (or `minor`) in #aipostit-deploys, **Actions → Bump version → Run workflow**, or `gh workflow run bump.yml -f part=patch`, which opens the PR "aipostit X.Y.Z" with auto-merge on and posts it to #aipostit-deploys; it refuses a version already tagged. `.github/workflows/tag-release.yml` tags the merge commit `aipostit/vX.Y.Z`, which starts the release. (By hand, if that workflow can't: `git tag aipostit/vX.Y.Z <merge commit> && git push origin aipostit/vX.Y.Z`; release tags can't be moved.)
2. Merging a bump deploys to staging with no further step (below), so apply a migration the new version needs **before** merging it.
3. The workflow builds `linux/amd64` and `linux/arm64`, scans for HIGH and CRITICAL vulnerabilities before anything is published, pushes `ghcr.io/easypeasyops/hotel_social_posts/aipostit`, attests its provenance and creates a GitHub Release whose notes give the digest. A tag that disagrees with `pyproject.toml` fails before publishing.
4. The first release creates the GHCR package as private: make it public (package settings) so the cluster can pull it without credentials.
5. Check the provenance: `gh attestation verify oci://ghcr.io/easypeasyops/hotel_social_posts/aipostit@<digest> --owner easypeasyops`.
6. The workflow then opens the staging deploy PR (`.github/scripts/deploy-pr.sh`), which merges itself when `ci` is green; Argo CD deploys it. Check staging, then promote: `/aipostit promote` in #aipostit-deploys, **Actions → Promote to prod → Run workflow**, or `gh workflow run promote.yml` opens the PR that gives prod staging's digest. Review and merge it yourself.
7. #aipostit-deploys follows each step (below): the release built or failed, each environment's new version once its deploy PR merges (staging's message links **Promote to prod**), and the prod PR waiting for your review.

The tag, the deploy PRs and their commits are made by the release GitHub App, because what the workflows' own `GITHUB_TOKEN` makes starts no other workflow (no release, no `ci` on a PR). Set it up once:

1. Create a GitHub App in the easypeasyops organization (Settings → Developer settings → GitHub Apps): no webhook, repository permissions **Contents: read and write** and **Pull requests: read and write**, installable only on this account. Install it on `hotel_social_posts` only.
2. In this repo's Settings → Secrets and variables → Actions, add the variable `RELEASE_APP_CLIENT_ID` (the app's Client ID) and the secret `RELEASE_APP_PRIVATE_KEY` (a private key generated on the app's page).
3. Turn on **Allow auto-merge** (Settings → General), which the staging PR needs.

If a workflow fails at "create-github-app-token", one of those is missing or the key was revoked: generate a new key and replace the secret.

### Deploy messages in Slack

`release.yml`, `promote.yml` and `deploy-notice.yml` (a merge that changes an image digest in `deploy/envs/<env>.yaml`, a hand rollback too) post to #aipostit-deploys through `.github/scripts/slack-notify.sh`. Alerts stay in the #aipostit-alerts-* channels. A message reports that a deploy PR merged; whether Argo CD synced it shows in the alert channels. Set it up once:

1. Create the channel #aipostit-deploys, then the Slack app **aipostit-deploys** (api.slack.com/apps → From scratch). It is its own app, apart from the alerts' app (aipostitalerts, whose webhooks the platform holds) and from deploybot's: messages carry the app's name, and each can be reinstalled or removed without touching the others.
2. Turn on **Incoming Webhooks** and **Add New Webhook to Workspace** for #aipostit-deploys. That asks for the one scope it needs, `incoming-webhook`; add no bot or user scopes.
3. Copy the webhook URL (Incoming Webhooks → Copy) and store it as the Actions secret `SLACK_DEPLOYS_WEBHOOK_URL`, from the clipboard so it stays out of shell history: `pbpaste | gh secret set SLACK_DEPLOYS_WEBHOOK_URL --repo easypeasyops/hotel_social_posts` (or Settings → Secrets and variables → Actions → New repository secret). `gh secret set`'s own hidden prompt may not take a paste and then waits forever: stop it with Ctrl+C and pipe instead. Setting it again replaces it.
4. Check: `gh secret list --repo easypeasyops/hotel_social_posts` shows it, and with the URL still on the clipboard `curl -fsS -H 'Content-Type: application/json' --data '{"text":"aipostit-deploys test"}' "$(pbpaste)"` answers `ok` and posts to the channel.

Slack never fails a workflow: without the secret, or when the post fails, the step only warns ("nothing posted to Slack", "the Slack post failed"). If messages stop, look for that warning in the run, then replace the webhook (a revoked one answers 403/404).

### From Slack

In #aipostit-deploys, `/aipostit status` says which release staging and prod run, and `/aipostit release patch|minor`, `promote` and `rollback staging|prod` start the same workflows as above, for the users deploybot allows. They only open PRs: prod's still wait for your review in GitHub. deploybot is its own app (`apps/deploybot/`, its RUNBOOK): if it doesn't answer, use Actions.

## Deployment and release checklist

1. Confirm required settings exist for both the API and worker services; the worker needs `REDIS_URL` and all provider/Supabase settings used by its tasks.
2. Apply any new Supabase migration deliberately before deploying code that depends on it. The application does not migrate the database at startup.
3. Ensure the `hotel-assets` bucket exists and its upload policies match the signed-upload flow, and that the `published-media` bucket exists and is public (migration `002`); without it, publishing fails on the image copy.
4. Deploy by digest: a release opens and merges the PR that sets `image.digest` in `deploy/envs/staging.yaml` (Argo CD deploys it on merge); check staging, then run **Promote to prod**, which opens the PR with the same digest in `deploy/envs/prod.yaml`, and merge it. Editing those files in a PR by hand still works, as for a rollback.
5. The worker deploys with the API: the chart's `workers.worker` runs the same image with `celery -A app.jobs.tasks.celery_app worker --loglevel=info --concurrency=2`.
6. Verify the API and worker logs (`kubectl -n aipostit-<env> logs deploy/aipostit` and `deploy/aipostit-worker`), then `GET /readyz` through the Gateway.
7. Verify a protected job trigger only in a controlled environment and ensure it is not exposed with the cron secret in logs or shell history.
8. Weekly generation is the `generate-weekly` CronJob in prod, the Buffer sync the hourly `sync-buffer` one, the invite purge the daily `purge-invites` one, the photo purge the daily `purge-photos` one (`deploy/service/values.yaml`); nothing to configure outside this repository.
9. For release validation, confirm a test hotel can create a draft, persist translations, and schedule an approved draft without sending unintended production posts.

## Routine operational checks

- Check the API and worker logs (`kubectl -n aipostit-<env> logs`) for startup errors, repeated task retries, or task failures.
- Check Redis availability and the worker's ability to consume jobs if tasks remain queued.
- Check Redis availability for operator sessions as well as Celery; login and authenticated dashboard/API requests require it.
- Check Supabase database and Storage health, and confirm the `hotel-assets` bucket is reachable.
- Check Anthropic, DeepL, and Buffer provider status and credentials when only one pipeline stage is failing.
- Review draft statuses in `content_drafts`, asset statuses in `assets`, and Buffer submission records in `publish_log`.
- For multilingual hotels, verify each expected row exists in `content_translations`; translation tasks can succeed with some languages missing.

## Reading the logs

The API and the worker log one JSON object per line to stdout (set `LOG_JSON=false` locally for plain lines). Every line a request logs carries its `request_id`, which is also the response's `X-Request-ID` header: ask a user for it, or take it from the access line (`"logger": "aipostit.access"`, with `route`, `status` and `duration_ms`).

```sh
# Everything one request logged
docker compose logs api | grep '"request_id": "<id>"'
# Server errors with their routes
docker compose logs api | grep -o '{.*' | jq -c 'select(.status >= 500) | {ts, route, status, request_id}'
# Translations that failed, by language
docker compose logs worker | grep -o '{.*' | jq -c 'select(.msg == "translation failed") | {draft_id, language, error}'
```

In the cluster, the same with `kubectl` (add `--since=1h` to narrow; each API pod logs its own requests, so read them all):

```sh
kubectl -n aipostit-<env> logs -l app.kubernetes.io/name=aipostit --prefix --tail=-1 | grep '"request_id": "<id>"'
kubectl -n aipostit-<env> logs -l app.kubernetes.io/name=aipostit --tail=-1 | grep -o '{.*' | jq -c 'select(.status >= 500) | {ts, route, status, request_id}'
kubectl -n aipostit-<env> logs deploy/aipostit-worker | grep -o '{.*' | jq -c 'select(.msg == "translation failed") | {draft_id, language, error}'
```

`kubectl logs` shows only what the running pods (and each one's previous container) wrote. The platform keeps every pod's lines for 30 days in VictoriaLogs (platform `docs/RUNBOOK.md`, Logs), so a pod that was replaced by a release or a crash can still be read: in Grafana (http://grafana.localhost:8090), Explore, data source **VictoriaLogs**. Each JSON field of a line is a field there (`msg` is `_msg`, `ts` is `_time`); the queries are LogsQL, and the time range comes from Grafana's picker:

```
# Everything one request logged
{kubernetes.pod_namespace="aipostit-prod"} request_id:="<id>"
# Server errors with their routes
{kubernetes.pod_namespace="aipostit-prod"} logger:="aipostit.access" status:>=500 | fields _time, route, status, request_id
# Translations that failed, by language
{kubernetes.pod_namespace="aipostit-prod"} "translation failed" | fields _time, draft_id, language, error
# What the worker did
{kubernetes.pod_namespace="aipostit-prod", kubernetes.container_name="worker"} | fields _time, level, logger, _msg
```

`aipostit-staging` for staging; `{kubernetes.pod_namespace=~"aipostit-.+"}` for both. If Grafana is away, the store answers the same queries itself (platform RUNBOOK, Logs), and `kubectl logs` still works for the pods that run.

## Reading the metrics

The API serves Prometheus metrics on port 9100 (`METRICS_PORT`), not on its public port: `curl -s localhost:9100/metrics | grep ^http_`. Per route template and status: `http_requests_total` counts requests and `http_request_duration_seconds` buckets their latency. A rising `status="5.."` count on one route points at that route's dependency; `route="unmatched"` is requests for paths the app doesn't have.

The job queue is there too (`grep ^celery_`), read from Redis by the API at each scrape: `celery_queue_length` is the tasks waiting for a worker and `celery_queue_oldest_task_age_seconds` how long the oldest has waited (0 for an empty queue, or for a task queued by a release older than the metric). Both are normally 0 or small for a minute or two; an age that keeps growing while the worker pod is Running is a worker that hangs: "Jobs are not progressing" below. In Prometheus, `max by (namespace) (celery_queue_oldest_task_age_seconds)`: every API pod reports the same queue.

## Reading the errors

Off until `SENTRY_DSN` is in the environment, and no environment has it yet: until then unhandled errors are only log lines (above). With a DSN (a Sentry or GlitchTip project's; a secret, so in `.env` locally and in the platform's store for the cluster), the API and the worker send each unhandled error and each line logged at ERROR to that project, grouped, with the stack trace. `SENTRY_ENVIRONMENT` and `SENTRY_RELEASE` name the environment and the version on each event.

An event of a request has a `request_id` tag: the same ID as the response's `X-Request-ID` header and the request's log lines, so `grep '"request_id": "<id>"'` (Reading the logs) shows what else that request did. Events carry no request body, query string, cookies, `Authorization` header or local variables, so the logs and the database are where to look for what was sent.

## Alerts

Prometheus evaluates aipostit's alert rules (`deploy/envs/prod.yaml`, `monitoring.rules`: prod's release ships them, for both environments) and Alertmanager posts them to Slack: `aipostit-prod`'s to #aipostit-alerts-prod, `aipostit-staging`'s to #aipostit-alerts-staging, with a message when each resolves. A **page** (red) is something to act on now, and in prod it notifies the channel (@channel); a **ticket** (yellow) is something to look at today. While a page fires, the tickets in the same environment are held back. Argo CD's alerts on `aipostit-<env>` come to the same channels (platform `docs/RUNBOOK.md`, Argo CD alerts). The routing, the webhooks and how to test or silence alerts are the platform's (`docs/RUNBOOK.md`, Slack alerts). Each alert's link opens its section below.

Change or add an alert in `deploy/envs/prod.yaml` with a scenario in `deploy/prometheus/alerts_test.yaml` and a section here (`tests/test_alert_rules.py` checks all three; it runs promtool in Docker). The thresholds are for low traffic: a ratio alone would fire on one failed request.

### AipostitApiDown

Page. No API pod in the environment has answered Prometheus's scrape for 5 minutes, or there is no API pod at all. Hotel staff and operators can't use the app. Follow "API health check fails" below; `kubectl -n aipostit-<env> get pods,events` first.

### AipostitHighErrorRate

Ticket. Over 5% of requests (probes left out) answered 5xx over 30 minutes, and at least 5 of them. Find the route and the cause: "Reading the metrics" (`status="5.."` by route) and "Reading the logs" (server errors with their routes) above. One route failing usually means its dependency (Supabase, a provider); every route failing, a release or configuration change: roll back as in "API health check fails".

### AipostitSlowResponses

Ticket. The API's 95th-percentile response time over 30 minutes is above 2.5 s, with at least 20 requests. Check which routes are slow (`http_request_duration_seconds` by route), then Supabase's and the providers' status. The pods' CPU and memory: `kubectl -n aipostit-<env> top pods`.

### AipostitApiNotReady

Ticket. Fewer API pods available than the environment asks for, for 15 minutes. A pod that fails `/readyz` (Redis doesn't answer) or doesn't start: `kubectl -n aipostit-<env> get pods`, then `describe pod` for its events and `logs` for its errors. Redis first if `/readyz` says `not ready: Redis`.

### AipostitWorkerDown

Page. No Celery worker pod available for 10 minutes: nothing is generated, translated, published or synced with Buffer, and queued tasks wait in Redis. `kubectl -n aipostit-<env> get pods -l app.kubernetes.io/name=aipostit-worker`, then `describe` and `logs deploy/aipostit-worker`. Then "Jobs are not progressing" below.

### AipostitRedisDown

Page. The environment's Redis (`aipostit-redis-0`) has not been ready for 5 minutes. Without it nobody can log in and no job runs; the API pods also fail `/readyz`, so their tickets are held back. `kubectl -n aipostit-<env> describe pod aipostit-redis-0` and `logs aipostit-redis-0`; its volume (`get pvc`) if it can't start.

### AipostitCrashLooping

Ticket. A container keeps exiting and Kubernetes is backing off restarting it, for 10 minutes. The alert names the pod and container: `kubectl -n aipostit-<env> logs <pod> -c <container> --previous` for why it exited. A missing key (a new setting not in the store) or a release that can't start are the usual causes; roll back a release as in "API health check fails".

### AipostitJobFailed

Ticket. A Job failed in the last 6 hours: a CronJob's run (`aipostit-sync-buffer-…`, `aipostit-generate-weekly-…`, `aipostit-purge-invites-…`, `aipostit-purge-photos-…`) or one made by hand. It resolves 6 hours after the Job started. `kubectl -n aipostit-<env> logs job/<job_name>` and `describe job/<job_name>`. The `generate-weekly` and `sync-buffer` Jobs only queue a task (`celery call`): their failure is usually Redis unreachable, not the task itself; the task's own errors are in the worker's logs. `purge-invites` does its work in the Job, so its failure is the purge's: the Job's log names each hotel it couldn't purge (`Could not purge the ended invites of hotel <id>`, with the error); the other hotels were purged. Once the cause (usually Supabase unreachable) is fixed, run it again; it only deletes what's still due. `purge-photos` works the same way: its log says how many photos' accounts Supabase couldn't be asked about (`Could not check the accounts of N profile photos`); those photos are kept and the rest deleted. Run it again as in "Service topology" above once the cause is fixed.

### AipostitWeeklyGenerationMissed

Ticket. No `generate-weekly` run has succeeded for 8 days: Monday's failed, or never started (the laptop was asleep past the CronJob's 50-minute starting deadline). Check `kubectl -n aipostit-prod get cronjob aipostit-generate-weekly` and its Jobs, then run it by hand (`kubectl -n aipostit-prod create job generate-now --from=cronjob/aipostit-generate-weekly`) and follow "Cron did not enqueue generation" below. It can't fire before the first success: the metric doesn't exist until then.

### SLO burn-rate alerts

`AipostitAvailabilityBudgetBurn` and `AipostitLatencyBudgetBurn`, each as a page and as a ticket. **Not live yet**: the rules are in this repo (`deploy/service/slo-rules.values.yaml`) and ship once the platform lists that file for prod; until then `AipostitHighErrorRate` and `AipostitSlowResponses` cover the same ground.

aipostit promises two things over 30 days (`deploy/prometheus/slos.yaml`), counted on requests to its own routes (probes and unknown paths left out), per environment: 99.5% answer without a 5xx, and 99% answer in under 2.5 s. What is left over is the error budget (0.5% and 1% of requests). An alert fires on how fast the budget is being spent, and only with at least 5 bad requests in its window, so one failure in a quiet hour stays quiet:

| Severity | Fires when the budget burns at | At that pace it is gone in |
| --- | --- | --- |
| Page | 14.4 times the allowed rate over 1 hour, or 6 times over 6 hours | 2 to 5 days |
| Ticket | 3 times over 1 day, or the allowed rate itself over 3 days | 10 to 30 days |

What to do is what the SLO measures. Availability: find the failing route and its cause as in AipostitHighErrorRate above. Latency: find the slow routes as in AipostitSlowResponses above. A burn that started with a release: roll back as in "API health check fails". The platform's SLO dashboard in Grafana (http://grafana.localhost:8090, "SLO") shows each budget, its burn rates and the traffic behind them; Prometheus keeps 10 days, so "budget remaining" covers at most the last 10 of the 30.

To change an objective, edit `deploy/prometheus/slos.yaml`, regenerate the rules with the platform's generator (the command is at the top of that file) and adjust the scenarios in `deploy/prometheus/slo_test.yaml`; CI fails on a rules file that doesn't match its spec.

## Incident procedures

### API health check fails

1. Inspect the API's logs and events (`kubectl -n aipostit-<env> describe pod`, `logs`) and recent release or configuration changes.
2. Verify required environment variables are present without printing their values.
3. Confirm the pods are Ready (`kubectl -n aipostit-<env> get pods`) and the Application is Synced and Healthy (`kubectl -n argocd get app aipostit-<env>`).
4. If the failure began with a release, roll back: `/aipostit rollback <env>` in #aipostit-deploys, **Actions → Roll back → Run workflow** with the environment, or `gh workflow run rollback.yml -f env=prod` opens the PR that gives it the release before the one it runs, by that release's digest (its notes), titled "deploy: aipostit <env> rolls back to vX.Y.Z" and posted to #aipostit-deploys. Staging's merges itself when `ci` is green; review and merge prod's yourself. Run it again to go back one more release. It refuses when no earlier `aipostit/v*` release exists or the digest line has no version (a hand edit): then put the previous digest back in `deploy/envs/<env>.yaml` by hand and merge. Rolling staging back also changes what **Promote to prod** gives prod next.
5. After recovery, check `/readyz` and perform a safe authenticated read.

Because `/healthz` is liveness-only, a successful response is not proof that dependencies are healthy. `/readyz` returns 503 `not ready: Redis` when Redis doesn't answer within 2 s: check Redis first. It doesn't cover Supabase or the providers.

### Jobs are not progressing

1. Check that the worker service is running the Celery command above and is configured with the same Redis URL as the API.
   In the cluster, ask the worker itself: the worker has no probe, so a hung Celery process looks Running and `AipostitWorkerDown` stays quiet. `kubectl -n aipostit-<env> exec deploy/aipostit-worker -- celery -A app.jobs.tasks.celery_app inspect ping --timeout 5` answers `pong` from a healthy worker; no reply means restart it (`rollout restart deployment/aipostit-worker`); its tasks wait in Redis and are redelivered.
2. Inspect worker logs for broker connection failures, task exceptions, and exhausted retries.
3. Confirm Redis reachability and inspect the queue using the service's approved operational tooling.
4. Check whether the task reached an external provider; do not blindly enqueue duplicates if a task may have completed an external action.
5. Correct the missing dependency/configuration, then retry only the affected work after checking its database and provider state.

### Asset remains pending, processing, or failed

1. Confirm Storage upload succeeded at the asset's recorded `storage_path` in `hotel-assets`.
2. Confirm the hotel upload page called `POST /api/v1/upload-capabilities/{hotel_id}/assets/{asset_id}/confirm` using an unexpired upload link, or that an operator called the protected asset endpoint.
3. Check worker logs for `process_asset` failure and confirm Redis/worker health.
4. The task makes a JPEG or PNG's thumbnail (`thumbnails/{hotel_id}/{asset_id}.webp` in `hotel-assets`) before marking it `ready`. A photo it can't open is `failed` at once, with `is not a photo Pillow can open` in the worker log: the file is broken or isn't the type its name says, so ask for it again. A missing `thumbnail_path` column (migration `005` not run) fails every photo through the retries; run the migration and re-upload. Videos are marked `ready` unchecked.
5. Avoid repeatedly confirming an asset: confirmation is guarded by the `pending` status and returns an error after the first successful confirmation.

The hotel upload page uses a short-lived, hotel-scoped capability instead of an operator credential. Ask an operator to generate a fresh link if it expires. The capability authorizes uploads and confirmation for one hotel only; it does not authorize listing or deleting media.

### Draft generation or translation is incomplete

1. Check the `generate_content` and `translate_content` task logs and the Anthropic/DeepL service status.
2. Confirm the hotel exists, has a valid tier, and has the expected channels. Generation can operate with no ready assets, using the hotel description only.
3. Inspect `content_drafts` and `content_translations` before rerunning. Generation retries after partial completion may have already created drafts.
4. Translation can skip individual failed languages while the overall task completes; retry or repair only missing translations using the project's approved procedure.
5. Every language failing with `403 Forbidden` from DeepL means it refused the key: check `DEEPL_API_KEY` and that it is a Free-plan key (the app calls `api-free.deepl.com`). The key travels in the `Authorization: DeepL-Auth-Key …` header; DeepL refuses it in the request body since 2026-01-15, which broke every translation until this was fixed (2026-11).

### Buffer scheduling failure or possible duplicate

1. Inspect the draft status, its `publish_log` rows, worker logs, and Buffer queue before retrying.
2. Verify the hotel has a `buffer_profiles` entry for the draft's network and that it is a Buffer **channel ID** (list them with the `channels` query in the [Buffer API Explorer](https://developers.buffer.com/explorer.html)). Verify `BUFFER_ACCESS_TOKEN` is a current Buffer API key (Settings → API; keys expire). The worker log's `BufferError` names the cause: `UNAUTHENTICATED: Access token is not valid` (the key is wrong, expired or revoked, or isn't a GraphQL API key: create one under Settings → API → Personal Access, with posting permission), `UNAUTHORIZED` or `FORBIDDEN` (the key lacks a permission), `NOT_FOUND` (channel ID), or Buffer's message for a typed error such as a full queue. To test a key from a shell, without printing it: `curl -s https://api.buffer.com -H "Authorization: Bearer $BUFFER_ACCESS_TOKEN" -H 'Content-Type: application/json' -d '{"query":"query { account { organizations { id name } } }"}'`. An Instagram draft whose `asset_ids` hold no ready JPEG or PNG fails with `ValueError: … refuses text-only posts` before Buffer is called: upload an image for the hotel and regenerate, or edit the draft's `asset_ids`.
3. If Buffer accepted the post but the database write failed, a Celery retry may submit it again. Confirm provider-side state and remove/resolve duplicates through Buffer before triggering another publish attempt.
4. After confirming the external action, reconcile `content_drafts` and `publish_log` through the approved database procedure.

The application currently schedules Turkish text only. A draft becomes `published` (or `failed`) when the hourly `sync-buffer` CronJob finds Buffer has sent it (or couldn't). It uses Buffer's GraphQL API since 2026-11; Buffer's legacy REST API (`api.bufferapp.com/1`) has brownouts on 2026-11-11 and 2026-12-09 and stops on 2027-02-01.

### Cron did not enqueue generation

1. Check the CronJob's last run: `kubectl -n aipostit-prod get cronjob,jobs` and the job pod's logs (`celery call` prints the task ID).
2. A manual `POST /internal/jobs/generate` must include `X-Cron-Secret`.
3. Check for an authorization failure, API health issue, or Redis/worker outage in logs.
4. If manually rerunning generation, inspect recent drafts first to avoid duplicates.

### A draft stays scheduled after its post went out

1. Check the `sync-buffer` CronJob's last runs: `kubectl -n aipostit-prod get cronjob,jobs`, then the worker's logs for `tasks.sync_buffer_posts`.
2. A warning `Buffer post <id>: NOT_FOUND ...` means Buffer no longer has the post (deleted in Buffer's app): the draft stays `scheduled`; reconcile it by hand after checking the network.
3. An HTTP 429 means Buffer's rate limit (shared by every key on the account): the next hour's run picks up where this one stopped.

## Security and data handling

- Store secrets only in a protected local `.env` (ignored by Git) and the platform's store, loaded from it with `platform/scripts/load-app-env.sh`.
- Never expose `SUPABASE_SERVICE_ROLE_KEY`, provider tokens, or `CRON_SECRET` to browser code or client logs.
- Dashboard browser sessions use an HttpOnly, SameSite=Strict cookie containing only an opaque Redis session ID. Session access and refresh tokens live in Redis. Keep `SESSION_COOKIE_SECURE=true` wherever the front door is HTTPS (the kind cluster's is plain HTTP, so both environments set it false).
- Password recovery requires `PUBLIC_BASE_URL` and a matching Supabase Auth redirect allow-list entry for `/auth/callback`.
- Hotel upload capabilities are shareable secrets in a URL fragment and expire after 24 hours. Share them only with the intended hotel contact.
- API hotel/asset/content routes require Supabase bearer authentication. The current database client uses the service-role key for server-side requests, so authenticated users are not isolated by hotel in application logic.
- A valid `GET /health` is public and reveals only liveness.
- Profile photos are personal data: a 256 px WebP per account at `avatars/{user_id}.webp` in the private `hotel-assets` bucket, served only to the account itself. Removing someone from a hotel, or deleting their Supabase account, leaves the object until the daily `purge-photos` CronJob (prod only: staging shares the Storage) deletes it: a photo whose account is deleted, or is neither hotel staff nor an operator. To run it now: `kubectl -n aipostit-prod create job purge-photos-now --from=cronjob/aipostit-purge-photos`. The same run deletes the logos of deleted hotels (`hotel-logos/{hotel_id}.webp`; a hotel's deletion leaves its Storage objects). The log says `Purged N profile photos no one can see` and `Purged N logos of deleted hotels` (counts only). It exits 1 if Supabase couldn't be asked about some account (`Could not check the accounts of N profile photos`): those photos are kept, the rest deleted; run it again later. For a data request that can't wait, delete the object in Storage by hand.
- Hotel deletion cascades to associated assets metadata, drafts, translations, and publish log rows. Confirm retention and deletion requirements before deleting a hotel; Storage objects are not explicitly removed by that database cascade.
- Use Supabase's configured backup/restore procedures for database recovery. This repository does not define backup schedules or a restore automation.

## Related documentation

- Component and data-flow design: [Architecture](./ARCHITECTURE.md)
