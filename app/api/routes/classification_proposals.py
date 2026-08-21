from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field
from sqlalchemy import select

from app.api.auth import CurrentUser
from app.api.deps import DbSession
from app.models.classification_proposals import ClassificationProposal
from app.schemas.common import ApiModel
from app.services.authorization import get_user_permission_codes
from app.services.classification_proposals import (
    DuplicateProposalError,
    approve_proposal,
    archive_proposal,
    associate_proposal,
    create_proposal,
    merge_proposals,
    observe_proposal,
    proposal_snapshot,
    proposal_suggestions,
    reject_proposal,
)

router = APIRouter(prefix="/classification-proposals")


class ProposalCreate(ApiModel):
    kind: str
    name: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=4000)
    department_id: int
    category_id: int | None = None
    parent_proposal_id: int | None = None
    origin_module: str = Field(default="common", max_length=80)
    origin_url: str | None = Field(default=None, max_length=500)
    origin_reference: str | None = Field(default=None, max_length=160)


class ProposalDecision(ApiModel):
    action: str
    approved_name: str | None = Field(default=None, max_length=160)
    target_id: int | None = None
    target_proposal_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)


def _require_any(db, user, *codes: str) -> set[str]:
    permissions = get_user_permission_codes(db, user)
    if not permissions.intersection(codes):
        raise HTTPException(status_code=403, detail="Permission denied.")
    return permissions


@router.get("/suggestions")
def suggestions(
    db: DbSession,
    current_user: CurrentUser,
    kind: str,
    name: str,
    department_id: int,
    category_id: int | None = None,
    parent_proposal_id: int | None = None,
    limit: int = Query(default=8, ge=1, le=20),
):
    _require_any(
        db,
        current_user,
        "classification.propose",
        "classification.provisional.use",
        "classification.validate",
        "classification.catalog.manage",
    )
    try:
        items = proposal_suggestions(
            db,
            kind=kind,
            name=name,
            department_id=department_id,
            category_id=category_id,
            parent_proposal_id=parent_proposal_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items}


@router.get("/active")
def active_proposals(db: DbSession, current_user: CurrentUser):
    _require_any(
        db,
        current_user,
        "classification.provisional.use",
        "classification.validate",
        "classification.catalog.manage",
    )
    proposals = db.scalars(
        select(ClassificationProposal)
        .where(ClassificationProposal.active.is_(True))
        .order_by(ClassificationProposal.kind, ClassificationProposal.proposed_name)
    ).all()
    return {"items": [proposal_snapshot(item) for item in proposals]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create(payload: ProposalCreate, db: DbSession, current_user: CurrentUser):
    _require_any(db, current_user, "classification.propose", "classification.catalog.manage")
    try:
        proposal = create_proposal(
            db,
            kind=payload.kind,
            name=payload.name,
            reason=payload.reason,
            department_id=payload.department_id,
            category_id=payload.category_id,
            parent_proposal_id=payload.parent_proposal_id,
            proposed_by_id=current_user.id,
            origin_module=payload.origin_module,
            origin_url=payload.origin_url,
            origin_reference=payload.origin_reference,
        )
        db.commit()
        db.refresh(proposal)
    except DuplicateProposalError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "existing": proposal_snapshot(exc.proposal)},
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return proposal_snapshot(proposal)


@router.post("/{proposal_id}/decision")
def decide(
    proposal_id: int,
    payload: ProposalDecision,
    db: DbSession,
    current_user: CurrentUser,
):
    if payload.action == "merge":
        _require_any(db, current_user, "classification.merge_reclassify")
    elif payload.action in {"approve", "link", "reject", "observe", "archive"}:
        _require_any(
            db,
            current_user,
            "classification.validate",
            "classification.catalog.manage",
        )
    else:
        raise HTTPException(status_code=400, detail="Unknown decision action.")
    proposal = db.get(ClassificationProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    try:
        if payload.action == "approve":
            approve_proposal(
                db,
                proposal=proposal,
                actor_user_id=current_user.id,
                approved_name=payload.approved_name,
                notes=payload.notes,
            )
        elif payload.action == "link":
            if not payload.target_id:
                raise ValueError("Indica a classificação oficial de destino.")
            associate_proposal(
                db,
                proposal=proposal,
                actor_user_id=current_user.id,
                target_id=payload.target_id,
                notes=payload.notes,
            )
        elif payload.action == "merge":
            target = (
                db.get(ClassificationProposal, payload.target_proposal_id)
                if payload.target_proposal_id
                else None
            )
            if not target:
                raise ValueError("Indica a proposta de destino.")
            merge_proposals(
                db,
                source=proposal,
                target=target,
                actor_user_id=current_user.id,
                notes=payload.notes,
            )
        elif payload.action == "reject":
            reject_proposal(
                db,
                proposal=proposal,
                actor_user_id=current_user.id,
                reason=payload.notes or "",
            )
        elif payload.action == "observe":
            observe_proposal(
                db,
                proposal=proposal,
                actor_user_id=current_user.id,
                notes=payload.notes or "",
            )
        else:
            archive_proposal(
                db,
                proposal=proposal,
                actor_user_id=current_user.id,
                notes=payload.notes,
            )
        db.commit()
        db.refresh(proposal)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"proposal": proposal_snapshot(proposal), "decided_at": datetime.now().isoformat()}
