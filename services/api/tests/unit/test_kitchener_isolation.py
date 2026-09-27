"""No path from the Kitchener research code into routing, in either direction.

PA-GEO-05 matches City records to OSM and writes research artifacts. None of
it may reach what PathAble routes on until a founder licensing decision says
so. This is checked statically, from the source, so it holds for code paths no
test happens to run:

- nothing that serves or builds routes imports the Kitchener modules — only
  the command line, which runs the research commands, does;
- the conflation modules import neither the database layer nor routing, so
  they cannot write anything routing reads.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pathable_api

PACKAGE = Path(pathable_api.__file__).parent
KITCHENER = PACKAGE / "geo" / "kitchener"
CONFLATION_MODULES = (
    "conflation.py",
    "holdout.py",
    "holdout_review.py",
    "benchmark.py",
    "benchmark_labels.py",
    "canonical.py",
    "evaluation.py",
    "failures_page.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_only_the_command_line_imports_the_kitchener_research_code() -> None:
    importers = sorted(
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if KITCHENER not in path.parents
        and any(name.startswith("pathable_api.geo.kitchener") for name in _imports(path))
    )

    assert importers == ["cli.py"]


def test_the_conflation_modules_reach_neither_the_database_nor_routing() -> None:
    forbidden = ("pathable_api.db", "pathable_api.routing", "pathable_api.api", "sqlalchemy")
    for module in CONFLATION_MODULES:
        path = KITCHENER / module
        assert path.exists(), module
        reached = {name for name in _imports(path) if name.startswith(forbidden)}
        assert not reached, f"{module} imports {sorted(reached)}"
