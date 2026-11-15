"""Negative custody tests for the isolated Oracle verification boundary."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from trading_oracle import local, probe

RUN = "a" * 32
IDENTITY = "b" * 64
NETWORK = "c" * 64


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> local.LocalRun:
    monkeypatch.setattr(local, "ROOT", tmp_path)
    monkeypatch.setattr(local, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(
        local, "private_directory", lambda path: path.mkdir(parents=True, exist_ok=True)
    )
    item = local.LocalRun(RUN, "desktop-linux")
    item.initialize()
    return item


@pytest.mark.parametrize("value", ["", "../outside", "A" * 32, "a" * 31, "a" * 33, "a" * 32 + "/x"])
def test_run_identifier_cannot_select_paths(value: str) -> None:
    with pytest.raises(local.OracleFailure):
        local.run_directory(value)


def test_path_guard_rejects_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local, "ROOT", tmp_path / "owned")
    with pytest.raises(local.OracleFailure):
        local.guarded(tmp_path / "outside")


def test_private_permissions_cannot_target_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local, "ROOT", tmp_path)
    monkeypatch.setattr(local, "CACHE", tmp_path / "cache")
    with pytest.raises(local.OracleFailure, match="private cache"):
        local.private_directory(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL regression")
def test_private_directory_replaces_unrelated_explicit_windows_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local, "ROOT", tmp_path)
    directory = tmp_path / "cache"
    monkeypatch.setattr(local, "CACHE", directory)
    directory.mkdir()
    # This disposable directory contains no credentials or application files.
    local.execute(["icacls", str(directory), "/grant", "*S-1-5-11:(OI)(CI)RX"])
    quoted = str(directory).replace("'", "''")
    inspect = (
        f"$acl=[System.IO.Directory]::GetAccessControl('{quoted}');"
        "foreach($rule in $acl.GetAccessRules($true,$true,"
        "[System.Security.Principal.SecurityIdentifier]))"
        "{[System.Console]::Out.WriteLine($rule.IdentityReference.Value)}"
    )
    before = local.execute(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", inspect])
    assert "S-1-5-11" in before.splitlines()
    local.private_directory(directory)
    after = local.execute(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", inspect])
    assert len(after.splitlines()) == 2
    assert "S-1-5-18" in after.splitlines()
    assert "S-1-5-11" not in after.splitlines()


def test_path_guard_rejects_hardlinked_secret(run: local.LocalRun) -> None:
    source = run.directory / "smoke_pwd"
    alias = run.directory / "alias"
    os.link(source, alias)
    with pytest.raises(local.OracleFailure):
        local.password(run.directory, "smoke_pwd")


def test_path_guard_rejects_reparse_component(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.lstat

    def linked(path: Path) -> Any:
        info = original(path)
        if path == run.directory:

            class Reparse:
                st_mode = info.st_mode
                st_nlink = info.st_nlink
                st_file_attributes = 0x400

            return Reparse()
        return info

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(local.OracleFailure):
        local.password(run.directory, "smoke_pwd")


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "c" * 32),
        ("context", "remote"),
        ("workspace", "elsewhere"),
        ("image", "untrusted:latest"),
        ("format", 2),
        ("status", "unknown"),
        ("outcome", "unknown"),
    ],
)
def test_manifest_mismatch_denies_cleanup(
    run: local.LocalRun, field: str, value: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = local.read_json(run.manifest)
    data[field] = value
    run.manifest.write_text(json.dumps(data))
    called: list[str] = []
    monkeypatch.setattr(run, "docker", lambda *args, **kwargs: called.append(args[0]))
    with pytest.raises(local.OracleFailure):
        run.cleanup()
    assert called == []
    assert (run.directory / "oracle_pwd").exists()


def test_unknown_manifest_fields_denied(run: local.LocalRun) -> None:
    data = local.read_json(run.manifest)
    data["dsn"] = "remote"
    run.manifest.write_text(json.dumps(data))
    with pytest.raises(local.OracleFailure):
        run.validate_manifest()


@pytest.mark.parametrize(
    "key",
    [
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "ORACLE_HOME",
        "TNS_ADMIN",
        "NLS_LANG",
        "TWO_TASK",
        "LOCAL",
        "ORA_SDTZ",
    ],
)
def test_ambient_target_overrides_denied(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(key, "private supplied value")
    with pytest.raises(local.OracleFailure) as caught:
        local.local_context()
    assert "private supplied value" not in str(caught.value)


def test_remote_context_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local.os, "environ", {})
    replies = iter(("remote", "tcp://127.0.0.1:2375"))
    monkeypatch.setattr(local, "execute", lambda *args, **kwargs: next(replies))
    with pytest.raises(local.OracleFailure):
        local.local_context()


@pytest.mark.parametrize(
    "details",
    [
        "windows|29.6.1|9000000000",
        "linux|27.9.1|9000000000",
        "linux|29.6.1|2000000000",
        "linux|invalid|9000000000",
    ],
)
def test_engine_profile_required(details: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local.os, "environ", {})
    replies = iter(("local", "unix:///var/run/docker.sock", details))
    monkeypatch.setattr(local, "execute", lambda *args, **kwargs: next(replies))
    with pytest.raises(local.OracleFailure):
        local.local_context()


def test_cleanup_preserves_custody_on_docker_failure(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*args: Any, **kwargs: Any) -> str:
        raise local.OracleFailure("Oracle verification tool failed.")

    monkeypatch.setattr(run, "docker", failed)
    with pytest.raises(local.OracleFailure):
        run.cleanup()
    assert (run.directory / "oracle_pwd").exists()
    assert run.validate_manifest()["status"] == "prepared"


def test_cleanup_with_no_resources_keeps_result_but_removes_secrets(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "resources", lambda kind: [])
    run.mark("passed")
    run.cleanup()
    assert run.validate_manifest()["outcome"] == "passed"
    assert run.validate_manifest()["status"] == "cleaned"
    assert not (run.directory / "oracle_pwd").exists()
    assert not (run.directory / "smoke_pwd").exists()
    run.cleanup()


def test_cleanup_refuses_unrelated_network_member(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        run, "resources", lambda kind: [IDENTITY if kind == "container" else NETWORK]
    )
    monkeypatch.setattr(
        run, "inspect", lambda kind, identity, **kwargs: {"Containers": {"d" * 64: {}}}
    )
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(run, "docker", lambda *args, **kwargs: commands.append(args))
    with pytest.raises(local.OracleFailure):
        run.cleanup()
    assert commands == []
    assert (run.directory / "oracle_pwd").exists()


def container_profile(run: local.LocalRun) -> dict[str, Any]:
    return {
        "Config": {"Image": local.IMAGE, "User": "oracle"},
        "Image": IDENTITY,
        "HostConfig": {
            "Privileged": False,
            "LogConfig": {"Type": "none"},
            "RestartPolicy": {"Name": "no"},
            "NetworkMode": run.name,
            "Memory": local.MEMORY,
            "MemorySwap": local.MEMORY,
            "NanoCpus": 2_000_000_000,
            "ShmSize": local.SHM,
            "PidsLimit": local.PIDS,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges"],
            "PortBindings": {"1521/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}]},
        },
        "Mounts": [
            {
                "Type": "bind",
                "RW": False,
                "Destination": "/run/secrets/oracle_pwd",
                "Source": str(run.directory / "oracle_pwd"),
            }
        ],
        "NetworkSettings": {"Networks": {run.name: {}}},
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("Privileged", True),
        ("NetworkMode", "host"),
        ("Memory", 0),
        ("MemorySwap", 0),
        ("NanoCpus", 0),
        ("ShmSize", 0),
        ("PidsLimit", 0),
        ("CapDrop", []),
        ("CapAdd", ["SYS_ADMIN"]),
        ("SecurityOpt", []),
        ("PortBindings", {"1521/tcp": [{"HostIp": "0.0.0.0", "HostPort": "1521"}]}),
    ],
)
def test_container_profile_denies_weakened_boundary(
    run: local.LocalRun, field: str, value: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "docker", lambda *args, **kwargs: IDENTITY)
    candidate = container_profile(run)
    run.validate_container(candidate)
    candidate["HostConfig"][field] = value
    with pytest.raises(ValueError):
        run.validate_container(candidate)


@pytest.mark.parametrize("change", ["mount", "write", "image", "user", "network"])
def test_container_target_and_mount_cannot_be_substituted(
    run: local.LocalRun, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "docker", lambda *args, **kwargs: IDENTITY)
    candidate = container_profile(run)
    if change == "mount":
        candidate["Mounts"][0]["Source"] = str(run.directory / "smoke_pwd")
    elif change == "write":
        candidate["Mounts"][0]["RW"] = True
    elif change == "network":
        candidate["NetworkSettings"]["Networks"]["another"] = {}
    else:
        candidate["Config"]["Image" if change == "image" else "User"] = "other"
    with pytest.raises(ValueError):
        run.validate_container(candidate)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"run_id": RUN, "port": True},
        {"run_id": RUN, "port": 1521, "dsn": "remote"},
        {"run_id": "../x", "port": 1521},
        {"run_id": RUN, "port": 65536},
        {"run_id": RUN, "port": 0},
        {"run_id": RUN, "port": "1521"},
    ],
)
def test_probe_descriptor_is_closed(value: object) -> None:
    with pytest.raises(ValueError):
        probe.descriptor(json.dumps(value))


def test_probe_descriptor_accepts_only_generated_run_and_port() -> None:
    assert probe.descriptor(json.dumps({"run_id": RUN, "port": 52171})) == (RUN, 52171)


def test_probe_failure_hides_supplied_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    monkeypatch.setattr(probe.sys, "stdin", io.StringIO("private-malformed-input"))
    assert probe.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Oracle smoke verification failed.\n"


def test_probe_rejects_duplicate_fields() -> None:
    with pytest.raises(ValueError):
        probe.descriptor('{"run_id":"' + RUN + '","port":1521,"port":1522}')


def test_manifest_rejects_boolean_format(run: local.LocalRun) -> None:
    value = local.read_json(run.manifest)
    value["format"] = True
    run.manifest.write_text(json.dumps(value))
    with pytest.raises(local.OracleFailure):
        run.validate_manifest()


@pytest.mark.parametrize(
    "change",
    [
        "internal",
        "binding",
        "icc",
        "extra",
        "driver",
        "ipv4_disabled",
        "ipv6_enabled",
        "ipv4_missing",
        "ipv6_missing",
        "ipv4_string",
        "ipv6_string",
    ],
)
def test_network_profile_is_exact(
    run: local.LocalRun, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = {
        "Labels": {local.LABEL: RUN, "com.trading.oracle.workspace": local.WORKSPACE},
        "Name": run.name,
        "Id": NETWORK,
        "Driver": "bridge",
        "Internal": False,
        "EnableIPv4": True,
        "EnableIPv6": False,
        "Options": dict(local.NETWORK_OPTIONS),
    }
    monkeypatch.setattr(run, "docker", lambda *args, **kwargs: json.dumps(data))
    run.inspect("network", NETWORK)
    if change == "internal":
        data["Internal"] = True
    elif change == "driver":
        data["Driver"] = "host"
    elif change == "extra":
        data["Options"]["unknown"] = "true"
    elif change == "binding":
        data["Options"]["com.docker.network.bridge.host_binding_ipv4"] = "0.0.0.0"
    elif change == "icc":
        data["Options"]["com.docker.network.bridge.enable_icc"] = "true"
    elif change == "ipv4_disabled":
        data["EnableIPv4"] = False
    elif change == "ipv6_enabled":
        data["EnableIPv6"] = True
    elif change == "ipv4_missing":
        del data["EnableIPv4"]
    elif change == "ipv6_missing":
        del data["EnableIPv6"]
    elif change == "ipv4_string":
        data["EnableIPv4"] = "true"
    else:
        data["EnableIPv6"] = "false"
    with pytest.raises(local.OracleFailure):
        run.inspect("network", NETWORK)


def test_process_lock_excludes_overlapping_cleanup_and_releases(run: local.LocalRun) -> None:
    with local.exclusive():
        with pytest.raises(local.OracleFailure):
            with local.exclusive():
                pytest.fail("second verifier entered")
    with local.exclusive():
        pass


def test_process_lock_releases_after_interruption(run: local.LocalRun) -> None:
    with pytest.raises(KeyboardInterrupt):
        with local.exclusive():
            raise KeyboardInterrupt
    with local.exclusive():
        pass


def test_missing_image_uses_only_fixed_pin_before_resources(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    digest = local.IMAGE.split(":23.26.3.0", 1)[0] + "@" + local.IMAGE.split("@", 1)[1]
    answers = iter(("", "", "sha256:" + IDENTITY, json.dumps([digest])))

    def docker(*args: str, **kwargs: Any) -> str:
        calls.append((args, kwargs))
        return next(answers)

    monkeypatch.setattr(run, "docker", docker)
    run.ensure_image()
    assert calls[1] == (("pull", "--quiet", local.IMAGE), {"timeout": 600})
    assert all(call[0][0] in {"image", "pull"} for call in calls)


def test_missing_image_download_failure_creates_no_resources(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str, **kwargs: Any) -> str:
        calls.append(args)
        if args[0] == "image":
            return ""
        raise local.OracleFailure("Oracle verification tool failed.")

    monkeypatch.setattr(run, "docker", docker)
    with pytest.raises(local.OracleFailure):
        run.ensure_image()
    assert calls[-1] == ("pull", "--quiet", local.IMAGE)
    assert all(call[0] in {"image", "pull"} for call in calls)


def test_image_without_expected_digest_is_denied(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = iter(("sha256:" + IDENTITY, "[]"))
    monkeypatch.setattr(run, "docker", lambda *args, **kwargs: next(values))
    with pytest.raises(local.OracleFailure):
        run.ensure_image()


def test_partial_initialization_keeps_manifest_and_can_clean(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = local.LocalRun("e" * 32, "desktop-linux")
    original = Path.open

    def fail_second_secret(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == partial.directory / "smoke_pwd":
            raise OSError("synthetic file failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_secret)
    with pytest.raises(OSError):
        partial.initialize()
    assert partial.created
    assert partial.validate_manifest()["status"] == "prepared"
    assert (partial.directory / "oracle_pwd").exists()
    monkeypatch.setattr(partial, "resources", lambda kind: [])
    partial.cleanup()
    assert partial.validate_manifest()["status"] == "cleaned"
    assert not (partial.directory / "oracle_pwd").exists()


def test_existing_directory_does_not_gain_cleanup_authority(run: local.LocalRun) -> None:
    other = local.LocalRun(RUN, "desktop-linux")
    before = run.manifest.read_bytes()
    with pytest.raises(FileExistsError):
        other.initialize()
    assert not other.created
    assert run.manifest.read_bytes() == before


def test_permissions_failure_precedes_secret_creation(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending = local.LocalRun("e" * 32, "desktop-linux")

    def denied(path: Path) -> None:
        if path == pending.directory / "config":
            raise local.OracleFailure("Cannot establish private Oracle file permissions.")
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(local, "private_directory", denied)
    with pytest.raises(local.OracleFailure):
        pending.initialize()
    assert pending.validate_manifest()["status"] == "prepared"
    assert not (pending.directory / "oracle_pwd").exists()
    assert not (pending.directory / "smoke_pwd").exists()
    monkeypatch.setattr(pending, "resources", lambda kind: [])
    pending.cleanup()
    assert pending.validate_manifest()["status"] == "cleaned"


def test_cleanup_custody_can_stop_own_runtime_profile_failure(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_id = "sha256:" + IDENTITY
    run.record_resource("image", image_id)
    run.record_resource("container", IDENTITY)
    candidate = container_profile(run)
    candidate["Config"]["Labels"] = {
        local.LABEL: RUN,
        "com.trading.oracle.workspace": local.WORKSPACE,
    }
    candidate["Name"] = "/" + run.name
    candidate["Id"] = IDENTITY
    candidate["Image"] = image_id
    candidate["HostConfig"]["Memory"] = 0
    present = True
    removed: list[tuple[str, ...]] = []

    def docker(*args: str, **kwargs: Any) -> str:
        nonlocal present
        if args[0] == "image":
            return image_id
        if args[:2] == ("container", "inspect"):
            return json.dumps(candidate)
        if args == ("rm", "--force", IDENTITY):
            present = False
            removed.append(args)
            return IDENTITY
        pytest.fail("unexpected Docker operation")

    monkeypatch.setattr(run, "docker", docker)
    monkeypatch.setattr(
        run, "resources", lambda kind: [IDENTITY] if present and kind == "container" else []
    )
    assert run.inspect("container", IDENTITY, custody_only=True)["Id"] == IDENTITY
    with pytest.raises(local.OracleFailure):
        run.inspect("container", IDENTITY)
    candidate["Id"] = "d" * 64
    with pytest.raises(local.OracleFailure):
        run.inspect("container", IDENTITY, custody_only=True)
    candidate["Id"] = IDENTITY
    run.mark("failed")
    run.cleanup()
    assert removed == [("rm", "--force", IDENTITY)]
    assert not present
    assert not (run.directory / "oracle_pwd").exists()
    assert not (run.directory / "smoke_pwd").exists()
    assert run.validate_manifest()["status"] == "cleaned"
    assert run.validate_manifest()["outcome"] == "failed"


def test_recorded_resource_cannot_be_replaced(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    run.record_resource("container", IDENTITY)
    monkeypatch.setattr(run, "docker", lambda *args, **kwargs: "d" * 64)
    with pytest.raises(local.OracleFailure):
        run.resources("container")


def test_bootstrap_waits_for_writable_unrestricted_pdb(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    readiness_calls = 0
    bootstrap_calls = 0

    def sql(statement: str, *, required: bool = True) -> str:
        nonlocal readiness_calls, bootstrap_calls
        if not required:
            readiness_calls += 1
            assert "FROM v$pdbs" in statement
            assert "name = 'FREEPDB1'" in statement
            assert "open_mode = 'READ WRITE'" in statement
            assert "restricted = 'NO'" in statement
            return "" if readiness_calls == 1 else "TRADING_READY"
        assert readiness_calls == 2
        assert "CREATE USER trading_smoke" in statement
        bootstrap_calls += 1
        return ""

    monkeypatch.setattr(run, "port", lambda: 15210)
    monkeypatch.setattr(run, "sql", sql)
    monkeypatch.setattr(local.time, "sleep", lambda seconds: None)
    run.bootstrap()
    assert bootstrap_calls == 1


def test_bootstrap_readiness_timeout_never_creates_identity(
    run: local.LocalRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter((0.0, 0.0, 301.0))

    def sql(statement: str, *, required: bool = True) -> str:
        assert not required
        assert "CREATE USER" not in statement
        return ""

    monkeypatch.setattr(run, "port", lambda: 15210)
    monkeypatch.setattr(run, "sql", sql)
    monkeypatch.setattr(local.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(local.time, "sleep", lambda seconds: None)
    with pytest.raises(local.OracleFailure, match="did not become ready"):
        run.bootstrap()


def test_probe_uses_only_its_locked_virtualenv() -> None:
    assert probe.package_directory().is_dir()


def test_probe_rejects_foreign_python_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe.sys, "prefix", str(probe.ROOT / "elsewhere"))
    with pytest.raises(ValueError):
        probe.package_directory()


def test_probe_rejects_foreign_package_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe.sysconfig, "get_path", lambda name: str(probe.ROOT))
    with pytest.raises(ValueError):
        probe.package_directory()
