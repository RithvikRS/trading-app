"""Owner-scoped security identity; names, ticker similarity and account balances never merge it."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError

from trading_db.accounts import AccountTransaction, AccountUnavailable, identifier, page, revision
from trading_db.connections import DatabaseFailure
from trading_db.workspace import WorkspaceDatabase, WorkspaceTransaction

MAX_RECORDS = 1000
NAME = r"^[A-Za-z0-9][A-Za-z0-9 &().,/'-]*$"
FundOption = Literal["growth", "idcw_payout", "idcw_reinvestment"]


class InstrumentUnavailable(DatabaseFailure):
    def __init__(self) -> None:
        super().__init__(
            "Instrument operation is unavailable or conflicts with the current revision."
        )


def validate_isin(value: str) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value, re.ASCII) is None:
        raise InstrumentUnavailable()
    expanded = "".join(
        str(ord(character) - 55) if character.isalpha() else character for character in value
    )
    total = 0
    for index, character in enumerate(reversed(expanded)):
        weighted = int(character) * (2 if index % 2 else 1)
        total += weighted // 10 + weighted % 10
    if total % 10:
        raise InstrumentUnavailable()
    return value


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class SchemeDefinition(Definition):
    name: str = Field(min_length=1, max_length=120, pattern=NAME, repr=False)


class InstrumentDefinition(SchemeDefinition):
    asset_class: Literal["equity", "etf", "mutual_fund"]
    isin: str = Field(repr=False)
    fund_scheme_id: UUID | None = None
    fund_plan: Literal["direct", "regular"] | None = None
    fund_option: FundOption | None = None
    fund_currency: Literal["INR"] | None = None

    @field_validator("isin")
    @classmethod
    def isin_checksum(cls, value: str) -> str:
        return validate_isin(value)

    @model_validator(mode="after")
    def variant(self) -> InstrumentDefinition:
        fields = (self.fund_scheme_id, self.fund_plan, self.fund_option, self.fund_currency)
        if self.asset_class == "mutual_fund":
            if any(value is None for value in fields) or self.fund_scheme_id == UUID(int=0):
                raise ValueError("Fund identity requires a scheme, plan, option and currency.")
        elif any(value is not None for value in fields):
            raise ValueError("Fund variant fields are unavailable for this asset class.")
        return self


class ListingDefinition(Definition):
    venue: Literal["XNSE", "XBOM", "XNYS", "XNAS", "ARCX"]
    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9.&/-]*$", repr=False)
    series: str = Field(default="", max_length=8, pattern=r"^([A-Z0-9]{1,8})?$")
    quote_currency: Literal["INR", "USD"]

    @model_validator(mode="after")
    def native_currency(self) -> ListingDefinition:
        expected = "INR" if self.venue in ("XNSE", "XBOM") else "USD"
        if self.quote_currency != expected:
            raise ValueError("Unsupported listing currency.")
        return self


class IdentifierDefinition(Definition):
    namespace: Literal["indmoney_india", "indmoney_us", "indmoney_funds", "ubs", "amfi_nav"]
    value: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$", repr=False
    )
    qualifier: Literal["", "growth", "idcw_payout", "idcw_reinvestment"] = ""

    @model_validator(mode="after")
    def qualified(self) -> IdentifierDefinition:
        if self.namespace == "amfi_nav":
            if not self.qualifier or re.fullmatch(r"[0-9]{1,12}", self.value, re.ASCII) is None:
                raise ValueError("AMFI identity requires an exact code and distribution option.")
        elif self.qualifier:
            raise ValueError("Qualifier is unavailable for this namespace.")
        return self


@dataclass(frozen=True, repr=False)
class Instrument:
    id: UUID
    definition: InstrumentDefinition


@dataclass(frozen=True, repr=False)
class Scheme:
    id: UUID
    definition: SchemeDefinition


@dataclass(frozen=True, repr=False)
class Listing:
    id: UUID
    instrument_id: UUID
    definition: ListingDefinition


@dataclass(frozen=True, repr=False)
class ProviderIdentifier:
    id: UUID
    definition: IdentifierDefinition


@dataclass(frozen=True)
class InstrumentMapping:
    identifier_id: UUID
    revision: int
    instrument_id: UUID | None
    listing_id: UUID | None
    reason: str


@dataclass(frozen=True)
class PositionIdentity:
    id: UUID
    account_id: UUID
    instrument_id: UUID
    holding_form: str


class InstrumentTransaction:
    def __init__(self, unit: WorkspaceTransaction) -> None:
        self._accounts = AccountTransaction(unit, None)

    def _execute(self, sql: str, **parameters: Any) -> Any:
        return self._accounts._execute(sql, **parameters)

    @contextmanager
    def _write(self) -> Iterator[None]:
        try:
            # Share the account lock: archive and position creation must serialize.
            with self._accounts._write():
                yield
        except AccountUnavailable:
            raise InstrumentUnavailable() from None

    def _budget(self, table: str) -> None:
        if (
            self._execute(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner").scalar_one()
            >= MAX_RECORDS
        ):
            raise InstrumentUnavailable()

    def scheme(self, definition: SchemeDefinition) -> Scheme:
        valid = SchemeDefinition.model_validate(definition.model_dump(warnings=False))
        with self._write():
            self._budget("fund_schemes")
            scheme_id = uuid4()
            self._execute(
                "INSERT INTO app.fund_schemes (owner_id,id,name) VALUES (:owner,:id,:name)",
                id=scheme_id,
                **valid.model_dump(),
            )
            return Scheme(scheme_id, valid)

    def get_scheme(self, scheme_id: UUID) -> Scheme | None:
        row = (
            self._execute(
                "SELECT id,name FROM app.fund_schemes WHERE owner_id=:owner AND id=:id",
                id=identifier(scheme_id),
            )
            .mappings()
            .one_or_none()
        )
        return Scheme(row["id"], SchemeDefinition(name=row["name"])) if row else None

    def schemes(self, *, limit: int = 25, after: UUID | None = None) -> tuple[Scheme, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT id,name FROM app.fund_schemes WHERE owner_id=:owner "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            after=after,
            limit=limit,
        ).mappings()
        return tuple(Scheme(row["id"], SchemeDefinition(name=row["name"])) for row in rows)

    @staticmethod
    def _instrument(row: Any) -> Instrument:
        return Instrument(
            row["id"],
            InstrumentDefinition.model_validate(
                {field: row[field] for field in InstrumentDefinition.model_fields}
            ),
        )

    def get(self, instrument_id: UUID) -> Instrument | None:
        row = (
            self._execute(
                "SELECT * FROM app.instruments WHERE owner_id=:owner AND id=:id",
                id=identifier(instrument_id),
            )
            .mappings()
            .one_or_none()
        )
        return self._instrument(row) if row else None

    def by_isin(self, isin: str) -> Instrument | None:
        row = (
            self._execute(
                "SELECT * FROM app.instruments WHERE owner_id=:owner AND isin=:isin",
                isin=validate_isin(isin),
            )
            .mappings()
            .one_or_none()
        )
        return self._instrument(row) if row else None

    def list(self, *, limit: int = 25, after: UUID | None = None) -> tuple[Instrument, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT * FROM app.instruments WHERE owner_id=:owner "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            after=after,
            limit=limit,
        ).mappings()
        return tuple(self._instrument(row) for row in rows)

    def create(self, definition: InstrumentDefinition) -> Instrument:
        valid = InstrumentDefinition.model_validate(definition.model_dump(warnings=False))
        with self._write():
            existing = self.by_isin(valid.isin)
            if existing:
                if existing.definition != valid:
                    raise InstrumentUnavailable()
                return existing
            self._budget("instruments")
            instrument_id = uuid4()
            self._execute(
                "INSERT INTO app.instruments "
                "(owner_id,id,asset_class,name,isin,fund_scheme_id,"
                "fund_plan,fund_option,fund_currency) "
                "VALUES (:owner,:id,:asset_class,:name,:isin,:fund_scheme_id,:fund_plan,"
                ":fund_option,:fund_currency)",
                id=instrument_id,
                **valid.model_dump(),
            )
            return Instrument(instrument_id, valid)

    def listing(self, instrument_id: UUID, definition: ListingDefinition) -> Listing:
        valid = ListingDefinition.model_validate(definition.model_dump(warnings=False))
        identifier(instrument_id)
        with self._write():
            row = self._execute(
                "SELECT id FROM app.instrument_listings WHERE owner_id=:owner "
                "AND instrument_id=:instrument AND venue=:venue AND symbol=:symbol "
                "AND series=:series AND quote_currency=:quote_currency",
                instrument=instrument_id,
                **valid.model_dump(),
            ).one_or_none()
            if row:
                return Listing(row[0], instrument_id, valid)
            self._budget("instrument_listings")
            listing_id = uuid4()
            self._execute(
                "INSERT INTO app.instrument_listings "
                "(owner_id,id,instrument_id,venue,symbol,series,quote_currency) "
                "VALUES (:owner,:id,:instrument,:venue,:symbol,:series,:quote_currency)",
                id=listing_id,
                instrument=instrument_id,
                **valid.model_dump(),
            )
            return Listing(listing_id, instrument_id, valid)

    def listings(
        self, instrument_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[Listing, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT * FROM app.instrument_listings WHERE owner_id=:owner "
            "AND instrument_id=:instrument "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            instrument=identifier(instrument_id),
            after=after,
            limit=limit,
        ).mappings()
        return tuple(
            Listing(
                row["id"],
                row["instrument_id"],
                ListingDefinition.model_validate(
                    {field: row[field] for field in ListingDefinition.model_fields}
                ),
            )
            for row in rows
        )

    def identifier(self, definition: IdentifierDefinition) -> ProviderIdentifier:
        valid = IdentifierDefinition.model_validate(definition.model_dump(warnings=False))
        with self._write():
            row = self._execute(
                "SELECT id FROM app.instrument_identifiers WHERE owner_id=:owner "
                "AND namespace=:namespace AND value=:value AND qualifier=:qualifier",
                **valid.model_dump(),
            ).one_or_none()
            if row:
                return ProviderIdentifier(row[0], valid)
            self._budget("instrument_identifiers")
            reference_id = uuid4()
            self._execute(
                "INSERT INTO app.instrument_identifiers (owner_id,id,namespace,value,qualifier) "
                "VALUES (:owner,:id,:namespace,:value,:qualifier)",
                id=reference_id,
                **valid.model_dump(),
            )
            return ProviderIdentifier(reference_id, valid)

    def mapping(self, reference_id: UUID) -> InstrumentMapping | None:
        row = (
            self._execute(
                "SELECT identifier_id,revision,instrument_id,listing_id,reason "
                "FROM app.instrument_mappings WHERE owner_id=:owner AND identifier_id=:id "
                "ORDER BY revision DESC LIMIT 1",
                id=identifier(reference_id),
            )
            .mappings()
            .one_or_none()
        )
        return InstrumentMapping(**row) if row else None

    def history(
        self, reference_id: UUID, *, limit: int = 25, before: int | None = None
    ) -> tuple[InstrumentMapping, ...]:
        page(limit, None)
        if before is not None:
            revision(before)
        rows = self._execute(
            "SELECT identifier_id,revision,instrument_id,listing_id,reason "
            "FROM app.instrument_mappings WHERE owner_id=:owner AND identifier_id=:id "
            "AND (CAST(:before AS bigint) IS NULL OR revision<:before) "
            "ORDER BY revision DESC LIMIT :limit",
            id=identifier(reference_id),
            before=before,
            limit=limit,
        ).mappings()
        return tuple(InstrumentMapping(**row) for row in rows)

    def map(
        self,
        reference_id: UUID,
        instrument_id: UUID | None,
        *,
        expected_revision: int,
        listing_id: UUID | None = None,
    ) -> InstrumentMapping:
        expected = revision(expected_revision, initial=True)
        identifier(reference_id)
        if instrument_id is not None:
            identifier(instrument_id)
        if listing_id is not None:
            identifier(listing_id)
            if instrument_id is None:
                raise InstrumentUnavailable()
        with self._write():
            present = self._execute(
                "SELECT id FROM app.instrument_identifiers WHERE owner_id=:owner AND id=:id",
                id=reference_id,
            ).one_or_none()
            current = self.mapping(reference_id)
            if present is None or (current.revision if current else 0) != expected:
                raise InstrumentUnavailable()
            if current and (current.instrument_id, current.listing_id) == (
                instrument_id,
                listing_id,
            ):
                return current
            if instrument_id is None and current is None:
                raise InstrumentUnavailable()
            self._budget("instrument_mappings")
            reason = (
                "unlinked" if instrument_id is None else "initial" if not current else "correction"
            )
            result = InstrumentMapping(
                reference_id, expected + 1, instrument_id, listing_id, reason
            )
            self._execute(
                "INSERT INTO app.instrument_mappings "
                "(owner_id,identifier_id,revision,previous_revision,"
                "instrument_id,listing_id,reason) "
                "VALUES (:owner,:id,:revision,:previous,:instrument,:listing,:reason)",
                id=reference_id,
                revision=result.revision,
                previous=expected or None,
                instrument=instrument_id,
                listing=listing_id,
                reason=reason,
            )
            return result

    def position(
        self, account_id: UUID, instrument_id: UUID, holding_form: str
    ) -> PositionIdentity:
        identifier(account_id)
        identifier(instrument_id)
        if type(holding_form) is not str or holding_form not in ("folio", "demat", "custody"):
            raise InstrumentUnavailable()
        with self._write():
            row = self._execute(
                "SELECT id FROM app.account_positions WHERE owner_id=:owner "
                "AND account_id=:account AND instrument_id=:instrument AND holding_form=:form",
                account=account_id,
                instrument=instrument_id,
                form=holding_form,
            ).one_or_none()
            if row:
                return PositionIdentity(row[0], account_id, instrument_id, holding_form)
            self._budget("account_positions")
            position_id = uuid4()
            self._execute(
                "INSERT INTO app.account_positions "
                "(owner_id,id,account_id,instrument_id,holding_form) "
                "VALUES (:owner,:id,:account,:instrument,:form)",
                id=position_id,
                account=account_id,
                instrument=instrument_id,
                form=holding_form,
            )
            return PositionIdentity(position_id, account_id, instrument_id, holding_form)

    def positions(
        self, account_id: UUID, *, limit: int = 25, after: UUID | None = None
    ) -> tuple[PositionIdentity, ...]:
        page(limit, after)
        rows = self._execute(
            "SELECT id,account_id,instrument_id,holding_form FROM app.account_positions "
            "WHERE owner_id=:owner AND account_id=:account "
            "AND (CAST(:after AS uuid) IS NULL OR id>CAST(:after AS uuid)) "
            "ORDER BY id LIMIT :limit",
            account=identifier(account_id),
            after=after,
            limit=limit,
        ).mappings()
        return tuple(PositionIdentity(**row) for row in rows)


class InstrumentDatabase:
    def __init__(self, url: URL, project: str) -> None:
        self._workspace = WorkspaceDatabase(url, project)

    def close(self) -> None:
        self._workspace.close()

    @contextmanager
    def transaction(self, owner_id: UUID) -> Iterator[InstrumentTransaction]:
        try:
            with self._workspace.transaction(owner_id) as unit:
                yield InstrumentTransaction(unit)
        except SQLAlchemyError, AccountUnavailable:
            raise InstrumentUnavailable() from None
