from __future__ import annotations

import ipaddress

from fastapi import Request


def parse_trusted_proxy_networks(
    value: str,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """解析逗号分隔的可信代理 IP 或 CIDR 配置。"""
    entries = (entry.strip() for entry in value.split(","))
    return tuple(ipaddress.ip_network(entry, strict=False) for entry in entries if entry)


def validate_production_trusted_proxies(value: str) -> None:
    """校验生产环境已显式配置至少一个合法可信代理地址范围。"""
    if not value.strip():
        raise ValueError("生产环境必须配置 TRUSTED_PROXIES")
    try:
        networks = parse_trusted_proxy_networks(value)
    except ValueError as exc:
        raise ValueError("TRUSTED_PROXIES 包含无效 IP 或 CIDR") from exc
    if not networks:
        raise ValueError("生产环境必须配置 TRUSTED_PROXIES")


def resolve_client_ip(request: Request, trusted_proxies: str) -> str:
    """仅在直连来源可信时按代理链解析真实客户端 IP。"""
    peer = request.client.host if request.client else "unknown"
    try:
        peer_address = ipaddress.ip_address(peer)
        networks = parse_trusted_proxy_networks(trusted_proxies)
    except ValueError:
        return peer
    if not any(peer_address in network for network in networks):
        return peer
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    chain = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
    chain.append(peer)
    for candidate in reversed(chain):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return peer
        if not any(address in network for network in networks):
            return str(address)
    return str(peer_address)
