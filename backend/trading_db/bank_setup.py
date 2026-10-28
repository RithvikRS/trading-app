"""Atomic bank identity creation with durable, owner-scoped intent replay."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from trading_api.bank_setup_contracts import (
    MAX_SETUPS,
    BankSetupCommand,
    BankSetupHead,
    BankSetupReceipt,
)
from trading_db.accounts import AccountDefinition, AccountTransaction
from trading_db.connections import DatabaseFailure
from trading_db.workspace import OwnerAccessDenied, WorkspaceTransaction

FIELDS = "id AS intent_id,revision,account_id,institution,label,currency_set"
DECLARATION = {"institution", "label", "currencies"}


class BankSetupUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Bank account setup is unavailable or conflicts with saved information.")


class BankSetupTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)

    def _active(self) -> None:
        # A transaction may have waited for another account operation. Observe active
        # ownership again after the lock, without claiming to serialize arbitrary admins.
        if (
            self._accounts._execute(
                "SELECT id FROM app.owners WHERE id=:owner AND is_active"
            ).scalar_one_or_none()
            is None
        ):
            raise OwnerAccessDenied()
        if (
            self._accounts._execute("SELECT current_setting('transaction_isolation')").scalar_one()
            != "read committed"
        ):
            raise BankSetupUnavailable()

    def _receipt(self, row: Any) -> BankSetupReceipt:
        try:
            return BankSetupReceipt.model_validate(
                dict(
                    intent_id=str(row["intent_id"]),
                    revision=row["revision"],
                    account_id=str(row["account_id"]),
                    institution=row["institution"],
                    label=row["label"],
                    currencies=tuple(row["currency_set"].split(",")),
                )
            )
        except ValidationError, AttributeError, TypeError, KeyError:
            raise BankSetupUnavailable() from None

    def _head(self) -> BankSetupHead:
        row = (
            self._accounts._execute(
                "SELECT " + FIELDS + " FROM app.bank_account_setups "
                "WHERE owner_id=:owner ORDER BY revision DESC LIMIT 1"
            )
            .mappings()
            .one_or_none()
        )
        saved = self._receipt(row) if row else None
        return BankSetupHead(revision=saved.revision if saved else 0, last_saved=saved)

    def query(self) -> BankSetupHead:
        with self._accounts._write():
            self._active()
            return self._head()

    def create(self, command: BankSetupCommand) -> BankSetupReceipt:
        try:
            valid = BankSetupCommand.model_validate(command.model_dump(warnings=False))
        except ValidationError, AttributeError:
            raise BankSetupUnavailable() from None
        with self._accounts._write():
            self._active()
            row = (
                self._accounts._execute(
                    "SELECT " + FIELDS + " FROM app.bank_account_setups "
                    "WHERE owner_id=:owner AND id=:id",
                    id=UUID(valid.intent_id),
                )
                .mappings()
                .one_or_none()
            )
            if row is not None:
                saved = self._receipt(row)
                if saved.revision != valid.expected_revision + 1 or saved.model_dump(
                    include=DECLARATION
                ) != valid.model_dump(include=DECLARATION):
                    raise BankSetupUnavailable()
                # Replay refers to the immutable creation declaration, independently of
                # later archival, currency additions, current head or exhausted quotas.
                return saved
            head = self._head()
            if head.revision != valid.expected_revision or head.revision >= MAX_SETUPS:
                raise BankSetupUnavailable()
            self._accounts._budget("bank_account_setups")
            account = self._accounts.create(
                AccountDefinition(kind="bank", market="IN", **valid.model_dump(include=DECLARATION))
            )
            row = (
                self._accounts._execute(
                    "INSERT INTO app.bank_account_setups "
                    "(owner_id,id,revision,previous_revision,account_id,"
                    "institution,label,currency_set) "
                    "VALUES (:owner,:id,:revision,:previous,:account,"
                    ":institution,:label,:currencies) "
                    "RETURNING " + FIELDS,
                    id=UUID(valid.intent_id),
                    revision=head.revision + 1,
                    previous=head.revision or None,
                    account=account.id,
                    institution=valid.institution,
                    label=valid.label,
                    currencies=",".join(valid.currencies),
                )
                .mappings()
                .one()
            )
            return self._receipt(row)
