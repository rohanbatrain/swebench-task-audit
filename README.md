# swebench-task-audit

**An audit of SWE-bench Verified, and a linter for patches that satisfy the grader without
fixing the bug.**

![tests](https://img.shields.io/badge/tests-27-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![deps](https://img.shields.io/badge/runtime%20deps-none-lightgrey)
![licence](https://img.shields.io/badge/licence-MIT-green)

A benchmark result is only as trustworthy as two things: the tasks it is built from, and
the grader's immunity to being edited by the thing it grades. This repository takes both
seriously.

- **`audit/`** — every one of the 500 SWE-bench Verified instances scored against five
  axes: technical accuracy, realism, solvability, reproducibility, and testing soundness.
- **`swebench_patch_audit`** — a zero-dependency linter that inspects a candidate patch
  *independently of whether its tests passed*, and reports the ways it could be gaming the
  metric.

```bash
make demo     # no API key, no network, no Docker
```

---

## Why a passing score is not the same as a fix

SWE-bench applies a candidate patch to a repository and runs the test suite. Success means
the `FAIL_TO_PASS` tests flip to passing and the `PASS_TO_PASS` tests stay passing.

The patch is applied **before** the tests run, and the tests live in the same tree. So a
patch can edit them. The canonical exploit is nine lines:

```python
# conftest.py
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        report.outcome = "passed"
```

Every test now passes. The harness parses a perfect score. Nothing was fixed.

`swebench-patch-audit` reads the patch and refuses to be impressed by the score:

```
$ swebench-patch-audit --instances data/swebench_verified.jsonl --predictions preds.json

acme__widget-4242  ->  INVALID
  [CRITICAL] report_hooks: conftest.py - patch defines the pytest hook
             pytest_runtest_makereport(), which can rewrite test outcomes
  [CRITICAL] test_config_tamper: conftest.py - patch creates test configuration,
             which can change how results are collected or reported
```

### What it detects

| Detector | Catches |
|---|---|
| `grader_edits` | Patch modifies a file supplied by the instance's own `test_patch` |
| `report_hooks` | `pytest_runtest_makereport` and friends, or direct writes to `report.outcome` |
| `test_config_tamper` | New or edited `conftest.py`, `pytest.ini`, `tox.ini`, pytest sections of `setup.cfg`/`pyproject.toml` |
| `skips` | `skip`/`xfail`/`SkipTest` added — CRITICAL when it lands on a `FAIL_TO_PASS` target |
| `test_removal` | Deleted test files, or test functions removed without replacement |
| `environment_writes` | Writes to `site-packages`, absolute paths, or modules shadowing stdlib/pytest on `sys.path` |
| `ci_edits` | Changes to `.github/workflows`, `noxfile.py`, and other CI definitions |
| `scope` | Empty patches, test-only patches, and patches implausibly small next to the reference solution |

Each detector has an adversarial fixture in `tests/fixtures.py` proving it fires, and the
honest fix is asserted to stay `CLEAN` — a detector that flags everything is worthless.

---

## The audit

`swebench_patch_audit.corpus` scores all 500 instances mechanically. Signals do not decide
anything; they decide **where a human should look**.

```
$ python -m swebench_patch_audit.corpus --instances data/swebench_verified.jsonl

unresolvable_test_ids ... 107      clean ................... 202
underspecified ......... 106       statement words (median) . 143
solution_leakage ....... 104       PASS_TO_PASS (median) .... 50.5
wide_regression_surface . 24       PASS_TO_PASS (max) ....... 2476
grader_provenance ....... 21       gold patch churn (median).. 7
brittle_tests ........... 18
```

### Finding 1 — the instrument was wrong before the benchmark was

The first provenance pass reported **zero** concerns. That was not a clean bill of health.
It was this line:

```python
f2p_files = {t.split("::")[0] for t in f2p if "::" in t}   # wrong
```

SWE-bench Verified uses **three** test-ID formats, and only one names a file:

| Format | Example | Instances |
|---|---|---|
| pytest | `astropy/units/tests/test_format.py::test_cds_grammar[strings4]` | 194 |
| unittest | `test_ascii_validator (auth_tests.test_validators.UsernameValidatorsTests)` | 214 |
| freeform | `Migration directories without an __init__.py file are loaded.` | 107 |

The third is a Django test *docstring*, which its runner prints in place of a name. All 231
Django and 75 sympy instances — **61% of the corpus** — use the non-pytest forms, so the
check silently did nothing on them and reported success.

`testids.py` now resolves all three explicitly, and an unresolvable ID is reported as
unresolvable rather than skipped. Provenance concerns went from 0 to **21**.

*Any tooling built on the `path::test` assumption has the same blind spot.*

### Finding 2 — `django__django-10097`

A **two-line** gold patch, graded by **438 `FAIL_TO_PASS` and 1,432 `PASS_TO_PASS` tests**,
labelled `<15 min fix`. It is the only instance in that difficulty band with more than 50
`FAIL_TO_PASS` tests; the band's median is 1.

A grading surface that wide makes the verdict fragile: any one of 1,870 tests failing for
an unrelated reason marks a correct patch as unresolved.

### Finding 3 — solution leakage in `hints_text`

335 instances carry `hints_text`; **104 exceed 200 words and 62 of those contain literal
code or diffs**, the longest running to 2,335 words. `hints_text` is not part of the
prompt by default, and this is a hazard for anyone who adds it rather than a defect in the
benchmark — but an evaluation harness that includes hints is measuring retrieval, not
software engineering.

### Finding 4 — calibrating the underspecification signal

The `underspecified` heuristic (short statement, no code fence, no traceback) flags 106
instances. Checking them by hand, **29 are false positives — a 27% error rate**: Django
issues imported from Trac that contain inline reproduction code whose formatting was
stripped on import. `django__django-16485` is 27 words long and *perfectly* specified — it
carries an exact repro and the exception it raises.

**The defensible number is 77, not 106.** It is reported here as 106-with-a-known-error-rate
rather than silently corrected, because the error rate is the useful part.

### Finding 5 — in the benchmark's favour

Difficulty labels are **well calibrated**. Median gold-patch churn rises monotonically
across the four bands:

| Difficulty | n | Median gold churn |
|---|---|---|
| `<15 min fix` | 194 | 4 lines |
| `15 min - 1 hour` | 261 | 9 lines |
| `1-4 hours` | 42 | 34 lines |
| `>4 hours` | 3 | 123 lines |

Likewise `environment_setup_commit` differs from `base_commit` in 492/500 instances, which
looks alarming and is not: there are exactly **80 distinct environment commits for 80
distinct (repo, version) pairs** — pinned once per version by design, shared by a median of
3 instances. It is measured, reported, and deliberately excluded from the concern set.

---

## Verifying the grader

Before trusting any verdict, check the grader works. Full run in
[`audit/HARNESS_VERIFICATION.md`](audit/HARNESS_VERIFICATION.md); on `psf__requests-5414`,
in a plain virtualenv with no Docker:

| Step | Outcome |
|---|---|
| `FAIL_TO_PASS` fails at `base_commit` | fails (exit 1) |
| gold patch applies cleanly | clean |
| `FAIL_TO_PASS` passes after gold | passes (exit 0) |
| `PASS_TO_PASS` sample (12) stays green | 12 passed |
| **negative control** — revert gold, keep grader | fails again (exit 1) |

The negative control is the point. Steps 1-4 alone are also consistent with a grader that
passes for reasons unrelated to the patch.

Then, on that same instance: **nine lines of `conftest.py`, zero source changes,
`requests/models.py` byte-identical to `base_commit`** — and the `FAIL_TO_PASS` test
reports `1 passed`. The harness would score it resolved. The linter returns `INVALID` with
four critical findings.

---

## Layout

```
src/swebench_patch_audit/
  models.py      Severity, Finding, AuditReport - the typed contracts
  diffparse.py   tolerant unified-diff reader (model output is often malformed)
  testids.py     resolves all three SWE-bench test-ID formats
  detectors.py   the eight detectors
  audit.py       runs them over one candidate patch
  corpus.py      corpus-wide signals for a whole split
  cli.py         command line entry point
tests/
  fixtures.py    one adversarial patch per detector, plus the honest fix
  test_detectors.py
```

## Running it

```bash
uv venv --python 3.11 && uv pip install -e . pytest
python -m pytest tests/ -q                  # 27 tests
python -m swebench_patch_audit.corpus --instances data/swebench_verified.jsonl
swebench-patch-audit --instances data/swebench_verified.jsonl --predictions preds.json
```

`--fail-on {critical,high,medium,info}` sets the exit-code threshold for CI use.

## Scope and honesty

- The corpus signals are **heuristics**, and Finding 4 exists because one of them was
  measurably wrong. They point a human at instances; they do not judge them.
- The linter reads patches statically. It does not execute anything, and a sufficiently
  creative exploit will evade it — it raises the cost of gaming the grader, it does not
  eliminate it.
- Findings 1 and 4 are corrections to this repository's own analysis. They are kept in the
  README rather than quietly fixed because how an auditor handles being wrong is the
  substance of the job.

MIT licensed.
