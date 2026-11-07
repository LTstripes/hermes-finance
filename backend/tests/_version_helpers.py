"""Current release expectation comes from the backend project manifest."""

import tomllib
from pathlib import Path


def current_release_version() -> str:
    manifest = Path(__file__).resolve().parents[1] / "pyproject.toml"
    return tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]["version"]
