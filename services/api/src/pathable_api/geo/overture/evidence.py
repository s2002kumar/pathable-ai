"""Deterministic JSON for manifests and evidence.

Two runs over the same inputs must produce the same content hash, so anyone
can tell whether a re-run reproduced a result or merely resembled it. Timings,
wall-clock timestamps and the machine a run happened on are real facts worth
recording, but they differ every time; they live under keys named in
:data:`VOLATILE_KEYS` and are left out of the hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

#: Keys whose values legitimately change between identical runs.
VOLATILE_KEYS: frozenset[str] = frozenset({"run", "measurement", "acquired_at", "generated_at"})


def canonical_json(document: Any, *, exclude: Iterable[str] = VOLATILE_KEYS) -> str:
    """Sorted keys, no insignificant whitespace, volatile keys removed at every depth."""
    return json.dumps(
        _without(document, frozenset(exclude)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_sha256(document: Any, *, exclude: Iterable[str] = VOLATILE_KEYS) -> str:
    return hashlib.sha256(canonical_json(document, exclude=exclude).encode("utf-8")).hexdigest()


def file_sha256(path: Path, *, chunk_bytes: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Readable, LF-terminated JSON — these files are committed as evidence and the
    repository's formatter rejects CRLF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _without(value: Any, exclude: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _without(v, exclude) for k, v in value.items() if k not in exclude}
    if isinstance(value, list | tuple):
        return [_without(item, exclude) for item in value]
    return value
