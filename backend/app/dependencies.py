from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import AdminSession, AdminUser
from app.security.session import SessionPayload, decode_session_token


def get_settings_from_request(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_session_payload(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> SessionPayload:
    token = request.cookies.get("spw_session", "")
    payload = decode_session_token(token, settings.session_secret)
    if payload is None:
        raise AppError("AUTH_REQUIRED", "请先登录", status_code=401)
    return payload


def require_user(
    payload: Annotated[SessionPayload, Depends(get_session_payload)],
    db: Annotated[Session, Depends(get_db)],
) -> AdminUser:
    active_session = db.get(AdminSession, payload.session_id)
    if active_session is None or active_session.revoked_at is not None:
        raise AppError("AUTH_REQUIRED", "请先登录", status_code=401)
    user = db.get(AdminUser, payload.user_id)
    if user is None or not user.is_active:
        raise AppError("AUTH_REQUIRED", "请先登录", status_code=401)
    return user


def require_csrf(
    request: Request,
    payload: Annotated[SessionPayload, Depends(get_session_payload)],
) -> None:
    if request.headers.get("X-CSRF-Token") != payload.csrf_token:
        raise AppError("CSRF_INVALID", "安全令牌无效，请刷新页面后重试", status_code=403)


DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[AdminUser, Depends(require_user)]

