"""Pytest 全局配置。"""
import socket

import pytest

from app.security.login_rate_limit import memory_login_rate_limiter


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """每个测试前清空登录速率限制器，防止跨测试累积。"""
    memory_login_rate_limiter.clear()
    yield
    memory_login_rate_limiter.clear()


@pytest.fixture(autouse=True)
def _resolve_example_hosts_to_public_address(monkeypatch: pytest.MonkeyPatch):
    """让示例域名稳定解析到文档公网地址，避免单元测试依赖外部 DNS。"""
    original_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host: str, port: int, *args: object, **kwargs: object):
        """拦截 example 测试域名，其余地址交给系统解析器。"""
        if host.endswith(".example.com") or host.endswith(".example"):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
            ]
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
