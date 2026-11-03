# Operations Runbook

## Scope

This runbook covers local startup, deployment checks, common incidents, and recovery for the current FastAPI/Celery application. It assumes access to the Railway project, Supabase project, Redis service, and provider dashboards. Never paste secrets into tickets, logs, or command output.

## Service topology

- **API:** FastAPI/Uvicorn web service. Railway's `railway.toml` uses `GET /health` as its health check.
- **Worker:** Celery process using the same application image; must be deployed as a separate Railway service with a worker start command.
- **Redis:** Celery broker/result backend and operator session store.
- **Supabase:** Postgres, Auth, the private `hotel-assets` Storage bucket (uploads) and the public `published-media` bucket (images being posted).
- **External providers:** Anthropic, DeepL, and Buffer.
- **Cron:** External Railway cron schedule calling the internal generation endpoint. The schedule itself is not defined in this repository.

## Prerequisites and configuration

Before starting the app, provision Supabase and Redis, create the `hotel-assets` Storage bucket, apply the migrations in `supabase/migrations/` in order (`002` creates the public `published-media` bucket), and configure provider credentials.

Set the following environment variables in the local `.env` or the appropriate Railway service settings:

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

Create operator accounts through the Supabase Auth administration process. The application provides password and magic-link sign-in plus a forgot-password flow, but does not provide sign-up or MFA. Set `PUBLIC_BASE_URL` to the exact app origin used in browser (no trailing slash required).

In Supabase **Authentication → URL Configuration**, set the Site URL to the app origin and add the callback URL to the redirect allow list:

- Local: Site URL `http://localhost:8000`; redirect URL `http://localhost:8000/auth/callback`
- Deployed: use the HTTPS app origin and add `<PUBLIC_BASE_URL>/auth/callback`

Keep the Supabase magic-link and password-recovery email templates configured to redirect to the provided redirect URL. Supabase must allow the callback URL or it may fall back to the Site URL.

## Local startup

From the project root:

```sh
docker compose up --build
```

This starts the API, worker, and Redis. The API listens on port `8000`; its code reloads as the source directory is mounted. Confirm basic process liveness:

```sh
curl --fail http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

This check does **not** verify Supabase, Redis, or provider connectivity. In local debug mode, `/docs` is available only if `DEBUG=true`. To stop local services, use `Ctrl+C` in the compose session.

Open `http://localhost:8000/login` to sign in with a provisioned Supabase Auth operator account using a password or email magic link. Use **Forgot your password?** to request a reset email; the recovery link opens a password form valid for 15 minutes. The application stores browser and recovery sessions in Redis, so local auth requires the compose Redis service. From the hotel dashboard, create or edit a hotel and generate its 24-hour upload link. For local HTTP, configure `SESSION_COOKIE_SECURE=false` in `.env` and restart the API.

## Development checks

