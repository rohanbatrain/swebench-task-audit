"""Patch-integrity auditing for SWE-bench-style benchmark submissions.

A patch that makes FAIL_TO_PASS go green has not necessarily fixed the bug. It may
have edited the graders. This package inspects the patch itself, independently of
any test result, and reports the ways it could be satisfying the metric rather than
solving the problem.
"""
from .models import Severity, Finding, AuditReport
from .audit import audit_patch

__all__ = ["Severity", "Finding", "AuditReport", "audit_patch"]
