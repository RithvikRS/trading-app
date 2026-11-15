"""Fresh-process synthetic Oracle smoke probe; never an application connection factory."""

import json
import os
import re
import stat
import sys
import sysconfig
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("Oracle smoke verification failed.")


def guarded(path: Path, *, file: bool = False) -> Path:
    path.relative_to(ROOT)
    require(path.resolve() == path)
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode))
        require(not (getattr(info, "st_file_attributes", 0) & 0x400))
        if item == path and file:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
        if item == ROOT:
            break
    return path


def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def descriptor(raw: str) -> tuple[str, int]:
    require(len(raw) <= 256)
    value = json.loads(raw, object_pairs_hook=unique_fields)
    require(isinstance(value, dict) and set(value) == {"run_id", "port"})
    run_id, port = value["run_id"], value["port"]
    require(type(run_id) is str and bool(re.fullmatch(r"[0-9a-f]{32}", run_id)))
    require(type(port) is int and 1024 <= port <= 65535)
    return run_id, port


def package_directory() -> Path:
    prefix = ROOT / "backend/.venv"
    require(Path(sys.prefix).resolve() == prefix.resolve())
    purelib = Path(sysconfig.get_path("purelib"))
    require(purelib.resolve() == purelib)
    purelib.relative_to(prefix)
    require(purelib.is_dir())
    return purelib


def run(raw: str) -> None:
    run_id, port = descriptor(raw)
    require(sys.flags.isolated == 1 and sys.flags.no_site == 1)
    require(os.environ.get("ORA_SDTZ") == "UTC")
    require(
        not any(
            key.startswith(("ORACLE_", "TNS_", "NLS_")) or key in {"TWO_TASK", "LOCAL"}
            for key in os.environ
        )
    )
    directory = guarded(ROOT / ".cache/oracle/runs" / run_id)
    config = guarded(directory / "config")
    require(config.is_dir() and not list(config.iterdir()))
    secret_path = guarded(directory / "smoke_pwd", file=True)
    require(secret_path.stat().st_size == 51)
    secret = secret_path.read_text(encoding="ascii")
    require(bool(re.fullmatch(r"Ta1[0-9a-f]{48}", secret)))
    # No sitecustomize or .pth startup code: add only this locked virtualenv package directory.
    sys.path.append(str(package_directory()))
    import oracledb

    cast(Callable[[], None], oracledb.enable_thin_mode)()
    require(oracledb.is_thin_mode())
    oracledb.defaults.fetch_decimals = True

    def connect(password: str) -> Any:
        connection = oracledb.connect(
            user="TRADING_SMOKE",
            password=password,
            host="127.0.0.1",
            port=port,
            service_name="FREEPDB1",
            config_dir=str(config),
            tcp_connect_timeout=5,
            retry_count=0,
        )
        connection.call_timeout = 5000
        return connection

    try:
        unexpected = connect("Invalid1" + "0" * 48)
    except oracledb.DatabaseError as error:
        require(getattr(error.args[0], "code", None) == 1017)
    else:
        unexpected.close()
        raise ValueError("Oracle smoke verification failed.")
    with connect(secret) as connection:
        require(connection.thin and connection.version.startswith("23.26.3."))
        with connection.cursor() as cursor:
            cursor.execute("SELECT SYS_CONTEXT('USERENV','CON_NAME'), USER FROM dual")
            require(cursor.fetchone() == ("FREEPDB1", "TRADING_SMOKE"))
            cursor.execute("SELECT marker FROM run_marker")
            require(cursor.fetchall() == [(run_id,)])
            cursor.execute("ALTER SESSION SET TIME_ZONE = '+00:00'")
            cursor.execute("SELECT SESSIONTIMEZONE FROM dual")
            require(cursor.fetchone() == ("+00:00",))
            values = ("999999999999999999.123456789012", "-0.000000000001", "1.230000000000")
            for source in values:
                cursor.execute(
                    "SELECT :source, CAST(:amount AS NUMBER(30,12)) FROM dual",
                    source=source,
                    amount=Decimal(source),
                )
                row = cursor.fetchone()
                require(
                    row is not None
                    and row[0] == source
                    and type(row[1]) is Decimal
                    and row[1] == Decimal(source)
                )
            day = date(2026, 1, 2)
            cursor.execute("SELECT CAST(:day AS DATE) FROM dual", day=day)
            require(cursor.fetchone() == (datetime(2026, 1, 2),))
            cursor.execute(
                "CREATE TABLE smoke_values (id NUMBER(2) PRIMARY KEY, "
                "amount NUMBER(30,12) NOT NULL, source VARCHAR2(32 BYTE) NOT NULL)"
            )
            cursor.execute(
                "INSERT INTO smoke_values VALUES (1, :amount, :source)",
                amount=Decimal(values[0]),
                source=values[0],
            )
            connection.commit()
            cursor.execute(
                "INSERT INTO smoke_values VALUES (2, :amount, :source)",
                amount=Decimal(values[1]),
                source=values[1],
            )
            connection.rollback()
        # A different physical connection proves the retained transaction boundary.
        with connect(secret) as observer:
            with observer.cursor() as cursor:
                cursor.execute("SELECT amount, source FROM smoke_values ORDER BY id")
                rows = cursor.fetchall()
                require(rows == [(Decimal(values[0]), values[0])] and type(rows[0][0]) is Decimal)


def main() -> int:
    try:
        run(sys.stdin.read(257))
    except BaseException:
        # Includes driver, JSON, filesystem and cancellation failures: no supplied values.
        print("Oracle smoke verification failed.", file=sys.stderr)
        return 1
    print("ORACLE_SMOKE_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
