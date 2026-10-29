#!/usr/bin/env sh
set -eu
.venv/bin/python -m chaos.run_scenario redis_eviction_storm
