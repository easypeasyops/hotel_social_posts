"""rollback.yml and deploy-pr.sh's rollback mode. The workflow's `target` step finds the
release before the one an environment runs, from the release tags; deploy-pr.sh then opens
the PR that sets that release's digest. Both run here as the workflow runs them, in a
throwaway git repo, with a stand-in `gh` that records what it was asked to do."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]  # aipostit is apps/aipostit/
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/rollback.yml").read_text())
DIGEST = "sha256:" + "a" * 64
OLD_DIGEST = "sha256:" + "b" * 64
GNU_SED = subprocess.run(["sed", "--version"], capture_output=True).returncode == 0  # noqa: S607


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A repo whose staging runs aipostit v0.5.2, with tags v0.4.2 to v0.5.2."""
    envs = tmp_path / "apps/aipostit/deploy/envs"
    envs.mkdir(parents=True)
    for env in ("staging", "prod"):
        (envs / f"{env}.yaml").write_text(
            f'environment: {env}\nimage:\n  digest: "{DIGEST}" # aipostit v0.5.2\n'
        )
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    for tag in ("aipostit/v0.4.2", "aipostit/v0.5.0", "aipostit/v0.5.1", "aipostit/v0.5.2"):
        _git(tmp_path, "tag", tag)
    _git(tmp_path, "tag", "postitglobal/v0.5.9")  # another app's tags never count
    return tmp_path


def _target(root: Path, env: str = "staging") -> tuple[subprocess.CompletedProcess[str], str]:
    (step,) = [s for s in WORKFLOW["jobs"]["rollback"]["steps"] if s.get("id") == "target"]
    out = root / "output"
    out.touch()
    environ = {**os.environ, "APP": "aipostit", "ENV": env, "GITHUB_OUTPUT": str(out)}
    result = subprocess.run(  # noqa: S603
        ["bash", "-eo", "pipefail", "-c", step["run"]],  # noqa: S607
        cwd=root,
        env=environ,
        capture_output=True,
        text=True,
    )
    return result, out.read_text()


def _runs(root: Path, version: str, env: str = "staging") -> None:
    path = root / f"apps/aipostit/deploy/envs/{env}.yaml"
    path.write_text(path.read_text().replace("v0.5.2", f"v{version}"))


def test_rollback_is_dispatched_by_hand_or_by_the_bot() -> None:
    inputs = WORKFLOW[True]["workflow_dispatch"]["inputs"]  # yaml reads `on` as True
    assert set(inputs) == {"app", "env", "requested_by"}
    assert inputs["env"]["options"] == ["staging", "prod"]


@pytest.mark.parametrize(
    ("runs", "target"), [("0.5.2", "0.5.1"), ("0.5.1", "0.5.0"), ("0.5.0", "0.4.2")]
)
def test_the_target_is_the_release_before_the_one_running(
    root: Path, runs: str, target: str
) -> None:
    _runs(root, runs)
    result, out = _target(root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert out.splitlines() == [f"current={runs}", f"target={target}"]


def test_a_version_never_tagged_still_goes_back_to_the_one_below(root: Path) -> None:
    _runs(root, "0.5.3", "prod")
    result, out = _target(root, "prod")
    assert result.returncode == 0, result.stdout
    assert out.splitlines() == ["current=0.5.3", "target=0.5.2"]


@pytest.mark.parametrize(
    ("env", "runs", "error"),
    [
        ("staging", "0.4.2", "no aipostit release before v0.4.2"),
        ("dev", "0.5.2", "is not staging or prod"),
    ],
)
def test_no_target_opens_nothing(root: Path, env: str, runs: str, error: str) -> None:
    _runs(root, runs)
    result, out = _target(root, env)
    assert result.returncode != 0
    assert error in result.stdout
    assert out == ""


def test_a_digest_line_without_a_version_is_refused(root: Path) -> None:
    path = root / "apps/aipostit/deploy/envs/staging.yaml"
    path.write_text(path.read_text().replace(" # aipostit v0.5.2", ""))
    result, out = _target(root)
    assert result.returncode != 0
    assert "names no version" in result.stdout


def _deploy_pr(
    root: Path, env: str, requested_by: str = "Emrah"
) -> tuple[subprocess.CompletedProcess[str], str]:
    """deploy-pr.sh in rollback mode, with a `gh` that logs its arguments."""
    bin_dir, log = root / "bin", root / "gh.log"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{log}"\n')
    gh.chmod(0o755)
    environ = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "easypeasyops/hotel_social_posts",
        "ROLLBACK": "1",
        "REQUESTED_BY": requested_by,
    }
    script = REPO / ".github/scripts/deploy-pr.sh"
    result = subprocess.run(  # noqa: S603
        [str(script), "aipostit", env, OLD_DIGEST, "0.5.1"],
        cwd=root,
        env=environ,
        capture_output=True,
        text=True,
    )
    return result, log.read_text() if log.exists() else ""


@pytest.mark.skipif(not GNU_SED, reason="deploy-pr.sh runs on Linux (GNU sed, base64 -w0)")
@pytest.mark.parametrize("env", ["staging", "prod"])
def test_a_rollback_pr_says_so_and_only_staging_merges_itself(root: Path, env: str) -> None:
    result, log = _deploy_pr(root, env)
    assert result.returncode == 0, result.stdout + result.stderr
    line = f'  digest: "{OLD_DIGEST}" # aipostit v0.5.1, rolled back'
    assert line in (root / f"apps/aipostit/deploy/envs/{env}.yaml").read_text().splitlines()
    assert f"refs/heads/rollback/aipostit-{env}-v0.5.1" in log
    assert f"--title deploy: aipostit {env} rolls back to v0.5.1" in log
    assert "Requested by Emrah." in log
    assert ("pr merge" in log) == (env == "staging")  # prod waits for a review


@pytest.mark.skipif(not GNU_SED, reason="deploy-pr.sh runs on Linux (GNU sed, base64 -w0)")
def test_a_requester_that_is_not_a_name_opens_nothing(root: Path) -> None:
    result, log = _deploy_pr(root, "prod", "@channel")
    assert result.returncode != 0
    assert "requested_by is not a name" in result.stdout
    assert log == ""
