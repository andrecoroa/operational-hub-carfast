from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.auth import CurrentUser
from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.models.admin import User
from app.schemas.auth import CurrentUserRead, LoginRequest, TokenResponse
from app.services.audit import record_audit
from app.services.authorization import get_user_authorized_unit_codes, get_user_permission_codes

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    user.last_login_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        detail=f"Login de {user.email}",
    )
    db.commit()
    return TokenResponse(access_token=create_access_token(str(user.id), settings.app_secret_key))


@router.get("/me", response_model=CurrentUserRead)
def me(current_user: CurrentUser, db: DbSession):
    return CurrentUserRead(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        permissions=sorted(get_user_permission_codes(db, current_user)),
        authorized_units=sorted(get_user_authorized_unit_codes(db, current_user)),
    )
