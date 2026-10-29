"""Code-based incident-agent evaluation and Markdown reporting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


NO_ROOT_VALUES = {None, "", "inconclusive"}


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """Expected result for one labelled incident."""

    case_id: str
    alerted_service: str
    expected_root: str | None
    expected_chain: tuple[str, ...]
    tags: tuple[str, ...]

    @property
    def is_incident(self) -> bool:
        """Return whether the case has a diagnosable root cause."""
        return self.expected_root not in NO_ROOT_VALUES


@dataclass(frozen=True, slots=True)
class TrailStep:
    """One service query and the services its result exposed."""

    queried_service: str
    discovered_services: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """Frozen output from one agent evaluation run."""

    case_id: str
    concluded_root: str | None
    causal_chain: tuple[str, ...]
    trail: tuple[TrailStep, ...]
    tool_calls: int
    cap_hit: bool
    auto_resolved: bool
    quality_label: bool
    judge_prediction: bool


@dataclass(frozen=True, slots=True)
class ConfusionMatrix:
    """Binary incident-detection outcomes."""

    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    """All metrics required by constitution section 10."""

    root_correct: int
    diagnosable_cases: int
    confusion: ConfusionMatrix
    mean_tool_calls: float
    cap_hits: int
    causal_violations: int
    false_alarm_rate: float
    auto_resolution_rate: float
    judge_tpr: float
    judge_tnr: float


def load_goldens(path: Path) -> tuple[GoldenCase, ...]:
    """Load labelled cases from YAML."""
    document = require_mapping(yaml.safe_load(path.read_text(encoding="utf-8")))
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise ValueError("goldens must contain a cases list")
    return tuple(golden_from_mapping(require_mapping(case)) for case in cases)


def load_runs(path: Path) -> tuple[EvaluationRun, ...]:
    """Load frozen agent runs from YAML."""
    document = require_mapping(yaml.safe_load(path.read_text(encoding="utf-8")))
    runs = document.get("runs")
    if not isinstance(runs, list):
        raise ValueError("recorded runs must contain a runs list")
    return tuple(run_from_mapping(require_mapping(run)) for run in runs)


def evaluate(
    goldens: Sequence[GoldenCase],
    runs: Sequence[EvaluationRun],
) -> EvaluationMetrics:
    """Score frozen runs against independently labelled cases."""
    run_by_id = {run.case_id: run for run in runs}
    require_same_case_ids(goldens, run_by_id)
    root_correct = 0
    diagnosable_cases = 0
    tp = tn = fp = fn = 0
    causal_violations = 0
    tool_calls = 0
    cap_hits = 0
    auto_resolved = 0
    judge_tp = judge_tn = judge_fp = judge_fn = 0

    for golden in goldens:
        run = run_by_id[golden.case_id]
        predicted_incident = run.concluded_root not in NO_ROOT_VALUES
        if golden.is_incident:
            diagnosable_cases += 1
            if predicted_incident:
                tp += 1
            else:
                fn += 1
            if run.concluded_root == golden.expected_root:
                root_correct += 1
        elif predicted_incident:
            fp += 1
        else:
            tn += 1
        if not causal_trail_is_valid(golden.alerted_service, run.trail):
            causal_violations += 1
        tool_calls += run.tool_calls
        cap_hits += int(run.cap_hit)
        auto_resolved += int(run.auto_resolved)
        if run.quality_label and run.judge_prediction:
            judge_tp += 1
        elif run.quality_label:
            judge_fn += 1
        elif run.judge_prediction:
            judge_fp += 1
        else:
            judge_tn += 1

    return EvaluationMetrics(
        root_correct=root_correct,
        diagnosable_cases=diagnosable_cases,
        confusion=ConfusionMatrix(tp, tn, fp, fn),
        mean_tool_calls=tool_calls / len(goldens),
        cap_hits=cap_hits,
        causal_violations=causal_violations,
        false_alarm_rate=safe_ratio(fp, fp + tn),
        auto_resolution_rate=safe_ratio(auto_resolved, len(goldens)),
        judge_tpr=safe_ratio(judge_tp, judge_tp + judge_fn),
        judge_tnr=safe_ratio(judge_tn, judge_tn + judge_fp),
    )


def causal_trail_is_valid(alerted_service: str, trail: Sequence[TrailStep]) -> bool:
    """Assert that every query target was exposed before it was queried."""
    allowed = {alerted_service}
    for step in trail:
        if step.queried_service not in allowed:
            return False
        allowed.update(step.discovered_services)
    return True


def alerted_service_baseline(goldens: Sequence[GoldenCase]) -> EvaluationMetrics:
    """Score the static baseline that blames the alerted service."""
    runs = tuple(
        EvaluationRun(
            case_id=case.case_id,
            concluded_root=case.alerted_service,
            causal_chain=(case.alerted_service,),
            trail=(TrailStep(case.alerted_service, ()),),
            tool_calls=1,
            cap_hit=False,
            auto_resolved=True,
            quality_label=case.expected_root == case.alerted_service,
            judge_prediction=case.expected_root == case.alerted_service,
        )
        for case in goldens
    )
    return evaluate(goldens, runs)


def render_report(
    candidate: EvaluationMetrics,
    baseline: EvaluationMetrics,
    case_count: int,
) -> str:
    """Render the reproducible evaluation report."""
    candidate_accuracy = safe_ratio(candidate.root_correct, candidate.diagnosable_cases)
    baseline_accuracy = safe_ratio(baseline.root_correct, baseline.diagnosable_cases)
    delta = candidate_accuracy - baseline_accuracy
    return f"""# Evaluation report

