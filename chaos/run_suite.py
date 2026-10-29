"""Run all chaos scenarios and print a compact result table."""

from __future__ import annotations

from chaos.harness import DependencyInvestigator, scenarios


def display_root(root: str | None) -> str:
    """Return a readable root-cause label."""
    return root or "nothing wrong"


def main() -> None:
    """Run six scenarios and exit non-zero on any wrong conclusion."""
    investigator = DependencyInvestigator()
    results = tuple(investigator.investigate(item) for item in scenarios())
    print("scenario                         expected          observed          result")
    print("-------------------------------  ----------------  ----------------  ------")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{result.name:<31}  "
            f"{display_root(result.expected_root):<16}  "
            f"{display_root(result.observed_root):<16}  "
            f"{status}"
        )
    passed = sum(int(result.passed) for result in results)
    print(f"\n{passed}/{len(results)} scenarios passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
