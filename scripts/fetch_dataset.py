"""Download a SWE-bench split to data/ as JSONL.

Separated from the audit so the audit has no network dependency: the corpus tool
reads a file, and fetching that file is somebody else's job.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default="princeton-nlp/SWE-bench_Verified")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", type=Path, default=Path("data/swebench_verified.jsonl"))
    args = ap.parse_args()

    from datasets import load_dataset  # imported late: only this script needs it

    ds = load_dataset(args.dataset, split=args.split)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ds.to_json(str(args.out))
    print(f"{args.dataset} [{args.split}] -> {args.out}  ({len(ds)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
