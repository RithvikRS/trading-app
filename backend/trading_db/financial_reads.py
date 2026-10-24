"""Explicit owner-scoped projections; financial identities do not imply balances."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from trading_api.read_contracts import (
    AccountView,
    FinancialPage,
    IdentityView,
    InstrumentView,
    PageQuery,
    PositionQuery,
    PositionView,
    SourceView,
)
from trading_db.accounts import AccountTransaction, AccountUnavailable
from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceTransaction


class FinancialReadUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__("Financial data is unavailable.")


def page_result[T: IdentityView](
    model: type[T], response: type[FinancialPage[T]], rows: list[Any], limit: int
) -> FinancialPage[T]:
    if len(rows) > limit + 1:
        raise FinancialReadUnavailable()
    items = tuple(model.model_validate(dict(row)) for row in rows[:limit])
    return response(items=items, next_after=items[-1].id if len(rows) > limit else None)


class FinancialReadTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)

    @contextmanager
    def consistent(self) -> Iterator[None]:
        try:
            with self._accounts._write():
                yield
        except AccountUnavailable, SQLAlchemyError, ValueError:
            raise FinancialReadUnavailable() from None

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    def accounts(self, query: PageQuery) -> FinancialPage[AccountView]:
        valid = PageQuery.model_validate(query)
        rows = (
            self._execute(
                "SELECT a.id::text AS id,a.kind,a.institution,a.market,a.label,a.revision,"
                "CASE WHEN a.archived_at IS NULL THEN 'active' ELSE 'archived' END AS state,"
                "ARRAY(SELECT c.currency FROM app.account_currencies c WHERE c.owner_id=a.owner_id "
                "AND c.account_id=a.id ORDER BY c.currency) AS currencies "
                "FROM app.financial_accounts a WHERE a.owner_id=:owner "
                "AND (CAST(:after AS uuid) IS NULL OR a.id>CAST(:after AS uuid)) "
                "ORDER BY a.id LIMIT :limit",
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(
            AccountView,
            FinancialPage[AccountView],
            [dict(row) | {"currencies": tuple(row["currencies"])} for row in rows],
            valid.limit,
        )

    def sources(self, query: PageQuery) -> FinancialPage[SourceView]:
        valid = PageQuery.model_validate(query)
        rows = (
            self._execute(
                "SELECT s.id::text AS id,s.namespace,m.revision AS mapping_revision,"
                "m.account_id::text AS account_id,CASE WHEN m.account_id IS NULL THEN 'unmapped' "
                "WHEN a.archived_at IS NOT NULL THEN 'archived' ELSE 'mapped' END AS state "
                "FROM app.source_accounts s LEFT JOIN LATERAL (SELECT revision,account_id FROM "
                "app.source_account_mappings WHERE owner_id=s.owner_id AND source_id=s.id "
                "ORDER BY revision DESC LIMIT 1) m ON true LEFT JOIN app.financial_accounts a "
                "ON a.owner_id=s.owner_id AND a.id=m.account_id WHERE s.owner_id=:owner AND "
                "(CAST(:after AS uuid) IS NULL OR s.id>CAST(:after AS uuid)) "
                "ORDER BY s.id LIMIT :limit",
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(SourceView, FinancialPage[SourceView], list(rows), valid.limit)

    def instruments(self, query: PageQuery) -> FinancialPage[InstrumentView]:
        valid = PageQuery.model_validate(query)
        rows = (
            self._execute(
                "SELECT id::text AS id,name,isin,asset_class,"
                "fund_scheme_id::text AS fund_scheme_id,fund_plan,fund_option,fund_currency "
                "FROM app.instruments WHERE owner_id=:owner AND "
                "(CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
                "ORDER BY id LIMIT :limit",
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(InstrumentView, FinancialPage[InstrumentView], list(rows), valid.limit)

    def positions(self, query: PositionQuery) -> FinancialPage[PositionView] | None:
        valid = PositionQuery.model_validate(query)
        account_id = UUID(valid.account_id)
        if not self._execute(
            "SELECT EXISTS(SELECT 1 FROM app.financial_accounts WHERE owner_id=:owner AND id=:id)",
            id=account_id,
        ).scalar_one():
            return None
        rows = (
            self._execute(
                "SELECT p.id::text AS id,p.account_id::text AS account_id,"
                "p.instrument_id::text AS instrument_id,p.holding_form,"
                "CASE WHEN a.archived_at IS NULL THEN 'active' "
                "ELSE 'archived' END AS account_state "
                "FROM app.account_positions p JOIN app.financial_accounts a "
                "ON a.owner_id=p.owner_id AND a.id=p.account_id WHERE p.owner_id=:owner AND "
                "p.account_id=:account AND "
                "(CAST(:after AS uuid) IS NULL OR p.id>CAST(:after AS uuid)) "
                "ORDER BY p.id LIMIT :limit",
                account=account_id,
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        return page_result(PositionView, FinancialPage[PositionView], list(rows), valid.limit)
