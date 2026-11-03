import hmac
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    AuthContext,
    get_auth_context,
    is_setup_required,
    require_same_origin,
)
from app.core.config import settings
from app.core.security import (
    csrf_token_for_session,
    dummy_password_hash,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from app.db.session import get_db
from app.models.activity import ActivityCategory, AppSetup, AuthSession, User
from app.schemas.auth import AuthSessionRead, AuthStatus, Credentials

router = APIRouter(prefix="/api/auth", tags=["authentication"])

DEFAULT_CATEGORIES = (
    ("Work", "#5B6EED"),
    ("Health", "#2E9C75"),
    ("Personal", "#D38B43"),
    ("Learning", "#8C67CB"),
    ("Leisure", "#D46A87"),
    ("Errands", "#64748B"),
)


def _issue_session(user: User, db: Session, response: Response) -> AuthSessionRead:
    token = new_token()
    csrf_token = csrf_token_for_session(token)
    now = datetime.now(UTC)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_hash=hash_token(csrf_token),
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(auth_session)
    db.commit()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return AuthSessionRead(username=user.username, csrf_token=csrf_token)


@router.get("/setup-status", response_model=AuthStatus)
def setup_status(db: Session = Depends(get_db)) -> AuthStatus:
    return AuthStatus(setup_required=is_setup_required(db))


@router.post("/setup", response_model=AuthSessionRead, status_code=status.HTTP_201_CREATED)
def setup(
    payload: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSessionRead:
    require_same_origin(request)
    setup_row = db.scalar(select(AppSetup).where(AppSetup.id == 1).with_for_update())
    if setup_row is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database setup is incomplete. Apply the latest migration.",
        )
    if setup_row.owner_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Initial setup is already complete. Public registration is disabled.",
        )

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        created_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        db.flush()
        setup_row.owner_user_id = user.id
        db.add_all(
            ActivityCategory(user_id=user.id, name=name, color=color)
            for name, color in DEFAULT_CATEGORIES
        )
        token = new_token()
        csrf_token = csrf_token_for_session(token)
        now = datetime.now(UTC)
        db.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token(token),
                csrf_hash=hash_token(csrf_token),
                created_at=now,
                expires_at=now + timedelta(hours=settings.session_ttl_hours),
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Initial setup is already complete.",
        ) from exc

    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return AuthSessionRead(username=user.username, csrf_token=csrf_token)


@router.post("/login", response_model=AuthSessionRead)
def login(
    payload: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthSessionRead:
    require_same_origin(request)
    user = db.scalar(select(User).where(User.username == payload.username))
    password_hash = user.password_hash if user else dummy_password_hash()
    if not verify_password(password_hash, payload.password) or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    return _issue_session(user, db, response)


@router.get("/session", response_model=AuthSessionRead)
def current_session(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
) -> AuthSessionRead:
    session_token = request.cookies[settings.session_cookie_name]
    csrf_token = csrf_token_for_session(session_token)
    return AuthSessionRead(username=context.user.username, csrf_token=csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> None:
    require_same_origin(request)
    csrf_token = request.headers.get("x-csrf-token")
    if not csrf_token or not hmac.compare_digest(
        context.session.csrf_hash, hash_token(csrf_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token.",
        )
    db.delete(context.session)
    db.commit()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
    )
