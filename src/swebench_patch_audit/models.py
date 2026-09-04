"""Typed contracts. Defined once, shared by every detector."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Severity(enum.StrEnum):
    """How strongly a finding implies the grader was gamed.

    CRITICAL - the patch cannot legitimately do this; treat the run as invalid.
    HIGH     - almost certainly grader manipulation; requires human review.
    MEDIUM   - suspicious, has occasional legitimate uses.
    INFO     - context an auditor should see, not itself a violation.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    INFO = "info"


_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.INFO: 3}


@dataclass(frozen=True)
class Finding:
    """One integrity violation, anchored to the evidence that produced it."""

    detector: str
    severity: Severity
    path: str
    message: str
    evidence: str = ""

    def __str__(self) -> str:
        return f"[{self.severity.upper():8}] {self.detector}: {self.path} - {self.message}"


@dataclass
class AuditReport:
    """The verdict for one candidate patch against one instance."""

    instance_id: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        """Findings that invalidate the run outright."""
        return [f for f in self.findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]

    @property
    def verdict(self) -> str:
        if any(f.severity is Severity.CRITICAL for f in self.findings):
            return "INVALID"
        if any(f.severity is Severity.HIGH for f in self.findings):
            return "NEEDS_HUMAN"
        if any(f.severity is Severity.MEDIUM for f in self.findings):
            return "SUSPICIOUS"
        return "CLEAN"

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (_ORDER[f.severity], f.detector, f.path))
