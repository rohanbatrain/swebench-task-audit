set -uo pipefail
UV=/usr/bin/uv
P="$HOME/repos/swebench-task-audit"
W="$HOME/repos/.swebench-work"; mkdir -p "$W"
cd "$P"

"$P/.venv/bin/python" - <<'PY' > /tmp/pick.txt
import json
rows=[json.loads(l) for l in open("data/swebench_verified.jsonl")]
c=sorted((r for r in rows if r["repo"]=="psf/requests"),
         key=lambda r: len(r["patch"])+len(r["test_patch"]))
r=c[0]
print(r["instance_id"]); print(r["base_commit"])
print(" ".join(json.loads(r["FAIL_TO_PASS"])))
print(" ".join(json.loads(r["PASS_TO_PASS"])[:12]))
open("/tmp/gold.patch","w").write(r["patch"])
open("/tmp/test.patch","w").write(r["test_patch"])
PY
IID=$(sed -n 1p /tmp/pick.txt); BASE=$(sed -n 2p /tmp/pick.txt)
F2P=$(sed -n 3p /tmp/pick.txt); P2P=$(sed -n 4p /tmp/pick.txt)
echo "INSTANCE     : $IID"
echo "BASE COMMIT  : $BASE"
echo "FAIL_TO_PASS : $F2P"
echo

cd "$W"
[ -d requests ] || git clone -q https://github.com/psf/requests.git requests
cd requests
git checkout -q -f "$BASE"; git clean -qfdx -e .v
[ -x .v/bin/python ] || $UV venv --python 3.11 .v -q
PYB="$PWD/.v/bin/python"
VIRTUAL_ENV="$PWD/.v" $UV pip install -q -e . pytest 2>&1 | tail -2
echo "env ready: $($PYB -V)  @ $(git rev-parse --short HEAD)"

run() { $PYB -m pytest "$@" -q --no-header -p no:cacheprovider 2>&1 | tail -3; return "${PIPESTATUS[0]}"; }

echo; echo "── apply test_patch (installs the grader) ────────────────────"
git apply /tmp/test.patch && echo "OK: test_patch applied cleanly"

echo; echo "── STEP 1  FAIL_TO_PASS at base commit — expect FAIL ─────────"
run $F2P; S1=$?; echo "   pytest exit=$S1  $([ $S1 -ne 0 ] && echo 'CORRECT: fails before the fix' || echo 'PROBLEM: passes without any fix')"

echo; echo "── STEP 2  apply gold patch ──────────────────────────────────"
git apply /tmp/gold.patch && echo "OK: gold patch applied cleanly to base_commit"

echo; echo "── STEP 3  FAIL_TO_PASS after gold — expect PASS ─────────────"
run $F2P; S3=$?; echo "   pytest exit=$S3  $([ $S3 -eq 0 ] && echo 'CORRECT: gold resolves the instance' || echo 'PROBLEM: gold does not resolve')"

echo; echo "── STEP 4  PASS_TO_PASS sample after gold — expect PASS ──────"
run $P2P; S4=$?; echo "   pytest exit=$S4  $([ $S4 -eq 0 ] && echo 'CORRECT: no regressions in sample' || echo 'PROBLEM: regression')"

echo; echo "── STEP 5  NEGATIVE CONTROL: revert gold, keep grader ────────"
git apply -R /tmp/gold.patch && run $F2P; S5=$?
echo "   pytest exit=$S5  $([ $S5 -ne 0 ] && echo 'CORRECT: grader tracks the patch, not the environment' || echo 'PROBLEM: passes with no fix — grader is not measuring anything')"

echo
echo "═══ VERDICT ═══"
echo "  fails at base ........ $([ $S1 -ne 0 ] && echo PASS || echo FAIL)"
echo "  gold applies clean ... PASS"
echo "  gold resolves F2P .... $([ $S3 -eq 0 ] && echo PASS || echo FAIL)"
echo "  P2P sample green ..... $([ $S4 -eq 0 ] && echo PASS || echo FAIL)"
echo "  negative control ..... $([ $S5 -ne 0 ] && echo PASS || echo FAIL)"
