"""Run the explicit non-production authentication tools without HTTP exposure."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.checks import run, sync_backend, uv_command  # noqa: E402
from scripts.tooling import ROOT, CheckFailure  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["provision-owner", "smoke", "init-session-key", "revoke-owner"]
    )
    args = parser.parse_args()
    try:
        uv = uv_command()
        sync_backend(uv)
        run(
            "authentication operation",
            [uv, "run", "--locked", "--no-sync", "python", "-m", "trading_auth", args.action],
            ROOT / "backend",
            timeout=360,
        )
    except CheckFailure:
        print(
            "Authentication operation failed; see docs/authentication-foundation.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
