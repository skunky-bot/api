from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Collection, CollectionContact, User, utcnow
from app.deps import get_current_user, get_db
from app.schemas.collection import (
    CollectionCreate, CollectionDetail, CollectionPage, CollectionUpdate, ContactPage,
)


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/collections", tags=["collector"], dependencies=[Depends(private_response)])


def require_enabled() -> None:
    if not settings.collector_enabled:
        raise HTTPException(503, "The collector is disabled in this environment")


def owned_collection(db: Session, collection_id: str, owner_id: str) -> Collection:
    collection = db.scalar(select(Collection).where(Collection.id == collection_id, Collection.owner_id == owner_id))
    if collection is None:
        raise HTTPException(404, "Collection not found")
    return collection


@router.post("", response_model=CollectionDetail, status_code=201)
def create_collection(
    body: CollectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_enabled()
    collection = Collection(owner_id=user.id, next_run_at=utcnow(), **body.model_dump())
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.get("", response_model=CollectionPage)
def list_collections(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = db.scalars(select(Collection).where(Collection.owner_id == user.id)
                       .order_by(Collection.created_at.desc(), Collection.id.desc())
                       .offset(offset).limit(limit + 1)).all()
    return {"enabled": settings.collector_enabled, "items": items[:limit], "has_more": len(items) > limit}


@router.get("/{collection_id}", response_model=CollectionDetail)
def get_collection(
    collection_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return owned_collection(db, collection_id, user.id)


@router.patch("/{collection_id}", response_model=CollectionDetail)
def update_collection(
    collection_id: str,
    body: CollectionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    collection = owned_collection(db, collection_id, user.id)
    if collection.mode != "continuous":
        raise HTTPException(409, "Pause and resume apply to continuous collections")

    if body.paused:
        eligible = Collection.status.in_(("scheduled", "running"))
        changes = {"status": "paused", "next_run_at": None, "lease_token": None, "lease_until": None}
    else:
        require_enabled()
        eligible = Collection.status == "paused"
        changes = {"status": "scheduled", "next_run_at": utcnow()}

    db.execute(update(Collection).where(Collection.id == collection_id, Collection.owner_id == user.id, eligible)
               .values(**changes).execution_options(synchronize_session=False))
    db.commit()
    db.refresh(collection)
    return collection


@router.get("/{collection_id}/contacts", response_model=ContactPage)
def list_contacts(
    collection_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    owned_collection(db, collection_id, user.id)
    items = db.scalars(select(CollectionContact).where(CollectionContact.collection_id == collection_id)
                       .order_by(CollectionContact.id.desc()).offset(offset).limit(limit + 1)).all()
    return {"items": items[:limit], "has_more": len(items) > limit}
