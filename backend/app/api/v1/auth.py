import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings
from app.dependencies import (
    CurrentUser,
    DatabaseSession,
    get_session_payload,
    get_settings_from_request,
    require_csrf,
)
from app.errors import AppError, success
from app.models import AdminSession, AdminUser, new_id
from app.security.client_ip import resolve_client_ip, validate_production_trusted_proxies
from app.security.login_rate_limit import (
    allow_redis_login_attempt,
    memory_login_rate_limiter,
    rate_limit_keys,
)
from app.security.password import verify_password
from app.security.session import SessionPayload, create_session_token

router = APIRouter(prefix="/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> dict[str, object]:
    if settings.app_env == "production":
        validate_production_trusted_proxies(settings.trusted_proxies)
    client_ip = resolve_client_ip(request, settings.trusted_proxies)
    keys = rate_limit_keys(client_ip, payload.username)
    try:
        allowed = allow_redis_login_attempt(
            request.app.state.redis_client,
            keys,
            limit=settings.login_rate_limit,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
    except Exception as exc:
        if settings.app_env != "development" or not settings.login_rate_limit_development_fallback:
            raise AppError(
                "AUTH_SERVICE_UNAVAILABLE",
                "登录服务暂时不可用，请稍后再试",
                status_code=503,
            ) from exc
        allowed = memory_login_rate_limiter.allow(
            keys,
            limit=settings.login_rate_limit,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
    if not allowed:
        raise AppError(
            "RATE_LIMITED",
            "登录尝试过于频繁，请稍后再试",
            status_code=429,
        )

    user = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    password_ok = verify_password(user.password_hash, payload.password) if user else False
    if user is None or not user.is_active or not password_ok:
        raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", status_code=401)
    session_id = new_id()
    token, csrf = create_session_token(
        user.id,
        settings.session_secret,
        settings.session_ttl_seconds,
        session_id=session_id,
    )
    db.add(
        AdminSession(
            id=session_id,
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            csrf_token=csrf,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    db.commit()
    response.set_cookie(
        "spw_session",
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        domain=settings.cookie_domain,
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        "spw_csrf",
        csrf,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        domain=settings.cookie_domain,
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    return success({"username": user.username})


@router.get("/me")
def me(user: CurrentUser) -> dict[str, object]:
    return success({"id": user.id, "username": user.username})


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    response: Response,
    _user: CurrentUser,
    db: DatabaseSession,
    session_payload: Annotated[SessionPayload, Depends(get_session_payload)],
) -> dict[str, object]:
    active_session = db.get(AdminSession, session_payload.session_id)
    if active_session is not None:
        active_session.revoked_at = datetime.now(UTC)
        db.commit()
    response.delete_cookie("spw_session", path="/")
    response.delete_cookie("spw_csrf", path="/")
    return success({"logged_out": True})
