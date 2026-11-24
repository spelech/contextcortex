"""
Listen address selection for the HTTP server.

HOST=localhost means "both loopback addresses": the server listens on 127.0.0.1 and on ::1.
Windows resolves localhost to ::1 first. If the server listens only on 127.0.0.1, every new
client connection to http://localhost waits about 200 ms for the IPv6 attempt to fail before
it falls back to IPv4. Two loopback sockets remove this delay and never expose the server on a
non-loopback interface. All other HOST values (127.0.0.1, 0.0.0.0, ::, a LAN address) keep
their usual single-socket uvicorn meaning.
"""

import asyncio
import logging
import os
import socket
import sys
from typing import Callable, List, Optional

import uvicorn

logger = logging.getLogger(__name__)

LOOPBACK_HOST_ALIAS = "localhost"
LOOPBACK_ADDRESSES = ("127.0.0.1", "::1")


def resolve_listen_hosts(host: str) -> List[str]:
    """Returns the addresses to listen on for a HOST value. Only "localhost" expands to two."""
    if (host or "").strip().lower() == LOOPBACK_HOST_ALIAS:
        return list(LOOPBACK_ADDRESSES)
    return [host]


def bind_tcp_socket(host: str, port: int) -> socket.socket:
    """Creates and binds one TCP socket. An IPv6 socket is IPv6-only (no IPv4-mapped traffic)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        # On Windows, SO_REUSEADDR lets a second process bind the same port; do not set it there.
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


def open_listen_sockets(
    hosts: List[str],
    port: int,
    bind: Callable[[str, int], socket.socket] = bind_tcp_socket,
) -> List[socket.socket]:
    """
    Binds the first host (required) and then the other hosts (optional) on the same port.
    A failure on an optional host (for example, IPv6 is disabled) logs a warning and is skipped.
    """
    primary = bind(hosts[0], port)
    sockets = [primary]
    bound_port = primary.getsockname()[1]
    for host in hosts[1:]:
        try:
            sockets.append(bind(host, bound_port))
        except OSError as exc:
            logger.warning("Cannot listen on %s port %d (%s); continuing without it.", host, bound_port, exc)
    return sockets


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Returns SelectorEventLoop on Windows to avoid ProactorEventLoop WinError 64 accept socket closure."""
    return asyncio.SelectorEventLoop()


def _windows_loop_override() -> Optional[str]:
    """Selects SelectorEventLoop on Windows unless CONTEXTCORTEX_WINDOWS_PROACTOR=1 opts back into Proactor."""
    if sys.platform != "win32":
        return None
    if os.getenv("CONTEXTCORTEX_WINDOWS_PROACTOR", "").strip().lower() in ("1", "true", "yes"):
        return None
    return "app.services.listen_sockets:selector_loop_factory"


def run_server(app, host: str, port: int) -> None:
    """Runs uvicorn on one socket, or on both loopback sockets when HOST=localhost."""
    loop_override = _windows_loop_override()
    hosts = resolve_listen_hosts(host)
    if len(hosts) == 1:
        if loop_override:
            uvicorn.run(app, host=host, port=port, loop=loop_override)
        else:
            uvicorn.run(app, host=host, port=port)
        return
    sockets = open_listen_sockets(hosts, port)
    for sock in sockets:
        address, bound_port = sock.getsockname()[:2]
        shown = f"[{address}]" if ":" in address else address
        logger.info("Listening on http://%s:%d", shown, bound_port)
    cfg_kwargs = {"host": LOOPBACK_ADDRESSES[0], "port": sockets[0].getsockname()[1]}
    if loop_override:
        cfg_kwargs["loop"] = loop_override
    config = uvicorn.Config(app, **cfg_kwargs)
    uvicorn.Server(config).run(sockets=sockets)
