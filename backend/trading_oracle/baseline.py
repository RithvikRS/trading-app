"""Run the retained smoke and ownership acceptance in one owned disposable instance."""

import json
import os
import secrets
import subprocess
import sys

from trading_oracle.baseline_protocol import digest, parse
from trading_oracle.local import ROOT, LocalRun, OracleFailure, exclusive, guarded, local_context


def baseline_probe(run: LocalRun) -> None:
    source = digest(ROOT)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "HOME", "USERPROFILE"}
    }
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(ROOT / "backend/trading_oracle/baseline_probe.py")],
            input=json.dumps({"run_id": run.run_id, "port": run.port()}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=900,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        raise OracleFailure("Oracle baseline probe did not complete.") from None
    try:
        if result.stderr or digest(ROOT) != source:
            raise ValueError("Invalid Oracle baseline result.")
        report = parse(result.stdout, source)
        if (result.returncode == 0) != (report["status"] == "passed"):
            raise ValueError("Invalid Oracle baseline result.")
    except ValueError:
        report = {
            "version": 1,
            "status": "failed",
            "stage": "setup",
            "completed": [],
            "error_code": None,
            "source_sha256": source,
        }
    receipt = guarded(run.directory / "baseline-result.json")
    with receipt.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, sort_keys=True) + "\n")
    if report["status"] != "passed":
        raise OracleFailure("Oracle baseline probe failed.")


def check() -> str:
    with exclusive():
        run = LocalRun(secrets.token_hex(16), local_context())
        print(f"Oracle baseline verification run: {run.run_id}", flush=True)
        try:
            run.initialize()
            run.start()
            run.bootstrap()
            run.probe()
            baseline_probe(run)
            run.mark("passed")
        except BaseException:
            if run.created and run.manifest.exists():
                run.mark("failed")
            raise
        finally:
            if run.created and run.manifest.exists():
                run.cleanup()
        return run.run_id


def main() -> int:
    try:
        run_id = check()
    except BaseException:
        print("Oracle baseline failed; inspect the private manifest for cleanup.", file=sys.stderr)
        return 1
    print(f"Oracle baseline passed; owned resources cleaned. Run: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
