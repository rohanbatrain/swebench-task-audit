"""Minimal unified-diff reader.

Deliberately dependency-free and tolerant: a candidate patch produced by a model is
often slightly malformed, and an auditor still needs to see what it touched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_DIFF_GIT = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)\s*$")
_MINUS = re.compile(r"^--- (?:a/)?(?P<p>.+?)\s*$")
_PLUS = re.compile(r"^\+\+\+ (?:b/)?(?P<p>.+?)\s*$")
_DEV_NULL = {"/dev/null", "dev/null"}


@dataclass
class FileDiff:
    """The changes a patch makes to a single path."""

    path: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False

    @property
    def churn(self) -> int:
        return len(self.added) + len(self.removed)

    @property
    def added_text(self) -> str:
        return "\n".join(self.added)


def parse_patch(patch: str) -> list[FileDiff]:
    """Split a unified diff into per-file changes.

    Returns an empty list for empty or unparseable input rather than raising - an
    empty patch is a legitimate prediction (the agent declined), and the caller
    decides what that means.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    pending_new = pending_deleted = False

    for line in (patch or "").splitlines():
        if m := _DIFF_GIT.match(line):
            current = FileDiff(path=m.group("b") if m.group("b") not in _DEV_NULL else m.group("a"))
            files.append(current)
            pending_new = pending_deleted = False
            continue
        if line.startswith("new file mode"):
            pending_new = True
            if current:
                current.is_new = True
            continue
        if line.startswith("deleted file mode"):
            pending_deleted = True
            if current:
                current.is_deleted = True
            continue
        if m := _MINUS.match(line):
            if m.group("p") in _DEV_NULL:
                pending_new = True
                if current:
                    current.is_new = True
            continue
        if m := _PLUS.match(line):
            path = m.group("p")
            if path in _DEV_NULL:
                pending_deleted = True
                if current:
                    current.is_deleted = True
            elif current is None:
                # A bare diff with no "diff --git" header.
                current = FileDiff(path=path, is_new=pending_new, is_deleted=pending_deleted)
                files.append(current)
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current.added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            current.removed.append(line[1:])

    return files


def changed_paths(patch: str) -> set[str]:
    """Every path a patch touches. Used to compare a candidate against test_patch."""
    return {f.path for f in parse_patch(patch)}
