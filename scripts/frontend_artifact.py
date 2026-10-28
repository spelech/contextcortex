#!/usr/bin/env python3
"""Build, synchronize, and verify the dashboard shipped by image overlays."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


MANIFEST = "build-manifest.json"


def inventory(directory: Path, *, sources: bool = False) -> dict[str, str]:
    if sources:
        paths = [path for path in directory.iterdir() if path.is_file()]
        for name in ("src", "public", "packages", "scripts"):
            paths.extend((directory / name).rglob("*"))
        paths = [
            path for path in paths
            if path.name != ".npmrc"
            and not path.name.endswith((".tsbuildinfo", ".log"))
        ]
    else:
        paths = [path for path in directory.rglob("*") if path != directory / MANIFEST]
    result = {}
    for path in sorted(paths):
        if not path.is_file():
            continue
        content = path.read_bytes()
        if sources:
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                content = content.replace(b"\r\n", b"\n")
        result[path.relative_to(directory).as_posix()] = hashlib.sha256(content).hexdigest()
    return result


def verify(root: Path, bundle: Path) -> None:
    manifest_path = bundle / MANIFEST
    if not manifest_path.is_file():
        raise ValueError(
            "Unverified dashboard: missing build-manifest.json. "
            "Run python scripts/frontend_artifact.py build, then sync; "
            "do not stamp an existing bundle."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Unverified dashboard: unsupported build manifest.")
    if manifest.get("sources") != inventory(root / "frontend", sources=True):
        raise ValueError("Stale dashboard: frontend inputs changed; rebuild and sync.")
    if not (bundle / "index.html").is_file() or manifest.get("files") != inventory(bundle):
        raise ValueError("Invalid dashboard: output files changed; rebuild and sync.")


def build(root: Path) -> None:
    frontend = root / "frontend"
    dist = frontend / "dist"
    before = inventory(frontend, sources=True)
    if dist.exists():
        shutil.rmtree(dist)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise ValueError("Dashboard build requires npm and the locked frontend dependencies.")
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)
    if before != inventory(frontend, sources=True):
        raise ValueError("Dashboard source changed during build; retry with stable inputs.")
    if not (dist / "index.html").is_file():
        raise ValueError("Dashboard build did not produce dist/index.html.")
    manifest = {"schema": 1, "sources": before, "files": inventory(dist)}
    (dist / MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify(root, dist)


def sync(root: Path) -> None:
    dist = root / "frontend" / "dist"
    verify(root, dist)
    destination = root / "www"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(dist, destination)
    verify(root, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "sync", "verify"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "build":
            build(root)
        elif args.command == "sync":
            sync(root)
        else:
            verify(root, root / "www")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Dashboard artifact error: {error}", file=sys.stderr)
        return 1
    print(f"Dashboard artifact {args.command}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
