# hotel_social_posts

The hotel social posts domain's apps, deployed on [easypeasyops/platform](https://github.com/easypeasyops/platform).
Each app lives in its own folder under `apps/`, with its code, deploy values, scripts and docs
(platform plan 3.5):

| App | What it is | Docs |
| --- | --- | --- |
| [aicansolveit](apps/aicansolveit/) | Hotel content: Claude drafts, DeepL translations, Buffer publishing; FastAPI with a Celery worker, data in Supabase | [Architecture](apps/aicansolveit/docs/ARCHITECTURE.md) · [Runbook](apps/aicansolveit/docs/RUNBOOK.md) |

Secrets never go into git: an app reads its keys from the environment (locally a `.env` that
`.gitignore` keeps out; in the cluster, the platform's secret store).
