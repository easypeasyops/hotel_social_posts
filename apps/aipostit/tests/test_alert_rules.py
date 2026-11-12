"""aipostit's alert rules (deploy/envs/prod.yaml, monitoring.rules.alerts).

An alert that never fires looks exactly like a healthy system, so every alert has a promtool
scenario that shows it firing (deploy/prometheus/alerts_test.yaml) and the scenarios pass;
and every alert links to a RUNBOOK section that exists.

The same for the SLO burn-rate alerts (deploy/service/slo-rules.values.yaml, generated from
deploy/prometheus/slos.yaml by the platform's gen_slo_rules.py; CI checks it is current):
their scenarios are deploy/prometheus/slo_test.yaml, and they share one RUNBOOK section.
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
SLO_SCENARIOS = APP / "deploy/prometheus/slo_test.yaml"
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


def _slo_rules_text() -> str:
    values = yaml.safe_load((APP / "deploy/service/slo-rules.values.yaml").read_text())
    text: str = values["monitoring"]["rules"]["slo"]
    return text


def _alerts(rules_text: str | None = None) -> list[dict[str, Any]]:
    groups = yaml.safe_load(rules_text or _rules_text())["groups"]
    return [rule for group in groups for rule in group["rules"] if "alert" in rule]


def _shown_to_fire(scenarios: Path) -> set[tuple[str, str]]:
    """Each (alert name, severity) a scenario expects to fire."""
    return {
        (case["alertname"], alert["exp_labels"]["severity"])
        for test in yaml.safe_load(scenarios.read_text())["tests"]
        for case in test.get("alert_rule_test", [])
        for alert in case["exp_alerts"]
    }


def _headings() -> set[str]:
    return {
        re.sub(r"[^\w\- ]", "", line.lstrip("#").strip().lower()).replace(" ", "-")
        for line in (APP / "docs/RUNBOOK.md").read_text().splitlines()
        if line.startswith("#")
    }


def test_every_alert_is_shown_to_fire() -> None:
    tested = {name for name, _ in _shown_to_fire(SCENARIOS)}
    alerts = {rule["alert"] for rule in _alerts()}
    assert alerts, "no alerts found"
    assert alerts <= tested, f"alerts never shown to fire: {sorted(alerts - tested)}"


def test_every_slo_alert_is_shown_to_fire_and_links_to_the_runbook() -> None:
    # A page and a ticket for one SLO share a name: each severity needs its own showing.
    alerts = _alerts(_slo_rules_text())
    assert alerts, "no SLO alerts found"
    wanted = {(rule["alert"], rule["labels"]["severity"]) for rule in alerts}
    assert wanted <= _shown_to_fire(SLO_SCENARIOS)
    for rule in alerts:
        assert rule["labels"]["severity"] in {"page", "ticket"}  # the platform's routes
        assert rule["alert"].startswith("Aipostit")  # the platform's inhibit rule matches it
        assert rule["annotations"]["runbook_url"] == f"{RUNBOOK_URL}#slo-burn-rate-alerts"
    assert "slo-burn-rate-alerts" in _headings()


def test_every_alert_has_a_severity_and_a_runbook_section() -> None:
    headings = _headings()
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
    (tmp_path / "slo.yaml").write_text(_slo_rules_text())
    shutil.copy(SCENARIOS, tmp_path / "alerts_test.yaml")
    shutil.copy(SLO_SCENARIOS, tmp_path / "slo_test.yaml")
    for path in tmp_path.iterdir():
        path.chmod(0o644)
    result = subprocess.run(  # noqa: S603
        ["docker", "run", "--rm", "-v", f"{tmp_path}:/r:ro", "--entrypoint", "promtool",  # noqa: S607
         PROMETHEUS_IMAGE, "test", "rules", "/r/alerts_test.yaml", "/r/slo_test.yaml"],
        capture_output=True,
        text=True,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
