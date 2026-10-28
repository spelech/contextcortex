"""Candidate resolution tests independent of application dependencies."""

import copy
import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import probe_python_baseline as probe


class TestPythonBaselineProbe(unittest.TestCase):
    def setUp(self):
        self.report = {
            "environment": {"python_full_version": "3.12.10", "sys_platform": "win32"},
            "install": [{
                "metadata": {"name": "example_package", "version": "1.2.3"},
                "download_info": {
                    "url": "https://user:secret@private.invalid/example.whl",
                    "archive_info": {"hashes": {"sha256": "a" * 64}},
                },
            }],
        }

    def run_probe(self, report=None, returncode=0, constraints="example-package==1.2.3\n"):
        completed = subprocess.CompletedProcess(
            [], returncode, json.dumps(self.report if report is None else report),
            "https://user:secret@private.invalid/ resolver failure",
        )
        with patch.object(Path, "read_text", return_value=constraints), \
                patch.object(probe.subprocess, "run", return_value=completed) as run:
            result = probe.resolve_candidate(Path("requirements.txt"), Path("candidate.txt"))
        return result, run.call_args.args[0]

    def test_resolves_cleanly_with_constraints_and_emits_only_candidate_inventory(self):
        result, command = self.run_probe()
        self.assertEqual(result["status"], "unreviewed-candidate")
        self.assertEqual(result["artifacts"], [{
            "name": "example-package", "version": "1.2.3", "sha256": "a" * 64,
        }])
        self.assertEqual(result["target"], self.report["environment"])
        self.assertNotIn("private.invalid", json.dumps(result))
        self.assertNotIn("secret", json.dumps(result))
        for flag in ("--dry-run", "--ignore-installed", "--no-cache-dir", "--quiet"):
            self.assertIn(flag, command)
        self.assertIn("--only-binary=:all:", command)
        self.assertEqual(command[command.index("--constraint") + 1], "candidate.txt")
        self.assertEqual(command[command.index("--requirement") + 1], "requirements.txt")
        self.assertEqual(command[command.index("--retries") + 1], "0")
        self.assertNotIn("--extra-index-url", command)

    def test_failed_resolver_does_not_expose_private_output_or_retry(self):
        with self.assertRaisesRegex(ValueError, r"resolution failed \(exit 1\)") as error:
            self.run_probe(returncode=1)
        self.assertNotIn("private.invalid", str(error.exception))
        self.assertNotIn("secret", str(error.exception))

    def test_rejects_unpinned_or_mismatched_transitive_artifacts(self):
        for constraints in ("other==1.2.3\n", "example-package==1.2.4\n"):
            with self.subTest(constraints=constraints), \
                    self.assertRaisesRegex(ValueError, "not exactly constrained"):
                self.run_probe(constraints=constraints)

    def test_rejects_missing_or_invalid_artifact_hash(self):
        for hashes in ({}, {"sha256": "invalid"}):
            report = copy.deepcopy(self.report)
            report["install"][0]["download_info"]["archive_info"]["hashes"] = hashes
            with self.subTest(hashes=hashes), self.assertRaisesRegex(ValueError, "SHA-256"):
                self.run_probe(report=report)

    def test_rejects_non_exact_constraints_before_contacting_pip(self):
        for constraints in ("example>=1\n", "--extra-index-url https://private.invalid\n",
                            "example==1.*\n", "example==1\nexample==2\n"):
            with self.subTest(constraints=constraints), \
                    patch.object(Path, "read_text", return_value=constraints), \
                    patch.object(probe.subprocess, "run") as run, \
                    self.assertRaisesRegex(ValueError, "exact pins"):
                probe.resolve_candidate(Path("requirements.txt"), Path("candidate.txt"))
            run.assert_not_called()

    def test_rejects_invalid_or_empty_report(self):
        for report in ({}, {"install": []}, {"install": [{"metadata": {}}]}):
            with self.subTest(report=report), self.assertRaisesRegex(ValueError, "report"):
                self.run_probe(report=report)

    def test_timeout_does_not_expose_captured_private_output(self):
        timeout = subprocess.TimeoutExpired(
            ["pip"], 180, output="https://user:secret@private.invalid/",
        )
        with patch.object(Path, "read_text", return_value="example-package==1.2.3"), \
                patch.object(probe.subprocess, "run", side_effect=timeout), \
                self.assertRaisesRegex(ValueError, "timed out") as error:
            probe.resolve_candidate(Path("requirements.txt"), Path("candidate.txt"))
        self.assertNotIn("secret", str(error.exception))

    def test_cli_writes_no_inventory_when_resolution_fails(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        completed = subprocess.CompletedProcess([], 1, "", "https://secret@private.invalid")
        with patch("sys.argv", ["probe_python_baseline.py"]), \
                patch.object(Path, "read_text", return_value="example-package==1.2.3"), \
                patch.object(probe.subprocess, "run", return_value=completed) as run, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(probe.main(), 1)
        run.assert_called_once()
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("resolution failed", stderr.getvalue())
        self.assertNotIn("secret", stderr.getvalue())

    def test_cli_emits_json_inventory_for_successful_probe(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        completed = subprocess.CompletedProcess([], 0, json.dumps(self.report), "")
        with patch("sys.argv", ["probe_python_baseline.py"]), \
                patch.object(Path, "read_text", return_value="example-package==1.2.3"), \
                patch.object(probe.subprocess, "run", return_value=completed), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(probe.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "unreviewed-candidate")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("secret", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
