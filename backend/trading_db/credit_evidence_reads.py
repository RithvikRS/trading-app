"""Finite typed credit evidence projections; no selection, current valuation or writes."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from trading_api.credit_evidence_contracts import (
    CreditCashView,
    CreditEvidenceHistoryPage,
    CreditEvidenceHistoryQuery,
    CreditEvidenceInspectQuery,
    CreditEvidencePage,
    CreditEvidenceQuery,
    CreditEvidenceView,
    CreditKind,
    evidence_model,
)
from trading_db.credit_reads import CreditReadTransaction
from trading_db.financial_reads import FinancialReadUnavailable

STATEMENT_ROLES = ("opening_liability", "closing_liability", "total_due", "minimum_due")
CURRENT_ROLES = ("outstanding", "unbilled", "credit_limit", "available_credit")
DAYS = {
    "statement": ("period_start", "period_end", "statement_date", "due_date"),
    "current": ("as_of_date",),
    "entry": ("transaction_date", "posting_date"),
}
COLUMNS = {
    "statement": (
        *DAYS["statement"],
        *(f"{role}_{part}" for role in STATEMENT_ROLES for part in ("source", "amount", "missing")),
    ),
    "current": (
        *DAYS["current"],
        "as_of_instant",
        *(f"{role}_{part}" for role in CURRENT_ROLES for part in ("source", "amount", "missing")),
    ),
    "entry": (
        *DAYS["entry"],
        "role",
        "treatment",
        "original_currency",
        *(
            f"{role}_{part}"
            for role in ("billing", "original")
            for part in ("source", "amount", "missing")
        ),
    ),
}


def _select(kind: CreditKind) -> str:
    # Table/column names are committed constants; caller filters remain bound values.
    return (
        "SELECT o.id::text AS id,o.kind,o.revision,o.previous_revision,"
        "o.source_id::text AS source_id,"
        "o.mapping_revision,o.account_id::text AS account_id,"
        "CASE WHEN a.archived_at IS NULL THEN 'active' ELSE 'archived' END AS account_state,"
        "NOT EXISTS(SELECT 1 FROM app.credit_evidence_observations n WHERE n.owner_id=o.owner_id "
        "AND n.id=o.id AND n.revision>o.revision) AS is_latest_revision,"
        "v.revision AS child_revision,v.kind AS child_kind,m.account_id::text AS mapping_account,"
        + ",".join("v." + name for name in COLUMNS[kind])
        + " FROM app.credit_evidence_observations o JOIN app.credit_billing_accounts a "
        "ON a.owner_id=o.owner_id AND a.id=o.account_id "
        "LEFT JOIN app.credit_source_account_mappings m "
        "ON m.owner_id=o.owner_id AND m.source_id=o.source_id AND m.revision=o.mapping_revision "
        f"LEFT JOIN app.credit_{kind}_values v ON v.owner_id=o.owner_id AND v.observation_id=o.id "
        "AND v.revision=o.revision WHERE o.owner_id=:owner "
        "AND o.account_id=:account AND o.kind=:kind "
    )


def _cash(row: Any, prefix: str, currency: Any = "INR") -> CreditCashView:
    value = CreditCashView.model_validate(
        dict(
            source=row[prefix + "_source"],
            currency=currency,
            missing_reason=row[prefix + "_missing"],
        )
    )
    parsed = value.cash().value
    stored = row[prefix + "_amount"]
    if parsed is None:
        if stored is not None:
            raise FinancialReadUnavailable()
    elif type(stored) is not Decimal or not stored.is_finite() or stored != parsed:
        raise FinancialReadUnavailable()
    return value


def project(row: Any, *, account: str, kind: CreditKind) -> CreditEvidenceView:
    try:
        return _project(row, account=account, kind=kind)
    except KeyError, ValueError, TypeError, AttributeError:
        raise FinancialReadUnavailable() from None


def _project(row: Any, *, account: str, kind: CreditKind) -> CreditEvidenceView:
    if (
        row["account_id"] != account
        or row["kind"] != kind
        or row["child_kind"] != kind
        or type(row["child_revision"]) is not int
        or row["child_revision"] != row["revision"]
        or row["mapping_account"] != account
    ):
        raise FinancialReadUnavailable()
    values: dict[str, Any] = {}
    for name in DAYS[kind]:
        day = row[name]
        if day is not None and type(day) is not date:
            raise FinancialReadUnavailable()
        values[name] = day.isoformat() if day is not None else None
    if kind in ("statement", "current"):
        for role in STATEMENT_ROLES if kind == "statement" else CURRENT_ROLES:
            values[role] = _cash(row, role)
        if kind == "current":
            values["as_of_instant"] = row["as_of_instant"]
    else:
        values.update(
            role=row["role"], treatment=row["treatment"], billing_amount=_cash(row, "billing")
        )
        if row["original_currency"] is None:
            if any(row["original_" + part] is not None for part in ("source", "amount", "missing")):
                raise FinancialReadUnavailable()
            values["original_amount"] = None
        else:
            values["original_amount"] = _cash(row, "original", row["original_currency"])
    fields = {
        name: row[name]
        for name in (
            "id",
            "kind",
            "revision",
            "previous_revision",
            "source_id",
            "mapping_revision",
            "account_id",
            "account_state",
            "is_latest_revision",
        )
    }
    return evidence_model(kind).model_validate(fields | {"values": values})


class CreditEvidenceReadTransaction(CreditReadTransaction):
    def _account(self, account: str) -> bool:
        return bool(
            self._execute(
                "SELECT EXISTS(SELECT 1 FROM app.credit_billing_accounts "
                "WHERE owner_id=:owner AND id=:account)",
                account=UUID(account),
            ).scalar_one()
        )

    def _root(self, account: str, kind: CreditKind, root: str) -> bool:
        return bool(
            self._execute(
                "SELECT EXISTS(SELECT 1 FROM app.credit_evidence_observations "
                "WHERE owner_id=:owner "
                "AND account_id=:account AND kind=:kind AND id=:id)",
                account=UUID(account),
                kind=kind,
                id=UUID(root),
            ).scalar_one()
        )

    def evidence_query(self, query: CreditEvidenceQuery) -> CreditEvidencePage | None:
        valid = CreditEvidenceQuery.model_validate(query)
        if not self._account(valid.account_id):
            return None
        rows = (
            self._execute(
                _select(valid.kind)
                + "AND (CAST(:after AS uuid) IS NULL OR o.id>CAST(:after AS uuid)) "
                "AND NOT EXISTS(SELECT 1 FROM app.credit_evidence_observations n "
                "WHERE n.owner_id=o.owner_id "
                "AND n.id=o.id AND n.revision>o.revision) ORDER BY o.id LIMIT :limit",
                account=UUID(valid.account_id),
                kind=valid.kind,
                after=UUID(valid.after) if valid.after else None,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        if len(rows) > valid.limit + 1:
            raise FinancialReadUnavailable()
        checked = tuple(project(row, account=valid.account_id, kind=valid.kind) for row in rows)
        ids = [item.id for item in checked]
        if (
            ids != sorted(set(ids))
            or any(
                not item.is_latest_revision
                or item.account_id != valid.account_id
                or item.kind != valid.kind
                for item in checked
            )
            or (valid.after is not None and any(identity <= valid.after for identity in ids))
        ):
            raise FinancialReadUnavailable()
        items = checked[: valid.limit]
        return CreditEvidencePage(
            items=items, next_after=items[-1].id if len(checked) > valid.limit else None
        )

    def evidence_history(
        self, query: CreditEvidenceHistoryQuery
    ) -> CreditEvidenceHistoryPage | None:
        valid = CreditEvidenceHistoryQuery.model_validate(query)
        if not self._root(valid.account_id, valid.kind, valid.id):
            return None
        rows = (
            self._execute(
                _select(valid.kind)
                + "AND o.id=:id AND (CAST(:before AS bigint) IS NULL OR o.revision<:before) "
                "ORDER BY o.revision DESC LIMIT :limit",
                account=UUID(valid.account_id),
                kind=valid.kind,
                id=UUID(valid.id),
                before=valid.before,
                limit=valid.limit + 1,
            )
            .mappings()
            .all()
        )
        if len(rows) > valid.limit + 1:
            raise FinancialReadUnavailable()
        checked = tuple(project(row, account=valid.account_id, kind=valid.kind) for row in rows)
        if valid.before is None and (not checked or not checked[0].is_latest_revision):
            raise FinancialReadUnavailable()
        for index, item in enumerate(checked):
            if (
                item.id != valid.id
                or item.account_id != valid.account_id
                or item.kind != valid.kind
                or (valid.before is not None and item.revision >= valid.before)
                or (
                    index
                    and (
                        item.revision != checked[index - 1].revision - 1
                        or item.is_latest_revision
                        or item.source_id != checked[0].source_id
                    )
                )
            ):
                raise FinancialReadUnavailable()
        items = checked[: valid.limit]
        return CreditEvidenceHistoryPage(
            items=items, next_before=items[-1].revision if len(checked) > valid.limit else None
        )

    def evidence_inspect(self, query: CreditEvidenceInspectQuery) -> CreditEvidenceView | None:
        valid = CreditEvidenceInspectQuery.model_validate(query)
        row = (
            self._execute(
                _select(valid.kind) + "AND o.id=:id AND o.revision=:revision",
                account=UUID(valid.account_id),
                kind=valid.kind,
                id=UUID(valid.id),
                revision=valid.at_revision,
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        item = project(row, account=valid.account_id, kind=valid.kind)
        if (
            item.id != valid.id
            or item.revision != valid.at_revision
            or item.account_id != valid.account_id
            or item.kind != valid.kind
        ):
            raise FinancialReadUnavailable()
        return item
