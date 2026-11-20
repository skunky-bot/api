"""Run durable one-time and continuous collections from the approved source registry."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated

import httpx
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.models import Collection, CollectionContact, User, utcnow
from app.db.session import SessionLocal
from app.services.pipeline import Pipeline, service_config
from app.services.web_fetch import PageFetcher, SourceError, registry_url

logger = logging.getLogger(__name__)
LEASE = timedelta(seconds=120)
POLL_SECONDS = 2
SERVICE_ERRORS = (httpx.HTTPError, KeyError, TypeError, ValueError, asyncio.TimeoutError)


class Source(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)


class Contacts(BaseModel):
    emails: list[Annotated[str, StringConstraints(min_length=1, max_length=254)]] = Field(max_length=25)
    phones: list[Annotated[str, StringConstraints(pattern=r"^\+[1-9][0-9]{6,14}$")]] = Field(max_length=25)


@dataclass(frozen=True)
class Run:
    collection_id: str
    token: str
    query: str
    region: str
    source_limit: int
    interval_minutes: int | None


@dataclass
class Sweep:
    matched: int = 0
    scanned: int = 0
    errors: list[str] = field(default_factory=list)
    contacts: dict[tuple[str, str], Source] = field(default_factory=dict)


def active_owner():
    return exists(select(User.id).where(User.id == Collection.owner_id, User.is_active.is_(True)))


def claim_next() -> Run | None:
    now = utcnow()
    due = or_(and_(Collection.status == "scheduled", Collection.next_run_at <= now),
              and_(Collection.status == "running", Collection.lease_until <= now))
    with SessionLocal.begin() as db:
        collection = db.scalar(select(Collection).where(due, active_owner())
                               .order_by(func.coalesce(Collection.next_run_at, Collection.lease_until), Collection.id)
                               .limit(1))
        if collection is None:
            return None
        token = str(uuid.uuid4())
        claim = db.execute(update(Collection).where(Collection.id == collection.id, due, active_owner())
                           .values(status="running", next_run_at=None, lease_token=token, lease_until=now + LEASE)
                           .execution_options(synchronize_session=False))
        if claim.rowcount == 1:
            return Run(collection.id, token, collection.query, collection.region,
                       collection.source_limit, collection.interval_minutes)
        return None


def lease_update(run: Run, now: datetime):
    return update(Collection).where(
        Collection.id == run.collection_id,
        Collection.status == "running",
        Collection.lease_token == run.token,
        Collection.lease_until > now,
        active_owner(),
    ).execution_options(synchronize_session=False)


def renew(run: Run) -> bool:
    now = utcnow()
    with SessionLocal.begin() as db:
        return db.execute(lease_update(run, now).values(lease_until=now + LEASE)).rowcount == 1


def finish(run: Run, sweep: Sweep) -> None:
    now = utcnow()
    failed = bool(sweep.errors and not sweep.scanned)
    continuous = run.interval_minutes is not None
    status = "scheduled" if continuous else ("failed" if failed else "completed")
    next_run = now + timedelta(minutes=run.interval_minutes) if continuous else None

    with SessionLocal.begin() as db:
        result = db.execute(lease_update(run, now).values(
            status=status, next_run_at=next_run, lease_token=None, lease_until=None, last_run_at=now,
            run_count=Collection.run_count + 1, last_scanned=sweep.scanned, last_matched=sweep.matched,
            last_error="\n".join(sweep.errors) if sweep.errors else None,
        ))
        if result.rowcount != 1 or not sweep.contacts:
            return

        existing = db.scalars(select(CollectionContact).where(
            CollectionContact.collection_id == run.collection_id,
            CollectionContact.value.in_({value for _, value in sweep.contacts}),
        )).all()
        by_key = {(row.kind, row.value): row for row in existing}
        new_count = 0
        for (kind, value), source in sweep.contacts.items():
            known = by_key.get((kind, value))
            if known is not None:
                known.last_seen = now
                continue
            db.add(CollectionContact(collection_id=run.collection_id, kind=kind, value=value,
                                     source_id=source.id, source_url=source.url, first_seen=now, last_seen=now))
            new_count += 1
        db.execute(update(Collection).where(Collection.id == run.collection_id)
                   .values(result_count=Collection.result_count + new_count))


async def process(run: Run, pipeline: Pipeline, fetcher: PageFetcher) -> None:
    sweep = Sweep()
    try:
        sources = await asyncio.wait_for(pipeline.search(run.query, run.source_limit, collection_only=True), timeout=15)
    except SERVICE_ERRORS:
        sweep.errors.append("Could not search the source registry")
        finish(run, sweep)
        return

    approved = [source for source in sources if source.get("enabled") is True
                and source.get("mode") == "web-collection" and source.get("outreach_allowed") is False]
    # Registry operators may list a page more than once under different labels.
    seen_urls = set()
    for item in approved[:run.source_limit]:
        if not renew(run):
            return
        try:
            source = Source.model_validate(item)
            url = str(registry_url(source.url))
            source.url = url
        except (ValidationError, SourceError):
            sweep.matched += 1
            sweep.errors.append("An approved registry entry has an invalid source ID or HTTPS URL")
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        sweep.matched += 1
        try:
            html = await fetcher.fetch(url)
        except SourceError as exc:
            sweep.errors.append(f"{source.id}: {exc}")
            continue
        if not renew(run):
            return
        try:
            raw_contacts = await asyncio.wait_for(pipeline.contacts(
                source.id, url, html, run.region, provenance="approved-web-collection",
            ), timeout=25)
            contacts = Contacts.model_validate(raw_contacts)
        except SERVICE_ERRORS:
            sweep.errors.append(f"{source.id}: Could not extract or normalize contacts")
            continue
        sweep.scanned += 1
        for kind, values in (("email", contacts.emails), ("phone", contacts.phones)):
            for value in values:
                sweep.contacts.setdefault((kind, value), source)
    finish(run, sweep)


async def run_forever(config: tuple[str, str, str, str]) -> None:
    async with (
        httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as internal,
        httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False,
                          limits=httpx.Limits(max_keepalive_connections=0)) as public,
    ):
        pipeline = Pipeline(internal, config)
        fetcher = PageFetcher(public)
        while True:
            try:
                run = claim_next()
                if run is not None:
                    await process(run, pipeline, fetcher)
                    continue
            except SQLAlchemyError as exc:
                logger.error("Collector database operation failed (%s). The queue will retry.", type(exc).__name__)
            await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    if not settings.collector_enabled:
        raise SystemExit("Set SKUNKY_COLLECTOR_ENABLED=true to start the collector worker")
    try:
        config = service_config()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger.info("Started the SkunkScrape collector worker")
    try:
        asyncio.run(run_forever(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
