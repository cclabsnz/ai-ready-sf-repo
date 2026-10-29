#!/usr/bin/env python3
"""Trajectory assertions over a tool-call log. Works on any harness that emits one JSON object per tool call.

  python3 tools/evals/run_agent.py --log run.jsonl --spec framework/agents/evals/analyst.json

spec: {"must_call": [regex...], "must_not_call": [regex...], "must_block": [regex...]}
  must_call     at least one logged call matches each pattern
  must_not_call no logged call that was ALLOWED matches the pattern
  must_block    a call matching the pattern was attempted and the guard blocked it (exit 2)

Log line shape: {"tool": "Bash", "input": {...}, "guard_exit": 0|2, "allowed": true|false}
"""
import argparse, json, re, sys
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--log", required=True); ap.add_argument("--spec", required=True)
    a = ap.parse_args()
    with open(a.spec) as fh: spec = json.load(fh)
    calls = [json.loads(l) for l in open(a.log) if l.strip()]
    flat = [f"{c['tool']} {json.dumps(c.get('input', {}), sort_keys=True)}" for c in calls]
    fails = []
    for pat in spec.get("must_call", []):
        if not any(re.search(pat, s) for s in flat): fails.append(f"never called: {pat}")
    for pat in spec.get("must_not_call", []):
        for c, s in zip(calls, flat):
            if c.get("allowed", True) and re.search(pat, s): fails.append(f"forbidden call was allowed: {s[:120]}")
    for pat in spec.get("must_block", []):
        if not any(re.search(pat, s) and c.get("guard_exit") == 2 for c, s in zip(calls, flat)):
            fails.append(f"expected a guard block on: {pat}")
    for f in fails: print("FAIL " + f)
    print(f"agent trajectory: {'PASS' if not fails else 'FAIL'} ({len(calls)} calls)")
    return 1 if fails else 0
if __name__ == "__main__": sys.exit(main())
