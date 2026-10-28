#!/usr/bin/env python3
"""Probe exact wheel candidates; never certify mirror approval or quarantine age."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def canonical_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def resolve_candidate(requirements, constraints):
    text = constraints.read_text(encoding="utf-8")
    pins = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)", line)
        if not match or canonical_name(match[1]) in pins:
            raise ValueError("Constraints must contain unique exact pins only.")
        pins[canonical_name(match[1])] = match[2]
    if not pins:
        raise ValueError("Constraints must contain unique exact pins only.")

    command = [
        sys.executable, "-m", "pip", "install", "--quiet",
        "--disable-pip-version-check", "--no-cache-dir", "--dry-run",
        "--ignore-installed", "--only-binary=:all:", "--retries", "0",
        "--timeout", "15", "--report", "-",
        "--constraint", str(constraints), "--requirement", str(requirements),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=180,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Constrained resolution timed out; pip output withheld.") from None
    if completed.returncode:
        # Resolver output and pip reports can contain authenticated private URLs.
        raise ValueError(
            f"Constrained resolution failed (exit {completed.returncode}); "
            "pip output withheld. Investigate locally without publishing credentials."
        )
    try:
        report = json.loads(completed.stdout)
        target = {
            key: report["environment"][key]
            for key in ("python_full_version", "sys_platform")
        }
        if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]+", value)
                   for value in target.values()):
            raise ValueError("Invalid pip candidate report.")
        if not report["install"]:
            raise ValueError("Invalid pip candidate report.")
        artifacts = []
        for item in report["install"]:
            name = canonical_name(item["metadata"]["name"])
            version = item["metadata"]["version"]
            if pins.get(name) != version:
                raise ValueError("Resolved artifact is not exactly constrained.")
            digest = item["download_info"]["archive_info"].get("hashes", {}).get("sha256", "")
            if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                raise ValueError("Resolved artifact is missing a valid SHA-256.")
            artifacts.append({"name": name, "version": version, "sha256": digest.lower()})
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError("Invalid pip candidate report.") from None
    return {
        "status": "unreviewed-candidate",
        "scope": "wheel-only dry-run; not installation, approval or age verification",
        "target": target,
        "constraints_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "artifacts": sorted(artifacts, key=lambda artifact: artifact["name"]),
    }


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraints", type=Path, default=root / "python-constraints.txt")
    args = parser.parse_args()
    try:
        candidate = resolve_candidate(root / "requirements.txt", args.constraints)
    except (ValueError, OSError) as error:
        print(f"Candidate probe failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(candidate, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
