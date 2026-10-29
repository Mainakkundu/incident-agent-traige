from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_prometheus_routes_payment_alerts_to_alertmanager() -> None:
    config = yaml.safe_load((ROOT / "monitoring/prometheus.yml").read_text())
    targets = config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert targets == ["alertmanager:9093"]


def test_alertmanager_routes_to_incident_webhook() -> None:
    config = yaml.safe_load((ROOT / "monitoring/alertmanager.yml").read_text())
    webhook = config["receivers"][0]["webhook_configs"][0]["url"]
    assert webhook.endswith("/webhooks/incident")


def test_high_error_rate_rule_identifies_payment_api() -> None:
    config = yaml.safe_load((ROOT / "monitoring/rules.yml").read_text())
    rule = config["groups"][0]["rules"][0]
    assert rule["alert"] == "HighErrorRate"
    assert rule["labels"]["service"] == "payment-api"
