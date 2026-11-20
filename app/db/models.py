import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    jobs = relationship("Job", back_populates="owner")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    job_type = Column(String(50), nullable=False, default="scrape")
    target = Column(String(2048), nullable=False)
    options_json = Column(Text, nullable=True)

    status = Column(String(50), nullable=False, default="queued", index=True)
    error = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    owner = relationship("User", back_populates="jobs")


class Collection(Base):
    __tablename__ = "web_collections"
    __table_args__ = (
        Index("ix_web_collections_due", "status", "next_run_at"),
        Index("ix_web_collections_lease", "status", "lease_until"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    query = Column(String(100), nullable=False)
    mode = Column(String(12), nullable=False)
    region = Column(String(2), nullable=False)
    source_limit = Column(Integer, nullable=False)
    interval_minutes = Column(Integer)
    status = Column(String(12), nullable=False, default="scheduled")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    next_run_at = Column(DateTime(timezone=True))
    lease_token = Column(String(36))
    lease_until = Column(DateTime(timezone=True))
    last_run_at = Column(DateTime(timezone=True))
    run_count = Column(Integer, nullable=False, default=0)
    result_count = Column(Integer, nullable=False, default=0)
    last_matched = Column(Integer, nullable=False, default=0)
    last_scanned = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)


class CollectionContact(Base):
    __tablename__ = "web_collection_contacts"
    __table_args__ = (UniqueConstraint("collection_id", "kind", "value"),)

    id = Column(Integer, primary_key=True)
    collection_id = Column(String(36), ForeignKey("web_collections.id"), nullable=False)
    kind = Column(String(5), nullable=False)
    value = Column(String(254), nullable=False)
    source_id = Column(String(100), nullable=False)
    source_url = Column(String(2048), nullable=False)
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
