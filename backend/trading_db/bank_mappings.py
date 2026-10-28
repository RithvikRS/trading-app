"""Owner-scoped bank mapping transitions over existing source and mapping records."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from trading_api.bank_mapping_contracts import (
    BankMappingChange,
    BankMappingHistoryPage,
    BankMappingHistoryQuery,
    BankMappingTarget,
    BankMappingTransition,
    BankSourceScope,
    checked,
    derive_transition,
    validate_history,
    validate_replay,
    validate_target,
)
from trading_db.accounts import AccountTransaction
from trading_db.connections import DatabaseFailure
from trading_db.workspace import OwnerAccessDenied, WorkspaceTransaction

FIELDS = "source_id,revision,previous_revision,account_id,reason"


class BankMappingUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Bank source mapping is unavailable or conflicts with saved information.")


class BankMappingTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)

    def _active(self) -> None:
        # Fresh after advisory/row waits; no owner row lock or global admin guarantee.
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
            raise BankMappingUnavailable()

    def _scope(self, source_id: str) -> BankSourceScope:
        row = (
            self._accounts._execute(
                "SELECT id,namespace FROM app.source_accounts WHERE owner_id=:owner AND id=:id",
                id=UUID(source_id),
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise BankMappingUnavailable()
        try:
            return BankSourceScope(source_id=str(row["id"]), namespace=row["namespace"])
        except ValidationError, KeyError, TypeError:
            raise BankMappingUnavailable() from None

    def _transition(self, scope: BankSourceScope, row: Any) -> BankMappingTransition:
        try:
            value = BankMappingTransition(
                source_id=str(row["source_id"]),
                namespace=scope.namespace,
                revision=row["revision"],
                previous_revision=row["previous_revision"],
                account_id=str(row["account_id"]) if row["account_id"] is not None else None,
                reason=row["reason"],
            )
            if value.source_id != scope.source_id:
                raise BankMappingUnavailable()
            return value
        except ValidationError, KeyError, TypeError, AttributeError:
            raise BankMappingUnavailable() from None

    def _one(
        self, scope: BankSourceScope, revision: int | None = None
    ) -> BankMappingTransition | None:
        row = (
            self._accounts._execute(
                "SELECT " + FIELDS + " FROM app.source_account_mappings "
                "WHERE owner_id=:owner AND source_id=:source "
                "AND (CAST(:revision AS bigint) IS NULL OR revision=:revision) "
                "ORDER BY revision DESC LIMIT 1",
                source=UUID(scope.source_id),
                revision=revision,
            )
            .mappings()
            .one_or_none()
        )
        return self._transition(scope, row) if row is not None else None

    def history(self, query: BankMappingHistoryQuery) -> BankMappingHistoryPage:
        try:
            request = checked(BankMappingHistoryQuery, query)
        except ValueError, TypeError, AttributeError, KeyError:
            raise BankMappingUnavailable() from None
        with self._accounts._write():
            self._active()
            scope = self._scope(request.source_id)
            head = self._one(scope)
            rows = (
                self._accounts._execute(
                    "SELECT " + FIELDS + " FROM app.source_account_mappings "
                    "WHERE owner_id=:owner AND source_id=:source "
                    "AND (CAST(:before AS bigint) IS NULL OR revision<:before) "
                    "ORDER BY revision DESC LIMIT :limit",
                    source=UUID(scope.source_id),
                    before=request.before,
                    limit=request.limit + 1,
                )
                .mappings()
                .all()
            )
            items = tuple(self._transition(scope, row) for row in rows[: request.limit])
            try:
                page = BankMappingHistoryPage(
                    source_id=scope.source_id,
                    namespace=scope.namespace,
                    head_revision=head.revision if head else 0,
                    head=head,
                    items=items,
                    next_before=items[-1].revision if len(rows) > request.limit else None,
                )
                return validate_history(request, page, source=scope)
            except ValueError, TypeError, AttributeError, KeyError:
                raise BankMappingUnavailable() from None

    def _admit_target(self, scope: BankSourceScope, account_id: str) -> None:
        institution = "hdfc" if scope.namespace == "hdfc_statement" else "sbi"
        locked = self._accounts._execute(
            "SELECT id FROM app.financial_accounts WHERE owner_id=:owner AND id=:id "
            "AND kind='bank' AND market='IN' AND institution=:institution "
            "AND archived_at IS NULL FOR SHARE",
            id=UUID(account_id),
            institution=institution,
        ).scalar_one_or_none()
        # FOR SHARE conflicts with non-key archive updates; KEY SHARE would not.
        # Even a no-row result after waiting must observe fresh ownership and target state.
        self._active()
        try:
            account = self._accounts.get(UUID(account_id))
            if locked is None or account is None:
                raise BankMappingUnavailable()
            target = BankMappingTarget.model_validate(
                dict(
                    id=str(account.id),
                    **account.definition.model_dump(),
                    revision=account.revision,
                    state="active" if account.archived_at is None else "archived",
                )
            )
            validate_target(scope, target)
        except ValueError, TypeError, AttributeError, KeyError:
            raise BankMappingUnavailable() from None

    def change(self, command: BankMappingChange) -> BankMappingTransition:
        try:
            request = checked(BankMappingChange, command)
        except ValueError, TypeError, AttributeError, KeyError:
            raise BankMappingUnavailable() from None
        with self._accounts._write():
            self._active()
            scope = self._scope(request.source_id)
            previous = (
                self._one(scope, request.expected_revision) if request.expected_revision else None
            )
            retained = self._one(scope, request.expected_revision + 1)
            if retained is not None:
                # This proves an equivalent transition exists, not which request caused it.
                # No current-head, quota or target-active admission applies to this branch.
                try:
                    return validate_replay(request, scope, previous, retained)
                except ValueError, TypeError, AttributeError, KeyError:
                    raise BankMappingUnavailable() from None
            head = self._one(scope)
            if (head.revision if head else 0) != request.expected_revision or head != previous:
                raise BankMappingUnavailable()
            try:
                expected = derive_transition(request, scope, previous)
            except ValueError, TypeError, AttributeError, KeyError:
                raise BankMappingUnavailable() from None
            if request.account_id is not None:
                self._admit_target(scope, request.account_id)
            self._accounts.map(
                UUID(scope.source_id),
                UUID(request.account_id) if request.account_id is not None else None,
                expected_revision=request.expected_revision,
            )
            saved = self._one(scope, expected.revision)
            if saved is None or saved != expected:
                raise BankMappingUnavailable()
            return saved
