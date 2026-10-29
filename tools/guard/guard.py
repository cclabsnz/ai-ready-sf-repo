#!/usr/bin/env python3
"""PreToolUse guard. Reads the hook JSON from stdin, exits 2 to block.

Exit codes (Claude Code semantics):
  0  allow
  2  block; stderr is shown to the model
  anything else is treated as a non-blocking warning, so this script
  never deliberately exits with another code.

Policy:
  - No org or network commands: sf, sfdx, git push, curl, wget, ssh.
  - Writes only to the active mode's paths (policy.json), never to always_blocked_writes.
  - WebFetch only to the allowlist.
  - Mode advise blocks every write and every Bash call except read-only
    ones (the kill switch). The committed .claude/settings.json is the
    ceiling: committed advise beats any local AI_FRAMEWORK_MODE.

The rules live in policy.json next to this file. Any internal error,
including an unreadable policy, blocks (exit 2): the hook runner treats
every other exit code as a warning and would let the call through.
"""
import json
import os
import re
import shlex
import sys

MODES = ("advise", "normal", "build", "maintain")
NO_SCOPE_MSG = "no active story scope; run tools/impacts/start.py <storyId> (WS8)"
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Found through __file__ because the wrapper runs us with -I (no cwd, no script dir on sys.path).
POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy.json")


def block(msg):
    try:
        sys.stderr.write(f"BLOCKED by tools/guard/guard.py: {msg}\n")
        sys.stderr.flush()
    except BaseException:
        # Closed or broken stderr must not turn a block into another exit code. _exit skips
        # the interpreter's shutdown flush, which would fail again and exit 120.
        os._exit(2)
    sys.exit(2)


def load_policy(path):
    try:
        with open(path, encoding="utf-8") as f:
            policy = json.load(f)
    except (OSError, ValueError) as e:
        block(f"policy unreadable: {e}; failing closed")
    if not isinstance(policy, dict) or policy.get("version") != 1:
        block("policy unreadable: version is not 1; failing closed")
    return policy


def project_dir():
    return os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def rel_path(root, path):
    """Path relative to root with ".." and symlinks resolved, so neither can carry a write out of ai-context/."""
    try:
        return os.path.relpath(os.path.realpath(os.path.join(root, path)), root).replace("\\", "/")
    except ValueError:  # Windows: path is on a different drive from the repo
        return None


def committed_mode(root):
    """The mode committed in settings.json. Anything unreadable or unknown is advise: the kill switch fails safe."""
    try:
        with open(os.path.join(root, ".claude", "settings.json"), encoding="utf-8") as f:
            mode = json.load(f)["env"]["AI_FRAMEWORK_MODE"]
    except Exception:
        return "advise"
    return mode if isinstance(mode, str) and mode in MODES else "advise"


def resolve_mode(committed, local):
    """Committed advise always wins. Only a committed normal lets a local override pick the mode."""
    if committed == "advise":
        return "advise"
    if committed == "normal":
        if local and local not in MODES:
            block(f"unknown AI_FRAMEWORK_MODE {local!r}; expected one of {MODES}. Failing closed.")
        return local or "normal"
    return "advise"  # build and maintain are personal; a committed one is not trusted


def active_scope(root):
    return []  # WS8 fills this from the active story


def write_block_reason(rel, mode, policy, scope):
    """None if the write is allowed, else the reason. Always-blocked paths are checked before the mode's list."""
    # Lowercased so a case-insensitive filesystem cannot reach .GIT/ or Tools/Guard/.
    low = rel.lower()
    # GitHub honours CODEOWNERS in docs/ too, so match the basename anywhere in the tree.
    if low.rsplit("/", 1)[-1] == "codeowners":
        return f"write to {rel!r} is never allowed (CODEOWNERS file). Guard, settings, CI and git internals change by human-applied patch."
    for p in policy["always_blocked_writes"]:
        if (low + "/").startswith(p.lower()) or low.startswith(p.lower()):
            return f"write to {rel!r} is never allowed (matches {p!r}). Guard, settings, CI and git internals change by human-applied patch."
    cfg = policy["modes"].get(mode)
    if cfg is None:
        return f"no write policy for mode {mode!r}; failing closed."
    allowed = tuple(cfg["writes"])
    if allowed and rel.startswith(allowed):
        return None
    if mode == "advise":
        return "framework is in ADVISE mode: no writes. Output the content in your reply instead."
    if cfg.get("scoped_source"):
        if scope and rel.startswith(tuple(scope)):
            return None
        return NO_SCOPE_MSG
    return f"write to {rel!r} is outside {allowed} in {mode.upper()} mode. The build is read-only; hand code to the squad."


SEPARATORS = {";", "&&", "||", "|", "&"}
REDIRECT_OP = re.compile(r"&>>?|[<>]+&?")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# Advise allows no redirect target but these; a "&" operator takes a file descriptor.
ADVISE_REDIRECT_TARGETS = {"/dev/null"}
ADVISE_FD_TARGETS = {"1", "2"}


FD_MARK = "\x01"  # prefixed to a digit glued to a redirect operator, so shlex output keeps that fact


