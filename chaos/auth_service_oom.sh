#!/usr/bin/env sh
set -eu
.venv/bin/python -m chaos.run_scenario auth_service_oom
