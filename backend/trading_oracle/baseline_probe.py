"""Fresh isolated acceptance child; role credentials are generated and retained only in memory."""

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def run(raw: str, complete: Callable[[str], None]) -> None:
    if sys.flags.isolated != 1 or sys.flags.no_site != 1:
        raise ValueError("Oracle baseline verification failed.")
    root = Path(__file__).resolve().parents[2]
    sys.path.append(str(root / "backend"))
    from trading_oracle.probe import descriptor, guarded, package_directory

    run_id, port = descriptor(raw)
    guarded(root / "backend")
    sys.path.append(str(package_directory()))
    from trading_oracle.local import LocalRun, local_context

    context = local_context()
    local = LocalRun(run_id, context)
    if local.validate_manifest()["status"] != "started" or local.port() != port:
        raise ValueError("Oracle baseline verification failed.")
    os.environ["ORA_SDTZ"] = "UTC"
    from oracle_tests.acceptance import check
    from trading_oracle.bootstrap import prepare

    complete("setup")
    result = prepare(local)
    complete("bootstrap")
    check(local, result, complete)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    sys.path.append(str(root / "backend"))
    from trading_oracle.baseline_protocol import STAGES, digest

    report: dict[str, Any] = {
        "version": 1,
        "status": "failed",
        "stage": "setup",
        "completed": [],
        "error_code": None,
        "source_sha256": digest(root),
    }

    def complete(stage: str) -> None:
        position = len(report["completed"])
        if position >= len(STAGES) or stage != STAGES[position]:
            raise ValueError("Invalid Oracle baseline stage.")
        report["completed"].append(stage)
        report["stage"] = STAGES[min(position + 1, len(STAGES) - 1)]

    try:
        run(sys.stdin.read(257), complete)
    except BaseException as error:
        current: BaseException | None = error
        for _ in range(8):
            if current is None:
                break
            code = getattr(current.args[0], "code", None) if current.args else None
            if type(code) is int and 0 <= code <= 65535:
                report["error_code"] = code
                break
            current = current.__context__
    else:
        report["status"] = "passed"
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
