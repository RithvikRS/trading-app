"""Bounded owner-scoped credit identity projections inside a READ ONLY transaction."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from trading_api.credit_read_contracts import (
    CreditAccountView,
    CreditMappingHistoryPage,
    CreditMappingHistoryQuery,
    CreditMappingView,
    CreditPage,
    CreditSourceView,
)
from trading_api.read_contracts import IdentityView, PageQuery
from trading_api.valuation_read_contracts import InspectQuery
from trading_db.financial_reads import FinancialReadUnavailable
from trading_db.workspace import OwnerAccessDenied, WorkspaceTransaction

ACCOUNT_FIELDS = (
    "a.id::text AS id,a.issuer,a.billing_currency,a.label,a.revision,"
    "CASE WHEN a.archived_at IS NULL THEN 'active' ELSE 'archived' END AS state "
)


class CreditReadTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._unit = unit

    def _execute(self, sql: str, **parameters: Any) -> Any:
        self._unit._require_open()
        return self._unit._connection.execute(
            text(sql), {"owner": self._unit._owner_id, **parameters}
        )

    def _access(self) -> None:
        row = self._execute(
            "SELECT current_setting('transaction_isolation')='read committed' "
            "AND current_setting('transaction_read_only')='on' AS permitted_mode,"
            "app.current_owner_id()=CAST(:owner AS uuid) AND EXISTS ("
            "SELECT 1 FROM app.owners WHERE id=:owner AND is_active) AS active"
        ).one()
        if not row.permitted_mode:
            raise FinancialReadUnavailable()
        if not row.active:
            raise OwnerAccessDenied()

    @contextmanager
    def consistent(self) -> Iterator[None]:
        self._unit._require_open()
        try:
            with self._unit._connection.begin_nested():
                self._access()
                self._execute(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('credit-accounts/v1:' || CAST(:owner AS text),0))"
                )
                self._access()
                yield
                self._access()
        except SQLAlchemyError, ValueError, TypeError, AttributeError:
            raise FinancialReadUnavailable() from None

    @staticmethod
    def _page[T: IdentityView](
        model: type[T], response: type[CreditPage[T]], rows: list[Any], query: PageQuery
    ) -> CreditPage[T]:
        if len(rows) > query.limit + 1:
            raise FinancialReadUnavailable()
        # Validate the sentinel too; a malformed probe must not create a false continuation.
        checked = tuple(model.model_validate(dict(row)) for row in rows)
        ids = [item.id for item in checked]
        if ids != sorted(set(ids)) or (
            query.after is not None and any(identity <= query.after for identity in ids)
        ):
            raise FinancialReadUnavailable()
        items = checked[: query.limit]
        return response(
            items=items, next_after=items[-1].id if len(checked) > query.limit else None
        )

    def accounts(self, query: PageQuery) -> CreditPage[CreditAccountView]:
        valid = PageQuery.model_validate(query)
        rows = (
            self._execute(
                "SELECT " + ACCOUNT_FIELDS + "FROM app.credit_billing_accounts a "
                "WHERE a.owner_id=:owner AND "
                "(CAST(:after AS uuid) IS NULL OR a.id>CAST(:after AS uuid)) "
                "ORDER BY a.id LIMIT :limit",
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return self._page(CreditAccountView, CreditPage[CreditAccountView], list(rows), valid)

    def account(self, query: InspectQuery) -> CreditAccountView | None:
        valid = InspectQuery.model_validate(query)
        row = (
            self._execute(
                "SELECT " + ACCOUNT_FIELDS + "FROM app.credit_billing_accounts a "
                "WHERE a.owner_id=:owner AND a.id=:id",
                id=UUID(valid.id),
            )
            .mappings()
            .one_or_none()
        )
        result = CreditAccountView.model_validate(dict(row)) if row else None
        if result is not None and result.id != valid.id:
            raise FinancialReadUnavailable()
        return result

    def sources(self, query: PageQuery) -> CreditPage[CreditSourceView]:
        valid = PageQuery.model_validate(query)
        rows = (
            self._execute(
                "SELECT s.id::text AS id,s.family,m.revision AS mapping_revision,"
                "m.account_id::text AS account_id,CASE WHEN m.account_id IS NULL THEN 'unmapped' "
                "WHEN a.archived_at IS NOT NULL THEN 'archived' ELSE 'mapped' END AS state "
                "FROM app.credit_source_handles s LEFT JOIN LATERAL (SELECT revision,account_id "
                "FROM app.credit_source_account_mappings "
                "WHERE owner_id=s.owner_id AND source_id=s.id "
                "ORDER BY revision DESC LIMIT 1) m ON true LEFT JOIN app.credit_billing_accounts a "
                "ON a.owner_id=s.owner_id AND a.id=m.account_id WHERE s.owner_id=:owner AND "
                "(CAST(:after AS uuid) IS NULL OR s.id>CAST(:after AS uuid)) "
                "ORDER BY s.id LIMIT :limit",
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return self._page(CreditSourceView, CreditPage[CreditSourceView], list(rows), valid)

    def mapping_history(self, query: CreditMappingHistoryQuery) -> CreditMappingHistoryPage | None:
        valid = CreditMappingHistoryQuery.model_validate(query)
        source = UUID(valid.id)
        if not self._execute(
            "SELECT EXISTS (SELECT 1 FROM app.credit_source_handles "
            "WHERE owner_id=:owner AND id=:id)",
            id=source,
        ).scalar_one():
            return None
        rows = (
            self._execute(
                "SELECT m.source_id::text AS source_id,m.revision,m.previous_revision,"
                "m.account_id::text AS account_id,m.reason,NOT EXISTS ("
                "SELECT 1 FROM app.credit_source_account_mappings n WHERE n.owner_id=m.owner_id "
                "AND n.source_id=m.source_id AND n.revision>m.revision) AS is_latest_revision,"
                "CASE WHEN m.account_id IS NULL THEN NULL WHEN a.archived_at IS NULL THEN 'active' "
                "ELSE 'archived' END AS account_state FROM app.credit_source_account_mappings m "
                "LEFT JOIN app.credit_billing_accounts a "
                "ON a.owner_id=m.owner_id AND a.id=m.account_id "
                "WHERE m.owner_id=:owner AND m.source_id=:source AND "
                "(CAST(:before AS bigint) IS NULL OR m.revision<:before) "
                "ORDER BY m.revision DESC LIMIT :limit",
                source=source,
                before=valid.before,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        if len(rows) > valid.limit + 1:
            raise FinancialReadUnavailable()
        checked = tuple(CreditMappingView.model_validate(dict(row)) for row in rows)
        if valid.before is None and checked and not checked[0].is_latest_revision:
            raise FinancialReadUnavailable()
        for index, item in enumerate(checked):
            if (
                item.source_id != valid.id
                or (valid.before is not None and item.revision >= valid.before)
                or (
                    index
                    and (
                        item.revision != checked[index - 1].revision - 1 or item.is_latest_revision
                    )
                )
            ):
                raise FinancialReadUnavailable()
        items = checked[: valid.limit]
        return CreditMappingHistoryPage(
            items=items, next_before=items[-1].revision if len(checked) > valid.limit else None
        )
