import re
import tomllib
from pathlib import Path

import airtwin

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
CITATION = Path(__file__).resolve().parents[1] / "CITATION.cff"


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", airtwin.__version__)


def test_version_matches_pyproject() -> None:
    with PYPROJECT.open("rb") as f:
        project = tomllib.load(f)["project"]
    assert project["version"] == airtwin.__version__


def test_version_matches_citation() -> None:
    match = re.search(r"^version:\s*(\S+)\s*$", CITATION.read_text(encoding="utf-8"), re.M)
    assert match is not None
    assert match.group(1) == airtwin.__version__
