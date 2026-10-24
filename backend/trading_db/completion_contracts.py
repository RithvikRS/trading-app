"""Bounded completion requests; economics and ownership resolve from database evidence."""

import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_db.account_keys import ReferenceUnavailable, reference


class CompletionContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class CompletionDirective(CompletionContract):
    row_id: UUID
    review_revision: int = Field(ge=1, le=9007199254740991)
    operation: Literal["record", "correct", "exclude"]
    position_id: UUID | None = None
    lot_id: UUID | None = None
    lot_source_row_id: UUID | None = None
    target_kind: Literal["event", "lot", "snapshot"] | None = None
    target_id: UUID | None = None
    target_revision: int | None = Field(default=None, ge=1, le=9007199254740991)
    correction_reason: (
        Literal["source_correction", "posting_update", "cancellation", "reinstatement"] | None
    ) = None

    @property
    def _has_provider_reference(self) -> bool:
        return False

    @model_validator(mode="after")
    def shape(self) -> CompletionDirective:
        for value in (
            self.row_id,
            self.position_id,
            self.lot_id,
            self.lot_source_row_id,
            self.target_id,
        ):
            if value is not None and not value.int:
                raise ValueError("Completion requires nonzero opaque identities.")
        if self.lot_id is not None and self.lot_source_row_id is not None:
            raise ValueError("A lot observation requires one explicit lot target.")
        if (
            self.lot_id is not None or self.lot_source_row_id is not None
        ) and self.position_id is None:
            raise ValueError("A lot target requires its explicit position.")
        if self.lot_source_row_id == self.row_id:
            raise ValueError("A source occurrence cannot reference itself as a lot.")
        correction = (
            self.target_kind,
            self.target_id,
            self.target_revision,
            self.correction_reason,
        )
        if self.operation == "correct":
            if (
                any(value is None for value in correction)
                or any(
                    value is not None
                    for value in (
                        self.position_id,
                        self.lot_id,
                        self.lot_source_row_id,
                    )
                )
                or self._has_provider_reference
            ):
                raise ValueError("Correction requires exactly one existing target and reason.")
            if self.correction_reason == "posting_update" and self.target_kind != "event":
                raise ValueError("Posting updates require event evidence.")
        elif any(value is not None for value in correction):
            raise ValueError("Only a correction can name a correction target.")
        if self.operation == "exclude" and (
            self._has_provider_reference
            or any(
                value is not None
                for value in (
                    self.position_id,
                    self.lot_id,
                    self.lot_source_row_id,
                )
            )
        ):
            raise ValueError("An excluded occurrence cannot request financial effects.")
        return self


class CompletionRow(CompletionDirective):
    provider_reference: str | None = Field(default=None, repr=False, max_length=128)

    @property
    def _has_provider_reference(self) -> bool:
        return self.provider_reference is not None

    @model_validator(mode="after")
    def private_reference(self) -> CompletionRow:
        if self.provider_reference is not None:
            try:
                reference(self.provider_reference)
            except ReferenceUnavailable:
                raise ValueError(
                    "Provider reference does not match its bounded contract."
                ) from None
        return self


class ManifestRow(CompletionDirective):
    provider_reference_supplied: bool

    @property
    def _has_provider_reference(self) -> bool:
        return self.provider_reference_supplied


class CompletionSelection(CompletionContract):
    row_id: UUID
    expected_revision: int = Field(ge=0, le=9007199254740991)
    reason: Literal["reviewed", "newer_evidence", "correction"] = "reviewed"

    @model_validator(mode="after")
    def nonzero(self) -> CompletionSelection:
        if not self.row_id.int:
            raise ValueError("Selection requires a nonzero source occurrence.")
        return self


class CompletionEnvelope(CompletionContract):
    idempotency_key: UUID
    batch_id: UUID
    batch_revision: int = Field(ge=1, le=9007199254740991)
    baseline: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$", repr=False)
    mode: Literal["reconciled", "limited"]
    rows: tuple[CompletionDirective, ...] = Field(min_length=1, max_length=100, repr=False)
    selections: tuple[CompletionSelection, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def identities(self) -> CompletionEnvelope:
        if not self.idempotency_key.int or not self.batch_id.int:
            raise ValueError("Completion requires nonzero opaque identities.")
        rows = {row.row_id: row for row in self.rows}
        if len(rows) != len(self.rows):
            raise ValueError("A source occurrence cannot be requested twice.")
        selected = {item.row_id for item in self.selections}
        if len(selected) != len(self.selections) or any(
            row_id not in rows or rows[row_id].operation == "exclude" for row_id in selected
        ):
            raise ValueError("Selections require unique included source occurrences.")
        if any(
            row.lot_source_row_id is not None
            and (
                row.lot_source_row_id not in rows
                or rows[row.lot_source_row_id].operation != "record"
                or rows[row.lot_source_row_id].lot_source_row_id is not None
                or rows[row.lot_source_row_id].lot_id is not None
            )
            for row in self.rows
        ):
            raise ValueError("A new lot reference requires a recorded occurrence in this batch.")
        return self


class CompletionRequest(CompletionEnvelope):
    rows: tuple[CompletionRow, ...] = Field(min_length=1, max_length=100, repr=False)


class CompletionManifest(CompletionEnvelope):
    request_contract: Literal[1]
    rows: tuple[ManifestRow, ...] = Field(min_length=1, max_length=100, repr=False)


def _encode(body: dict[str, object]) -> str:
    result = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(result.encode("utf-8")) > 65536:
        raise ValueError("Completion request exceeds its bounded manifest.")
    return result


def canonical_request(request: CompletionRequest) -> str:
    valid = CompletionRequest.model_validate(request)
    body = valid.model_dump(mode="json", exclude={"rows", "selections"}, exclude_none=True)
    body["rows"] = [
        row.model_dump(mode="json", exclude={"provider_reference"}, exclude_none=True)
        | {"provider_reference_supplied": row.provider_reference is not None}
        for row in sorted(valid.rows, key=lambda value: value.row_id)
    ]
    body["selections"] = [
        item.model_dump(mode="json")
        for item in sorted(valid.selections, key=lambda value: value.row_id)
    ]
    body["request_contract"] = 1
    return _encode(body)


def parse_manifest(value: str) -> CompletionManifest:
    """Accept only the exact bounded public representation, without private placeholders."""
    if type(value) is not str or len(value.encode("utf-8")) > 65536:
        raise ValueError("Completion manifest is unavailable.")
    valid = CompletionManifest.model_validate_json(value)
    body = valid.model_dump(mode="json", exclude={"rows", "selections"}, exclude_none=True)
    body["rows"] = [
        row.model_dump(mode="json", exclude_none=True)
        for row in sorted(valid.rows, key=lambda item: item.row_id)
    ]
    body["selections"] = [
        item.model_dump(mode="json")
        for item in sorted(valid.selections, key=lambda item: item.row_id)
    ]
    if _encode(body) != value:
        raise ValueError("Completion manifest is not canonical.")
    return valid
