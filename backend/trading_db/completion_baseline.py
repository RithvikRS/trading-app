"""Internal stale-state tokens; these neither complete imports nor prove reconciliation."""

import hmac
import re
from collections.abc import Iterator
from contextlib import contextmanager

from trading_db.accounts import AccountTransaction, AccountUnavailable
from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceTransaction


class CompletionUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Import completion is unavailable or conflicts with current evidence.")


class CompletionBaseline:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)

    def _current(self) -> str:
        result = self._accounts._execute("SELECT app.financial_baseline()").scalar_one()
        if type(result) is not str or re.fullmatch(r"[0-9a-f]{64}", result) is None:
            raise CompletionUnavailable()
        return result

    def current(self) -> str:
        try:
            with self._accounts._write():
                return self._current()
        except AccountUnavailable:
            raise CompletionUnavailable() from None

    @contextmanager
    def guard(self, expected: str) -> Iterator[None]:
        """Keep comparison and dependent writes under one owner lock and savepoint."""
        if type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise CompletionUnavailable()
        try:
            with self._accounts._write():
                if not hmac.compare_digest(expected, self._current()):
                    raise CompletionUnavailable()
                yield
        except AccountUnavailable:
            raise CompletionUnavailable() from None
