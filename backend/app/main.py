from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.events import EventWatermarkHub
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.database import create_database_engine
from app.errors import AppError
from app.health import RedisHealthClient, readiness_checks
from app.integrations.oneimg import OneImgClient


def create_app(
    *,
    settings: Settings | None = None,
    engine: Engine | None = None,
    redis_client: RedisHealthClient | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    app_settings.validate_production()
    database_engine = engine or create_database_engine(app_settings.database_url)
    application = FastAPI(
        title="沙发场景提示词工作台 API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    application.state.settings = app_settings
    application.state.engine = database_engine
    application.state.redis_client = redis_client or Redis.from_url(app_settings.redis_url)
    application.state.event_watermark_hub = EventWatermarkHub(database_engine)
    application.state.session_factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    application.state.oneimg_client = (
        OneImgClient(
            app_settings.oneimg_base_url,
            app_settings.oneimg_api_token,
            timeout_seconds=app_settings.oneimg_timeout_seconds,
            allow_private_networks=app_settings.ssrf_allow_private_networks,
        )
        if app_settings.oneimg_base_url and app_settings.oneimg_api_token
        else None
    )

    @application.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            {
                "data": None,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
            status_code=exc.status_code,
        )

    @application.middleware("http")
    async def enforce_csrf(request: Request, call_next: Any) -> Any:
        is_mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        is_protected_api = request.url.path.startswith("/api/v1/")
        if is_mutation and is_protected_api and request.url.path != "/api/v1/auth/login":
            from app.security.session import decode_session_token

            token = request.cookies.get("spw_session", "")
            payload = decode_session_token(token, app_settings.session_secret)
            csrf = request.headers.get("X-CSRF-Token")
            if payload is not None and csrf != payload.csrf_token:
                return JSONResponse(
                    {
                        "data": None,
                        "error": {
                            "code": "CSRF_INVALID",
                            "message": "安全令牌无效，请刷新页面后重试",
                            "details": {},
                        },
                    },
                    status_code=403,
                )
        return await call_next(request)

    @application.get("/health/live", include_in_schema=False)
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", include_in_schema=False)
    def health_ready() -> JSONResponse:
        ready, checks = readiness_checks(
            database_engine,
            application.state.redis_client,
            redis_required=app_settings.health_redis_required,
            backup_root=app_settings.backup_dir if app_settings.backup_enabled else None,
            backup_rpo_hours=app_settings.backup_rpo_hours,
        )
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "checks": checks},
            status_code=200 if ready else 503,
        )

    application.include_router(api_router)
    return application


app = create_app()
