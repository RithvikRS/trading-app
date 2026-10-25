"""Explicit local administration with sanitized failure output."""

import argparse
import os
import subprocess
import sys

from trading_db import migrate
from trading_db.connections import DatabaseFailure
from trading_db.local import development, disposable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "migrate", "status", "down", "check"])
    args = parser.parse_args()
    suite_timeout = (
        2700
        if os.name == "nt" and "CI" not in os.environ and "GITHUB_ACTIONS" not in os.environ
        else 1080
    )
    try:
        if args.action == "check":
            with disposable() as service:
                environment = dict(
                    os.environ, TRADING_TEST_CONTEXT=str(service.write_test_context())
                )
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "database_tests", "--tb=short", "--maxfail=1"],
                    env=environment,
                    check=False,
                    timeout=suite_timeout,
                )
                if result.returncode:
                    return 1
        else:
            service = development()
            if args.action == "up":
                service.up()
                print("Local PostgreSQL is ready on 127.0.0.1:55432; run migrate separately.")
            elif args.action == "down":
                service.down()
                print("Local PostgreSQL stopped; development data and credentials retained.")
            elif args.action == "migrate":
                migrate.apply(service.url("migrator"), service.project)
                print("Local database migration completed.")
            else:
                current = migrate.revision(service.url("migrator"), service.project)
                print(f"Local schema revision: {current}")
    except subprocess.TimeoutExpired:
        print(
            f"Database verification exceeded its {suite_timeout // 60}-minute limit.",
            file=sys.stderr,
        )
        return 1
    except DatabaseFailure as error:
        # This exception type contains only fixed, reviewed diagnostic messages.
        print(f"Database operation failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Database/driver/Docker exceptions can include SQL, URLs, passwords, or server details.
        print(
            "Database operation failed. Check local Docker, credentials and the database runbook.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
