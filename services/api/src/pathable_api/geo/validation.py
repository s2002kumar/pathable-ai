"""Dataset validation.

A dataset must pass validation before it can be activated, so this is the gate
that stops a broken import from becoming the network people route on.

Errors block activation; warnings do not. That split is deliberate: real OSM
extracts always contain oddities — an unconnected footpath stub, a way with no
surface tag — and a policy that blocked on those would mean no real dataset
could ever go live, which would push everyone toward disabling validation
entirely.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import box

from pathable_api.geo.enums import Severity
from pathable_api.geo.network import NetworkPayload

#: How far outside the declared bounds a geometry may stray before it is an
#: error rather than rounding. ~110 m at this latitude.
_BOUNDS_TOLERANCE_DEGREES = 0.001


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    severity: Severity
    message: str
    entity_type: str | None = None
    entity_reference: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "entity_type": self.entity_type,
            "entity_reference": self.entity_reference,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    findings: tuple[ValidationFinding, ...]

    @property
    def errors(self) -> tuple[ValidationFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def is_valid(self) -> bool:
        """Only errors block activation."""
        return not self.errors

    def summary(self) -> dict[str, Any]:
        by_code = Counter(f.code for f in self.findings)
        return {
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "codes": dict(by_code),
            # Bounded so a dataset with 10k identical warnings does not write a
            # 10k-element JSON blob into every row.
            "findings": [f.to_dict() for f in self.findings[:200]],
            "truncated": len(self.findings) > 200,
        }


def validate_network(
    payload: NetworkPayload,
    *,
    declared_bounds: tuple[float, float, float, float] | None = None,
    expected_node_count: int | None = None,
    expected_edge_count: int | None = None,
) -> ValidationReport:
    """Check a network's structural and geometric integrity."""
    findings: list[ValidationFinding] = []

    # --- Emptiness --------------------------------------------------------
    if payload.node_count == 0:
        findings.append(
            ValidationFinding(
                code="dataset.no_nodes",
                severity=Severity.ERROR,
                message="Dataset contains no nodes; nothing can be routed.",
                entity_type="dataset",
            )
        )
    if payload.edge_count == 0:
        findings.append(
            ValidationFinding(
                code="dataset.no_edges",
                severity=Severity.ERROR,
                message="Dataset contains no edges; nothing can be routed.",
                entity_type="dataset",
            )
        )

    # --- Node identity and geometry ---------------------------------------
    node_ids: set[str] = set()
    duplicate_nodes: set[str] = set()
    for node in payload.nodes:
        if node.source_node_id in node_ids:
            duplicate_nodes.add(node.source_node_id)
        node_ids.add(node.source_node_id)

        if node.geometry.is_empty:
            findings.append(
                ValidationFinding(
                    code="node.empty_geometry",
                    severity=Severity.ERROR,
                    message="Node geometry is empty.",
                    entity_type="node",
                    entity_reference=node.source_node_id,
                )
            )
        elif not _is_plausible_lonlat(node.longitude, node.latitude):
            findings.append(
                ValidationFinding(
                    code="node.invalid_coordinates",
                    severity=Severity.ERROR,
                    message="Node coordinates are outside the valid WGS84 range.",
                    entity_type="node",
                    entity_reference=node.source_node_id,
                    details={"longitude": node.longitude, "latitude": node.latitude},
                )
            )

    for duplicate in sorted(duplicate_nodes):
        findings.append(
            ValidationFinding(
                code="node.duplicate_identity",
                severity=Severity.ERROR,
                message="Two nodes share one source identity within the dataset.",
                entity_type="node",
                entity_reference=duplicate,
            )
        )

    # --- Edge identity, topology and geometry -----------------------------
    edge_identities: set[tuple[str, str, int]] = set()
    for edge in payload.edges:
        reference = f"{edge.source_u}->{edge.source_v}#{edge.edge_key}"

        identity = (edge.source_u, edge.source_v, edge.edge_key)
        if identity in edge_identities:
            findings.append(
                ValidationFinding(
                    code="edge.duplicate_identity",
                    severity=Severity.ERROR,
                    message="Two edges share one identity within the dataset.",
                    entity_type="edge",
                    entity_reference=reference,
                )
            )
        edge_identities.add(identity)

        for endpoint, role in ((edge.source_u, "from"), (edge.source_v, "to")):
            if endpoint not in node_ids:
                findings.append(
                    ValidationFinding(
                        code="edge.missing_endpoint_node",
                        severity=Severity.ERROR,
                        message=f"Edge {role} node is not present in the dataset.",
                        entity_type="edge",
                        entity_reference=reference,
                        details={"missing_node": endpoint},
                    )
                )

        if edge.geometry.is_empty or len(edge.geometry.coords) < 2:
            findings.append(
                ValidationFinding(
                    code="edge.invalid_geometry",
                    severity=Severity.ERROR,
                    message="Edge geometry is empty or has fewer than two positions.",
                    entity_type="edge",
                    entity_reference=reference,
                )
            )
        elif not edge.geometry.is_valid:
            findings.append(
                ValidationFinding(
                    code="edge.invalid_geometry",
                    severity=Severity.ERROR,
                    message="Edge geometry is not a valid linestring.",
                    entity_type="edge",
                    entity_reference=reference,
                )
            )

        if edge.length <= 0:
            findings.append(
                ValidationFinding(
                    code="edge.non_positive_length",
                    severity=Severity.ERROR,
                    message="Edge length must be greater than zero.",
                    entity_type="edge",
                    entity_reference=reference,
                    details={"length_m": edge.length},
                )
            )

        missing = edge.features.unknown_attributes
        if missing:
            findings.append(
                ValidationFinding(
                    code="edge.missing_accessibility_data",
                    severity=Severity.WARNING,
                    message="Edge is missing accessibility attributes; treated as unknown.",
                    entity_type="edge",
                    entity_reference=reference,
                    details={"attributes": list(missing)},
                )
            )

    # --- Declared bounds --------------------------------------------------
    actual = payload.bounds()
    if declared_bounds is not None and actual is not None:
        allowed = box(*declared_bounds).buffer(_BOUNDS_TOLERANCE_DEGREES)
        if not allowed.contains(box(*actual)):
            findings.append(
                ValidationFinding(
                    code="dataset.geometry_outside_bounds",
                    severity=Severity.ERROR,
                    message="Dataset geometry extends materially outside the declared bounds.",
                    entity_type="dataset",
                    details={"declared": list(declared_bounds), "actual": list(actual)},
                )
            )

    # --- Count agreement --------------------------------------------------
    if expected_node_count is not None and expected_node_count != payload.node_count:
        findings.append(
            ValidationFinding(
                code="dataset.node_count_mismatch",
                severity=Severity.ERROR,
                message="Recorded node count does not match the number of nodes.",
                entity_type="dataset",
                details={"expected": expected_node_count, "actual": payload.node_count},
            )
        )
    if expected_edge_count is not None and expected_edge_count != payload.edge_count:
        findings.append(
            ValidationFinding(
                code="dataset.edge_count_mismatch",
                severity=Severity.ERROR,
                message="Recorded edge count does not match the number of edges.",
                entity_type="dataset",
                details={"expected": expected_edge_count, "actual": payload.edge_count},
            )
        )

    return ValidationReport(findings=tuple(findings))


def _is_plausible_lonlat(longitude: float, latitude: float) -> bool:
    return -180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0
