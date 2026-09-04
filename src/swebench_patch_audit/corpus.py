"""Corpus-wide audit signals for a SWE-bench split.

Hand-auditing 500 instances is not feasible, and sampling blind wastes the budget on
healthy tasks. These signals are mechanical proxies for the five axes the audit cares
about - they do not decide anything, they decide *where to look*.
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .diffparse import changed_paths, parse_patch
from .testids import format_mix, resolve_all

# Assertions pinned to an exact rendered string are the classic over-rigid test: a
# functionally correct patch that words the message differently still fails.
_BRITTLE_ASSERT = re.compile(
    r"""(?x)
    assert\s+(?:repr|str)\s*\(
  | \.\s*(?:assertEqual|assertEquals)\s*\(\s*(?:repr|str)\s*\(
  | assert\s+\w+(?:\(\))?\s*==\s*["'][^"']{25,}["']
  | match\s*=\s*(?:r?["'])[^"']{20,}
    """
)
_TRACEBACK = re.compile(r"Traceback \(most recent call last\)")
_CODEBLOCK = re.compile(r"```|::\n\n\s{4}|>>> ")


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return [value] if value else []
        return [str(v) for v in parsed] if isinstance(parsed, list) else [str(parsed)]
    return [str(v) for v in (value or [])]


@dataclass
class InstanceSignals:
    """Mechanical audit signals for one instance."""

    instance_id: str
    repo: str
    difficulty: str
    statement_words: int
    has_repro_code: bool
    has_traceback: bool
    hints_words: int
    n_fail_to_pass: int
    n_pass_to_pass: int
    f2p_files_outside_test_patch: int
    test_patch_churn: int
    gold_patch_churn: int
    gold_touches_tests_only: bool
    brittle_assert_hits: int
    env_commit_differs: bool
    n_test_ids_unresolvable: int
    test_id_formats: dict[str, int]

    # --- the five axes, as boolean concerns -------------------------------------

    @property
    def concern_underspecified(self) -> bool:
        """Short statement, no reproduction code and no traceback: little to go on."""
        return self.statement_words < 100 and not self.has_repro_code and not self.has_traceback

    @property
    def concern_solution_leakage(self) -> bool:
        """The issue thread carries substantial discussion, which can contain the fix."""
        return self.hints_words >= 200

    @property
    def concern_brittle_tests(self) -> bool:
        """Graders assert on exact rendered output rather than behaviour."""
        return self.brittle_assert_hits > 0

    @property
    def concern_grader_provenance(self) -> bool:
        """A FAIL_TO_PASS target lives in a file the test_patch never touches.

        The test was not written for this issue, so it may be failing for an
        unrelated reason - a reproducibility risk, not necessarily a defect.
        """
        return self.f2p_files_outside_test_patch > 0

    @property
    def concern_unresolvable_test_ids(self) -> bool:
        """A FAIL_TO_PASS target cannot be traced to a file by identifier alone.

        Django prints test docstrings in place of names, so the grader for these
        instances cannot be located mechanically - it has to be run to be found.
        """
        return self.n_test_ids_unresolvable > 0

    # `environment_setup_commit` differing from `base_commit` is NOT a concern: it is
    # pinned once per (repo, version) and shared across instances by design. Measured,
    # reported, and deliberately excluded from the concern set.

    @property
    def concern_wide_regression_surface(self) -> bool:
        """Very large PASS_TO_PASS sets make a single flaky test look like a regression."""
        return self.n_pass_to_pass > 500

    def concerns(self) -> list[str]:
        return [
            name.removeprefix("concern_")
            for name in dir(self)
            if name.startswith("concern_") and getattr(self, name)
        ]


def signals_for(row: dict[str, Any]) -> InstanceSignals:
    statement = row.get("problem_statement") or ""
    hints = row.get("hints_text") or ""
    test_patch = row.get("test_patch") or ""
    gold = row.get("patch") or ""
    f2p = _as_list(row.get("FAIL_TO_PASS"))
    repo = row.get("repo", "")
    test_files = changed_paths(test_patch)
    gold_files = parse_patch(gold)

    resolutions = resolve_all(f2p, repo=repo)
    f2p_files = {r.path for r in resolutions if r.resolved}
    outside = {f for f in f2p_files if f and f not in test_files}
    unresolvable = sum(1 for r in resolutions if not r.resolved)

    return InstanceSignals(
        instance_id=row["instance_id"],
        repo=row.get("repo", "?"),
        difficulty=row.get("difficulty", "?"),
        statement_words=len(statement.split()),
        has_repro_code=bool(_CODEBLOCK.search(statement)),
        has_traceback=bool(_TRACEBACK.search(statement)),
        hints_words=len(hints.split()),
        n_fail_to_pass=len(f2p),
        n_pass_to_pass=len(_as_list(row.get("PASS_TO_PASS"))),
        f2p_files_outside_test_patch=len(outside),
        test_patch_churn=sum(f.churn for f in parse_patch(test_patch)),
        gold_patch_churn=sum(f.churn for f in gold_files),
        gold_touches_tests_only=bool(gold_files) and all("test" in f.path for f in gold_files),
        brittle_assert_hits=len(_BRITTLE_ASSERT.findall(test_patch)),
        env_commit_differs=bool(row.get("environment_setup_commit"))
        and row.get("environment_setup_commit") != row.get("base_commit"),
        n_test_ids_unresolvable=unresolvable,
        test_id_formats=format_mix(f2p, repo=repo),
    )


def load_split(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line := line.strip():
                yield json.loads(line)


def summarise(all_signals: Iterable[InstanceSignals]) -> dict[str, Any]:
    sigs = list(all_signals)
    concern_names = [
        n.removeprefix("concern_") for n in dir(InstanceSignals) if n.startswith("concern_")
    ]
    counts = {c: sum(1 for s in sigs if c in s.concerns()) for c in concern_names}
    return {
        "n_instances": len(sigs),
        "concern_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "clean": sum(1 for s in sigs if not s.concerns()),
        "statement_words_median": statistics.median(s.statement_words for s in sigs),
        "hints_words_median": statistics.median(s.hints_words for s in sigs),
        "instances_with_any_hints": sum(1 for s in sigs if s.hints_words > 0),
        "pass_to_pass_median": statistics.median(s.n_pass_to_pass for s in sigs),
        "pass_to_pass_max": max(s.n_pass_to_pass for s in sigs),
        "gold_churn_median": statistics.median(s.gold_patch_churn for s in sigs),
        "test_id_formats": {
            fmt: sum(s.test_id_formats.get(fmt, 0) for s in sigs)
            for fmt in ("pytest", "unittest", "freeform")
        },
        "instances_using_each_format": {
            fmt: sum(1 for s in sigs if s.test_id_formats.get(fmt, 0))
            for fmt in ("pytest", "unittest", "freeform")
        },
        "env_commit_pinned_per_repo_version": {
            "instances_where_env_differs_from_base": sum(1 for s in sigs if s.env_commit_differs),
            "note": "pinned per (repo, version) by design; excluded from concerns",
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Compute corpus-wide SWE-bench audit signals.")
    ap.add_argument("--instances", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path("audit/corpus_signals.json"))
    args = ap.parse_args(argv)

    sigs = [signals_for(r) for r in load_split(args.instances)]
    summary = summarise(sigs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "summary": summary,
                "instances": [asdict(s) | {"concerns": s.concerns()} for s in sigs],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
