import copy
import hashlib
import io
import json
import subprocess
import tarfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml
from scripts import checks, policy, tooling
from scripts.tooling import ROOT, CheckFailure


class RunnerTests(unittest.TestCase):
    def test_failed_command_does_not_disclose_captured_output(self):
        output = io.StringIO()
        result = subprocess.CompletedProcess([], 1, "synthetic-sensitive", "synthetic-sensitive")
        with patch("scripts.checks.subprocess.run", return_value=result), redirect_stdout(output):
            with self.assertRaises(CheckFailure):
                checks.run("scanner", ["scanner"], quiet=True)
        self.assertNotIn("synthetic-sensitive", output.getvalue())

    def test_missing_or_timed_out_command_is_failure(self):
        for error in [FileNotFoundError(), subprocess.TimeoutExpired(["tool"], 1)]:
            with (
                self.subTest(error=type(error).__name__),
                patch("scripts.checks.subprocess.run", side_effect=error),
            ):
                with self.assertRaises(CheckFailure):
                    checks.run("scanner", ["tool"], quiet=True)

    def test_all_stops_after_failure_without_pass_message(self):
        output = io.StringIO()
        with (
            patch("sys.argv", ["checks.py", "all"]),
            patch("scripts.checks.repository"),
            patch("scripts.checks.backend", side_effect=CheckFailure("Audit unavailable.")),
            patch("scripts.checks.frontend") as frontend,
            redirect_stdout(output),
            redirect_stderr(output),
        ):
            self.assertEqual(checks.main(), 1)
        frontend.assert_not_called()
        self.assertNotIn("PASS:", output.getvalue())

    def test_source_snapshot_includes_untracked_but_rejects_path_escape(self):
        with checks.scratch() as root:
            (root / "tracked.txt").write_text("tracked")
            (root / "new.txt").write_text("untracked")
            target = root / "snapshot"
            with patch("scripts.checks.run", return_value="tracked.txt\0new.txt\0deleted.txt\0"):
                checks.source_snapshot(target, root)
            self.assertEqual((target / "new.txt").read_text(), "untracked")
            self.assertFalse((target / "deleted.txt").exists())
            with patch("scripts.checks.run", return_value="../outside.txt\0"):
                with self.assertRaises(ValueError):
                    checks.source_snapshot(target, root)

    def test_broken_documentation_link_fails(self):
        with checks.scratch() as root:
            (root / "docs").mkdir()
            (root / "README.md").write_text("[Missing](docs/missing.md)")
            with self.assertRaises(CheckFailure):
                checks.documentation_links(root)


class ToolIntegrityTests(unittest.TestCase):
    def manifest(self, root: Path):
        manifest = json.loads((ROOT / "scripts/tools.json").read_text())
        (root / "scripts").mkdir()
        (root / "scripts/tools.json").write_text(json.dumps(manifest))
        return manifest

    def test_tampered_cached_binary_is_not_replaced_or_executed(self):
        with checks.scratch() as root:
            manifest = self.manifest(root)
            target = (
                root
                / ".cache/check-tools"
                / f"gitleaks-{manifest['gitleaks']['version']}"
                / "windows-x86_64/gitleaks.exe"
            )
            target.parent.mkdir(parents=True)
            target.write_bytes(b"changed binary")
            with (
                patch("platform.system", return_value="Windows"),
                patch("platform.machine", return_value="AMD64"),
                patch("urllib.request.urlopen") as network,
            ):
                with self.assertRaisesRegex(CheckFailure, "checksum mismatch"):
                    tooling.get_tool("gitleaks", root)
            network.assert_not_called()
            self.assertEqual(target.read_bytes(), b"changed binary")

    def test_download_checksum_is_checked_before_archive_parsing(self):
        with checks.scratch() as root:
            self.manifest(root)
            response = io.BytesIO(b"untrusted archive")
            response.url = "https://github.com/synthetic"
            with (
                patch("platform.system", return_value="Linux"),
                patch("platform.machine", return_value="x86_64"),
                patch("urllib.request.urlopen", return_value=response),
                patch("scripts.tooling.extract_binary") as extract,
            ):
                with self.assertRaisesRegex(CheckFailure, "checksum mismatch"):
                    tooling.get_tool("gitleaks", root)
            extract.assert_not_called()
            self.assertFalse((root / ".cache/check-tools").exists())

    def test_archive_paths_are_not_extracted(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("../escape", "unexpected")
            archive.writestr("gitleaks.exe", "expected")
        self.assertEqual(
            tooling.extract_binary(payload.getvalue(), "tool.zip", "gitleaks.exe"), b"expected"
        )

    def test_tar_symlink_member_is_rejected(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            link = tarfile.TarInfo("gitleaks")
            link.type = tarfile.SYMTYPE
            link.linkname = "../outside"
            archive.addfile(link)
        with self.assertRaises(CheckFailure):
            tooling.extract_binary(payload.getvalue(), "tool.tar.gz", "gitleaks")

    def test_correct_checksum_passes_and_incorrect_pin_fails(self):
        tooling.verify_hash(b"binary", hashlib.sha256(b"binary").hexdigest())
        with self.assertRaises(CheckFailure):
            tooling.verify_hash(b"binary", "missing")


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.document = yaml.load(
            (ROOT / ".github/workflows/verification.yml").read_text(), Loader=yaml.BaseLoader
        )

    def test_current_policy_passes(self):
        policy.validate_repository()

    def test_unsafe_workflow_changes_fail(self):
        mutations = [
            lambda d: d.update({"defaults": {"run": {"shell": "bash -c 'exit 0'"}}}),
            lambda d: d["permissions"].update(contents="write"),
            lambda d: d["on"].update(pull_request_target={}),
            lambda d: d["on"]["push"].update({"paths-ignore": ["docs/**"]}),
            lambda d: d["jobs"]["backend"].update({"if": "false"}),
            lambda d: d["jobs"]["frontend"].update({"continue-on-error": "true"}),
            lambda d: d["jobs"]["backend"]["steps"][0].update(uses="actions/checkout@main"),
            lambda d: d["jobs"]["backend"]["steps"][0]["with"].update(
                {"persist-credentials": "true"}
            ),
            lambda d: d["jobs"]["repository"]["steps"][0]["with"].update({"fetch-depth": "1"}),
            lambda d: d["jobs"]["backend"]["steps"][1]["with"].update({"enable-cache": "true"}),
            lambda d: d["jobs"]["backend"]["steps"][-1].update(run="echo skipped"),
            lambda d: d["jobs"]["frontend"]["steps"][-1].update({"continue-on-error": "true"}),
            lambda d: d["jobs"].pop("frontend"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                changed = copy.deepcopy(self.document)
                mutate(changed)
                with self.assertRaises(CheckFailure):
                    policy.validate_workflow(changed)


if __name__ == "__main__":
    unittest.main()
