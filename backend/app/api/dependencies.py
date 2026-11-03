import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.security import hash_token
from app.db.session import get_db
from app.models.activity import AppSetup, AuthSession, User

COOKIE_CLEAR_VALUE = (
    f'{settings.session_cookie_name}=""; Max-Age=0; Path=/; HttpOnly; '
    f'SameSite=strict{"; Secure" if settings.session_cookie_secure else ""}'
)


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin != settings.frontend_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )


def get_auth_context(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthContext:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
            headers={"Set-Cookie": COOKIE_CLEAR_VALUE},
        )

    auth_session = db.scalar(
        select(AuthSession)
        .options(joinedload(AuthSession.user))
        .where(AuthSession.token_hash == hash_token(token))
    )
    now = datetime.now(UTC)
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
            headers={"Set-Cookie": COOKIE_CLEAR_VALUE},
        )
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        db.delete(auth_session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
            headers={"Set-Cookie": COOKIE_CLEAR_VALUE},
        )
    return AuthContext(user=auth_session.user, session=auth_session)


def require_authenticated_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user


def require_csrf(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    require_same_origin(request)
    csrf_token = request.headers.get("x-csrf-token")
    if not csrf_token or not hmac.compare_digest(
        context.session.csrf_hash, hash_token(csrf_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token.",
        )
    return context


def is_setup_required(db: Session) -> bool:
    setup = db.get(AppSetup, 1)
    return setup is None or setup.owner_user_id is None
