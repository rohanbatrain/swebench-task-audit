"""Command line entry point: audit predictions against SWE-bench instances."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .audit import audit_patch
from .models import AuditReport, Severity

_COLOUR = {
    Severity.CRITICAL: "\033[1;31m",
    Severity.HIGH: "\033[31m",
    Severity.MEDIUM: "\033[33m",
    Severity.INFO: "\033[36m",
}
_RESET = "\033[0m"


def load_instances(path: Path) -> dict[str, dict[str, Any]]:
    """Read the SWE-bench dataset export, keyed by instance_id."""
    out: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line := line.strip():
                row = json.loads(line)
                out[row["instance_id"]] = row
    return out


def load_predictions(path: Path) -> list[dict[str, Any]]:
    """Read predictions as JSON list, JSONL, or the {instance_id: {...}} mapping."""
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(obj, dict) and not {"instance_id", "model_patch"} & obj.keys():
                return [{"instance_id": k, **v} for k, v in obj.items()]
            return [obj]
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def render(report: AuditReport, *, colour: bool) -> str:
    lines = [f"{report.instance_id}  ->  {report.verdict}"]
    for f in report.sorted_findings():
        prefix = _COLOUR[f.severity] if colour else ""
        suffix = _RESET if colour else ""
        lines.append(f"  {prefix}{f}{suffix}")
        if f.evidence:
            lines.append(f"      evidence: {f.evidence.splitlines()[0][:110]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="swebench-patch-audit",
        description="Flag SWE-bench patches that game the grader instead of fixing the bug.",
    )
    ap.add_argument("--instances", required=True, type=Path, help="SWE-bench dataset .jsonl")
    ap.add_argument("--predictions", required=True, type=Path, help="predictions file")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--fail-on", default="high", choices=[s.value for s in Severity],
                    help="exit non-zero when a finding at or above this severity appears")
    args = ap.parse_args(argv)

    instances = load_instances(args.instances)
    threshold = list(Severity).index(Severity(args.fail_on))
    reports, worst = [], len(Severity)

    for pred in load_predictions(args.predictions):
        iid = pred.get("instance_id")
        instance = instances.get(iid)
        if instance is None:
            print(f"warning: no instance {iid!r} in dataset, skipping", file=sys.stderr)
            continue
        patch = pred.get("model_patch") or pred.get("prediction") or pred.get("patch") or ""
        reports.append(audit_patch(patch, instance))

    for report in reports:
        for f in report.findings:
            worst = min(worst, list(Severity).index(f.severity))
        if args.json:
            continue
        print(render(report, colour=sys.stdout.isatty()))

    if args.json:
        print(json.dumps(
            [{"instance_id": r.instance_id, "verdict": r.verdict,
              "findings": [vars(f) | {"severity": f.severity.value} for f in r.sorted_findings()]}
             for r in reports], indent=2))

    clean = sum(1 for r in reports if r.verdict == "CLEAN")
    print(f"\n{len(reports)} audited: {clean} clean, {len(reports) - clean} flagged", file=sys.stderr)
    return 1 if worst <= threshold else 0


if __name__ == "__main__":
    raise SystemExit(main())
