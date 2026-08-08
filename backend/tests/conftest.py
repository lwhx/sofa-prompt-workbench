"""Pytest 全局配置。"""
import pytest

from app.api.v1 import auth as auth_module


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """每个测试前清空登录速率限制器，防止跨测试累积。"""
    auth_module._login_attempts.clear()
    yield
    auth_module._login_attempts.clear()