Dependencies are in `pyproject.toml`, pinned with hashes in `uv.lock`; the Docker image installs exactly the lock. From `apps/aicansolveit/`, with [uv](https://docs.astral.sh/uv/):

| Step | Command |
| --- | --- |
| Install exactly the locked dependencies | `uv sync --locked` |
| Format and lint | `uv run ruff format .` and `uv run ruff check .` |
| Type check | `uv run mypy app tests` |
| Tests (no `.env` needed: they use placeholders) | `uv run pytest` |
| The image, black-box | `docker build -t aicansolveit:dev . && scripts/smoke.sh` |

Change a dependency with `uv add <package>==<version>` (or edit `pyproject.toml`, then `uv lock`) and commit both files. CI runs the same commands on every pull request (`.github/workflows/ci.yml` at the repo root, through the platform's reusable workflows); a pull request is ready to merge when its `ci` check is green. Code that came in with the import still has inline `noqa` markers and modules listed under mypy's overrides in `pyproject.toml`: they come off as the code is fixed and typed.

## Deployment and release checklist

1. Confirm required settings exist for both the API and worker services; the worker needs `REDIS_URL` and all provider/Supabase settings used by its tasks.
2. Apply any new Supabase migration deliberately before deploying code that depends on it. The application does not migrate the database at startup.
3. Ensure the `hotel-assets` bucket exists and its upload policies match the signed-upload flow, and that the `published-media` bucket exists and is public (migration `002`); without it, publishing fails on the image copy.
4. Deploy the API from the repository's Dockerfile and preserve the `GET /health` Railway check.
5. Deploy a separate worker using:

   ```sh
   celery -A app.jobs.tasks.celery_app worker --loglevel=info --concurrency=2
   ```

6. Verify API and worker startup logs, then call `/health` on the deployed API.
7. Verify a protected job trigger only in a controlled environment and ensure it is not exposed with the cron secret in logs or shell history.
8. Configure the external Railway cron schedule to send `POST /internal/jobs/generate` with the `X-Cron-Secret` header. The intended cadence is weekly, but the cadence must be set in Railway; it is not encoded in this repository.
9. For release validation, confirm a test hotel can create a draft, persist translations, and schedule an approved draft without sending unintended production posts.

## Routine operational checks

- Check the Railway API and worker logs for startup errors, repeated task retries, or task failures.
- Check Redis availability and the worker's ability to consume jobs if tasks remain queued.
- Check Redis availability for operator sessions as well as Celery; login and authenticated dashboard/API requests require it.
- Check Supabase database and Storage health, and confirm the `hotel-assets` bucket is reachable.
- Check Anthropic, DeepL, and Buffer provider status and credentials when only one pipeline stage is failing.
- Review draft statuses in `content_drafts`, asset statuses in `assets`, and Buffer submission records in `publish_log`.
- For multilingual hotels, verify each expected row exists in `content_translations`; translation tasks can succeed with some languages missing.

## Incident procedures

### API health check fails

1. Inspect Railway API deployment logs and recent release/configuration changes.
2. Verify required environment variables are present without printing their values.
3. Confirm the web service is listening on Railway's `$PORT` and that the deployment start command is correct.
4. Roll back to the last known-good deployment if the failure began with a release and rollback is the established project procedure.
5. After recovery, check `/health` and perform a safe authenticated read.

Because `/health` is liveness-only, a successful response is not proof that dependencies are healthy.

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

The application currently schedules Turkish text only and has no Buffer webhook/polling process to update a draft to `published`. It uses Buffer's GraphQL API since 2026-11; Buffer's legacy REST API (`api.bufferapp.com/1`) has brownouts on 2026-11-11 and 2026-12-09 and stops on 2027-02-01.

### Cron did not enqueue generation

1. Verify the Railway cron schedule and target URL are configured; neither is defined by this repository.
2. Confirm the request is `POST /internal/jobs/generate` and includes `X-Cron-Secret`.
3. Check for an authorization failure, API health issue, or Redis/worker outage in logs.
4. If manually rerunning generation, inspect recent drafts first to avoid duplicates.

## Security and data handling

- Store secrets only in Railway's secret settings or a protected local `.env`; `.env` is ignored by Git.
- Never expose `SUPABASE_SERVICE_ROLE_KEY`, provider tokens, or `CRON_SECRET` to browser code or client logs.
- Dashboard browser sessions use an HttpOnly, SameSite=Strict cookie containing only an opaque Redis session ID. Session access and refresh tokens live in Redis. Keep `SESSION_COOKIE_SECURE=true` in deployed environments.
- Magic-link authentication requires `PUBLIC_BASE_URL` and a matching Supabase Auth redirect allow-list entry for `/auth/callback`.
- Hotel upload capabilities are shareable secrets in a URL fragment and expire after 24 hours. Share them only with the intended hotel contact.
- API hotel/asset/content routes require Supabase bearer authentication. The current database client uses the service-role key for server-side requests, so authenticated users are not isolated by hotel in application logic.
- A valid `GET /health` is public and reveals only liveness.
- Hotel deletion cascades to associated assets metadata, drafts, translations, and publish log rows. Confirm retention and deletion requirements before deleting a hotel; Storage objects are not explicitly removed by that database cascade.
- Use Supabase's configured backup/restore procedures for database recovery. This repository does not define backup schedules or a restore automation.

## Related documentation

- Component and data-flow design: [Architecture](./ARCHITECTURE.md)
