# Operations Runbook

## Scope

This runbook covers local startup, deployment checks, common incidents, and recovery for the current FastAPI/Celery application. It assumes access to the cluster (`kubectl`, Argo CD), the Supabase project and the provider dashboards. Never paste secrets into tickets, logs, or command output.

## Service topology

- **API:** FastAPI/Uvicorn web service. Liveness is `GET /healthz`, readiness `GET /readyz` (Redis answers).
- **Worker:** Celery process using the same application image, with its own command (the chart's `workers.worker`).
- **Redis:** Celery broker/result backend and operator session store.
- **Supabase:** Postgres, Auth, the private `hotel-assets` Storage bucket (uploads) and the public `published-media` bucket (images being posted).
- **External providers:** Anthropic, DeepL, and Buffer.
- **Cron:** the cluster's `generate-weekly` and `sync-buffer` CronJobs (below). Railway ran the app and its cron until plan 5.9.
- **In the cluster (from plan 5.9):** the same pieces from `deploy/` (ARCHITECTURE, In the cluster): API and worker Deployments, the Redis StatefulSet, the `generate-weekly` CronJob (Mondays 06:00 UTC, prod only: staging shares prod's Supabase). Run it now: `kubectl -n postitglobal-prod create job generate-now --from=cronjob/postitglobal-generate-weekly`; in staging, queue one hotel with `POST /internal/jobs/generate/<hotel_id>`. The `sync-buffer` CronJob (hourly at :15, prod only) marks drafts Buffer has sent `published` and those it couldn't send `failed`; run it now with `kubectl -n postitglobal-prod create job sync-now --from=cronjob/postitglobal-sync-buffer`. Its keys come from the platform's store: `platform/scripts/load-app-env.sh postitglobal .env`, then restart the API and the worker to read changed keys (`kubectl -n postitglobal-<env> rollout restart deployment`).

## Prerequisites and configuration

Before starting the app, provision Supabase and Redis, create the `hotel-assets` Storage bucket, apply the migrations in `supabase/migrations/` in order (`002` creates the public `published-media` bucket, `003` the `hotel_members` table for hotel staff), and configure provider credentials.

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

The blank values above are placeholders; supply secrets through your secret manager. `REDIS_URL` defaults to the local URL shown. `SESSION_COOKIE_SECURE=false` is required only when using plain HTTP on local development; keep it true in deployed environments. `CLAUDE_DRAFT_MODEL` and `CLAUDE_PREMIUM_MODEL` are optional. Keep the Supabase service-role key server-side only; it bypasses row-level security.

Create operator accounts through the Supabase Auth administration process. The application provides password sign-in (and Google, when enabled) plus a forgot-password flow, but does not provide sign-up or MFA. An account reaches the dashboard and the operator API only with the operator role, which you set by hand. Staging and prod share one Supabase project, so this covers both. In the Supabase **SQL editor**:

```sql
update auth.users
set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role": "operator"}'
where email in ('operator@example.com');
```

Remove the role with `raw_app_meta_data - 'role'`. The app reads the role from Supabase on every request, so either change applies at once with no new sign-in. Run the update for every existing operator **before** deploying a version with the role check: without it they get "This account doesn't have access to postitglobal." To list the operators: `select email from auth.users where raw_app_meta_data->>'role' = 'operator';`.

Hotel staff are accounts without the operator role that belong to one hotel. They sign in at the same `/login` and land on `/hotel`, which shows their hotel's files, lets them upload more, and links to the drafts waiting for review (`/hotel/drafts`), which they can edit, approve (published as from the dashboard) or reject. To invite staff, open the hotel on the dashboard and use **Create staff invite link**, then send the link (valid for 7 days, usable by several people) to the hotel. Each person opens it, enters their work email and a password, and lands on `/hotel`. The invite works like a password: anyone holding it can make an account for that hotel until it expires, and only rotating `SECRET_KEY` revokes it early (which also ends every upload link). An email that already has an account can't sign up again; to add an existing account to a hotel, or to make staff by hand, create the user in Supabase **Authentication → Users → Add user** (with a password, auto-confirmed) if needed, then in the SQL editor:

```sql
insert into hotel_members (user_id, hotel_id, email)
select u.id, h.id, u.email from auth.users u, hotels h
where u.email = 'staff@example.com' and h.slug = 'the-hotel-slug';
```

To take someone's access away, use **Remove** next to their email in the hotel's "Hotel staff" section (or delete their `hotel_members` row). It takes effect on their next request. Their Supabase account stays, with no access; delete it in **Authentication → Users** if it shouldn't exist at all. Set `PUBLIC_BASE_URL` to the exact app origin used in browser (no trailing slash required).

In Supabase **Authentication → URL Configuration**, set the Site URL to the app origin and add the callback URL to the redirect allow list:

- Local: Site URL `http://localhost:8000`; redirect URL `http://localhost:8000/auth/callback`
- Deployed: use the HTTPS app origin and add `<PUBLIC_BASE_URL>/auth/callback`

Keep the Supabase password-recovery email template configured to redirect to the provided redirect URL. Supabase must allow the callback URL or it may fall back to the Site URL.

In Supabase **Authentication → Sign In / Providers**, keep **Allow new users to sign up** off. The app never needs Supabase to create users on its own, and Google sign-in relies on this setting to stay limited to existing accounts.

### Google sign-in

The **Continue with Google** button shows only when `GOOGLE_SIGN_IN=true` (deploy value `config.googleSignIn`, per environment in `deploy/envs/`). Set it up once; staging and prod share the Supabase project, so they share the provider:

1. In [Google Cloud console](https://console.cloud.google.com/) → **APIs & Services → OAuth consent screen**: user type External, app name postitglobal, your support email. Scopes: `openid`, `email`, `profile` only. Publish the app (in Testing, only listed test users can sign in).
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type Web application. Under **Authorized redirect URIs** add Supabase's callback, shown on the Supabase Google provider page: `https://<project-ref>.supabase.co/auth/v1/callback`. Google sends people back to Supabase, not to the app, so no app URL goes here.
3. In Supabase **Authentication → Sign In / Providers → Google**: enable it and paste the client ID and client secret. Keep the secret out of git; it lives only in Supabase.
4. In Supabase **Authentication → URL Configuration → Redirect URLs**, add each origin's Google callback next to `/auth/callback`:
   - Local: `http://localhost:8000/auth/callback/google`
   - Staging: `http://staging.postitglobal.localhost:8080/auth/callback/google`
   - Prod: `http://postitglobal.localhost:8080/auth/callback/google` (the HTTPS origin once prod has one)
5. Set `GOOGLE_SIGN_IN=true` (`.env` locally; `config.googleSignIn: "true"` in the environment's values) and redeploy.

Check it: an operator whose account email is the Google address signs in and lands on the hotel list. A Google address without an account sees "There's no postitglobal account for that Google address", and no user appears in Supabase **Authentication → Users**. To turn it off, set `GOOGLE_SIGN_IN=false`; Google identities already linked stay in Supabase, harmlessly.

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

Dependencies are in `pyproject.toml`, pinned with hashes in `uv.lock`; the Docker image installs exactly the lock. From `apps/postitglobal/`, with [uv](https://docs.astral.sh/uv/):

| Step | Command |
| --- | --- |
| Install exactly the locked dependencies | `uv sync --locked` |
| Format and lint | `uv run ruff format .` and `uv run ruff check .` |
| Type check | `uv run mypy app tests` |
| Tests (no `.env` needed: they use placeholders) | `uv run pytest` |
| The image, black-box (non-root, probes, JSON logs, metrics, clean SIGTERM exit) | `docker build -t postitglobal:dev . && scripts/smoke.sh` |

Change a dependency with `uv add <package>==<version>` (or edit `pyproject.toml`, then `uv lock`) and commit both files. CI runs the same commands on every pull request (`.github/workflows/ci.yml` at the repo root, through the platform's reusable workflows); a pull request is ready to merge when its `ci` check is green. Code that came in with the import still has inline `noqa` markers and modules listed under mypy's overrides in `pyproject.toml`: they come off as the code is fixed and typed.

## Cut a release

A release is an image built, scanned and signed by `.github/workflows/release.yml` from a tag `postitglobal/vX.Y.Z` that matches `version` in `apps/postitglobal/pyproject.toml`. Only such images run in the cluster: the platform's admission policy and deploy gate require this workflow's provenance at this app's tag.

1. Bump `version` in `pyproject.toml` in a PR, and merge it.
2. Tag the merge commit (`git log --oneline -1` first: the tag must be on that commit, and release tags can't be moved):

   ```sh
   git fetch && git checkout main && git pull
   git tag postitglobal/v0.1.0 && git push origin postitglobal/v0.1.0
   ```

3. The workflow builds `linux/amd64` and `linux/arm64`, scans for HIGH and CRITICAL vulnerabilities before anything is published, pushes `ghcr.io/easypeasyops/hotel_social_posts/postitglobal`, attests its provenance and creates a GitHub Release whose notes give the digest. A tag that disagrees with `pyproject.toml` fails before publishing.
4. The first release creates the GHCR package as private: make it public (package settings) so the cluster can pull it without credentials.
5. Check the provenance: `gh attestation verify oci://ghcr.io/easypeasyops/hotel_social_posts/postitglobal@<digest> --owner easypeasyops`.

## Deployment and release checklist

1. Confirm required settings exist for both the API and worker services; the worker needs `REDIS_URL` and all provider/Supabase settings used by its tasks.
2. Apply any new Supabase migration deliberately before deploying code that depends on it. The application does not migrate the database at startup.
3. Ensure the `hotel-assets` bucket exists and its upload policies match the signed-upload flow, and that the `published-media` bucket exists and is public (migration `002`); without it, publishing fails on the image copy.
4. Deploy by digest: set `image.digest` in `deploy/envs/staging.yaml` in a PR (Argo CD deploys it on merge), check staging, then the same digest in `deploy/envs/prod.yaml`.
5. The worker deploys with the API: the chart's `workers.worker` runs the same image with `celery -A app.jobs.tasks.celery_app worker --loglevel=info --concurrency=2`.
6. Verify the API and worker logs (`kubectl -n postitglobal-<env> logs deploy/postitglobal` and `deploy/postitglobal-worker`), then `GET /readyz` through the Gateway.
7. Verify a protected job trigger only in a controlled environment and ensure it is not exposed with the cron secret in logs or shell history.
8. Weekly generation is the `generate-weekly` CronJob in prod, the Buffer sync the hourly `sync-buffer` one (`deploy/service/values.yaml`); nothing to configure outside this repository.
9. For release validation, confirm a test hotel can create a draft, persist translations, and schedule an approved draft without sending unintended production posts.

## Routine operational checks

- Check the API and worker logs (`kubectl -n postitglobal-<env> logs`) for startup errors, repeated task retries, or task failures.
- Check Redis availability and the worker's ability to consume jobs if tasks remain queued.
- Check Redis availability for operator sessions as well as Celery; login and authenticated dashboard/API requests require it.
- Check Supabase database and Storage health, and confirm the `hotel-assets` bucket is reachable.
- Check Anthropic, DeepL, and Buffer provider status and credentials when only one pipeline stage is failing.
- Review draft statuses in `content_drafts`, asset statuses in `assets`, and Buffer submission records in `publish_log`.
- For multilingual hotels, verify each expected row exists in `content_translations`; translation tasks can succeed with some languages missing.

## Reading the logs

The API and the worker log one JSON object per line to stdout (set `LOG_JSON=false` locally for plain lines). Every line a request logs carries its `request_id`, which is also the response's `X-Request-ID` header: ask a user for it, or take it from the access line (`"logger": "postitglobal.access"`, with `route`, `status` and `duration_ms`).

```sh
# Everything one request logged
docker compose logs api | grep '"request_id": "<id>"'
# Server errors with their routes
docker compose logs api | grep -o '{.*' | jq -c 'select(.status >= 500) | {ts, route, status, request_id}'
# Translations that failed, by language
docker compose logs worker | grep -o '{.*' | jq -c 'select(.msg == "translation failed") | {draft_id, language, error}'
```

## Reading the metrics

The API serves Prometheus metrics on port 9100 (`METRICS_PORT`), not on its public port: `curl -s localhost:9100/metrics | grep ^http_`. Per route template and status: `http_requests_total` counts requests and `http_request_duration_seconds` buckets their latency. A rising `status="5.."` count on one route points at that route's dependency; `route="unmatched"` is requests for paths the app doesn't have.

## Incident procedures

### API health check fails

1. Inspect the API's logs and events (`kubectl -n postitglobal-<env> describe pod`, `logs`) and recent release or configuration changes.
2. Verify required environment variables are present without printing their values.
3. Confirm the pods are Ready (`kubectl -n postitglobal-<env> get pods`) and the Application is Synced and Healthy (`kubectl -n argocd get app postitglobal-<env>`).
4. If the failure began with a release, roll back: put the previous digest back in `deploy/envs/<env>.yaml` and merge.
5. After recovery, check `/readyz` and perform a safe authenticated read.

Because `/healthz` is liveness-only, a successful response is not proof that dependencies are healthy. `/readyz` returns 503 `not ready: Redis` when Redis doesn't answer within 2 s: check Redis first. It doesn't cover Supabase or the providers.

### Jobs are not progressing

1. Check that the worker service is running the Celery command above and is configured with the same Redis URL as the API.
2. Inspect worker logs for broker connection failures, task exceptions, and exhausted retries.
3. Confirm Redis reachability and inspect the queue using the service's approved operational tooling.
4. Check whether the task reached an external provider; do not blindly enqueue duplicates if a task may have completed an external action.
5. Correct the missing dependency/configuration, then retry only the affected work after checking its database and provider state.

### Asset remains pending, processing, or failed

1. Confirm Storage upload succeeded at the asset's recorded `storage_path` in `hotel-assets`.
2. Confirm the hotel upload page called `POST /api/v1/upload-capabilities/{hotel_id}/assets/{asset_id}/confirm` using an unexpired upload link, or that an operator called the protected asset endpoint.
3. Check worker logs for `process_asset` failure and confirm Redis/worker health.
4. The current task only marks a confirmed asset `ready`; it does not validate or transform the file.
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

1. Check the CronJob's last run: `kubectl -n postitglobal-prod get cronjob,jobs` and the job pod's logs (`celery call` prints the task ID).
2. A manual `POST /internal/jobs/generate` must include `X-Cron-Secret`.
3. Check for an authorization failure, API health issue, or Redis/worker outage in logs.
4. If manually rerunning generation, inspect recent drafts first to avoid duplicates.

### A draft stays scheduled after its post went out

1. Check the `sync-buffer` CronJob's last runs: `kubectl -n postitglobal-prod get cronjob,jobs`, then the worker's logs for `tasks.sync_buffer_posts`.
2. A warning `Buffer post <id>: NOT_FOUND ...` means Buffer no longer has the post (deleted in Buffer's app): the draft stays `scheduled`; reconcile it by hand after checking the network.
3. An HTTP 429 means Buffer's rate limit (shared by every key on the account): the next hour's run picks up where this one stopped.

## Security and data handling

- Store secrets only in a protected local `.env` (ignored by Git) and the platform's store, loaded from it with `platform/scripts/load-app-env.sh`.
- Never expose `SUPABASE_SERVICE_ROLE_KEY`, provider tokens, or `CRON_SECRET` to browser code or client logs.
- Dashboard browser sessions use an HttpOnly, SameSite=Strict cookie containing only an opaque Redis session ID. Session access and refresh tokens live in Redis. Keep `SESSION_COOKIE_SECURE=true` in deployed environments.
- Password recovery requires `PUBLIC_BASE_URL` and a matching Supabase Auth redirect allow-list entry for `/auth/callback`.
- Hotel upload capabilities are shareable secrets in a URL fragment and expire after 24 hours. Share them only with the intended hotel contact.
- API hotel/asset/content routes require Supabase bearer authentication. The current database client uses the service-role key for server-side requests, so authenticated users are not isolated by hotel in application logic.
- A valid `GET /health` is public and reveals only liveness.
- Hotel deletion cascades to associated assets metadata, drafts, translations, and publish log rows. Confirm retention and deletion requirements before deleting a hotel; Storage objects are not explicitly removed by that database cascade.
- Use Supabase's configured backup/restore procedures for database recovery. This repository does not define backup schedules or a restore automation.

## Related documentation

- Component and data-flow design: [Architecture](./ARCHITECTURE.md)
