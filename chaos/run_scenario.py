"""Command-line entrypoint for one chaos scenario."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from chaos.harness import run_named_scenario


def parse_args() -> argparse.Namespace:
    """Parse the required scenario name."""
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    return parser.parse_args()


def main() -> None:
    """Run one scenario and fail if its conclusion is wrong."""
    result = run_named_scenario(parse_args().scenario)
    print(json.dumps(asdict(result), sort_keys=True))
    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
