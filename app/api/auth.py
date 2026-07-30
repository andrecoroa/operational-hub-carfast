from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import verify_access_token
from app.models.admin import User
from app.services.authorization import user_has_permission

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    session_user_id = request.session.get("user_id")
    if session_user_id:
        subject = str(session_user_id)
    elif credentials:
        subject = verify_access_token(credentials.credentials, settings.app_secret_key)
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
            )
    else:
        subject = None
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from exc
    user = db.scalar(select(User).where(User.id == user_id, User.active.is_(True)))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission_code: str):
    def dependency(db: DbSession, current_user: CurrentUser) -> User:
        if not user_has_permission(db, current_user, permission_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        return current_user

    return dependency


def require_method_permission(read_permission: str, write_permission: str):
    def dependency(request: Request, db: DbSession, current_user: CurrentUser) -> User:
        permission_code = read_permission if request.method in {"GET", "HEAD", "OPTIONS"} else write_permission
        if not user_has_permission(db, current_user, permission_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        return current_user

    return dependency