def mask_quotes(s):
    """s with every quoted or escaped character replaced by "x", except "$" inside double quotes (it still expands there)."""
    out, q, i = [], None, 0
    while i < len(s):
        c = s[i]
        if q == "'":
            q = None if c == "'" else q
            out.append("x")
        elif q == '"':
            if c == "\\":
                out.append("xx")
                i += 1
            else:
                q = None if c == '"' else q
                out.append("$" if c == "$" else "x")
        elif c == "\\":
            out.append("xx")
            i += 1
        else:
            if c in "'\"":
                q = c
                c = "x"
            out.append(c)
        i += 1
    return "".join(out)[: len(s)]


def has_expansion(cmd):
    """True when the shell would expand cmd in a way token inspection cannot see: any unquoted or double-quoted "$", or any unquoted brace (nested braces defeat pattern matching, so no brace form is tried)."""
    masked = mask_quotes(cmd)
    return any(c in masked for c in "${}")


def mark_fds(line):
    """Prefix FD_MARK to digits glued to a following redirect operator ("2>" yes, "2 >" no)."""
    masked = mask_quotes(line)
    starts = [m.start() for m in re.finditer(r"(?<![^\s;&|()])\d+(?=[<>])", masked)]
    for s in reversed(starts):
        line = line[:s] + FD_MARK + line[s:]
    return line


def parse_bash(cmd):
    """Split a command line into segments of shell words, or None when it cannot be read safely.

    None means block: unbalanced quotes, substitution, process substitution, subshells and any
    operator other than the plain separators and redirects.
    """
    if "$(" in cmd or "`" in cmd or "<(" in cmd or FD_MARK in cmd or has_expansion(cmd):
        return None
    segments = []
    # shlex drops newlines as whitespace, so split on them first. A quote spanning lines is unbalanced here: blocked.
    for line in cmd.split("\n"):
        lex = shlex.shlex(mark_fds(line), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""  # shlex would drop everything after a mid-word "#"; bash does not
        try:
            tokens = list(lex)
        except ValueError:
            return None
        seg = []
        for tok in tokens:
            if tok in SEPARATORS:
                if seg:
                    segments.append(seg)
                seg = []
            elif all(c in "();<>|&" for c in tok) and not REDIRECT_OP.fullmatch(tok):
                return None
            else:
                seg.append(tok)
        if seg:
            segments.append(seg)
    return segments


def split_redirects(seg):
    """(words, redirects). A redirect is (operator, target); target is None when the operator ends the segment."""
    words, redirects = [], []
    i = 0
    prev_word = False
    while i < len(seg):
        tok = seg[i]
        if REDIRECT_OP.fullmatch(tok):
            if prev_word and words[-1].startswith(FD_MARK):
                words.pop()  # the fd number in "2>x" belongs to the redirect
            target = seg[i + 1] if i + 1 < len(seg) else None
            redirects.append((tok, target))
            i += 2
            prev_word = False
            continue
        words.append(tok)
        prev_word = True
        i += 1
    return words, redirects


def segment_command(seg):
    words, _ = split_redirects(seg)
    while words and ASSIGNMENT.match(words[0]):
        words.pop(0)
    return words


def segment_matches(seg, patterns):
    text = " ".join(segment_command(seg))
    return any(re.fullmatch(p, text) for p in patterns)


def advise_block_reason(cmd, patterns):
    """None if every segment of cmd is read-only, else the reason."""
    segments = parse_bash(cmd)
    if segments is None:
        return "the command cannot be parsed safely (unbalanced quote, substitution or subshell)."
    for seg in segments:
        words, redirects = split_redirects(seg)
        for op, target in redirects:
            fd_dup = op.endswith("&") and target in ADVISE_FD_TARGETS
            if not fd_dup and target not in ADVISE_REDIRECT_TARGETS:
                return f"redirect {op} {target or ''} is not allowed; only /dev/null and &1/&2 are."
        if words and ASSIGNMENT.match(words[0]):
            return "environment assignments before a command are not allowed."
        if not segment_matches(seg, patterns):
            return "only read-only commands are allowed."
    return None


def main():
    policy = load_policy(POLICY_PATH)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        block("could not parse hook input; failing closed")
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input", {}) or {}
    root = project_dir()
    mode = resolve_mode(committed_mode(root), os.environ.get("AI_FRAMEWORK_MODE", "").strip().lower())

    if tool == "Bash":
        cmd = inp.get("command", "")
        for pat in policy["blocked_commands"]:
            if re.search(pat, cmd):
                block(f"command matches blocked pattern {pat!r}. Write numbered steps for a human to run instead.")
        if mode == "advise":
            patterns = [p for g in policy["modes"]["advise"]["bash_allow"] for p in policy["bash_groups"][g]]
            reason = advise_block_reason(cmd, patterns)
            if reason:
                block(f"framework is in ADVISE mode: {reason} Output recommendations, do not act.")

    elif tool in WRITE_TOOLS:
        path = (inp.get("file_path") or inp.get("path") or "").replace("\\", "/")
        rel = rel_path(root, path)
        if rel is None:
            block(f"write to {path!r} is on a different drive from the repo.")
        reason = write_block_reason(rel, mode, policy, active_scope(root))
        if reason:
            block(reason)

    elif tool == "WebFetch":
        url = inp.get("url", "")
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        allowlist = policy["fetch_allowlist"]
        if not any(host == h or host.endswith("." + h) for h in allowlist):
            block(f"fetch to {host!r} is not on the allowlist {tuple(allowlist)}.")

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        block("internal error; failing closed")
