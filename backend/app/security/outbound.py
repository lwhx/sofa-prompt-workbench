from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpcore
import httpx

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


class OutboundURLValidationError(ValueError):
    """表示外联 URL 不符合统一 SSRF 安全策略。"""


class _PinnedIPTransport(httpx.BaseTransport):
    """将连接目标固定到已校验 IP，同时保留原始 Host 与 TLS SNI。"""

    def __init__(self, address: str) -> None:
        """初始化连接级 IP 固定传输层。"""
        self._address = address
        self._transport = httpx.HTTPTransport(trust_env=False)
        self._transport._pool._network_backend = _PinnedNetworkBackend(address)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """改写底层连接地址并保留应用层目标主机信息。"""
        hostname = request.url.host
        port = request.url.port
        default_port = 443 if request.url.scheme == "https" else 80
        authority = hostname if port in {None, default_port} else f"{hostname}:{port}"
        headers = request.headers.copy()
        headers["Host"] = authority
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = hostname
        secured_request = httpx.Request(
            method=request.method,
            url=request.url,
            headers=headers,
            content=request.stream,
            extensions=extensions,
        )
        return self._transport.handle_request(secured_request)

    def close(self) -> None:
        """关闭底层连接池。"""
        self._transport.close()


class _PinnedNetworkBackend(httpcore.SyncBackend):
    """将 httpcore 的 TCP 建连主机固定到已校验 IP。"""

    def __init__(self, address: str) -> None:
        """保存唯一允许连接的目标 IP。"""
        self._address = address

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        """忽略上层域名，仅连接预先解析并校验的 IP。"""
        return super().connect_tcp(
            self._address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


def _is_explicit_private_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判断地址是否属于允许显式放行的 RFC 私网范围。"""
    candidate = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    resolved_address = candidate or address
    return any(resolved_address in network for network in _PRIVATE_NETWORKS)


def _validate_address(address_text: str, *, allow_private_networks: bool) -> None:
    """校验单个解析地址，拒绝环回、链路本地、保留及其他非公网地址。"""
    try:
        address = ipaddress.ip_address(address_text.split("%", 1)[0])
    except ValueError as exc:
        raise OutboundURLValidationError("URL 主机解析结果不是有效 IP 地址") from exc
    if address.is_global:
        return
    if allow_private_networks and _is_explicit_private_address(address):
        return
    raise OutboundURLValidationError("URL 不允许指向环回、私网、链路本地或保留地址")


def _resolve_addresses(parsed: SplitResult, *, allow_private_networks: bool) -> tuple[str, ...]:
    """解析并校验目标地址，返回可用于连接固定的 IP 列表。"""
    hostname = parsed.hostname
    if hostname is None:
        raise OutboundURLValidationError("URL 缺少主机名")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError as literal_error:
        try:
            records = socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise OutboundURLValidationError("URL 主机名无法解析") from exc
        addresses = tuple(dict.fromkeys(str(record[4][0]) for record in records if record[4]))
        if not addresses:
            raise OutboundURLValidationError("URL 主机名未解析到 IP 地址") from literal_error
    else:
        addresses = (str(literal_address),)
    for address_text in addresses:
        _validate_address(address_text, allow_private_networks=allow_private_networks)
    return addresses


def _normalized_parts(value: str) -> SplitResult:
    """校验 URL 基本结构并返回规范化后的组成部分。"""
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise OutboundURLValidationError("URL 必须是有效的 HTTP 或 HTTPS 地址")
    if parsed.username is not None or parsed.password is not None:
        raise OutboundURLValidationError("URL 不允许包含用户名或密码")
    hostname = parsed.hostname.rstrip(".").lower()
    if not hostname or "%" in hostname:
        raise OutboundURLValidationError("URL 主机名格式无效")
    try:
        port = parsed.port
    except ValueError as exc:
        raise OutboundURLValidationError("URL 端口格式无效") from exc
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{rendered_host}:{port}" if port is not None else rendered_host
    return SplitResult(parsed.scheme.lower(), netloc, parsed.path, parsed.query, parsed.fragment)


def validate_outbound_url(
    value: str,
    *,
    allow_private_networks: bool = False,
    strip_query: bool = False,
) -> str:
    """校验协议、凭据、DNS 全部结果及地址类型，并返回规范化 URL。"""
    parsed = _normalized_parts(value)
    _resolve_addresses(parsed, allow_private_networks=allow_private_networks)
    return _render_url(parsed, strip_query=strip_query)


def _render_url(parsed: SplitResult, *, strip_query: bool = False) -> str:
    """根据已规范化组成部分生成不含片段的 URL。"""
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "" if strip_query else parsed.query,
            "",
        )
    )


def request_outbound(
    method: str,
    url: str,
    *,
    allow_private_networks: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    """在请求前重新执行 SSRF 校验，并强制禁用 HTTP 重定向。"""
    parsed = _normalized_parts(url)
    addresses = _resolve_addresses(parsed, allow_private_networks=allow_private_networks)
    safe_url = _render_url(parsed)
    kwargs["follow_redirects"] = False
    with httpx.Client(transport=_PinnedIPTransport(addresses[0]), trust_env=False) as client:
        return client.request(method, safe_url, **kwargs)
