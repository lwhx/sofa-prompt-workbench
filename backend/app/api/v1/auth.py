import hashlib
from datetime import UTC, datetime, timedelta
from threading import Lock
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
from app.security.password import verify_password
from app.security.session import SessionPayload, create_session_token

router = APIRouter(prefix="/auth", tags=["认证"])

# 内存级登录速率限制：{ip: [timestamp, ...]}
# 窗口 60 秒，超过 login_rate_limit 次则拒绝
_login_attempts: dict[str, list[datetime]] = {}
_login_lock = Lock()
_LOGIN_WINDOW_SECONDS = 60
_LOGIN_MAX_TRACKED_IPS = 10_000


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
    # 速率限制检查（线程安全 + 自动清理过期 IP）
    client_ip = request.client.host if request.client else "unknown"
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=_LOGIN_WINDOW_SECONDS)
    with _login_lock:
        recent = [t for t in _login_attempts.get(client_ip, []) if t > cutoff]
        if len(recent) >= settings.login_rate_limit:
            raise AppError(
                "RATE_LIMITED",
                "登录尝试过于频繁，请稍后再试",
                status_code=429,
            )
        _login_attempts[client_ip] = recent + [now]
        # 防止内存泄漏：清理过期的 IP 条目，上限保护
        if len(_login_attempts) > _LOGIN_MAX_TRACKED_IPS:
            expired_ips = [ip for ip, times in _login_attempts.items() if not any(t > cutoff for t in times)]
            for ip in expired_ips:
                del _login_attempts[ip]

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

