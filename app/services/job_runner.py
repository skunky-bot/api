"""Job execution boundary.

This repository does not yet bundle a production scraper worker. Mark jobs
as failed rather than falsely reporting successfully scraped zero records.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Job
from app.db.session import SessionLocal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_job(job_id: str) -> None:
    """Fail closed until a supported, durable scraper executor is integrated."""
    db: Session = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return

        job.status = "failed"
        job.started_at = utcnow()
        job.completed_at = utcnow()
        job.error = (
            "Scraper worker is not configured. No extraction was performed. "
            "Integrate a real worker before enabling job execution."
        )
        job.result_json = None
        db.add(job)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
