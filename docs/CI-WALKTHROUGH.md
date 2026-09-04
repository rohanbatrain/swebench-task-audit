# How the CI works, and why each piece is there

A walkthrough of the two workflows in this repository — what each decision buys, what it
costs, and the three things that broke on the way to green. Written so the reasoning is
recoverable later, not just the result.

---

## The premise

The README makes checkable claims: 500 instances audited, a grader verified with a
negative control, an exploit that defeats it. A README asserting those is worth very
little. **A workflow that re-derives them on a machine neither of us controls is worth a
lot more.**

So `scripts/prove.py` does not print results — it *asserts* them:

```python
def expect(condition: bool, description: str) -> bool:
    """Record an assertion without aborting, so every step still runs and reports."""
    mark = "PASS" if condition else "FAIL"
    print(f"   [{mark}] {description}")
    if not condition:
        FAILURES.append(description)
    return condition
```

Every expectation is recorded, all steps run to completion, and the process exits non-zero
if any failed. **A green check means the demonstration reproduced.** A script that merely
ran to completion would prove nothing — and "the job passed" would be exactly the kind of
green-that-means-nothing this repository exists to detect.

---

## Why CI is a better home than a laptop

SWE-bench's official evaluation images are built for **x86_64**. On an arm64 machine
(any Apple Silicon Mac) a meaningful fraction of those image builds fail, and you spend
your afternoon on Docker rather than on the audit.

GitHub's `ubuntu-latest` runners are x86_64 Linux. The architecture problem simply does
not exist there. That is not a workaround — for this benchmark, CI is the *correct*
platform, and a laptop is the compromise.

---

## `ci.yml` — the quality gates

### Two jobs, not one

`gates` (ruff, format, mypy) runs once. `tests` runs three times, once per Python version.
Separating them means a formatting slip fails in ~20 seconds instead of waiting behind
three test matrices.

### `fail-fast: false`

```yaml
strategy:
  fail-fast: false
  matrix:
    python: ["3.11", "3.12", "3.13"]
```

Default behaviour cancels the whole matrix when one leg fails. That hides information: if
3.11 fails you want to know whether 3.12 and 3.13 also fail, because "broken on one
version" and "broken everywhere" are different bugs with different causes. Turning
fail-fast off costs a few runner-minutes and buys a complete picture.

### Least privilege

```yaml
permissions:
  contents: read
```

Neither workflow writes to the repository, so neither gets a token that can. Set this
explicitly on every workflow — the default is broader than you want, and a compromised
action inherits whatever the token can do.

### Cancel superseded runs

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

Push three times in a minute and you have three runs racing, of which only the last
matters. This kills the older two. Note the group key includes the ref, so runs on
different branches never cancel each other.

---

## `proof.yml` — the demonstrations

Three jobs, deliberately named as claims rather than as tasks:

```
corpus audit · 500 instances
harness verification · negative control
exploit · 9 lines, no source change
```

Someone scanning the Actions tab reads three assertions and three green checks. Naming a
job `build` or `test` wastes that space.

They run in parallel and each fetches the dataset independently. That duplicates roughly
thirty seconds of download three times — accepted on purpose, because jobs with no
`needs:` between them cannot fail in a confusing order, and the parallel layout renders
better. The `actions/cache` step on `~/.cache/huggingface` takes most of the cost back.

### Job summaries are the actual deliverable

`GITHUB_STEP_SUMMARY` is a file path. Anything appended to it renders as Markdown on the
run page, above the logs:

```yaml
- name: Render findings to the run summary
  run: python scripts/summarize_corpus.py audit/corpus_signals.json >> "$GITHUB_STEP_SUMMARY"
```

This is the difference between "the job passed" and "here are the findings, in a table, on
the page you already opened." Nobody expands a log to read your results; they will read a
summary.

Two details worth stealing:

- **Strip ANSI colour before embedding logs.** Terminal escapes render as literal
  `ESC[1m` garbage in Markdown: `sed 's/\x1b\[[0-9;]*m//g'`.
- **`if: always()`** on the summary step, so a *failed* demonstration still explains
  itself instead of leaving an empty page.

### `set -o pipefail`

```yaml
run: |
  set -o pipefail
  uv run python scripts/prove.py verify ... 2>&1 | tee verify.log
```

Without it, a pipeline's exit status is the *last* command's — so `tee` succeeding would
mask `prove.py` failing, and the job would go green on a broken demonstration. This is the
same class of bug as everything else in this repository: a check that reports success
having verified nothing.

### The weekly schedule

```yaml
schedule:
  - cron: "17 6 * * 1"
```

Reproducibility is not established once. Upstream `psf/requests` could move, HuggingFace
could change an export, a transitive dependency could break the 3.11 environment. A weekly
run turns "it reproduced in September" into a standing claim. The odd minute (`17`) avoids
the top-of-hour spike when everyone's crons fire at once and GitHub queues them.

---

## Pinning actions to SHAs

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

