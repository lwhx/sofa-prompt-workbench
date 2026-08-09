from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from threading import Lock
from typing import Protocol


class RedisRateLimitClient(Protocol):
    """定义登录限流所需的 Redis 命令。"""

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        """原子执行限流脚本并返回是否放行。"""


_SLIDING_WINDOW_SCRIPT = """
local now = tonumber(ARGV[1])
local cutoff = now - tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
for _, key in ipairs(KEYS) do
  redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
  if redis.call('ZCARD', key) >= limit then
    return 0
  end
end
local member = ARGV[4]
for _, key in ipairs(KEYS) do
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, ARGV[2])
end
return 1
"""


class MemoryLoginRateLimiter:
    """提供仅限开发降级使用的进程内滑动窗口限流器。"""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        """初始化时间源、互斥锁与限流记录。"""
        self._clock = clock
        self._lock = Lock()
        self._attempts: dict[str, list[float]] = {}

    def allow(self, keys: tuple[str, ...], *, limit: int, window_seconds: int) -> bool:
        """原子检查所有维度并在放行时记录本次尝试。"""
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            recent_by_key = {
                key: [timestamp for timestamp in self._attempts.get(key, ()) if timestamp > cutoff]
                for key in keys
            }
            if any(len(attempts) >= limit for attempts in recent_by_key.values()):
                return False
            for key, attempts in recent_by_key.items():
                self._attempts[key] = [*attempts, now]
            if len(self._attempts) > 20_000:
                self._attempts = {
                    key: attempts
                    for key, attempts in self._attempts.items()
                    if any(timestamp > cutoff for timestamp in attempts)
                }
        return True

    def clear(self) -> None:
        """清空开发降级记录。"""
        with self._lock:
            self._attempts.clear()


def rate_limit_keys(client_ip: str, username: str) -> tuple[str, str]:
    """生成不暴露用户名和地址明文的双维度 Redis 键。"""
    ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
    identity = f"{username.strip().casefold()}\0{client_ip}"
    identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return (f"spw:login-rate:ip:{ip_hash}", f"spw:login-rate:identity:{identity_hash}")


def allow_redis_login_attempt(
    client: RedisRateLimitClient,
    keys: tuple[str, ...],
    *,
    limit: int,
    window_seconds: int,
) -> bool:
    """通过 Redis Lua 脚本执行多维度原子滑动窗口限流。"""
    now_milliseconds = time.time_ns() // 1_000_000
    window_milliseconds = window_seconds * 1_000
    member = f"{now_milliseconds}:{secrets.token_hex(8)}"
    result = client.eval(
        _SLIDING_WINDOW_SCRIPT,
        len(keys),
        *keys,
        now_milliseconds,
        window_milliseconds,
        limit,
        member,
    )
    return bool(result)


memory_login_rate_limiter = MemoryLoginRateLimiter()
