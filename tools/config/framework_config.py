#!/usr/bin/env python3
"""The one reader of .ai-framework.json.

Usage:
  framework_config.py source-root [--root <repo>]   the source root, relative to the repo
  framework_config.py show [--root <repo>]          the whole config, defaults filled in, as JSON

--root defaults to this checkout (computed from this file's location, never the cwd).

Keys (any other top-level key is an error, so a typo surfaces):
  startingPoint  "existing" or "greenfield"; default "existing"
  sourceRoot     the folder holding force-app/ and pkg-*/, relative to the repo; default "."
                 It must resolve (realpath) inside the repo.
  impactChecks   {"noImpact": ..., "outOfScope": ...}, each "comment" or "fail";
                 default "comment". Other keys inside impactChecks are ignored.

A missing file means the defaults. Every problem raises ValueError; the CLI prints it on
stderr and exits 2.
Exit codes: 0 ok, 2 bad usage or an invalid config. Stdlib only. Offline. Writes nothing.
"""
import argparse
import json
import os
import sys

CHECKOUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILENAME = ".ai-framework.json"
KNOWN_KEYS = ("startingPoint", "sourceRoot", "impactChecks")
STARTING_POINTS = ("existing", "greenfield")
SETTING_KEYS = ("noImpact", "outOfScope")
SETTING_VALUES = ("comment", "fail")
MAX_VALUE = 200


def _show(value):
    """A config value as one bounded, escaped token for an error message."""
    try:
        text = json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError, RecursionError):
        text = type(value).__name__
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + "..."


def _read(root):
    path = os.path.join(root, FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (RecursionError, MemoryError, OSError) as exc:
        raise ValueError("%s cannot be read: %s" % (FILENAME, type(exc).__name__))
    if not isinstance(data, dict):
        raise ValueError("%s is not a JSON object" % FILENAME)
    unknown = sorted(k for k in data if k not in KNOWN_KEYS)
    if unknown:
        raise ValueError("%s: unknown key %s; the known keys are %s"
                         % (FILENAME, ", ".join(_show(k) for k in unknown), ", ".join(KNOWN_KEYS)))
    return data


def _impact_checks(data):
    settings = {k: "comment" for k in SETTING_KEYS}
    checks = data.get("impactChecks")
    if checks is None:
        return settings
    if not isinstance(checks, dict):
        raise ValueError("%s: impactChecks is not an object" % FILENAME)
    for k in SETTING_KEYS:
        if k in checks:
            if checks[k] not in SETTING_VALUES:
                raise ValueError("%s: impactChecks.%s %s is not one of %s"
                                 % (FILENAME, k, _show(checks[k]), ", ".join(SETTING_VALUES)))
            settings[k] = checks[k]
    return settings


def load(root):
    """The config at <root>/.ai-framework.json with defaults filled in; ValueError when invalid."""
    data = _read(root)
    starting = data.get("startingPoint", "existing")
    if starting not in STARTING_POINTS:
        raise ValueError("%s: startingPoint %s is not one of %s"
                         % (FILENAME, _show(starting), ", ".join(STARTING_POINTS)))
    source = data.get("sourceRoot", ".")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("%s: sourceRoot %s is not a non-empty string" % (FILENAME, _show(source)))
    return {"startingPoint": starting, "sourceRoot": source, "impactChecks": _impact_checks(data)}


def _inside(top, path):
    """True when path is top or below it. On Windows, paths on different drives are never inside."""
    try:
        return os.path.commonpath([top, path]) == top
    except ValueError:
        return False


def source_root(root):
    """Absolute real path of sourceRoot. ValueError when it resolves outside root or is no folder."""
    source = load(root)["sourceRoot"]
    top = os.path.realpath(root)
    path = os.path.realpath(os.path.join(top, source))
    if not _inside(top, path):
        raise ValueError("%s: sourceRoot %s resolves outside the repo" % (FILENAME, _show(source)))
    if not os.path.isdir(path):
        raise ValueError("%s: sourceRoot %s is not a directory" % (FILENAME, _show(source)))
    return path


def impact_checks(root):
    """{"noImpact": ..., "outOfScope": ...}, each comment or fail; ValueError otherwise.
    Validates only the file, its top-level keys and impactChecks, so a value pr_check does not
    use (startingPoint, sourceRoot) cannot stop the PR check."""
    return _impact_checks(_read(root))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read .ai-framework.json.")
    ap.add_argument("command", choices=("source-root", "show"))
    ap.add_argument("--root", default=CHECKOUT)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        if args.command == "source-root":
            top = os.path.realpath(args.root)
            print(os.path.relpath(source_root(args.root), top).replace(os.sep, "/"))
        else:
            print(json.dumps(load(args.root), indent=1, sort_keys=True))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
