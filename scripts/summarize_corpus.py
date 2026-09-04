"""Render the corpus audit as a GitHub job summary.

Kept out of the package on purpose: presentation belongs to the caller, not to the
tool. `corpus.py` emits JSON; this turns one JSON file into markdown.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MEANING = {
    "unresolvable_test_ids": "FAIL_TO_PASS target cannot be traced to a file from its identifier",
    "underspecified": "under 100 words, no code fence, no traceback (27% false-positive rate)",
    "solution_leakage": "hints_text of 200+ words",
    "wide_regression_surface": "over 500 PASS_TO_PASS tests",
    "grader_provenance": "FAIL_TO_PASS target in a file test_patch never touches",
    "brittle_tests": "assertions pinned to exact rendered strings",
}


def main(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    s = data["summary"]
    out: list[str] = []

    out.append("## Corpus audit — SWE-bench Verified\n")
    out.append(f"Scored **{s['n_instances']} instances**; **{s['clean']}** flagged nothing.\n")

    out.append("| Signal | Instances | What it means |")
    out.append("|---|--:|---|")
    for name, count in s["concern_counts"].items():
        out.append(f"| `{name}` | {count} | {MEANING.get(name, '')} |")
    out.append("")

    out.append("### Corpus shape\n")
    out.append("| Measure | Value |")
    out.append("|---|--:|")
    out.append(f"| Median problem-statement words | {s['statement_words_median']:.0f} |")
    out.append(f"| Median hints words | {s['hints_words_median']:.0f} |")
    out.append(f"| Instances carrying any hints | {s['instances_with_any_hints']} |")
    out.append(f"| Median PASS_TO_PASS | {s['pass_to_pass_median']:.1f} |")
    out.append(f"| Max PASS_TO_PASS | {s['pass_to_pass_max']} |")
    out.append(f"| Median reference-patch churn | {s['gold_churn_median']:.0f} lines |")
    out.append("")

    fmts = s["test_id_formats"]
    inst = s["instances_using_each_format"]
    total_ids = sum(fmts.values())
    non_pytest = total_ids - fmts["pytest"]
    out.append("### Test-ID formats — the reason the first audit pass was wrong\n")
    out.append("| Format | Identifiers | Instances using it | Names a file? |")
    out.append("|---|--:|--:|---|")
    for f, names in (("pytest", "yes"), ("unittest", "derived"), ("freeform", "**no**")):
        out.append(f"| `{f}` | {fmts[f]} | {inst[f]} | {names} |")
    out.append("")
    out.append(
        f"**{non_pytest} of {total_ids} identifiers ({non_pytest / total_ids:.0%}) are not "
        "`path::test`.** A checker assuming that one format silently does nothing on them "
        "and reports success.\n"
    )

    env = s["env_commit_pinned_per_repo_version"]
    out.append("### A signal measured and deliberately rejected\n")
    out.append(
        f"`environment_setup_commit` differs from `base_commit` in "
        f"**{env['instances_where_env_differs_from_base']}/{s['n_instances']}** instances. "
        "That is not drift — it is pinned once per `(repo, version)` by design, so it is "
        "excluded from the concern set rather than reported as a finding.\n"
    )
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
