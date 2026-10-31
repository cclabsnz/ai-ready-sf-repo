#!/usr/bin/env python3
"""Run time and tool-call count from a Claude Code session transcript.

Usage:
  python3 demo/measure/timing.py <session.jsonl>

Reads JSON lines; each line may carry an ISO `timestamp`. Prints
{start, end, durationSeconds, toolCalls}. Tool calls are assistant content blocks of type
`tool_use`. Lines that are not JSON objects are skipped. Exit 0 on success, 2 when no timestamps
are found or the file cannot be read.
"""
import argparse
import json
import sys
from datetime import datetime, timezone


def parse(ts):
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def measure(lines):
    stamps, calls = [], 0
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        ts = rec.get("timestamp")
        if isinstance(ts, str):
            try:
                stamps.append((parse(ts), ts))
            except ValueError:
                pass
        msg = rec.get("message")
        if rec.get("type") == "assistant" and isinstance(msg, dict) and isinstance(msg.get("content"), list):
            calls += sum(1 for b in msg["content"] if isinstance(b, dict) and b.get("type") == "tool_use")
    if not stamps:
        return None
    first, last = min(stamps), max(stamps)
    return {"start": first[1], "end": last[1],
            "durationSeconds": (last[0] - first[0]).total_seconds(), "toolCalls": calls}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    a = ap.parse_args(argv)
    try:
        with open(a.session, encoding="utf-8") as fh:
            result = measure(fh)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if result is None:
        print("error: no timestamps found", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
