"""Synthetic release identity preparation; no tag, network or production data."""

import importlib.util
import json
import shutil
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.ci_runtime_release

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "prepare_version", ROOT / "scripts/prepare_release_version.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

FILES = (
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/src/hermes_finance/__init__.py",
    "frontend/package.json",
    "frontend/package-lock.json",
    "backend/tests/test_health.py",
    "backend/tests/test_r05_11_release_verification.py",
    "backend/tests/test_r13_00_release_verification.py",
)


@pytest.fixture
def fixture(tmp_path):
    for name in FILES:
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/release-notes-9.8.7.md").write_text("Synthetic notes", encoding="utf-8")
    return tmp_path


def test_updates_independent_release_identities(fixture):
    module.prepare(fixture, "9.8.7")
    project = tomllib.loads((fixture / FILES[0]).read_text())
    lock = tomllib.loads((fixture / FILES[1]).read_text())
    front = json.loads((fixture / FILES[3]).read_text())
    npm = json.loads((fixture / FILES[4]).read_text())
    package = next(p for p in lock["package"] if p["name"] == project["project"]["name"])
    assert (
        project["project"]["version"]
        == package["version"]
        == front["version"]
        == npm["version"]
        == npm["packages"][""]["version"]
        == "9.8.7"
    )
    for name in FILES[2:]:
        assert '"9.8.7"' in (fixture / name).read_text()


def test_rejects_inconsistent_input_before_any_write(fixture):
    path = fixture / FILES[3]
    current = tomllib.loads((fixture / FILES[0]).read_text())["project"]["version"]
    path.write_text(path.read_text().replace(f'"{current}"', '"0.0.0"'))
    before = {name: (fixture / name).read_bytes() for name in FILES}
    with pytest.raises(ValueError, match="disagree"):
        module.prepare(fixture, "9.8.7")
    assert before == {name: (fixture / name).read_bytes() for name in FILES}


def test_missing_notes_refuses_without_writes(fixture):
    before = {name: (fixture / name).read_bytes() for name in FILES}
    with pytest.raises(ValueError, match="release notes"):
        module.prepare(fixture, "9.8.6")
    assert before == {name: (fixture / name).read_bytes() for name in FILES}


def test_interrupted_commit_rolls_back_prior_files(fixture, monkeypatch):
    before = {name: (fixture / name).read_bytes() for name in FILES}
    replace = module.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic failure")
        return replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_second)
    with pytest.raises(OSError, match="restored"):
        module.prepare(fixture, "9.8.7")
    assert before == {name: (fixture / name).read_bytes() for name in FILES}


def test_wrong_runtime_version_with_decoy_refuses_before_write(fixture):
    version_file = fixture / FILES[2]
    old = tomllib.loads((fixture / FILES[0]).read_text())["project"]["version"]
    version_file.write_text(f'__version__ = "0.0.0"\nOTHER = "{old}"\n')
    before = {name: (fixture / name).read_bytes() for name in FILES}
    with pytest.raises(ValueError, match="runtime version disagrees"):
        module.prepare(fixture, "9.8.7")
    assert before == {name: (fixture / name).read_bytes() for name in FILES}


def test_non_ascii_version_rejected(fixture):
    with pytest.raises(ValueError, match="stable"):
        module.prepare(fixture, "1.2٣.4")


def test_keyboard_interrupt_restores_exact_crlf_bytes(fixture, monkeypatch):
    for name in FILES:
        path = fixture / name
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    before = {name: (fixture / name).read_bytes() for name in FILES}
    replace = module.os.replace
    calls = 0

    def interrupt(source, target):
        nonlocal calls
        calls += 1
        result = replace(source, target)
        if calls == 4:
            raise KeyboardInterrupt()
        return result

    monkeypatch.setattr(module.os, "replace", interrupt)
    with pytest.raises(OSError, match="restored"):
        module.prepare(fixture, "9.8.7")
    assert before == {name: (fixture / name).read_bytes() for name in FILES}


def test_linked_parent_is_refused(fixture, tmp_path):
    backend = fixture / "backend"
    outside = tmp_path / "outside"
    backend.rename(outside)
    try:
        backend.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    before = (outside / "pyproject.toml").read_bytes()
    with pytest.raises(ValueError, match="Linked paths"):
        module.prepare(fixture, "9.8.7")
    assert (outside / "pyproject.toml").read_bytes() == before


def test_docstring_decoy_does_not_count_as_runtime_assignment(fixture):
    path = fixture / FILES[2]
    old = tomllib.loads((fixture / FILES[0]).read_text())["project"]["version"]
    path.write_text(f'__version__ = \'0.0.0\'\n"""\n__version__ = "{old}"\n"""\n')
    with pytest.raises(ValueError, match="runtime version disagrees"):
        module.prepare(fixture, "9.8.7")


def test_annotated_second_assignment_is_refused(fixture):
    path = fixture / FILES[2]
    with path.open("a") as output:
        output.write('__version__: str = "0.0.0"\n')
    with pytest.raises(ValueError, match="runtime version disagrees"):
        module.prepare(fixture, "9.8.7")


def test_comment_version_decoy_does_not_hide_wrong_health_assertion(fixture):
    path = fixture / FILES[5]
    old = tomllib.loads((fixture / FILES[0]).read_text())["project"]["version"]
    path.write_text(path.read_text().replace(f'"{old}"', '"0.0.0"') + f'\n# "{old}"\n')
    with pytest.raises(ValueError, match="Version assertions disagree"):
        module.prepare(fixture, "9.8.7")


def test_malformed_runtime_rejected_before_write(fixture):
    path = fixture / FILES[2]
    path.write_text("__version__ = (\n")
    before = {name: (fixture / name).read_bytes() for name in FILES}
    with pytest.raises(SyntaxError):
        module.prepare(fixture, "9.8.7")
    assert before == {name: (fixture / name).read_bytes() for name in FILES}
