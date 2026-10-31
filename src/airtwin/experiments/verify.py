"""Check that regenerated result tables equal the committed reference tables, value by value.

Numbers must agree within an absolute tolerance (NaN equals NaN); text must be identical;
both files must have the same columns and rows. Timing tables are machine-dependent and are
not part of the reference.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

MAX_REPORTED = 20


def compare_table(regenerated: Path, reference: Path, tolerance: float) -> list[str]:
    """Differences between two CSV files (empty if they agree)."""
    if not regenerated.is_file():
        return [f"{regenerated}: missing"]
    new, ref = pd.read_csv(regenerated), pd.read_csv(reference)
    if list(new.columns) != list(ref.columns):
        return [f"{reference.name}: columns differ: {list(new.columns)} vs {list(ref.columns)}"]
    if len(new) != len(ref):
        return [f"{reference.name}: {len(new)} rows, reference has {len(ref)}"]
    problems = []
    for column in ref.columns:
        for i, (a, b) in enumerate(zip(new[column], ref[column], strict=True)):
            both_numbers = isinstance(a, int | float) and isinstance(b, int | float)
            if both_numbers:
                if math.isnan(a) and math.isnan(b):
                    continue
                if abs(a - b) <= tolerance:
                    continue
            elif a == b or (pd.isna(a) and pd.isna(b)):
                continue
            problems.append(f"{reference.name} row {i} {column}: {a!r} != {b!r}")
    return problems


def verify_results(results: Path, reference: Path, tolerance: float) -> list[str]:
    """Compare every reference CSV under ``reference`` with its counterpart under ``results``."""
    references = sorted(reference.rglob("*.csv"))
    if not references:
        return [f"no reference tables under {reference}"]
    problems: list[str] = []
    for ref in references:
        problems += compare_table(results / ref.relative_to(reference), ref, tolerance)
    return problems


def sha256sums(base: Path, files: Iterable[Path]) -> str:
    """``sha256sum``-style lines for files, with paths relative to ``base``."""
    lines = []
    for path in sorted(files):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(base).as_posix()}")
    return "\n".join(lines) + "\n"
