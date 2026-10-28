"""Exercise dashboard publication without installing frontend dependencies."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "frontend_artifact.py"


@pytest.fixture
def checkout(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "src" / "app.js").write_text("current dashboard", encoding="utf-8")
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"build": "node build.cjs"}}), encoding="utf-8"
    )
    (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
    (frontend / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    # A dependency-free compiler fixture; the real npm process must succeed
    # before publication, just as with the application's TypeScript/Vite build.
    (frontend / "build.cjs").write_text(
        "const fs = require('node:fs');\n"
        "fs.mkdirSync('dist/assets', {recursive: true});\n"
        "fs.copyFileSync('index.html', 'dist/index.html');\n"
        "fs.copyFileSync('src/app.js', 'dist/assets/app.js');\n",
        encoding="utf-8",
    )
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "obsolete.js").write_text("old dashboard", encoding="utf-8")
    return tmp_path


def run_tool(root, command):
    return subprocess.run(
        [sys.executable, str(TOOL), command, "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def build_and_sync(root):
    for command in ("build", "sync"):
        result = run_tool(root, command)
        assert result.returncode == 0, result.stdout + result.stderr


def test_fresh_build_syncs_exact_output_and_removes_obsolete_assets(checkout):
    build_and_sync(checkout)
    result = run_tool(checkout, "verify")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (checkout / "www" / "assets" / "app.js").read_text() == "current dashboard"
    assert not (checkout / "www" / "obsolete.js").exists()
    assert sorted(p.relative_to(checkout / "www") for p in (checkout / "www").rglob("*")) == sorted(
        p.relative_to(checkout / "frontend" / "dist")
        for p in (checkout / "frontend" / "dist").rglob("*")
    )


def test_unverified_bundle_cannot_be_stamped_or_synced(checkout):
    dist = checkout / "frontend" / "dist"
    shutil.copytree(checkout / "www", dist)
    for command in ("verify", "sync"):
        result = run_tool(checkout, command)
        assert result.returncode != 0
        assert "unverified dashboard" in result.stderr.lower()
    assert not (dist / "build-manifest.json").exists()
    assert (checkout / "www" / "obsolete.js").exists()


@pytest.mark.parametrize(
    "relative_path",
    [
        "frontend/src/app.js",
        "frontend/package-lock.json",
        "frontend/vite.config.js",
        "frontend/public/new.svg",
        "frontend/packages/helper.tgz",
        "frontend/scripts/helper.js",
        "frontend/.env.production",
        "www/assets/app.js",
        "www/assets/extra.js",
        "www/assets/build-manifest.json",
        "www/index.html",
    ],
)
def test_source_or_output_changes_reject_previously_built_bundle(checkout, relative_path):
    build_and_sync(checkout)
    path = checkout / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("changed after build", encoding="utf-8")
    result = run_tool(checkout, "verify")
    assert result.returncode != 0
    assert "dashboard" in result.stderr.lower()


def test_deleted_asset_is_rejected(checkout):
    build_and_sync(checkout)
    (checkout / "www" / "assets" / "app.js").unlink()
    assert run_tool(checkout, "verify").returncode != 0


def test_source_line_endings_do_not_invalidate_transferred_artifacts(checkout):
    source = checkout / "frontend" / "src" / "app.js"
    source.write_bytes(b"current dashboard\n")
    build_and_sync(checkout)
    source.write_bytes(b"current dashboard\r\n")
    result = run_tool(checkout, "verify")
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_build_cannot_reuse_old_output_or_publish_manifest(checkout):
    build_and_sync(checkout)
    (checkout / "frontend" / "build.cjs").write_text("process.exit(7)", encoding="utf-8")
    result = run_tool(checkout, "build")
    assert result.returncode != 0
    assert not (checkout / "frontend" / "dist" / "build-manifest.json").exists()
    assert run_tool(checkout, "sync").returncode != 0
    assert (checkout / "www" / "assets" / "app.js").read_text() == "current dashboard"


def test_source_change_during_build_cannot_be_attested(checkout):
    with (checkout / "frontend" / "build.cjs").open("a", encoding="utf-8") as script:
        script.write("fs.writeFileSync('src/app.js', 'raced source');\n")
    result = run_tool(checkout, "build")
    assert result.returncode != 0
    assert "source changed during build" in result.stderr.lower()
    assert not (checkout / "frontend" / "dist" / "build-manifest.json").exists()
    assert (checkout / "www" / "obsolete.js").exists()


def overlay_context(checkout):
    for name in ("Dockerfile.overlay", ".dockerignore", "main.py", "docker-entrypoint.sh"):
        shutil.copy2(ROOT / name, checkout / name)
    (checkout / "scripts").mkdir()
    shutil.copy2(TOOL, checkout / "scripts" / TOOL.name)
    shutil.copytree(ROOT / "app", checkout / "app", ignore=shutil.ignore_patterns("__pycache__"))
    (checkout / "certs").mkdir()
    shutil.copy2(ROOT / "certs" / "README.md", checkout / "certs" / "README.md")


def docker_build(checkout):
    runtime = os.environ.get("ISSUE53_RUNTIME_IMAGE")
    if not runtime:
        pytest.skip("Set ISSUE53_RUNTIME_IMAGE to a cached Python runtime for Docker regression")
    overlay_context(checkout)
    return subprocess.run(
        [
            "docker", "build", "--network=none", "--pull=false", "--progress=plain",
            "--file", "Dockerfile.overlay",
            "--tag", "contextcortex-issue53-regression:test",
            "--build-arg", f"RUNTIME_IMAGE={runtime}", ".",
        ],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )


def test_overlay_build_rejects_unverified_dashboard(checkout):
    result = docker_build(checkout)
    output = result.stdout + result.stderr
    assert result.returncode != 0, "Overlay silently accepted the stale dashboard"
    assert "unverified dashboard" in output.lower(), output


def test_overlay_installs_verified_output_in_both_served_directories(checkout):
    if not os.environ.get("ISSUE53_RUNTIME_IMAGE"):
        pytest.skip("Set ISSUE53_RUNTIME_IMAGE to a cached Python runtime for Docker regression")
    build_and_sync(checkout)
    result = docker_build(checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    probe = (
        "from pathlib import Path; "
        "expected = {'index.html', 'assets/app.js', 'build-manifest.json'}; "
        "bundles = [Path('/app/www'), Path('/app/frontend/dist')]; "
        "assert all({p.relative_to(b).as_posix() for p in b.rglob('*') if p.is_file()} "
        "== expected for b in bundles); "
        "assert all((b / 'assets/app.js').read_text() == 'current dashboard' for b in bundles)"
    )
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--network=none",
            "--name", "contextcortex-issue53-verify",
            "--entrypoint", "python", "contextcortex-issue53-regression:test", "-c", probe,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
