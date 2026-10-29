"""Hard gates and report generation for the frozen evaluation run."""

from __future__ import annotations

from pathlib import Path

from evals.harness import evaluate, load_goldens, load_runs, write_report


ROOT = Path(__file__).resolve().parents[1]
GOLDENS_PATH = ROOT / "goldens.yaml"
RUNS_PATH = ROOT / "evals" / "recorded_runs.yaml"
REPORT_PATH = ROOT / "evals" / "REPORT.md"


def test_e1_missed_incidents_hard_gate() -> None:
    metrics = evaluate(load_goldens(GOLDENS_PATH), load_runs(RUNS_PATH))
    assert metrics.confusion.false_negative <= 1


def test_e3_causal_validity_hard_gate() -> None:
    metrics = evaluate(load_goldens(GOLDENS_PATH), load_runs(RUNS_PATH))
    assert metrics.causal_violations == 0


def test_report_is_generated_by_pytest() -> None:
    report = write_report(GOLDENS_PATH, RUNS_PATH, REPORT_PATH)
    assert "E1 root-cause accuracy" in report
    assert "Judge health" in report
    assert report.count("PASS") == 2
