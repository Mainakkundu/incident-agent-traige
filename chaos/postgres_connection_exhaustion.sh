#!/usr/bin/env sh
set -eu
.venv/bin/python -m chaos.run_scenario postgres_connection_exhaustion
