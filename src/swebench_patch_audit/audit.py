"""Run every detector over one candidate patch."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import detectors
from .diffparse import parse_patch
from .models import AuditReport


def _as_list(value: Any) -> list[str]:
    """FAIL_TO_PASS ships as a JSON string in some exports and a list in others."""
    if value is None:
        return []
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return [value] if value else []
        return [str(v) for v in parsed] if isinstance(parsed, list) else [str(parsed)]
    return [str(v) for v in value]


def audit_patch(candidate_patch: str, instance: Mapping[str, Any]) -> AuditReport:
    """Audit one candidate patch against the SWE-bench instance it answers.

    `instance` is a row of the SWE-bench dataset: it must carry `test_patch`,
    `patch` (the gold solution) and `FAIL_TO_PASS`.
    """
    files = parse_patch(candidate_patch)
    fail_to_pass = _as_list(instance.get("FAIL_TO_PASS"))
    report = AuditReport(instance_id=str(instance.get("instance_id", "<unknown>")))

    report.findings.extend(detectors.detect_grader_edits(files, test_patch=instance.get("test_patch", "")))
    report.findings.extend(detectors.detect_test_config_tamper(files))
    report.findings.extend(detectors.detect_report_hooks(files))
    report.findings.extend(detectors.detect_skips(files, fail_to_pass=fail_to_pass))
    report.findings.extend(detectors.detect_test_removal(files, fail_to_pass=fail_to_pass))
    report.findings.extend(detectors.detect_environment_writes(files))
    report.findings.extend(detectors.detect_ci_edits(files))
    report.findings.extend(detectors.detect_scope(files, gold_patch=instance.get("patch", "")))
    return report
