import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.database.portable_postgres import (
    PortablePostgresManager,
    bootstrap_portable_postgres_if_needed,
    find_free_port,
    get_bundle_base_dir,
)


def _create_fake_pg_bins(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if os.name == "nt" else ""
    for tool in ("initdb", "pg_ctl", "postgres"):
        p = bin_dir / f"{tool}{suffix}"
        p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        p.chmod(0o755)


def test_find_free_port_returns_valid_port():
    """Verifies that find_free_port returns an available TCP port on localhost."""
    port = find_free_port(54329)
    assert isinstance(port, int)
    assert 1024 <= port <= 65535


def test_portable_postgres_availability_detection(tmp_path):
    """Verifies that PortablePostgresManager accurately detects when PostgreSQL binaries exist."""
    empty_bin = tmp_path / "empty_bin"
    empty_bin.mkdir()
    mgr_missing = PortablePostgresManager(pg_bin_dir=empty_bin, data_dir=tmp_path / "pgdata")
    assert mgr_missing.is_available() is False

    valid_bin = tmp_path / "pgsql" / "bin"
    _create_fake_pg_bins(valid_bin)
    mgr_valid = PortablePostgresManager(pg_bin_dir=valid_bin, data_dir=tmp_path / "pgdata")
    assert mgr_valid.is_available() is True
    assert mgr_valid.is_initialized() is False


def test_portable_postgres_initialize_cluster_writes_config(tmp_path, monkeypatch):
    """Verifies that initialize_cluster runs initdb and appends user-space tuning to postgresql.conf."""
    valid_bin = tmp_path / "pgsql" / "bin"
    _create_fake_pg_bins(valid_bin)
    data_dir = tmp_path / "data" / "pgdata"

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "PG_VERSION").write_text("16\n", encoding="utf-8")
        (data_dir / "postgresql.conf").write_text("# base config\n", encoding="utf-8")
        res = MagicMock()
        res.returncode = 0
        res.stdout = "ok"
        res.stderr = ""
        return res

    monkeypatch.setattr(subprocess, "run", fake_run)

    mgr = PortablePostgresManager(pg_bin_dir=valid_bin, data_dir=data_dir, port=54330)
    mgr.initialize_cluster()

    assert mgr.is_initialized() is True
    assert len(calls) == 1
    assert "initdb" in calls[0][0]
    conf_text = (data_dir / "postgresql.conf").read_text(encoding="utf-8")
    assert "shared_buffers = 128MB" in conf_text
    assert "listen_addresses = '127.0.0.1'" in conf_text


def test_portable_postgres_start_and_stop_lifecycle(tmp_path, monkeypatch):
    """Verifies that start() launches pg_ctl, provisions database + vector extension, sets env vars, and stop() halts the cluster."""
    valid_bin = tmp_path / "pgsql" / "bin"
    _create_fake_pg_bins(valid_bin)
    data_dir = tmp_path / "data" / "pgdata"

    running_state = {"running": False}
    executed_cmds = []

    def fake_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        res = MagicMock()
        exe_name = os.path.basename(cmd[0])
        if "initdb" in exe_name:
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "PG_VERSION").write_text("16\n", encoding="utf-8")
            (data_dir / "postgresql.conf").write_text("# conf\n", encoding="utf-8")
            res.returncode = 0
        elif "pg_ctl" in exe_name and "status" in cmd:
            res.returncode = 0 if running_state["running"] else 3
        elif "pg_ctl" in exe_name and "start" in cmd:
            running_state["running"] = True
            res.returncode = 0
        elif "pg_ctl" in exe_name and "stop" in cmd:
            running_state["running"] = False
            res.returncode = 0
        else:
            res.returncode = 0
        return res

    monkeypatch.setattr(subprocess, "run", fake_run)

    sql_executed = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            sql_executed.append((query, params))
            m = MagicMock()
            m.fetchone.return_value = None
            return m

    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: FakeConn())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    monkeypatch.delenv("VECTOR_STORE_PROVIDER", raising=False)

    mgr = PortablePostgresManager(
        pg_bin_dir=valid_bin,
        data_dir=data_dir,
        port=54331,
        user="postgres",
        dbname="contextcortex",
    )
    db_url = mgr.start()

    assert db_url == f"postgresql+psycopg://postgres@127.0.0.1:{mgr.port}/contextcortex"
    assert os.environ.get("DATABASE_URL") == db_url
    assert os.environ.get("VECTOR_STORE") == "pgvector"
    assert any("CREATE DATABASE" in q for q, _ in sql_executed)
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in q for q, _ in sql_executed)

    mgr.stop()
    assert running_state["running"] is False
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("VECTOR_STORE", None)
    os.environ.pop("VECTOR_STORE_PROVIDER", None)


def test_bootstrap_skips_when_database_url_already_set(monkeypatch):
    """Verifies that bootstrap_portable_postgres_if_needed respects an existing DATABASE_URL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://custom:5432/db")
    try:
        assert bootstrap_portable_postgres_if_needed() == "postgresql://custom:5432/db"
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
