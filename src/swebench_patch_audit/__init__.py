"""Patch-integrity auditing for SWE-bench-style benchmark submissions.

A patch that makes FAIL_TO_PASS go green has not necessarily fixed the bug. It may
have edited the graders. This package inspects the patch itself, independently of
any test result, and reports the ways it could be satisfying the metric rather than
solving the problem.
"""

from .audit import audit_patch
from .models import AuditReport, Finding, Severity

__all__ = ["AuditReport", "Finding", "Severity", "audit_patch"]