Not `@v7`. A **tag is a mutable pointer** — whoever controls the repository can move `v7`
to any commit, and every workflow in the world pinned to `v7` runs the new code on the
next build. A commit SHA cannot be moved without a SHA-1 collision.

The trailing comment carries the human-readable version, because
`3d3c42e5aac5ba805825da76410c181273ba90b1` tells a reader nothing.

Resolve a tag to its SHA with:

```bash
gh api repos/actions/checkout/git/ref/tags/v7.0.1 --jq '.object.sha'
# annotated tags need one more hop:
gh api repos/actions/checkout/git/tags/<sha> --jq '.object.sha'
```

The cost is real: pinned actions do not receive security patches automatically. Renovate
or Dependabot is the answer — they open a PR that updates the SHA and the comment together.

---

## Three things that broke

Kept because the failures are more instructive than the final YAML.

### 1 · `uv pip install --system` fails two different ways

The first CI run failed on all four jobs, with two distinct errors:

```
py3.11, py3.13:  error: No system Python installation found for Python 3.11
py3.12:          error: The interpreter at /usr is externally managed
```

Both come from `--system`, which means *install into the interpreter on PATH rather than a
virtualenv*:

- For **3.11 and 3.13**, `setup-uv` downloads a **uv-managed** interpreter. It is not a
  system installation, so `--system` looks for one and finds nothing.
- For **3.12**, the runner already ships Debian's Python — which is **PEP 668
  externally-managed**, a marker distributions set to stop `pip` corrupting a
  package-manager-owned interpreter.

The fix is to stop fighting it:

```yaml
- run: |
    uv venv
    uv pip install -e ".[dev]"
- run: uv run pytest
```

`uv venv` creates `.venv`, `uv pip install` finds it automatically, `uv run` executes
inside it. Works identically across all three versions.

**The lesson:** `--system` is for containers you already own end to end. On a shared
runner, make your own environment.

### 2 · A regex that matched most of what it should

Converting `python x.py` to `uv run python x.py` across the workflow, I used:

```python
re.sub(r'^(\s+)run: python scripts/', r'\1run: uv run python scripts/', t, flags=re.M)
```

It missed two lines, because YAML has two spellings and I only handled one:

```yaml
      - run: python scripts/fetch_dataset.py      # inline form, has "- " before "run:"
        run: python scripts/fetch_dataset.py      # block form
```

Caught only because I printed the leftovers afterwards instead of assuming the
substitution was complete:

```python
leftover = [l for l in s.splitlines() if 'python scripts/' in l and 'uv run' not in l]
print("leftover:", leftover or "none")
```

**The lesson, and it is the repository's whole thesis:** a transformation that reports
success having transformed a subset is worse than one that fails loudly. Always print what
your pass *did not* touch.

### 3 · A relative path resolved against the wrong directory

`prove.py` cloned into `.swebench-work/.swebench-work/requests`:

```python
repo_dir = work / "requests"                       # relative: .swebench-work/requests
run(["git", "clone", url, str(repo_dir)], cwd=work)  # cwd is ALSO .swebench-work
```

Both the path and the working directory carried the prefix. The fix is one line, applied
once at entry:

```python
args.work = args.work.resolve()
args.dataset = args.dataset.resolve()
```

**The lesson:** resolve paths to absolute at the boundary. Any function that later runs a
subprocess with a different `cwd` is a trap for relative paths.

---

## Reading a failed run without opening a browser

```bash
gh run list --limit 5                       # what ran, and how it went
gh run view <id> --json jobs \
  --jq '.jobs[] | "\(.name): \(.conclusion)"'   # which job failed
gh run view <id> --log-failed               # ONLY the failing steps' logs
gh run watch <id> --exit-status             # block until done, exit non-zero on failure
gh run download <id> -n corpus-signals      # pull an artifact down
gh run rerun <id> --failed                  # retry only what failed
```

`--log-failed` is the one that matters. `gh run view --log` prints everything, which for a
matrix build is tens of thousands of lines.

---

## Verifying reproducibility for real

The corpus audit ran on three machines: an Arch laptop and two GitHub runners. Comparing
the summary the CI artifact produced against the one computed locally:

```
summaries identical: True
```

Same 500 instances, same 202 clean, same 107/106/104/24/21/18 concern counts, same
`{pytest: 364, unittest: 990, freeform: 162}` format split. That is what makes the numbers
in the README defensible — not that they were computed carefully once, but that a machine
neither of us controls computes the same ones on every push.

---

## `action.yml` — the linter as a reusable action

The composite action lets any repository audit its own SWE-bench predictions:

```yaml
- uses: rohanbatrain/swebench-task-audit@main
  with:
    instances: data/swebench_verified.jsonl
    predictions: preds.json
    fail-on: high
```

`using: composite` means it runs as steps in the caller's job rather than in a container —
no image to build, and it inherits whatever Python the caller set up. `fail-on` maps to the
CLI's exit-code threshold, so a repository can decide whether a `medium` finding should
break its build or merely be reported.
