"""Resolving SWE-bench test identifiers to source files.

SWE-bench does not use one test-ID format. Across the Verified split there are three,
and only one of them names a file:

    pytest    astropy/modeling/tests/test_separable.py::test_separable[compound6]
    unittest  test_ascii_validator (auth_tests.test_validators.UsernameValidatorsTests)
    freeform  Migration directories without an __init__.py file are loaded.

The last is a Django test *docstring*, which its runner prints in place of a name.
Any tool that assumes `path::test` silently does nothing on the 61% of instances that
use the other two - and reports a clean result while having checked nothing. This
module exists so that failure is impossible to make by accident: every ID resolves to
a Resolution that states plainly whether a file was recovered.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass

_PYTEST = re.compile(r"^(?P<path>[\w./\-]+\.py)::(?P<rest>.+)$")
_UNITTEST = re.compile(r"^(?P<name>[\w.]+)\s+\((?P<dotted>[\w.]+)\)\s*$")
_CLASS_SEGMENT = re.compile(r"^[A-Z]")

# Repos whose test packages are rooted outside the importable package directory.
_TEST_ROOTS = {"django/django": "tests/"}


class IdFormat(enum.StrEnum):
    PYTEST = "pytest"
    UNITTEST = "unittest"
    FREEFORM = "freeform"


@dataclass(frozen=True)
class Resolution:
    """One test identifier, and the file it names if it names one."""

    raw: str
    fmt: IdFormat
    path: str | None
    test: str | None = None

    @property
    def resolved(self) -> bool:
        return self.path is not None


def resolve(test_id: str, *, repo: str = "") -> Resolution:
    """Map one test identifier to a source path where the format allows it."""
    raw = test_id.strip()

    if m := _PYTEST.match(raw):
        return Resolution(raw, IdFormat.PYTEST, m.group("path"), m.group("rest"))

    if m := _UNITTEST.match(raw):
        segments = m.group("dotted").split(".")
        # Trailing CamelCase segments are class names, not path components.
        while len(segments) > 1 and _CLASS_SEGMENT.match(segments[-1]):
            segments.pop()
        path = "/".join(segments) + ".py"
        if (root := _TEST_ROOTS.get(repo)) and not path.startswith(root):
            path = root + path
        return Resolution(raw, IdFormat.UNITTEST, path, m.group("name"))

    return Resolution(raw, IdFormat.FREEFORM, None, raw)


def resolve_all(test_ids: list[str], *, repo: str = "") -> list[Resolution]:
    return [resolve(t, repo=repo) for t in test_ids]


def format_mix(test_ids: list[str], *, repo: str = "") -> dict[str, int]:
    """How many identifiers of each format an instance uses."""
    counts = dict.fromkeys((f.value for f in IdFormat), 0)
    for r in resolve_all(test_ids, repo=repo):
        counts[r.fmt.value] += 1
    return counts
