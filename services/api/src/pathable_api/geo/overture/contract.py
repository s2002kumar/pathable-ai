"""The columns this pipeline depends on, checked against what a file actually holds.

A schema version number is a claim; the Parquet schema is the fact. Before a
file is read for real, its schema is compared with the contract below. Every
column and nested field the pipeline reads must be present with a compatible
type, and a file that fails is refused with the failures named. Columns the
contract does not mention are allowed and recorded — Overture adds properties
between releases, and an addition is not a reason to stop.

The contract is deliberately narrow: identity, provenance, topology, extent,
geometry, and the three attribute lists the source-independence measurement
inspects (``road_surface``, ``width_rules``, ``access_restrictions``). Everything
else is carried into the regional extract untouched but not relied on, so it is
not listed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Scalar:
    #: DuckDB type ids that satisfy this field.
    kinds: frozenset[str]

    def describe(self) -> str:
        return "|".join(sorted(self.kinds))


@dataclass(frozen=True, slots=True)
class ListOf:
    element: TypeSpec

    def describe(self) -> str:
        return f"{self.element.describe()}[]"


@dataclass(frozen=True, slots=True)
class StructOf:
    fields: Mapping[str, TypeSpec]

    def describe(self) -> str:
        return "STRUCT(" + ", ".join(f"{k} {v.describe()}" for k, v in self.fields.items()) + ")"


TypeSpec = Scalar | ListOf | StructOf

VARCHAR = Scalar(frozenset({"varchar"}))
DOUBLE = Scalar(frozenset({"double"}))
INTEGER = Scalar(frozenset({"integer", "bigint"}))
GEOMETRY = Scalar(frozenset({"geometry"}))

_BBOX = StructOf({"xmin": DOUBLE, "xmax": DOUBLE, "ymin": DOUBLE, "ymax": DOUBLE})

_SOURCE = StructOf(
    {
        "property": VARCHAR,
        "dataset": VARCHAR,
        "record_id": VARCHAR,
        "update_time": VARCHAR,
        "between": ListOf(DOUBLE),
        "version": VARCHAR,
        "confidence": DOUBLE,
    }
)

SEGMENT_CONTRACT: dict[str, TypeSpec] = {
    "id": VARCHAR,
    "subtype": VARCHAR,
    "class": VARCHAR,
    "subclass": VARCHAR,
    "connectors": ListOf(StructOf({"connector_id": VARCHAR, "at": DOUBLE})),
    "sources": ListOf(_SOURCE),
    "geometry": GEOMETRY,
    "version": INTEGER,
    "bbox": _BBOX,
    "road_surface": ListOf(StructOf({"value": VARCHAR, "between": ListOf(DOUBLE)})),
    "width_rules": ListOf(StructOf({"value": DOUBLE, "between": ListOf(DOUBLE)})),
    "access_restrictions": ListOf(StructOf({"access_type": VARCHAR, "between": ListOf(DOUBLE)})),
}

CONNECTOR_CONTRACT: dict[str, TypeSpec] = {
    "id": VARCHAR,
    "sources": ListOf(_SOURCE),
    "geometry": GEOMETRY,
    "version": INTEGER,
    "bbox": _BBOX,
}

BRIDGE_CONTRACT: dict[str, TypeSpec] = {
    "id": VARCHAR,
    "dataset": VARCHAR,
    "record_id": VARCHAR,
    "update_time": VARCHAR,
    "resource": VARCHAR,
    "version": VARCHAR,
    "between": ListOf(DOUBLE),
    "dataset_between": ListOf(DOUBLE),
}

CHANGELOG_CONTRACT: dict[str, TypeSpec] = {
    "id": VARCHAR,
    "bbox": _BBOX,
    "columns_changed": ListOf(VARCHAR),
    "change_type": VARCHAR,
    "type": VARCHAR,
}

CONTRACTS: dict[str, dict[str, TypeSpec]] = {
    "segment": SEGMENT_CONTRACT,
    "connector": CONNECTOR_CONTRACT,
    "bridge": BRIDGE_CONTRACT,
    "changelog": CHANGELOG_CONTRACT,
}


class DuckType(Protocol):
    """The part of ``duckdb.DuckDBPyType`` the contract needs."""

    @property
    def id(self) -> str: ...

    @property
    def children(self) -> list[tuple[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class ObservedType:
    """A plain-data copy of a DuckDB type, so checks are testable without DuckDB."""

    kind: str
    rendered: str
    #: Struct fields by name; a list's element under the single key ``""``.
    children: Mapping[str, ObservedType] = field(default_factory=dict)


def observe(duck_type: DuckType) -> ObservedType:
    kind = str(duck_type.id)
    children: dict[str, ObservedType] = {}
    if kind == "list":
        children[""] = observe(duck_type.children[0][1])
    elif kind == "struct":
        for name, child in duck_type.children:
            children[str(name)] = observe(child)
    return ObservedType(kind=kind, rendered=str(duck_type), children=children)


@dataclass(frozen=True, slots=True)
class SchemaCheck:
    artifact: str
    missing: tuple[str, ...]
    mismatched: tuple[str, ...]
    additional: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return not self.missing and not self.mismatched

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "compatible": self.compatible,
            "missing": list(self.missing),
            "mismatched": list(self.mismatched),
            "additional_columns": list(self.additional),
        }


class IncompatibleSchemaError(RuntimeError):
    def __init__(self, check: SchemaCheck, location: str) -> None:
        self.check = check
        problems = [f"missing {name}" for name in check.missing] + list(check.mismatched)
        super().__init__(
            f"{check.artifact} file {location} does not satisfy the column contract: "
            + "; ".join(problems)
        )


def check_schema(
    artifact: str,
    columns: Sequence[str],
    types: Sequence[ObservedType],
    contract: Mapping[str, TypeSpec] | None = None,
) -> SchemaCheck:
    expected = contract if contract is not None else CONTRACTS[artifact]
    observed = dict(zip(columns, types, strict=True))
    missing: list[str] = []
    mismatched: list[str] = []
    for name, spec in expected.items():
        if name not in observed:
            missing.append(name)
            continue
        _compare(name, spec, observed[name], missing, mismatched)
    additional = tuple(sorted(name for name in observed if name not in expected))
    return SchemaCheck(artifact, tuple(missing), tuple(mismatched), additional)


def _compare(
    path: str,
    spec: TypeSpec,
    observed: ObservedType,
    missing: list[str],
    mismatched: list[str],
) -> None:
    match spec:
        case Scalar(kinds):
            if observed.kind not in kinds:
                mismatched.append(f"{path} is {observed.rendered}, expected {spec.describe()}")
        case ListOf(element):
            if observed.kind != "list":
                mismatched.append(f"{path} is {observed.rendered}, expected {spec.describe()}")
                return
            _compare(f"{path}[]", element, observed.children[""], missing, mismatched)
        case StructOf(fields):
            if observed.kind != "struct":
                mismatched.append(f"{path} is {observed.rendered}, expected a STRUCT")
                return
            for name, child_spec in fields.items():
                child = observed.children.get(name)
                if child is None:
                    missing.append(f"{path}.{name}")
                    continue
                _compare(f"{path}.{name}", child_spec, child, missing, mismatched)
