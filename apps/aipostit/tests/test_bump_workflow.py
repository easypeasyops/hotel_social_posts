"""bump.yml: opens the PR that bumps an app's version. Its `bump` step writes the new version
into apps/<app>/pyproject.toml and the app's own entry in uv.lock (the two must agree: a tag
that disagrees with pyproject.toml fails the release). That step runs here as the workflow
runs it, on copies of aipostit's two files."""

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]  # aipostit is apps/aipostit/
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/bump.yml").read_text())


def _bump_step(
    root: Path, part: str, app: str = "aipostit"
) -> tuple[subprocess.CompletedProcess[str], str]:
    (step,) = [s for s in WORKFLOW["jobs"]["bump"]["steps"] if s.get("id") == "bump"]
    out = root / "output"
    out.touch()
    env = {**os.environ, "APP": app, "PART": part, "GITHUB_OUTPUT": str(out)}
    result = subprocess.run(  # noqa: S603
        ["bash", "-e", "-c", step["run"]],  # noqa: S607
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    return result, out.read_text()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A checkout holding aipostit's pyproject.toml and uv.lock at version 0.5.2."""
    app = tmp_path / "apps/aipostit"
    app.mkdir(parents=True)
    version = _versions(REPO)[0]
    for name in ("pyproject.toml", "uv.lock"):
        text = (REPO / "apps/aipostit" / name).read_text()
        (app / name).write_text(text.replace(f'version = "{version}"', 'version = "0.5.2"', 1))
    return tmp_path


def _versions(root: Path) -> tuple[str, str]:
    project = tomllib.loads((root / "apps/aipostit/pyproject.toml").read_text())
    lock = tomllib.loads((root / "apps/aipostit/uv.lock").read_text())
    (own,) = [p for p in lock["package"] if p["name"] == "aipostit"]
    return project["project"]["version"], own["version"]


def test_bump_is_dispatched_by_hand_or_by_the_bot() -> None:
    inputs = WORKFLOW[True]["workflow_dispatch"]["inputs"]  # yaml reads `on` as True
    assert set(inputs) == {"app", "part", "requested_by"}
    assert inputs["part"]["options"] == ["patch", "minor"]


@pytest.mark.parametrize(("part", "new"), [("patch", "0.5.3"), ("minor", "0.6.0")])
def test_a_bump_changes_both_files_and_nothing_else(root: Path, part: str, new: str) -> None:
    before = {p: p.read_text() for p in (root / "apps/aipostit").iterdir()}
    result, out = _bump_step(root, part)
    assert result.returncode == 0, result.stdout + result.stderr
    assert out.splitlines() == ["old=0.5.2", f"new={new}"]
    assert _versions(root) == (new, new)
    for path, text in before.items():  # one line each: the version
        changed = [
            (a, b)
            for a, b in zip(text.splitlines(), path.read_text().splitlines(), strict=True)
            if a != b
        ]
        assert changed == [('version = "0.5.2"', f'version = "{new}"')]


def test_a_lock_that_disagrees_changes_nothing(root: Path) -> None:
    lock = root / "apps/aipostit/uv.lock"
    lock.write_text(lock.read_text().replace('version = "0.5.2"', 'version = "0.5.1"', 1))
    project = (root / "apps/aipostit/pyproject.toml").read_text()
    result, out = _bump_step(root, "patch")
    assert result.returncode != 0
    assert "uv.lock doesn't hold" in result.stderr
    assert out == ""
    assert (root / "apps/aipostit/pyproject.toml").read_text() == project


@pytest.mark.parametrize(
    ("app", "part", "error"),
    [("Aipostit", "patch", "is not an app name"), ("aipostit", "major", "is not patch or minor")],
)
def test_a_bad_input_is_refused(root: Path, app: str, part: str, error: str) -> None:
    result, out = _bump_step(root, part, app)
    assert result.returncode != 0
    assert error in result.stdout
    assert out == ""


def test_the_repo_files_agree_today() -> None:
    """What the step relies on: the real files hold one version line each, and agree."""
    project, lock = _versions(REPO)
    assert project == lock
