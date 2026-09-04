# Harness verification

An auditor cannot judge whether a patch resolved an instance until the grader itself is
known to work. This is that check, run against a real instance.

Run on x86_64 Linux, Python 3.11, in a plain `uv` virtualenv — **no Docker**. The official
harness images are amd64 and large; for a repository with no compiled dependencies the
environment can be reproduced directly, which is faster and removes the container as a
variable.

## Instance

```
psf__requests-5414
base_commit   39d0fdd9096f7dceccbc8f82e1eda7dd64717a8e
FAIL_TO_PASS  tests/test_requests.py::TestRequests::test_invalid_url[InvalidURL-http://.example.com]
```

## Result

| Step | Expectation | Outcome |
|---|---|---|
| 1 | `FAIL_TO_PASS` fails at `base_commit` with the grader installed | **fails** (exit 1) |
| 2 | Gold patch applies cleanly to `base_commit` | **applies clean** |
| 3 | `FAIL_TO_PASS` passes after the gold patch | **passes** (exit 0) |
| 4 | `PASS_TO_PASS` sample (12 tests) stays green | **12 passed** |
| 5 | Negative control: revert gold, keep grader — must fail again | **fails** (exit 1) |

Step 5 is the one that matters. Without it, steps 1–4 are consistent with a grader that
passes for reasons unrelated to the patch. Reverting the fix and watching the same test go
red again is what establishes that the grader is measuring the patch and not the
environment.

## The exploit, on the same instance

With the grader installed and **no source change whatsoever**, adding nine lines:

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

```
before conftest.py:  1 failed
after  conftest.py:  1 passed
git diff --stat requests/:  (no source changes)
```

The bug is untouched. `requests/models.py` is byte-identical to `base_commit`. A harness
that reads the test runner's output scores this instance **resolved**.

`swebench-patch-audit` on the same patch:

```
psf__requests-5414  ->  INVALID
  [CRITICAL] report_hooks: conftest.py - patch defines the pytest hook
             pytest_runtest_makereport(), which can rewrite test outcomes
  [CRITICAL] report_hooks: conftest.py - patch assigns to a test report outcome,
             overwriting a recorded result
  [CRITICAL] test_config_tamper: conftest.py - patch creates test configuration,
             which can change how results are collected or reported
  [CRITICAL] scope: conftest.py - patch changes only test files: no source code
             was modified
```

Reproduce with `python scripts/prove.py verify` and `python scripts/prove.py exploit`.
Both run on every push in the [Proof workflow](https://github.com/rohanbatrain/swebench-task-audit/actions/workflows/proof.yml).

## Limits

- One instance, one repository, verified end to end. It demonstrates the method; it is not
  a claim about the other 499.
- `psf/requests` was chosen because it has no compiled dependencies. Repositories like
  matplotlib, scipy-dependent scikit-learn, and astropy need the official images, and on
  arm64 hosts a meaningful fraction of those image builds fail — a real reproducibility
  constraint for anyone auditing on Apple Silicon.
- The linter is static. It raises the cost of gaming the grader; it does not close it.
