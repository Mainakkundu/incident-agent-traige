from __future__ import annotations

from pathlib import Path

from chaos.harness import DependencyInvestigator, scenarios


ROOT = Path(__file__).resolve().parents[1]


def test_six_chaos_scenarios_reach_expected_conclusions() -> None:
    investigator = DependencyInvestigator()
    results = tuple(investigator.investigate(item) for item in scenarios())

    assert len(results) == 6
    assert all(result.passed for result in results)


def test_clean_control_concludes_nothing_is_wrong() -> None:
    clean = next(item for item in scenarios() if item.name == "nothing_is_wrong")

    result = DependencyInvestigator().investigate(clean)

    assert result.observed_root is None
    assert result.services_inspected == ("payment-api",)


def test_each_scenario_has_a_shell_entrypoint() -> None:
    for item in scenarios():
        assert (ROOT / "chaos" / f"{item.name}.sh").is_file()
