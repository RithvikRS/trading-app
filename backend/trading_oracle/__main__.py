"""Run a disposable Oracle smoke check or recover one interrupted owned run."""

import argparse
import sys

from trading_oracle.local import OracleFailure, cleanup, verify


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("check")
    recovery = subcommands.add_parser("cleanup")
    recovery.add_argument("run_id")
    args = parser.parse_args()
    try:
        if args.action == "check":
            run_id = verify()
            print(f"Oracle smoke checks passed; owned resources cleaned. Run: {run_id}")
        else:
            cleanup(args.run_id)
            print("Owned Oracle verification resources cleaned.")
    except OracleFailure as error:
        print(str(error), file=sys.stderr)
        return 1
    except BaseException:
        print(
            "Oracle verification stopped; inspect the private run manifest for cleanup.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
