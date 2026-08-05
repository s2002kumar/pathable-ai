"""Deterministic OpenAPI export.

The exported document is the contract source of truth: ``packages/contracts``
generates TypeScript from it and CI fails when the committed output drifts from
what the code produces. That only works if the export is byte-stable, so this
module builds the app from a fixed configuration rather than the ambient
environment, and serialises with sorted keys.

Usage::

    uv run python -m pathable_api.openapi_export path/to/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pathable_api.core.config import Settings
from pathable_api.main import create_app


def export_settings() -> Settings:
    """Fixed configuration used for export.

    Nothing here may come from the host environment — ``_env_file=None`` also
    disables .env discovery — otherwise the generated document would differ
    between a developer's machine and CI, and the drift check would be useless.
    """
    return Settings(
        _env_file=None,
        environment="test",
        service_name="pathable-api",
        app_version="0.1.0",
        database_url=None,
        allowed_origins=(),
        log_level="WARNING",
        log_format="console",
    )


def build_openapi_document() -> dict[str, Any]:
    """Return the OpenAPI document as a plain dictionary."""
    app = create_app(export_settings())
    document: dict[str, Any] = app.openapi()
    return document


def serialise(document: dict[str, Any]) -> str:
    """Serialise deterministically: sorted keys, stable indent, trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_openapi(destination: Path) -> Path:
    """Write the document to ``destination`` and return the path.

    ``newline="\\n"`` is explicit: on Windows, text mode would translate to CRLF,
    so the committed artefact would differ byte-for-byte from the one CI
    generates on Linux purely because of the host operating system.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        serialise(build_openapi_document()), encoding="utf-8", newline="\n"
    )
    return destination


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    destination = Path(args[0]) if args else Path("openapi.json")
    written = write_openapi(destination)
    sys.stdout.write(f"OpenAPI written to {written}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
