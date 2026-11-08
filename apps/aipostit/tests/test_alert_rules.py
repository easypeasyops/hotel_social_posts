"""aipostit's alert rules (deploy/envs/prod.yaml, monitoring.rules.alerts).

An alert that never fires looks exactly like a healthy system, so every alert has a promtool
scenario that shows it firing (deploy/prometheus/alerts_test.yaml) and the scenarios pass;
and every alert links to a RUNBOOK section that exists.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

APP = Path(__file__).resolve().parents[1]
SCENARIOS = APP / "deploy/prometheus/alerts_test.yaml"
RUNBOOK_URL = (
    "https://github.com/easypeasyops/hotel_social_posts/blob/main/apps/aipostit/docs/RUNBOOK.md"
)
PROMETHEUS_IMAGE = (  # v3.15.0, the platform's promtool
    "prom/prometheus@sha256:efd719c99d83b060d9daefdcf00360461adf279f45ef5391f8d111892118753e"
)


def _rules_text() -> str:
    values = yaml.safe_load((APP / "deploy/envs/prod.yaml").read_text())
    assert values["monitoring"]["clusterWide"] is True  # the chart ships rules only then
    text: str = values["monitoring"]["rules"]["alerts"]
    return text


def _alerts() -> list[dict[str, Any]]:
    groups = yaml.safe_load(_rules_text())["groups"]
    return [rule for group in groups for rule in group["rules"] if "alert" in rule]


def test_every_alert_is_shown_to_fire() -> None:
    tested = {
        case["alertname"]
        for test in yaml.safe_load(SCENARIOS.read_text())["tests"]
        for case in test.get("alert_rule_test", [])
        if case["exp_alerts"]
    }
    alerts = {rule["alert"] for rule in _alerts()}
    assert alerts, "no alerts found"
    assert alerts <= tested, f"alerts never shown to fire: {sorted(alerts - tested)}"


def test_every_alert_has_a_severity_and_a_runbook_section() -> None:
    headings = {
        re.sub(r"[^\w\- ]", "", line.lstrip("#").strip().lower()).replace(" ", "-")
        for line in (APP / "docs/RUNBOOK.md").read_text().splitlines()
        if line.startswith("#")
    }
    for rule in _alerts():
        name = rule["alert"]
        assert rule["labels"]["severity"] in {"page", "ticket"}, name  # the platform's routes
        url = rule["annotations"]["runbook_url"]
        assert url == f"{RUNBOOK_URL}#{name.lower()}", name
        assert name.lower() in headings, f"{name}: no RUNBOOK heading"


def test_promtool_scenarios_pass(tmp_path: Path) -> None:
    if (
        not shutil.which("docker")
        or subprocess.run(
            ["docker", "info"],  # noqa: S607
            capture_output=True,
        ).returncode
    ):
        if os.environ.get("CI"):
            pytest.fail("Docker is required for the promtool scenarios in CI")
        pytest.skip("Docker not available")
    tmp_path.chmod(0o755)  # the promtool container runs as nobody
    (tmp_path / "alerts.yaml").write_text(_rules_text())
    shutil.copy(SCENARIOS, tmp_path / "alerts_test.yaml")
    for path in tmp_path.iterdir():
        path.chmod(0o644)
    result = subprocess.run(  # noqa: S603
        ["docker", "run", "--rm", "-v", f"{tmp_path}:/r:ro", "--entrypoint", "promtool",  # noqa: S607
         PROMETHEUS_IMAGE, "test", "rules", "/r/alerts_test.yaml"],
        capture_output=True,
        text=True,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
