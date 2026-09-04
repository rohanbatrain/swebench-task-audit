.PHONY: demo test audit gates lint clean

PY := ./.venv/bin/python

demo: ## Run the detector against every adversarial fixture. No key, no network.
	@$(PY) -c "import sys; sys.path[:0]=['src','tests']; \
	from fixtures import *; from swebench_patch_audit import audit_patch; \
	cases=[('honest fix',LEGITIMATE),('rewrites the grader',EDITS_GRADER), \
	('conftest rewrites outcomes',CONFTEST_HOOK),('pytest.ini loosens collection',PYTEST_INI), \
	('skips the target test',SKIPS_TARGET),('deletes the target test',DELETES_TEST), \
	('overwrites site-packages',WRITES_SITE_PACKAGES),('shadows stdlib ast',SHADOWS_STDLIB), \
	('weakens CI',EDITS_CI),('empty patch',EMPTY),('implausibly small',TRIVIAL)]; \
	[print(f'{n:<32} {audit_patch(p,INSTANCE).verdict:<12} ' \
	f'{[f.detector for f in audit_patch(p,INSTANCE).findings]}') for n,p in cases]"

test: ## Run the test suite.
	@$(PY) -m pytest tests/ -q

audit: ## Recompute corpus-wide signals for the Verified split.
	@$(PY) -m swebench_patch_audit.corpus --instances data/swebench_verified.jsonl

gates: ## Run exactly what CI runs, in the same order.
	@uv run ruff check . --output-format=concise
	@uv run ruff format --check .
	@uv run mypy
	@uv run pytest

clean:
	@rm -rf .pytest_cache **/__pycache__
