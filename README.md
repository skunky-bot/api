# SkunkScrape API

FastAPI control-plane scaffold for SkunkScrape. This service provides authentication, job submission, job-status lookup, and result retrieval. **Scraping is not yet implemented by this service:** the current job runner simulates execution and reports zero records.

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
