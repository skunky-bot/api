# SkunkScrape API

FastAPI control plane for SkunkScrape. The web collector runs through the authenticated `/collections` API and a dedicated worker. The legacy `/jobs` runner reports that its scraper is unavailable.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/login` | Authenticate with form-encoded username/password and receive a JWT |
| `POST` | `/jobs` | Submit a job (authenticated) |
| `GET` | `/jobs/{id}` | Read a job belonging to the authenticated user |
| `GET` | `/results/{id}` | Retrieve completed job result belonging to the authenticated user |
| `GET` | `/healthz` | Liveness check |

The routes above use the configured `API_V1_PREFIX` (empty by default).

## Local development

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env  # Windows PowerShell: Copy-Item .env.example .env
```

Before running, set a strong unique `SECRET_KEY` and `BOOTSTRAP_ADMIN_PASSWORD` in your **local, untracked** `.env` file. Then:

```bash
uvicorn app.main:app --reload
pytest
```

Visit `http://127.0.0.1:8000/docs` for the OpenAPI UI. In production, disable or protect interactive API docs as appropriate.

## Production readiness

- **Do not expose the simulated job runner as a functional scraper.** Replace `app/services/job_runner.py` with a durable, observable worker service before advertising real results.
- Do not use default credentials, the example JWT signing secret, or SQLite as a shared multi-instance production database.
- Supply secrets through a managed secrets provider or secure deployment environment, not committed configuration files.
- Configure explicit CORS origins, TLS, authentication/authorization, rate limiting, per-tenant isolation, input validation, and audit logging.
- Use a real queue/worker architecture (such as Cloud Tasks / Cloud Run Jobs, or Celery and Redis) for retries, dead-letter handling, and horizontal scaling.
- Treat contact data under POPIA and relevant source terms; implement consent, retention, suppression, and deletion controls.
- Add CI checks for tests, secret scanning, and dependency vulnerabilities before production deployment.

## Related repositories

- [Web console](https://github.com/skunky-bot/www)
- [Studio and Python toolkit](https://github.com/skunky-bot/studio)
- [Cloud pipeline prototype](https://github.com/skunky-bot/SkunkScrapeCodex)
- [Source registry](https://github.com/skunky-bot/sources)

The repositories currently document different deployment approaches. **No hosting or migration decision is implied by this README.** Select a single deployment architecture through a documented architecture decision record before consolidating services.

## Skunky service preview (development-only)

`POST /pipeline/preview` is an authenticated, **stateless** preview endpoint which calls registered internal services in order: `search → scan → collect`. It accepts a bounded HTML document supplied by the caller. The API verifies that the source ID is present in the selected registry and the source hostname matches. It **does not fetch websites, persist contacts, run background scraping, or authorize outreach**.

Set `SKUNKY_SEARCH_URL`, `SKUNKY_SCAN_URL`, `SKUNKY_COLLECT_URL`, and a shared `SKUNKY_SERVICE_TOKEN` through deployment secrets. Keep these service endpoints on a private network and use HTTPS/mTLS in production. When unconfigured, the preview returns 503.

Example request body (requires an authenticated bearer token):

```json
{
  "query": "demo",
  "source_id": "example-docs",
  "source_url": "https://example.com/",
  "html": "<a href=\"mailto:info@example.com\">Contact</a>",
  "region": "ZA"
}
```

The preview fixture only validates integration wiring. See `skunky-bot/www/docs/architecture/ADR-0001-skunky-platform.md` for migration gates.

## Web Collector

Set `SKUNKY_COLLECTOR_ENABLED=true` for the API and worker. Start the API first to initialise its database. Start one worker with `python -m app.services.collector_worker` using the same `DATABASE_URL` and internal pipeline environment variables. The [console repository](https://github.com/skunky-bot/www#web-collector) includes a Compose profile with a persistent development database.

All collector routes require the operator's bearer token.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/collections` | Save criteria and queue the first scan |
| `GET` | `/collections` | List the operator's scans and schedules |
| `GET` | `/collections/{id}` | Read current state and the latest scan outcome |
| `PATCH` | `/collections/{id}` | Set `{"paused": true}` or `{"paused": false}` for a continuous collection |
| `GET` | `/collections/{id}/contacts` | Read stored contacts with first source URL and observation dates |

Example continuous request:

```json
{"query":"solar Cape Town","mode":"continuous","interval_minutes":60,"region":"ZA","source_limit":5}
```

Use `mode: "once"` and omit `interval_minutes` for a single pass. Continuous intervals range from 15 to 1,440 minutes and are measured from the end of each run. Each collection retains unique email addresses and phone numbers across runs. Interrupted runs become eligible again after their worker lease expires. A pause prevents an in-flight run from saving results.

The worker scans the exact public HTTPS URLs approved in the Search service registry. Review source permissions and purpose before enabling each entry. For example:

```json
{
  "schema_version": 1,
  "sources": [
    {
      "id": "solar-directory",
      "label": "Cape Town solar installers",
      "url": "https://directory.example.org/solar/contact",
      "tags": ["solar", "Cape Town"],
      "enabled": false,
      "mode": "web-collection",
      "outreach_allowed": false
    }
  ]
}
```

Point Search at the reviewed file with `SKUNKY_SOURCE_REGISTRY_PATH` and set `enabled: true` on approved entries. The worker checks `robots.txt`, uses a public IP pinned to the registered TLS hostname, limits page sizes and requests, and skips redirected URLs. Configure the worker's egress firewall and data retention before a production rollout.
