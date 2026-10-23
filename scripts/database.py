"""Manage only the project's local development PostgreSQL service."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.checks import run, sync_backend, uv_command  # noqa: E402
from scripts.tooling import ROOT, CheckFailure  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "migrate", "status", "down"])
    args = parser.parse_args()
    try:
        uv = uv_command()
        sync_backend(uv)
        run(
            "local PostgreSQL",
            [uv, "run", "--locked", "--no-sync", "python", "-m", "trading_db", args.action],
            ROOT / "backend",
        )
    except CheckFailure as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
