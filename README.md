# hotel_social_posts

The hotel social posts domain's apps, deployed on [easypeasyops/platform](https://github.com/easypeasyops/platform).
Each app lives in its own folder under `apps/`, with its code, deploy values, scripts and docs
(platform plan 3.5):

| App | What it is | Docs |
| --- | --- | --- |
| [aipostit](apps/aipostit/) | Hotel content: Claude drafts, DeepL translations, Buffer publishing; FastAPI with a Celery worker, data in Supabase | [Architecture](apps/aipostit/docs/ARCHITECTURE.md) · [Runbook](apps/aipostit/docs/RUNBOOK.md) · [Product](apps/aipostit/docs/product/) |

CI (`.github/workflows/ci.yml`) runs the platform's reusable checks on every pull request;
`ci` is the one check a merge needs.

Secrets never go into git: an app reads its keys from the environment (locally a `.env` that
`.gitignore` keeps out; in the cluster, the platform's secret store).
