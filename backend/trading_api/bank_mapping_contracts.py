"""Finite bank assignment transitions; history proves state, not request delivery."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from trading_api.credit_read_contracts import private_payload
from trading_api.read_contracts import AccountView, OpaqueIdentifier, WireModel

MAX_MAPPING_REVISION = 9007199254740991

type BankNamespace = Literal["hdfc_statement", "sbi_statement"]
type ExpectedMappingRevision = Annotated[int, Field(ge=0, lt=MAX_MAPPING_REVISION)]
type StoredMappingRevision = Annotated[int, Field(ge=1, le=MAX_MAPPING_REVISION)]
type MappingHeadRevision = Annotated[int, Field(ge=0, le=MAX_MAPPING_REVISION)]


def invalid() -> None:
    raise ValueError("Bank source mapping is unavailable.")


def checked[T: WireModel](model: type[T], value: T) -> T:
    # Revalidate constructed models without allowing a supplied serializer to choose a schema.
    if type(value) is not model:
        invalid()
    return model.model_validate(private_payload(value))


class BankSourceScope(WireModel):
    source_id: OpaqueIdentifier
    namespace: BankNamespace


class BankMappingChange(WireModel):
    source_id: OpaqueIdentifier
    expected_revision: ExpectedMappingRevision
    account_id: OpaqueIdentifier | None

    @model_validator(mode="after")
    def initial_link(self) -> BankMappingChange:
        if self.expected_revision == 0 and self.account_id is None:
            invalid()
        return self


class BankMappingTransition(BankSourceScope):
    revision: StoredMappingRevision
    previous_revision: StoredMappingRevision | None
    account_id: OpaqueIdentifier | None
    reason: Literal["initial", "correction", "unlinked"]

    @model_validator(mode="after")
    def predecessor(self) -> BankMappingTransition:
        if self.previous_revision != (self.revision - 1 if self.revision > 1 else None):
            invalid()
        expected = (
            "unlinked"
            if self.account_id is None
            else ("initial" if self.revision == 1 else "correction")
        )
        if self.reason != expected or (self.revision == 1 and self.account_id is None):
            invalid()
        return self


class BankMappingHead(BankSourceScope):
    head_revision: MappingHeadRevision
    head: BankMappingTransition | None

    @model_validator(mode="after")
    def current_head(self) -> BankMappingHead:
        if (self.head_revision == 0) != (self.head is None):
            invalid()
        if self.head is not None and (
            self.head.revision != self.head_revision
            or self.head.source_id != self.source_id
            or self.head.namespace != self.namespace
        ):
            invalid()
        return self


class BankMappingHistoryQuery(WireModel):
    source_id: OpaqueIdentifier
    limit: int = Field(default=25, ge=1, le=100)
    before: StoredMappingRevision | None = None


class BankMappingHistoryPage(BankMappingHead):
    items: tuple[BankMappingTransition, ...] = Field(max_length=100, repr=False)
    next_before: StoredMappingRevision | None

    @model_validator(mode="after")
    def history(self) -> BankMappingHistoryPage:
        expected_cursor = (
            self.items[-1].revision if self.items and self.items[-1].revision > 1 else None
        )
        if self.next_before != expected_cursor:
            invalid()
        for index, item in enumerate(self.items):
            if (
                item.source_id != self.source_id
                or item.namespace != self.namespace
                or item.revision > self.head_revision
            ):
                invalid()
            newer = self.items[index - 1] if index else self.head
            if index and newer is not None and newer.previous_revision != item.revision:
                invalid()
            if newer is not None:
                if newer.revision == item.revision and newer != item:
                    invalid()
                if newer.previous_revision == item.revision and newer.account_id == item.account_id:
                    invalid()
        return self


class BankMappingTarget(AccountView):
    kind: Literal["bank"]
    institution: Literal["hdfc", "sbi"]
    market: Literal["IN"]
    state: Literal["active"]
    label: str = Field(pattern=r"^[A-Za-z][A-Za-z .()-]{0,63}$", repr=False)

    @model_validator(mode="after")
    def canonical_native_currencies(self) -> BankMappingTarget:
        if self.currencies not in (("INR",), ("USD",), ("INR", "USD")):
            invalid()
        return self


def validate_target(source: BankSourceScope, target: BankMappingTarget) -> BankMappingTarget:
    scope, active = checked(BankSourceScope, source), checked(BankMappingTarget, target)
    if (scope.namespace, active.institution) not in (
        ("hdfc_statement", "hdfc"),
        ("sbi_statement", "sbi"),
    ):
        invalid()
    return active


def derive_transition(
    command: BankMappingChange,
    source: BankSourceScope,
    previous: BankMappingTransition | None,
) -> BankMappingTransition:
    request, scope = checked(BankMappingChange, command), checked(BankSourceScope, source)
    predecessor = checked(BankMappingTransition, previous) if previous is not None else None
    if request.source_id != scope.source_id or request.expected_revision != (
        predecessor.revision if predecessor is not None else 0
    ):
        invalid()
    if predecessor is not None and (
        predecessor.source_id != scope.source_id
        or predecessor.namespace != scope.namespace
        or predecessor.account_id == request.account_id
    ):
        invalid()
    return BankMappingTransition(
        source_id=scope.source_id,
        namespace=scope.namespace,
        revision=request.expected_revision + 1,
        previous_revision=request.expected_revision or None,
        account_id=request.account_id,
        reason="unlinked"
        if request.account_id is None
        else ("initial" if request.expected_revision == 0 else "correction"),
    )


def validate_replay(
    command: BankMappingChange,
    source: BankSourceScope,
    previous: BankMappingTransition | None,
    retained: BankMappingTransition,
) -> BankMappingTransition:
    expected = derive_transition(command, source, previous)
    saved = checked(BankMappingTransition, retained)
    if saved != expected:
        invalid()
    return saved


def validate_history(
    query: BankMappingHistoryQuery,
    page: BankMappingHistoryPage,
    *,
    source: BankSourceScope,
    minimum_revision: int = 0,
) -> BankMappingHistoryPage:
    request = checked(BankMappingHistoryQuery, query)
    response = checked(BankMappingHistoryPage, page)
    selected = checked(BankSourceScope, source)
    if (
        type(minimum_revision) is not int
        or not 0 <= minimum_revision <= MAX_MAPPING_REVISION
        or response.source_id != request.source_id
        or request.source_id != selected.source_id
        or response.namespace != selected.namespace
        or response.head_revision < minimum_revision
    ):
        invalid()
    start = (
        min(response.head_revision, request.before - 1)
        if request.before
        else response.head_revision
    )
    count = min(start, request.limit)
    if len(response.items) != count or (response.items and response.items[0].revision != start):
        invalid()
    return response
