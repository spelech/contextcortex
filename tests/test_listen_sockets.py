"""
Tests for HTTP listen address selection.
HOST=localhost must listen on both loopback addresses (127.0.0.1 and ::1) so that clients that
resolve localhost to ::1 first (Windows) connect at once. Other HOST values keep one socket.
"""

import logging
import socket
from pathlib import Path

import pytest

from app.services import listen_sockets
from app.services.listen_sockets import open_listen_sockets, resolve_listen_hosts, run_server

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ipv6_loopback_available() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
        return True
    except OSError:
        return False


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST", " localhost "])
def test_localhost_expands_to_both_loopback_addresses(host):
    assert resolve_listen_hosts(host) == ["127.0.0.1", "::1"]


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "0.0.0.0", "::", "192.168.1.20", "my-host.example.com"])
def test_explicit_host_values_keep_a_single_address(host):
    assert resolve_listen_hosts(host) == [host]


def test_open_listen_sockets_binds_ipv4_and_ipv6_loopback_on_same_port():
    if not _ipv6_loopback_available():
        pytest.skip("IPv6 loopback is not available on this machine")
    sockets = open_listen_sockets(["127.0.0.1", "::1"], 0)
    try:
        assert len(sockets) == 2
        ipv4, ipv6 = sockets
        assert ipv4.family == socket.AF_INET and ipv4.getsockname()[0] == "127.0.0.1"
        assert ipv6.family == socket.AF_INET6 and ipv6.getsockname()[0] == "::1"
        assert ipv4.getsockname()[1] == ipv6.getsockname()[1]
        assert ipv6.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
    finally:
        for sock in sockets:
            sock.close()


def test_open_listen_sockets_skips_unavailable_ipv6_with_warning(caplog):
    def bind(host, port):
        if ":" in host:
            raise OSError("IPv6 disabled")
        return listen_sockets.bind_tcp_socket(host, port)

    with caplog.at_level(logging.WARNING, logger="app.services.listen_sockets"):
        sockets = open_listen_sockets(["127.0.0.1", "::1"], 0, bind=bind)
    try:
        assert [s.getsockname()[0] for s in sockets] == ["127.0.0.1"]
        assert "Cannot listen on ::1" in caplog.text
    finally:
        for sock in sockets:
            sock.close()


def test_open_listen_sockets_fails_when_ipv4_loopback_cannot_bind():
    def bind(host, port):
        raise OSError("port in use")

    with pytest.raises(OSError, match="port in use"):
        open_listen_sockets(["127.0.0.1", "::1"], 3000, bind=bind)


def test_run_server_uses_plain_uvicorn_run_for_explicit_host(monkeypatch):
    calls = []
    monkeypatch.setattr(listen_sockets.uvicorn, "run", lambda app, host, port: calls.append((host, port)))
    monkeypatch.setattr(listen_sockets, "open_listen_sockets", lambda *a, **k: pytest.fail("must not open sockets"))
    run_server(object(), "0.0.0.0", 3000)
    assert calls == [("0.0.0.0", 3000)]


def test_run_server_passes_both_loopback_sockets_to_uvicorn_for_localhost(monkeypatch):
    served = {}

    class FakeServer:
        def __init__(self, config):
            served["config"] = config

        def run(self, sockets=None):
            served["sockets"] = sockets

    fake_v4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    fake_v4.bind(("127.0.0.1", 0))
    try:
        monkeypatch.setattr(listen_sockets.uvicorn, "Server", FakeServer)
        monkeypatch.setattr(listen_sockets.uvicorn, "run", lambda *a, **k: pytest.fail("must not use uvicorn.run"))
        monkeypatch.setattr(listen_sockets, "open_listen_sockets", lambda hosts, port: [fake_v4])
        run_server(object(), "localhost", 0)
        assert served["sockets"] == [fake_v4]
        assert served["config"].host == "127.0.0.1"
    finally:
        fake_v4.close()


def test_portable_defaults_use_localhost_for_dual_loopback():
    main_source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("HOST", "localhost")' in main_source
    assert 'os.getenv("HOST", "0.0.0.0")' in main_source  # Docker default is unchanged
    portable_env = (REPO_ROOT / "scripts" / "portable" / ".env.example").read_text(encoding="utf-8")
    assert "\nHOST=localhost\n" in portable_env
