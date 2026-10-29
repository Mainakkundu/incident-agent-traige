.PHONY: test eval chaos-suite

test:
	.venv/bin/python -m pytest -q

eval:
	.venv/bin/python -m pytest evals/test_evals.py -q

chaos-suite:
	.venv/bin/python -m chaos.run_suite
