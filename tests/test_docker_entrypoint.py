import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("sh") is None, reason="Requires a POSIX shell")
@pytest.mark.parametrize("update_status", [0, 23])
def test_runtime_ca_update_controls_application_start(tmp_path, update_status):
    """Verifies that runtime CA bundle updates copy certificates and fail closed when update-ca-certificates errors."""
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "private.crt").write_text("test certificate", encoding="ascii")

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "stale.crt").write_text("stale certificate", encoding="ascii")

    tools = tmp_path / "bin"
    tools.mkdir()
    tool = tools / "update-ca-certificates"
    tool.write_text(f"#!/bin/sh\nexit {update_status}\n", encoding="ascii")
    tool.chmod(0o755)

    entrypoint = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
    result = subprocess.run(
        ["sh", str(entrypoint), "printf", "application-started"],
        env={
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "EXTRA_CA_CERTS_DIR": str(certs),
            "RUNTIME_CA_CERTS_DIR": str(runtime_dir),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert not (runtime_dir / "stale.crt").exists()
    assert (runtime_dir / "private.crt").read_text(encoding="ascii") == "test certificate"

    if update_status == 0:
        assert result.returncode == 0
        assert "Loaded private CA certificates" in result.stdout
        assert result.stdout.endswith("application-started")
    else:
        assert result.returncode != 0
        assert "application-started" not in result.stdout
        assert "CA trust store" in result.stderr


@pytest.mark.skipif(shutil.which("sh") is None, reason="Requires a POSIX shell")
@pytest.mark.parametrize("create_empty_dir", [False, True])
def test_runtime_ca_empty_or_missing_dir_skips_update_and_starts(tmp_path, create_empty_dir):
    """Verifies that an empty or missing EXTRA_CA_CERTS_DIR skips CA trust updates and launches the command cleanly."""
    certs = tmp_path / "certs"
    if create_empty_dir:
        certs.mkdir()

    runtime_dir = tmp_path / "runtime"
    tools = tmp_path / "bin"
    tools.mkdir()
    tool = tools / "update-ca-certificates"
    tool.write_text("#!/bin/sh\nexit 99\n", encoding="ascii")
    tool.chmod(0o755)

    entrypoint = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
    result = subprocess.run(
        ["sh", str(entrypoint), "printf", "application-started"],
        env={
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "EXTRA_CA_CERTS_DIR": str(certs),
            "RUNTIME_CA_CERTS_DIR": str(runtime_dir),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "application-started"
