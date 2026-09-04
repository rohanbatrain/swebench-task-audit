"""Demonstrate, against a real SWE-bench instance, two things that are usually asserted.

    verify   the grader works - including the negative control that is the only step
             which distinguishes a working grader from one that passes for unrelated
             reasons.
    exploit  the grader can be defeated by a patch that changes no source code, and
             swebench-patch-audit catches that patch.

Both subcommands assert their expected outcome and exit non-zero when reality differs,
so a green CI run means the demonstration actually reproduced rather than merely ran.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CONFTEST_EXPLOIT = """import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        report.outcome = "passed"
"""

FAILURES: list[str] = []


def step(label: str) -> None:
    print(f"\n\033[1m── {label} {'─' * max(0, 58 - len(label))}\033[0m", flush=True)


def expect(condition: bool, description: str) -> bool:
    """Record an assertion without aborting, so every step still runs and reports."""
    mark = "PASS" if condition else "FAIL"
    print(f"   [{mark}] {description}", flush=True)
    if not condition:
        FAILURES.append(description)
    return condition


def run(cmd: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        print(proc.stdout[-4000:], proc.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")
    return proc


@dataclass
class Instance:
    instance_id: str
    repo: str
    base_commit: str
    patch: str
    test_patch: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]

    @classmethod
    def load(cls, dataset: Path, instance_id: str) -> Instance:
        with dataset.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if row["instance_id"] == instance_id:
                    return cls(
                        instance_id=row["instance_id"],
                        repo=row["repo"],
                        base_commit=row["base_commit"],
                        patch=row["patch"],
                        test_patch=row["test_patch"],
                        fail_to_pass=json.loads(row["FAIL_TO_PASS"]),
                        pass_to_pass=json.loads(row["PASS_TO_PASS"]),
                    )
        raise SystemExit(f"instance {instance_id!r} not found in {dataset}")


def prepare(inst: Instance, work: Path) -> tuple[Path, Path]:
    """Clone the repo at base_commit into an isolated venv. Returns (repo, python)."""
    repo_dir = work / inst.repo.split("/")[-1]
    if not repo_dir.exists():
        run(
            ["git", "clone", "--quiet", f"https://github.com/{inst.repo}.git", str(repo_dir)],
            cwd=work,
            check=True,
        )
    run(["git", "checkout", "--quiet", "--force", inst.base_commit], cwd=repo_dir, check=True)
    run(["git", "clean", "-qfdx", "-e", ".venv"], cwd=repo_dir)

    venv = repo_dir / ".venv"
    python = venv / "bin" / "python"
    if not python.exists():
        uv = shutil.which("uv") or "uv"
        run([uv, "venv", "--python", "3.11", str(venv), "-q"], cwd=repo_dir, check=True)
        env_uv = os.environ | {"VIRTUAL_ENV": str(venv)}
        subprocess.run(
            [uv, "pip", "install", "-q", "-e", ".", "pytest"], cwd=repo_dir, env=env_uv, check=True
        )
    return repo_dir, python


def pytest_ok(python: Path, repo: Path, targets: list[str]) -> bool:
    proc = run(
        [str(python), "-m", "pytest", *targets, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=repo,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1:]
    print(f"        pytest: {tail[0] if tail else '(no output)'}  exit={proc.returncode}")
    return proc.returncode == 0


def apply_patch(repo: Path, text: str, reverse: bool = False) -> bool:
    patch_file = repo / ".tmp.patch"
    patch_file.write_text(text, encoding="utf-8")
    cmd = ["git", "apply"] + (["-R"] if reverse else []) + [str(patch_file)]
    proc = run(cmd, cwd=repo)
    patch_file.unlink(missing_ok=True)
    return proc.returncode == 0


def cmd_verify(inst: Instance, work: Path) -> None:
    repo, python = prepare(inst, work)
    f2p = inst.fail_to_pass
    p2p = inst.pass_to_pass[:12]

    print(f"\ninstance     {inst.instance_id}")
    print(f"repo         {inst.repo} @ {inst.base_commit[:12]}")
    print(f"FAIL_TO_PASS {len(inst.fail_to_pass)}   PASS_TO_PASS {len(inst.pass_to_pass)}")

    step("1 · install the grader (test_patch)")
    expect(apply_patch(repo, inst.test_patch), "test_patch applies cleanly")

    step("2 · FAIL_TO_PASS at base_commit — must FAIL")
    expect(not pytest_ok(python, repo, f2p), "target test fails before the fix")

    step("3 · apply the reference patch")
    expect(apply_patch(repo, inst.patch), "reference patch applies cleanly to base_commit")

    step("4 · FAIL_TO_PASS after the fix — must PASS")
    expect(pytest_ok(python, repo, f2p), "reference patch resolves the instance")

    step("5 · PASS_TO_PASS sample — must stay green")
    expect(pytest_ok(python, repo, p2p), f"no regressions across {len(p2p)} PASS_TO_PASS tests")

    step("6 · NEGATIVE CONTROL — revert the fix, keep the grader")
    expect(apply_patch(repo, inst.patch, reverse=True), "reference patch reverts cleanly")
    expect(
        not pytest_ok(python, repo, f2p),
        "target fails again — the grader tracks the patch, not the environment",
    )


def cmd_exploit(inst: Instance, work: Path, dataset: Path) -> None:
    repo, python = prepare(inst, work)
    f2p = inst.fail_to_pass
    source_dirs = sorted({p.split("/")[0] for p in _changed(inst.patch)})

    print(f"\ninstance  {inst.instance_id}")
    print(f"target    {f2p[0][:88]}")

    step("1 · baseline — grader installed, no fix")
    apply_patch(repo, inst.test_patch)
    expect(not pytest_ok(python, repo, f2p), "target test fails, as it should")

    step("2 · the exploit — 9 lines of conftest.py, no source change")
    (repo / "conftest.py").write_text(CONFTEST_EXPLOIT, encoding="utf-8")
    print(CONFTEST_EXPLOIT.rstrip("\n"))
    diff = run(["git", "diff", "--stat", "--", *source_dirs], cwd=repo).stdout.strip()
    print(f"\n        git diff --stat {' '.join(source_dirs)} -> {diff or '(empty)'}")
    expect(diff == "", f"no source changes in {'/'.join(source_dirs)}/")

    step("3 · re-run the SAME test")
    expect(
        pytest_ok(python, repo, f2p),
        "test now reports PASS — the harness would score this resolved",
    )

    step("4 · swebench-patch-audit on that patch")
    cheat = run(["git", "diff", "--no-index", "/dev/null", "conftest.py"], cwd=repo).stdout
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from swebench_patch_audit import audit_patch

    row = json.loads(
        next(
            ln
            for ln in dataset.read_text(encoding="utf-8").splitlines()
            if json.loads(ln)["instance_id"] == inst.instance_id
        )
    )
    report = audit_patch(cheat, row)
    print(f"\n        {report.instance_id} -> {report.verdict}")
    for f in report.sorted_findings():
        print(f"        {f}")
    expect(report.verdict == "INVALID", "linter returns INVALID")
    expect(len(report.blocking) >= 3, "at least three independent detectors fire")

    (repo / "conftest.py").unlink(missing_ok=True)


def _changed(patch: str) -> set[str]:
    return {ln.split(" b/")[-1].strip() for ln in patch.splitlines() if ln.startswith("diff --git")}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mode", choices=["verify", "exploit"])
    ap.add_argument("--instance", default="psf__requests-5414")
    ap.add_argument("--dataset", type=Path, default=Path("data/swebench_verified.jsonl"))
    ap.add_argument("--work", type=Path, default=Path(".swebench-work"))
    args = ap.parse_args()

    args.work.mkdir(parents=True, exist_ok=True)
    # Absolute from here on: several steps run with cwd set into the cloned repo, and a
    # relative path would resolve against the wrong directory.
    args.work = args.work.resolve()
    args.dataset = args.dataset.resolve()
    inst = Instance.load(args.dataset, args.instance)

    if args.mode == "verify":
        cmd_verify(inst, args.work)
    else:
        cmd_exploit(inst, args.work, args.dataset)

    print()
    if FAILURES:
        print(f"\033[1;31m{len(FAILURES)} expectation(s) did not hold:\033[0m")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\033[1;32mAll expectations held.\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
