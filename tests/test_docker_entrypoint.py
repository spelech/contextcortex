import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("sh") is None, reason="Requires a POSIX shell")
@pytest.mark.parametrize("update_status", [0, 23])
def test_runtime_ca_update_controls_application_start(tmp_path, update_status):
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "private.crt").write_text("test certificate", encoding="ascii")
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, status in [("mkdir", 0), ("cp", 0), ("update-ca-certificates", update_status)]:
        tool = tools / name
        tool.write_text(f"#!/bin/sh\nexit {status}\n", encoding="ascii")
        tool.chmod(0o755)

    entrypoint = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
    result = subprocess.run(
        ["sh", str(entrypoint), "printf", "application-started"],
        env={**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
             "EXTRA_CA_CERTS_DIR": str(certs)},
        capture_output=True,
        text=True,
        check=False,
    )

    if update_status == 0:
        assert result.returncode == 0
        assert "Loaded private CA certificates" in result.stdout
        assert result.stdout.endswith("application-started")
    else:
        assert result.returncode != 0
        assert "application-started" not in result.stdout
        assert "CA trust store" in result.stderr
