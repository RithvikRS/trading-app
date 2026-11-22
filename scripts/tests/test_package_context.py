"""Build policy unit tests; actual Docker context export runs in operations."""

import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import operations, package_context, policy
from scripts.tooling import ROOT, CheckFailure


class BuildContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = set(package_context.FIXED_INPUTS)
        for parent, suffixes in package_context.SOURCE_DIRECTORIES.items():
            for suffix in suffixes:
                paths.add(f"{parent}/included{suffix}")
        self.paths = tuple(sorted(paths))
        for name in self.paths:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "local source bytes; do not copy into synthetic fixture\n", encoding="utf-8"
            )
        (self.root / package_context.MANIFEST).write_text(
            "\n".join(self.paths) + "\n", encoding="utf-8"
        )
        (self.root / ".dockerignore").write_text(
            package_context.ignore_text(self.paths), encoding="utf-8"
        )
        self.tracking = patch(
            "scripts.package_context.tracked_inputs", return_value=frozenset(self.paths)
        )
        self.tracking.start()
        self.addCleanup(self.tracking.stop)

    def test_exact_inputs_and_descendant_denial(self):
        self.assertEqual(package_context.validate_build_context(self.root), self.paths)
        lines = (self.root / ".dockerignore").read_text().splitlines()
        self.assertEqual(lines[0], "**")
        self.assertEqual(lines[1::2], [f"!{name}" for name in self.paths])
        self.assertEqual(lines[2::2], [f"{name}/**" for name in self.paths])

    def test_broadening_and_rule_order_are_rejected(self):
        good = package_context.ignore_text(self.paths)
        variants = [
            good + "!backend/\n",
            good + "!frontend/\n",
            good + "!backend/trading_api/*.py\n",
            good + "!frontend/workspace/src/*.tsx\n",
            good.replace("backend/trading_api/included.py/**\n", ""),
            "\n".join(reversed(good.splitlines())) + "\n",
        ]
        for content in variants:
            with self.subTest(content=content[-60:]):
                (self.root / ".dockerignore").write_text(content, encoding="utf-8")
                with self.assertRaises(CheckFailure):
                    package_context.validate_build_context(self.root)

    def test_manifest_paths_duplicates_and_order_are_rejected(self):
        for path in ["../outside.py", "/backend/a.py", "backend/trading_api/*.py", "backend/.env"]:
            with self.subTest(path=path):
                (self.root / package_context.MANIFEST).write_text(path + "\n", encoding="utf-8")
                with self.assertRaises(CheckFailure):
                    package_context.validate_build_context(self.root)
        for paths in [(*self.paths, self.paths[0]), tuple(reversed(self.paths))]:
            (self.root / package_context.MANIFEST).write_text("\n".join(paths) + "\n")
            with self.assertRaises(CheckFailure):
                package_context.validate_build_context(self.root)

    def test_tracking_drift_and_missing_input_fail(self):
        with patch("scripts.package_context.tracked_inputs", return_value=frozenset()):
            with self.assertRaises(CheckFailure):
                package_context.validate_build_context(self.root)
        (self.root / self.paths[0]).unlink()
        with self.assertRaises(CheckFailure):
            package_context.validate_build_context(self.root)

    def test_directory_substitution_fails_before_build(self):
        target = self.root / "backend/trading_api/included.py"
        target.unlink()
        target.mkdir()
        (target / "private.txt").write_text("synthetic excluded input")
        with self.assertRaises(CheckFailure):
            package_context.validate_build_context(self.root)

    def test_hardlinked_source_and_policy_files_fail(self):
        for index, name in enumerate(
            ["backend/trading_api/included.py", ".dockerignore", package_context.MANIFEST]
        ):
            target = self.root / name
            alias = self.root / f"hardlink-{index}"
            alias.hardlink_to(target)
            try:
                self.assertGreater(target.stat().st_nlink, 1)
                with self.assertRaises(CheckFailure):
                    package_context.validate_build_context(self.root)
            finally:
                alias.unlink()

    def test_link_and_windows_reparse_metadata_fail(self):
        original = Path.lstat
        for target in [
            self.root / "backend/trading_api/included.py",
            self.root / "backend/trading_api",
            self.root / ".dockerignore",
            self.root / package_context.MANIFEST,
        ]:
            for symbolic in [False, True]:

                def substituted(path, target=target, symbolic=symbolic, **kwargs):
                    if path == target:
                        return SimpleNamespace(
                            st_mode=stat.S_IFLNK if symbolic else original(path).st_mode,
                            st_file_attributes=0 if symbolic else 0x400,
                        )
                    return original(path, **kwargs)

                with (
                    self.subTest(path=target, symbolic=symbolic),
                    patch.object(Path, "lstat", substituted),
                ):
                    with self.assertRaises(CheckFailure):
                        package_context.validate_build_context(self.root)

    def test_dockerfile_specific_ignore_is_rejected(self):
        (self.root / "infra/application/Dockerfile.dockerignore").write_text("**\n!**\n")
        with self.assertRaises(CheckFailure):
            package_context.validate_build_context(self.root)

    def test_actual_probe_receives_only_synthetic_inputs_and_is_bounded(self):
        directory = self.root / "owned-run"
        directory.mkdir()
        calls = []

        def fake_docker(args, **kwargs):
            calls.append((args, kwargs))
            context = Path(args[-1])
            output = Path(args[args.index("--output") + 1].removeprefix("type=local,dest="))
            for name in self.paths:
                source = context / name
                payload = source.read_bytes()
                expected = (
                    package_context.PROBE_DOCKERFILE.encode()
                    if name == "infra/application/Dockerfile"
                    else package_context.SYNTHETIC_INPUT
                )
                self.assertEqual(payload, expected)
                target = output / "context" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                if name.startswith("backend/trading_connectors/"):
                    target = output / "connectors" / Path(name).name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            for name in package_context.synthetic_exclusions():
                self.assertEqual((context / name).read_bytes(), package_context.SYNTHETIC_EXCLUDED)

        package_context.verify_build_context(
            self.root, directory, ["docker", "--context", "synthetic-local"], fake_docker
        )
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(kwargs, {"timeout": 120})
        self.assertEqual(args[:5], ["docker", "--context", "synthetic-local", "buildx", "build"])
        self.assertEqual(args[args.index("--builder") + 1], "synthetic-local")
        self.assertIn("--network=none", args)
        self.assertIn("--no-cache", args)
        self.assertNotIn("--push", args)
        self.assertNotIn("--pull", args)

    def test_probe_failure_and_missing_export_fail(self):
        for failing in [True, False]:
            with self.subTest(failing=failing):
                directory = self.root / f"run-{failing}"
                directory.mkdir()

                def fake_docker(*args, failing=failing, **kwargs):
                    if failing:
                        raise CheckFailure("Synthetic command failure.")

                with self.assertRaises(CheckFailure):
                    package_context.verify_build_context(
                        self.root,
                        directory,
                        ["docker", "--context", "synthetic-local"],
                        fake_docker,
                    )

    def test_export_rejects_missing_extra_or_changed_content(self):
        export = self.root / "export"
        export.mkdir()
        expected = {"context/allowed.py": b"synthetic"}
        target = export / "context/allowed.py"
        target.parent.mkdir()
        with self.assertRaises(CheckFailure):
            package_context.validate_context_export(export, expected)
        target.write_bytes(b"synthetic")
        package_context.validate_context_export(export, expected)
        target.write_bytes(b"changed")
        with self.assertRaises(CheckFailure):
            package_context.validate_context_export(export, expected)
        target.write_bytes(b"synthetic")
        (export / "private.txt").write_bytes(b"excluded")
        with self.assertRaises(CheckFailure):
            package_context.validate_context_export(export, expected)


class BuildEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.cache_patch = patch("scripts.operations.CACHE", self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.private_patch = patch(
            "scripts.operations.private_directory",
            side_effect=lambda path: path.mkdir(mode=0o700, parents=True, exist_ok=True),
        )
        self.private_patch.start()
        self.addCleanup(self.private_patch.stop)

    def ambient(self):
        return {
            "PATH": "synthetic-path",
            "BUILDX_CONFIG": str(self.cache / "foreign-builder-state"),
            "BUILDX_BUILDER": "synthetic-remote",
            "buildx_metadata_provenance": "max",
            "BUILDKIT_HOST": "tcp://synthetic.invalid:1234",
            "buildkit_progress": "plain",
            "COMPOSE_BAKE": "true",
            "compose_file": "synthetic-foreign.yaml",
            "TRADING_API_SECRET": "synthetic-private",
            "DOCKER_BUILDKIT": "0",
        }

    def test_fresh_state_replaces_ambient_builder_controls(self):
        directory = self.cache / "run"
        directory.mkdir()
        foreign = self.cache / "foreign-builder-state"
        foreign.mkdir()
        marker = foreign / "same-name-instance"
        marker.write_text("synthetic foreign builder")
        original = self.ambient()
        environment = operations.build_environment(directory, original)
        self.assertEqual(
            environment, {"PATH": "synthetic-path", "BUILDX_CONFIG": str(directory / "buildx")}
        )
        self.assertEqual(list((directory / "buildx").iterdir()), [])
        self.assertEqual(marker.read_text(), "synthetic foreign builder")
        self.assertEqual(original, self.ambient())

    def test_existing_builder_state_and_unowned_directory_fail(self):
        directory = self.cache / "run"
        directory.mkdir()
        (directory / "buildx").mkdir()
        (directory / "buildx/old-state").write_text("synthetic")
        with self.assertRaises(CheckFailure):
            operations.build_environment(directory, self.ambient())
        self.assertTrue((directory / "buildx/old-state").is_file())
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(CheckFailure):
                operations.build_environment(Path(other), self.ambient())

    def test_builder_state_permission_failure_does_not_return_environment(self):
        directory = self.cache / "run"
        directory.mkdir()
        with patch("scripts.operations.private_directory", side_effect=OSError()):
            with self.assertRaises(CheckFailure):
                operations.build_environment(directory, self.ambient())

    def test_probe_and_production_failures_share_isolation_and_cleanup(self):
        for fail_probe in [True, False]:
            with self.subTest(fail_probe=fail_probe):
                calls = []
                configurations = []

                def certificate(directory):
                    for name in ["certificate.pem", "key.pem"]:
                        (directory / name).write_text("synthetic certificate input")
                    return object()

                def fake_command(
                    args, *, environment=None, calls=calls, configurations=configurations, **kwargs
                ):
                    self.assertIsNotNone(environment)
                    environment = dict(environment)
                    self.assertEqual(environment["PATH"], "synthetic-path")
                    configurations.append(Path(environment["BUILDX_CONFIG"]))
                    self.assertEqual(
                        {
                            key: value
                            for key, value in environment.items()
                            if key.upper().startswith(("BUILDX_", "BUILDKIT_", "COMPOSE_"))
                        },
                        {"BUILDX_CONFIG": str(configurations[-1])},
                    )
                    self.assertNotIn("DOCKER_BUILDKIT", environment)
                    self.assertNotIn("TRADING_API_SECRET", environment)
                    calls.append(args)
                    if "buildx" in args and "--load" in args:
                        self.assertEqual(
                            args,
                            [
                                "docker",
                                "--context",
                                "synthetic-local",
                                "buildx",
                                "build",
                                "--builder",
                                "synthetic-local",
                                "--pull",
                                "--load",
                                "--file",
                                str(ROOT / "infra/application/Dockerfile"),
                                "--tag",
                                "trading-app:local-rehearsal",
                                str(ROOT),
                            ],
                        )
                        self.assertEqual(kwargs, {"timeout": 900})
                        raise CheckFailure("Synthetic production failure.")
                    return ""

                def fake_probe(root, directory, docker, run, fail_probe=fail_probe):
                    self.assertEqual(list((directory / "buildx").iterdir()), [])
                    run([*docker, "buildx", "build", "--builder", "synthetic-local"], timeout=120)
                    if fail_probe:
                        raise CheckFailure("Synthetic probe failure.")

                with (
                    patch("scripts.operations.os", SimpleNamespace(environ=self.ambient())),
                    patch("scripts.operations.validate_packaging"),
                    patch("scripts.operations.local_context", return_value="synthetic-local"),
                    patch("scripts.operations.certificate", side_effect=certificate),
                    patch("scripts.operations.command", side_effect=fake_command),
                    patch("scripts.operations.verify_build_context", side_effect=fake_probe),
                    self.assertRaises(CheckFailure),
                ):
                    operations.main()
                self.assertGreaterEqual(len(calls), 2)
                self.assertEqual(len(set(configurations)), 1)
                self.assertEqual(calls[-1][-3:], ["down", "--timeout", "10"])
                self.assertFalse(configurations[0].parent.exists())
                self.assertFalse(any("up" in args for args in calls))


class TrackingAndIntegrationTests(unittest.TestCase):
    def inventory(self, names):
        return "".join(f"100644 {'a' * 40} 0\t{name}\0" for name in sorted(names))

    def test_tracking_reads_index_not_untracked_working_files(self):
        result = subprocess.CompletedProcess(
            [], 0, self.inventory(package_context.FIXED_INPUTS), ""
        )
        with patch("scripts.package_context.subprocess.run", return_value=result) as run:
            self.assertEqual(package_context.tracked_inputs(ROOT), package_context.FIXED_INPUTS)
        self.assertEqual(run.call_args.args[0], ["git", "ls-files", "--stage", "-z"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_git_failure_links_and_merge_conflicts_fail(self):
        good = self.inventory(package_context.FIXED_INPUTS)
        for result in [
            subprocess.CompletedProcess([], 1, "", "synthetic private detail"),
            subprocess.CompletedProcess([], 0, good.replace("100644", "120000", 1), ""),
            subprocess.CompletedProcess([], 0, good.replace(" 0\t", " 2\t", 1), ""),
            subprocess.CompletedProcess([], 0, "malformed", ""),
            subprocess.CompletedProcess([], 0, good + good, ""),
        ]:
            with patch("scripts.package_context.subprocess.run", return_value=result):
                with self.assertRaises(CheckFailure):
                    package_context.tracked_inputs(ROOT)
        for error in [OSError(), subprocess.TimeoutExpired(["git"], 15)]:
            with patch("scripts.package_context.subprocess.run", side_effect=error):
                with self.assertRaises(CheckFailure):
                    package_context.tracked_inputs(ROOT)

    def test_packaging_policy_includes_context_validation(self):
        with patch("scripts.policy.validate_build_context") as validate:
            policy.validate_packaging(ROOT)
        validate.assert_called_once_with(ROOT)


if __name__ == "__main__":
    unittest.main()