Generated by `pytest` from {case_count} labelled cases and `evals/recorded_runs.yaml`.
The candidate inputs are frozen run artifacts, so this report is reproducible and does not call a live model.

| Measure | Candidate | Static baseline | Delta |
|---|---:|---:|---:|
| E1 root-cause accuracy on diagnosable cases | {candidate_accuracy:.1%} ({candidate.root_correct}/{candidate.diagnosable_cases}) | {baseline_accuracy:.1%} | {delta:+.1%} |
| E2 mean tool calls | {candidate.mean_tool_calls:.2f} | {baseline.mean_tool_calls:.2f} | {candidate.mean_tool_calls - baseline.mean_tool_calls:+.2f} |
| E2 cap hits | {candidate.cap_hits} | {baseline.cap_hits} | {candidate.cap_hits - baseline.cap_hits:+d} |
| E3 causal-trail violations | {candidate.causal_violations} | {baseline.causal_violations} | {candidate.causal_violations - baseline.causal_violations:+d} |
| E4 false-alarm rate | {candidate.false_alarm_rate:.1%} | {baseline.false_alarm_rate:.1%} | {candidate.false_alarm_rate - baseline.false_alarm_rate:+.1%} |
| E6 auto-resolution rate | {candidate.auto_resolution_rate:.1%} | {baseline.auto_resolution_rate:.1%} | {candidate.auto_resolution_rate - baseline.auto_resolution_rate:+.1%} |

## Incident confusion matrix

| | Predicted incident | Predicted no incident |
|---|---:|---:|
| Actual incident | {candidate.confusion.true_positive} | {candidate.confusion.false_negative} |
| Actual no incident / inconclusive | {candidate.confusion.false_positive} | {candidate.confusion.true_negative} |

## Judge health

- TPR: {candidate.judge_tpr:.1%}
- TNR: {candidate.judge_tnr:.1%}

## Hard gates

- E1 missed incidents ≤ 1: {'PASS' if candidate.confusion.false_negative <= 1 else 'FAIL'}
- E3 causal-trail violations = 0: {'PASS' if candidate.causal_violations == 0 else 'FAIL'}

The static baseline always blames the alerted service. It is included to show whether the agent adds value over a non-agentic default, not as a production comparator.
"""


def write_report(goldens_path: Path, runs_path: Path, report_path: Path) -> str:
    """Evaluate artifacts and write the generated Markdown report."""
    goldens = load_goldens(goldens_path)
    candidate = evaluate(goldens, load_runs(runs_path))
    baseline = alerted_service_baseline(goldens)
    report = render_report(candidate, baseline, len(goldens))
    report_path.write_text(report, encoding="utf-8")
    return report


def golden_from_mapping(data: Mapping[str, Any]) -> GoldenCase:
    """Build a typed golden case."""
    alert = require_mapping(data.get("alert"))
    raw_root = data.get("expected_root")
    root = None if raw_root is None else str(raw_root)
    return GoldenCase(
        case_id=str(data["id"]),
        alerted_service=str(alert["service"]),
        expected_root=root,
        expected_chain=tuple(str(item) for item in data.get("expected_chain", [])),
        tags=tuple(str(item) for item in data.get("tags", [])),
    )


def run_from_mapping(data: Mapping[str, Any]) -> EvaluationRun:
    """Build a typed frozen evaluation run."""
    raw_root = data.get("concluded_root")
    root = None if raw_root is None else str(raw_root)
    trail_data = data.get("trail", [])
    if not isinstance(trail_data, list):
        raise ValueError("run trail must be a list")
    return EvaluationRun(
        case_id=str(data["id"]),
        concluded_root=root,
        causal_chain=tuple(str(item) for item in data.get("causal_chain", [])),
        trail=tuple(trail_step_from_mapping(require_mapping(item)) for item in trail_data),
        tool_calls=int(data["tool_calls"]),
        cap_hit=bool(data["cap_hit"]),
        auto_resolved=bool(data["auto_resolved"]),
        quality_label=bool(data["quality_label"]),
        judge_prediction=bool(data["judge_prediction"]),
    )


def trail_step_from_mapping(data: Mapping[str, Any]) -> TrailStep:
    """Build one typed reasoning-trail step."""
    return TrailStep(
        queried_service=str(data["query"]),
        discovered_services=tuple(str(item) for item in data.get("discovered", [])),
    )


def require_mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping or reject malformed YAML."""
    if not isinstance(value, Mapping):
        raise ValueError("expected a mapping")
    return value


def require_same_case_ids(
    goldens: Sequence[GoldenCase],
    run_by_id: Mapping[str, EvaluationRun],
) -> None:
    """Require exactly one run for every labelled case."""
    golden_ids = {case.case_id for case in goldens}
    run_ids = set(run_by_id)
    if golden_ids != run_ids:
        missing = sorted(golden_ids - run_ids)
        extra = sorted(run_ids - golden_ids)
        raise ValueError(f"run IDs do not match goldens; missing={missing}, extra={extra}")


def safe_ratio(numerator: int, denominator: int) -> float:
    """Return a ratio with a defined zero-denominator result."""
    return 0.0 if denominator == 0 else numerator / denominator
