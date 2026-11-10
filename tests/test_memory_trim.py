import os
from pathlib import Path
import platform
import shutil
import subprocess
from unittest.mock import patch

import pytest

from app.services.memory_utils import trim_memory


def test_trim_memory_runs_safely():
    """Verifies that trim_memory executes without exceptions on the host system."""
    res = trim_memory()
    assert isinstance(res, bool)


def test_trim_memory_non_linux_noop(monkeypatch):
    """Verifies that trim_memory gracefully no-ops on non-Linux platforms."""
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    assert trim_memory() is False


def test_trim_memory_handles_libc_exception(monkeypatch):
    """Verifies that trim_memory catches and logs any C library or ctypes exceptions."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    def mock_cdll(_name):
        raise OSError("Simulated missing libc")

    monkeypatch.setattr("ctypes.CDLL", mock_cdll)
    assert trim_memory() is False


@pytest.mark.skipif(shutil.which("sh") is None, reason="Requires a POSIX shell")
def test_docker_entrypoint_sets_malloc_arena_max_default(tmp_path):
    """Verifies that docker-entrypoint.sh sets MALLOC_ARENA_MAX=2 by default."""
    entrypoint = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
    env = {k: v for k, v in os.environ.items() if k != "MALLOC_ARENA_MAX"}
    result = subprocess.run(
        ["sh", str(entrypoint), "sh", "-c", 'printf "%s" "$MALLOC_ARENA_MAX"'],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "2"


@pytest.mark.skipif(shutil.which("sh") is None, reason="Requires a POSIX shell")
def test_docker_entrypoint_preserves_custom_malloc_arena_max(tmp_path):
    """Verifies that docker-entrypoint.sh preserves user-configured MALLOC_ARENA_MAX."""
    entrypoint = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
    env = {**os.environ, "MALLOC_ARENA_MAX": "4"}
    result = subprocess.run(
        ["sh", str(entrypoint), "sh", "-c", 'printf "%s" "$MALLOC_ARENA_MAX"'],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "4"
