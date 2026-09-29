"""部署级管理 API 的访问边界。

AI-Research-OS 有意不引入用户账号系统。空间键只隔离普通研究数据，并非身份凭据，
因此不能授权备份恢复、密钥或配置更新等部署级操作。

策略：
* 真正的本机请求无需令牌，以保留零登录桌面工作流；
* 非本机请求必须提供与 ``ADMIN_TOKEN`` 匹配的 ``X-Admin-Token``；
* 同时检查代理请求头及浏览器 Origin/Referer，避免经 Vite 开发代理转发的局域网请求
  被误判为本机请求。
"""
from __future__ import annotations

import hmac
import ipaddress
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request, status

from . import config

ADMIN_HEADER = "X-Admin-Token"


def _is_loopback_host(value: str | None) -> bool:
    """判断主机名或 IP 是否表示本机回环地址。"""
    raw = (value or "").strip().lower().strip("[]")
    if not raw:
        return False
    if raw in {"localhost", "testclient"}:  # testclient 是 Starlette 进程内测试主机名。
        return True
    # 请求头中的地址可能带端口；上一步已经移除了 IPv6 的方括号。
    if raw.count(":") == 1 and raw.rsplit(":", 1)[1].isdigit():
        raw = raw.rsplit(":", 1)[0]
    try:
        address = ipaddress.ip_address(raw)
        if address.is_loopback:
            return True
        mapped = getattr(address, "ipv4_mapped", None)
        return bool(mapped and mapped.is_loopback)
    except ValueError:
        return False


def _header_url_is_local(value: str | None) -> bool:
    """校验浏览器 Origin/Referer；不透明或格式错误的值按远程来源处理。"""
    if not value:
        return True
    try:
        return _is_loopback_host(urlsplit(value).hostname)
    except ValueError:
        return False


def request_is_local(request: Request) -> bool:
    """保守判断原始调用方是否来自本机。

    ``X-Forwarded-For`` 优先于套接字对端地址，这对代表浏览器从回环地址连接 FastAPI
    的 Vite 代理很重要。浏览器携带 Origin/Referer 时，它们也必须指向回环地址。
    """
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    # 仅信任本机反向代理提供的转发信息，防止远程客户端直接伪造
    # X-Forwarded-For: 127.0.0.1 绕过管理令牌校验。
    if forwarded and _is_loopback_host(peer):
        caller = forwarded.split(",", 1)[0].strip()
    else:
        caller = peer
    if not _is_loopback_host(caller):
        return False
    if not _header_url_is_local(request.headers.get("origin")):
        return False
    if not _header_url_is_local(request.headers.get("referer")):
        return False
    return True


def admin_token_matches(candidate: str | None) -> bool:
    expected = config.settings.admin_token.strip()
    supplied = (candidate or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


async def require_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias=ADMIN_HEADER),
) -> None:
    """保护部署级敏感操作的 FastAPI 依赖。"""
    if request_is_local(request) or admin_token_matches(x_admin_token):
        return
    configured = bool(config.settings.admin_token.strip())
    detail = (
        f"远程系统管理需要有效的 {ADMIN_HEADER}"
        if configured
        else f"远程系统管理已禁用；请在后端配置 ADMIN_TOKEN 后使用 {ADMIN_HEADER}"
    )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def startup_security_message() -> str:
    """返回不泄露令牌的可见启动安全摘要。"""
    host = config.settings.app_host.strip()
    public_bind = host not in {"127.0.0.1", "::1", "localhost"}
    configured = bool(config.settings.admin_token.strip())
    if configured:
        strength = "" if len(config.settings.admin_token) >= 32 else " WARNING: token is shorter than 32 characters."
        return (
            "[security] admin APIs: localhost or X-Admin-Token; "
            f"remote administration enabled with ADMIN_TOKEN.{strength}"
        )
    if public_bind:
        return (
            "[security] WARNING: server is bound beyond loopback; remote admin APIs "
            "are blocked until ADMIN_TOKEN is configured."
        )
    return "[security] admin APIs are restricted to localhost."


__all__ = [
    "ADMIN_HEADER",
    "admin_token_matches",
    "request_is_local",
    "require_admin",
    "startup_security_message",
]
