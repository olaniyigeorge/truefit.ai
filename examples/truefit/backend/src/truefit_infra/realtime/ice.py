"""
ICE server configuration shared by the REST endpoint the browser calls and the
server-side peer connection, so both sides use the same STUN and TURN servers.

STUN is always included. A TURN relay is added only when TURN_SERVER_URL is set;
its credentials come from TURN_USERNAME and TURN_CREDENTIAL, never from source.
"""

from __future__ import annotations

from src.truefit_infra.config import AppConfig

STUN_URL = "stun:stun.l.google.com:19302"


def build_ice_servers() -> list[dict]:
    """ICE servers as plain dicts (the shape browsers' RTCPeerConnection expects)."""
    servers: list[dict] = [{"urls": STUN_URL}]
    if AppConfig.TURN_SERVER_URL:
        servers.append(
            {
                "urls": AppConfig.TURN_SERVER_URL,
                "username": AppConfig.TURN_USERNAME,
                "credential": AppConfig.TURN_CREDENTIAL,
            }
        )
    return servers
