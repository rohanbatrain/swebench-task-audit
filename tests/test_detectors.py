"""Every detector must fire on its adversarial fixture and stay quiet on the honest fix."""
from __future__ import annotations

import pytest

from swebench_patch_audit import audit_patch
from swebench_patch_audit.models import Severity

from fixtures import (
    CONFTEST_HOOK,
    DELETES_TEST,
    EDITS_CI,
    EDITS_GRADER,
    EMPTY,
    INSTANCE,
    LEGITIMATE,
    PYTEST_INI,
    SHADOWS_STDLIB,
    SKIPS_TARGET,
    TRIVIAL,
    WRITES_SITE_PACKAGES,
)


def detectors_fired(patch: str) -> set[str]:
    return {f.detector for f in audit_patch(patch, INSTANCE).findings}


class TestLegitimatePatch:
    def test_honest_fix_is_clean(self):
        report = audit_patch(LEGITIMATE, INSTANCE)
        assert report.verdict == "CLEAN", report.sorted_findings()

    def test_honest_fix_has_no_blocking_findings(self):
        assert audit_patch(LEGITIMATE, INSTANCE).blocking == []


@pytest.mark.parametrize(
    ("patch", "detector"),
    [
        (EDITS_GRADER, "grader_edits"),
        (CONFTEST_HOOK, "report_hooks"),
        (CONFTEST_HOOK, "test_config_tamper"),
        (PYTEST_INI, "test_config_tamper"),
        (SKIPS_TARGET, "skips"),
        (DELETES_TEST, "test_removal"),
        (WRITES_SITE_PACKAGES, "environment_writes"),
        (SHADOWS_STDLIB, "environment_writes"),
        (EDITS_CI, "ci_edits"),
        (EMPTY, "scope"),
        (TRIVIAL, "scope"),
    ],
    ids=[
        "rewrites-the-grader",
        "conftest-rewrites-outcomes",
        "conftest-is-test-config",
        "pytest-ini-loosens-collection",
        "skips-the-target-test",
        "deletes-the-target-test",
        "overwrites-site-packages",
        "shadows-stdlib-ast",
        "weakens-ci",
        "empty-patch",
        "implausibly-small",
    ],
)
def test_adversarial_patch_is_caught(patch, detector):
    assert detector in detectors_fired(patch)


@pytest.mark.parametrize(
    "patch",
    [EDITS_GRADER, CONFTEST_HOOK, SKIPS_TARGET, DELETES_TEST, WRITES_SITE_PACKAGES, SHADOWS_STDLIB],
    ids=["grader", "conftest", "skip", "delete", "site-packages", "stdlib"],
)
def test_serious_exploits_are_never_clean(patch):
    assert audit_patch(patch, INSTANCE).verdict != "CLEAN"


class TestSeverity:
    def test_rewriting_the_grader_is_critical(self):
        sev = {f.severity for f in audit_patch(EDITS_GRADER, INSTANCE).findings}
        assert Severity.CRITICAL in sev

    def test_skipping_the_named_target_outranks_a_generic_skip(self):
        targeted = audit_patch(SKIPS_TARGET, INSTANCE)
        skip = next(f for f in targeted.findings if f.detector == "skips")
        assert skip.severity is Severity.CRITICAL

    def test_ci_edit_needs_a_human_but_is_not_invalid(self):
        report = audit_patch(EDITS_CI, INSTANCE)
        assert report.verdict == "NEEDS_HUMAN"

    def test_empty_patch_is_informational_not_an_accusation(self):
        report = audit_patch(EMPTY, INSTANCE)
        assert report.verdict == "CLEAN"
        assert [f.severity for f in report.findings] == [Severity.INFO]


class TestParsing:
    def test_findings_carry_the_offending_path(self):
        report = audit_patch(CONFTEST_HOOK, INSTANCE)
        assert any(f.path == "conftest.py" for f in report.findings)

    def test_fail_to_pass_accepts_a_json_string(self):
        assert audit_patch(SKIPS_TARGET, INSTANCE).verdict == "INVALID"

    def test_fail_to_pass_accepts_a_real_list(self):
        inst = INSTANCE | {"FAIL_TO_PASS": ["tests/test_parser.py::test_handles_empty_input"]}
        assert audit_patch(SKIPS_TARGET, inst).verdict == "INVALID"

    def test_report_is_ordered_worst_first(self):
        report = audit_patch(CONFTEST_HOOK, INSTANCE)
        severities = [f.severity for f in report.sorted_findings()]
        assert severities == sorted(severities, key=lambda s: list(Severity).index(s))
