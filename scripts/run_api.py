"""Run the local webhook, approval, and audit API."""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    """Serve the application factory on the Alertmanager callback port."""
    uvicorn.run("src.runtime:create_app", factory=True, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
