"""Request-derived client identity used by auth flows and the audit trail.

Two auth routers had grown an identical ``_client_info`` building the same
``{user_agent, source_ip}`` metadata dict, and the audit writer open-coded the
same two extractions a third time. The truncation lengths are not arbitrary:
they match the stored column widths (user agent 512, source IP 64), so a client
sending an oversized header must be clamped rather than allowed to fail the
insert or bloat the audit row.
"""

from __future__ import annotations

from fastapi import Request

# Stored column bounds; clamping here keeps every writer consistent.
USER_AGENT_MAX_LENGTH = 512
SOURCE_IP_MAX_LENGTH = 64

__all__ = [
    "SOURCE_IP_MAX_LENGTH",
    "USER_AGENT_MAX_LENGTH",
    "client_request_info",
    "client_source_ip",
    "client_user_agent",
]


def client_source_ip(request: Request | None) -> str | None:
    """Return the peer address, or ``None`` when the transport has no client."""
    if request is None or request.client is None:
        return None
    host = request.client.host
    if not host:
        return None
    return host[:SOURCE_IP_MAX_LENGTH]


def client_user_agent(request: Request | None) -> str | None:
    """Return the User-Agent header, clamped to its stored width."""
    if request is None:
        return None
    user_agent = request.headers.get("user-agent")
    if not user_agent:
        return None
    return user_agent[:USER_AGENT_MAX_LENGTH]


def client_request_info(request: Request) -> dict[str, object]:
    """Return the ``{user_agent, source_ip}`` metadata dict for auth events.

    Absent values are omitted rather than stored as ``None`` so the audit
    metadata stays compact for clients that send neither header.
    """
    info: dict[str, object] = {}
    user_agent = client_user_agent(request)
    if user_agent:
        info["user_agent"] = user_agent
    source_ip = client_source_ip(request)
    if source_ip:
        info["source_ip"] = source_ip
    return info
