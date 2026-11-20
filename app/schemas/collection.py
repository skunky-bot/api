from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Mode = Literal["once", "continuous"]
State = Literal["scheduled", "running", "paused", "completed", "failed"]
ContactKind = Literal["email", "phone"]


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


UtcDateTime = Annotated[datetime, AfterValidator(as_utc)]


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    mode: Mode
    region: str = Field(default="ZA", pattern=r"^[A-Z]{2}$")
    source_limit: int = Field(default=5, ge=1, le=10)
    interval_minutes: int | None = Field(default=None, ge=15, le=1440)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.mode == "continuous" and self.interval_minutes is None:
            raise ValueError("Set a scan interval for continuous collection")
        if self.mode == "once" and self.interval_minutes is not None:
            raise ValueError("Set an interval only for continuous collection")
        return self


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool


class CollectionDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    query: str
    mode: Mode
    region: str
    source_limit: int
    interval_minutes: int | None
    status: State
    created_at: UtcDateTime
    next_run_at: UtcDateTime | None
    last_run_at: UtcDateTime | None
    run_count: int
    result_count: int
    last_matched: int
    last_scanned: int
    last_error: str | None


class CollectionPage(BaseModel):
    enabled: bool
    items: list[CollectionDetail]
    has_more: bool


class ContactDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ContactKind
    value: str
    source_id: str
    source_url: str
    first_seen: UtcDateTime
    last_seen: UtcDateTime


class ContactPage(BaseModel):
    items: list[ContactDetail]
    has_more: bool
