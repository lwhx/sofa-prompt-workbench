from __future__ import annotations

import socket

import httpcore
import pytest

from app.security.outbound import (
    OutboundURLValidationError,
    request_outbound,
    validate_outbound_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://public.example.com/file",
        "https://user:password@public.example.com/api",
    ],
)
def test_rejects_unsupported_protocols_and_credentials(url: str) -> None:
    """非 HTTP 协议及带凭据 URL 必须被拒绝。"""
    with pytest.raises(OutboundURLValidationError):
        validate_outbound_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "http://192.0.2.1",
        "http://[::1]",
        "http://[fe80::1]",
        "http://[fc00::1]",
    ],
)
def test_rejects_loopback_private_link_local_and_reserved_addresses(url: str) -> None:
    """默认策略必须拒绝所有非公网目标地址。"""
    with pytest.raises(OutboundURLValidationError):
        validate_outbound_url(url)


def test_development_override_only_allows_private_networks() -> None:
    """显式开关仅放行私网，不能放行环回、链路本地或保留地址。"""
    assert validate_outbound_url(
        "http://192.168.1.20/api",
        allow_private_networks=True,
    ) == "http://192.168.1.20/api"
    for blocked_url in ("http://127.0.0.1", "http://169.254.169.254", "http://192.0.2.1"):
        with pytest.raises(OutboundURLValidationError):
            validate_outbound_url(blocked_url, allow_private_networks=True)


def test_dns_rejects_hostname_when_any_answer_is_not_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS 多地址解析中任一危险地址都必须导致整条 URL 被拒绝。"""
    def fake_getaddrinfo(
        _host: str,
        _port: int,
        *,
        type: socket.SocketKind,
    ) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]]:
        """返回一条公网和一条私网测试记录。"""
        assert type == socket.SOCK_STREAM
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(OutboundURLValidationError):
        validate_outbound_url("https://mixed.example.com/api")


def test_request_pins_validated_ip_and_preserves_host_and_tls_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """请求连接必须固定到已校验 IP，并保留原始 Host 与 TLS SNI。"""
    resolutions = 0
    captured: dict[str, object] = {}

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *,
        type: socket.SocketKind,
    ) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]]:
        """首次返回公网 IP，后续返回私网 IP 以模拟 DNS rebinding。"""
        nonlocal resolutions
        assert type == socket.SOCK_STREAM
        resolutions += 1
        address = "93.184.216.34" if resolutions == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    def fake_pool_handle_request(
        pool: httpcore.ConnectionPool,
        request: httpcore.Request,
    ) -> httpcore.Response:
        """捕获进入连接池的原始请求和固定网络后端。"""
        backend = pool._network_backend
        captured["scheme"] = request.url.scheme
        captured["target_host"] = request.url.host
        captured["port"] = request.url.port
        captured["target"] = request.url.target
        captured["host"] = dict(request.headers)[b"Host"].decode("ascii")
        captured["sni_hostname"] = request.extensions["sni_hostname"]
        captured["address"] = backend._address
        return httpcore.Response(200, content=b"")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(httpcore.ConnectionPool, "handle_request", fake_pool_handle_request)

    response = request_outbound("GET", "https://public.example.net:8443/api")

    assert response.status_code == 200
    assert resolutions == 1
    assert captured == {
        "scheme": b"https",
        "target_host": b"public.example.net",
        "port": 8443,
        "target": b"/api",
        "host": "public.example.net:8443",
        "sni_hostname": "public.example.net",
        "address": "93.184.216.34",
    }


def test_production_rejects_private_network_override() -> None:
    """生产环境不得启用开发私网放行开关。"""
    from app.config import Settings

    settings = Settings(
        app_env="production",
        session_secret="production-session-secret-at-least-32-bytes",
        secure_cookies=True,
        oneimg_base_url="https://93.184.216.34",
        oneimg_api_token="token",
        ai_base_url="https://93.184.216.34/v1",
        ai_api_key="key",
        ai_model="model",
        database_url="sqlite:///production.db",
        redis_url="redis://redis.internal:6379/0",
        ssrf_allow_private_networks=True,
    )

    with pytest.raises(ValueError, match="不允许放行"):
        settings.validate_production()


def test_production_requires_trusted_proxy_networks() -> None:
    """生产环境必须显式声明可信反向代理地址范围。"""
    from app.config import Settings
    from app.security.client_ip import validate_production_trusted_proxies

    settings = Settings(
        app_env="production",
        session_secret="production-session-secret-at-least-32-bytes",
        secure_cookies=True,
        oneimg_base_url="https://93.184.216.34",
        oneimg_api_token="token",
        ai_base_url="https://93.184.216.34/v1",
        ai_api_key="key",
        ai_model="model",
        database_url="sqlite:///production.db",
        redis_url="redis://redis.internal:6379/0",
        login_rate_limit_development_fallback=False,
    )

    with pytest.raises(ValueError, match="TRUSTED_PROXIES"):
        settings.validate_production()
        validate_production_trusted_proxies(settings.trusted_proxies)
