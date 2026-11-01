#!/usr/bin/env python3
"""PreToolUse guard. Reads the hook JSON from stdin, exits 2 to block.

Exit codes (Claude Code semantics):
  0  allow
  2  block; stderr is shown to the model
  anything else is treated as a non-blocking warning, so this script
  never deliberately exits with another code.

Policy:
  - No network commands (git push, curl, wget, ssh) and no sfdx. The Salesforce CLI (sf) runs only at the
    mode's level (policy.json sf.mode_level), never an always_blocked command.
  - Writes only to the active mode's paths (policy.json), never to always_blocked_writes.
  - Outside advise, every Bash command must also be on the mode's bash_allow list.
  - In every mode, a "$", a brace or a "[[:class:]]" bracket outside single quotes blocks the line: the shell
    could expand it into an option or path the guard never sees. So does a heredoc, whose body the quote masker
    cannot read. An unquoted glob word that could expand to an
    option ("-[o]", or "*" next to a file named "--pre=sh") is blocked too, and so is a line with more than
    GLOB_WORD_LIMIT glob words.
  - WebFetch only to the allowlist.
  - Every other tool: tools.read_only pass; MCP tools are blocked in advise and, in other modes, when a whole
    segment of their name is a write verb (tools.mcp_write_pattern); the rest are blocked in advise only. Before
    all of that, any tool but Bash whose input has a "command" is blocked in every mode.
  - Tripwire: while the guard, settings, CI workflows, GitHub hooks or CODEOWNERS differ from HEAD, or .git/config
    or .git/hooks/ differ from the baseline a human recorded with --rebaseline, every write and non-read-only Bash
    call is blocked.
  - Mode advise blocks every write and every Bash call except read-only
    ones (the kill switch). The committed .claude/settings.json is the
    ceiling: committed advise beats any local AI_FRAMEWORK_MODE.
  - The hook times out at 10 s, so the guard blocks itself after DEADLINE_SECONDS and gives git GIT_TIMEOUT.

The rules live in policy.json next to this file. Any internal error,
including an unreadable policy, blocks (exit 2): the hook runner treats
every other exit code as a warning and would let the call through.
"""
import fnmatch
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.parse

# ---- Policy, mode and limits ----

MODES = ("advise", "normal", "build", "maintain")
# The hook times out at 10 s, and a timed-out hook may let the call through, so the guard stops itself well before.
DEADLINE_SECONDS = 7
DEADLINE = [time.monotonic() + DEADLINE_SECONDS]  # reset at the start of main()
GIT_TIMEOUT = 3
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


def check_deadline():
    if time.monotonic() > DEADLINE[0]:
        block("guard ran out of time; failing closed")


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


# ---- Tripwire and git trust ----

BASELINE = "ai-guard-baseline"
GIT_CONFIG_MARK = ".git config (unreadable include or hooksPath value)"
GIT_STATE_MARK = ".git config/hooks (differ from the baseline, or no baseline)"
REBASELINE_MSG = ("git config or hooks differ from the baseline a human recorded, or there is none. A human must review "
                  ".git/config, its includes and the hooks, then run in a terminal: python3 tools/guard/guard.py --rebaseline")
# Keys that git itself rewrites when a remote is added or an upstream is set; everything else in the config is hashed.
CONFIG_IGNORED = {"remote": {"url", "pushurl", "fetch"}, "branch": {"remote", "merge", "rebase"}}
SECTION_LINE = re.compile(r'\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\]\s*([#;].*)?$')
KEY_LINE = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*(?:=(.*))?$", re.S)
MAX_INCLUDE_DEPTH = 10
UNSAFE_PATH_VALUE = re.compile(r'["\\#;]')


class ConfigDoubt(ValueError):
    """A config line the guard cannot read the way git does."""


CONFIG_MSG = ("an include.path, includeIf path or core.hooksPath in the git config uses quotes, backslashes or comments, "
              "which the guard cannot read the way git does. A human must simplify that line, then run in a terminal: "
              "python3 tools/guard/guard.py --rebaseline")


def git_dirs(root):
    """(gitdir, commondir) of the work tree at root, read from .git without running git. Raises OSError."""
    dot = os.path.join(root, ".git")
    if os.path.isdir(dot):
        gitdir = dot
    else:
        with open(dot, encoding="utf-8") as f:  # a linked worktree: ".git" is a file
            first = f.readline().strip()
        if not first.startswith("gitdir:"):
            raise OSError("unrecognised .git file")
        gitdir = os.path.realpath(os.path.join(root, first[len("gitdir:"):].strip()))
        if not os.path.isdir(gitdir):
            raise OSError("gitdir is not a directory")
    try:
        with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as f:
            common = os.path.realpath(os.path.join(gitdir, f.read().strip()))
    except FileNotFoundError:
        common = gitdir
    return gitdir, common


def config_entries(path):
    """(section, subsection, key, value) for every key line of a git config file. ValueError when a line is doubtful."""
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        raw = f.read().split("\n")
    out, section, sub, i = [], None, "", 0
    while i < len(raw):
        line = raw[i].rstrip("\r")
        i += 1
        while (len(line) - len(line.rstrip("\\"))) & 1 and i < len(raw):  # an odd run of backslashes continues the line
            line = line[:-1] + raw[i].rstrip("\r")
            i += 1
        line = line.strip()
        if not line or line[0] in "#;":
            continue
        m = SECTION_LINE.match(line)
        if m:
            section, sub = m.group(1).lower(), m.group(2) or ""
            if m.group(2) is None and "." in section:  # the old [section.subsection] spelling
                section, sub = section.split(".", 1)
            continue
        m = KEY_LINE.match(line)
        if not m or section is None:
            raise ValueError(f"cannot parse {path}: {line!r}")
        out.append((section, sub, m.group(1).lower(), (m.group(2) or "").strip()))
    return out


def git_state_digest(root):
    """(digest, gitdir): SHA-256 over the common .git/config, the files it includes, every hooks file (default dir and
    core.hooksPath) and the .git pointer of a linked worktree. Raises OSError or ValueError when it cannot be computed."""
    gitdir, common = git_dirs(root)
    h = hashlib.sha256()

    def feed(tag, data):
        h.update(tag.encode("utf-8", "surrogateescape") + b"\0" + hashlib.sha256(data).digest())

    hook_dirs = [os.path.join(common, "hooks")]

    def scan(path, depth):
        if depth > MAX_INCLUDE_DEPTH:
            raise ValueError("config includes nested too deeply")
        for section, sub, key, value in config_entries(path):
            if key in CONFIG_IGNORED.get(section, ()):
                continue
            feed("cfg", "\0".join((section, sub, key, value)).encode("utf-8", "surrogateescape"))
            is_include = key == "path" and section in ("include", "includeif")
            if (is_include or (section == "core" and key == "hookspath")) and UNSAFE_PATH_VALUE.search(value):
                raise ConfigDoubt(f"{section}.{key} value {value!r}")  # git strips quotes and comments anywhere in the value
            if is_include:
                target = os.path.expanduser(value.strip('"'))
                target = os.path.normpath(os.path.join(os.path.dirname(path), target))
                if os.path.isfile(target):
                    with open(target, "rb") as f:
                        feed("include " + value, f.read())
                    scan(target, depth + 1)
                else:
                    feed("include " + value, b"missing")
            elif section == "core" and key == "hookspath":
                hook_dirs.append(os.path.normpath(os.path.join(root, os.path.expanduser(value.strip('"')))))

    scan(os.path.join(common, "config"), 0)
    if os.path.isfile(os.path.join(root, ".git")):
        with open(os.path.join(root, ".git"), "rb") as f:
            feed("gitfile", f.read())
    for n, hooks in enumerate(hook_dirs):  # the dirs are named by position: absolute paths differ between symlinked spellings
        feed(f"hooks-dir {n}", b"")
        if not os.path.isdir(hooks):
            continue  # a missing hooks directory counts as empty
        for base, dirs, names in os.walk(hooks, onerror=lambda e: (_ for _ in ()).throw(e)):
            dirs.sort()
            for name in sorted(names):
                path = os.path.join(base, name)
                with open(path, "rb") as f:
                    feed("hook " + os.path.relpath(path, hooks).replace("\\", "/"), f.read())
    return h.hexdigest(), gitdir


def git_state_problem(root):
    """None when the git config and hooks match the recorded baseline, else "unverifiable" or "baseline"."""
    try:
        digest, gitdir = git_state_digest(root)
    except ConfigDoubt:
        return "config"
    except (OSError, ValueError):
        return "unverifiable"
    try:
        with open(os.path.join(gitdir, BASELINE), encoding="ascii") as f:
            recorded = f.read().strip()
    except (OSError, ValueError):
        return "baseline"
    return None if recorded == digest else "baseline"


def git_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git_timeout():
    """At most GIT_TIMEOUT, and never past the deadline. A timeout raises, which callers treat as unverifiable."""
    return max(0.1, min(GIT_TIMEOUT, DEADLINE[0] - time.monotonic()))


def run_git(root, *args):
    cmd = ["git", "-C", root, "-c", "core.fsmonitor=false"] + list(args)
    return subprocess.run(cmd, capture_output=True, timeout=git_timeout(), stdin=subprocess.DEVNULL, env=git_env())


def tripwire_dirty(root, paths):
    """Files that differ from HEAD (or from the .git baseline), [] when clean, None when that cannot be verified."""
    problem = git_state_problem(root)
    if problem == "unverifiable":
        return None
    if problem == "config":
        return [GIT_CONFIG_MARK]
    if problem:
        # Not asking git: a planted core.fsmonitor in .git/config runs code on `git status`.
        return [GIT_STATE_MARK]
    try:
        p = run_git(root, "status", "--porcelain", "--untracked-files=all", "--no-renames", "--", *paths)
        if p.returncode != 0:
            return None
        dirty = [line[3:] for line in p.stdout.decode("utf-8", "replace").splitlines() if len(line) > 3]
        # skip-worktree and assume-unchanged hide edits from `git status`
        q = run_git(root, "ls-files", "-v", "--", *paths)
    except (OSError, subprocess.SubprocessError):
        return None
    if q.returncode != 0:
        return None
    for line in q.stdout.decode("utf-8", "replace").splitlines():
        if line[:1] and (line[0].islower() or line[0] == "S"):
            dirty.append(f"{line[2:]} (skip-worktree or assume-unchanged)")
    return dirty


def tripwire_reason(root, policy):
    """None when the guard's files are clean, else the message that blocks writes and non-read-only Bash."""
    dirty = tripwire_dirty(root, policy["tripwire_paths"])
    if dirty is None:
        return "cannot verify guard files (not a git checkout?); commit or revert them to continue."
    if dirty == [GIT_CONFIG_MARK]:
        return CONFIG_MSG
    if dirty == [GIT_STATE_MARK]:
        return REBASELINE_MSG
    if dirty:
        return f"guard files changed since the last commit: {', '.join(dirty)}; commit or revert them to continue."
    return None


def git_block_reason(root, segments):
    """Reason to refuse a Bash command that runs git while the git config or hooks cannot be trusted, else None.
    Even read-only git runs whatever core.fsmonitor or a hook names. segments is main()'s non-strict parse."""
    if not any(command_base(command_words(seg)) == "git" for seg in segments):
        return None
    problem = git_state_problem(root)
    if problem == "unverifiable":
        return "cannot verify .git (not a git checkout?), so git is not run from here."
    if problem == "config":
        return "git is blocked: " + CONFIG_MSG
    if problem:
        return "git is blocked: " + REBASELINE_MSG
    return None


def guard_token_reason(segments):
    """Reason when a parsed (unquoted) word names guard.py or is --rebaseline, else None. Backs up the blocked_commands
    regexes, which see the raw text: guard''.py and --rebasel''ine slip past them. segments is main()'s non-strict
    parse, so a "$" elsewhere on the line cannot hide the words."""
    for seg in segments:
        for word in command_words(seg):
            if word == "--rebaseline" or command_base([word]) == "guard.py":
                return "the guard's own script and --rebaseline are for a human at a terminal. Write numbered steps for a human to run instead."
    return None


def write_baseline(root):
    digest, gitdir = git_state_digest(root)
    with open(os.path.join(gitdir, BASELINE), "w", encoding="ascii") as f:
        f.write(digest + "\n")


def rebaseline(start):
    """Human-run: record the current git config and hooks as the baseline. Needs a terminal, so the hook cannot reach it."""
    try:
        interactive = sys.stdin.isatty()
    except (OSError, ValueError):
        interactive = False
    if not interactive:
        block("--rebaseline must be run by a human in a terminal, not through a hook or a script.")
    try:
        p = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, timeout=GIT_TIMEOUT,
                           stdin=subprocess.DEVNULL, env=git_env())
        if p.returncode != 0 or not p.stdout.strip():
            block(f"--rebaseline: {start} is not inside a git work tree.")
        write_baseline(os.path.realpath(p.stdout.decode("utf-8", "surrogateescape").strip()))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        block(f"--rebaseline failed: {e}")
    sys.stdout.write(f"baseline recorded in the git directory ({BASELINE})\n")
    sys.exit(0)


# ---- Write paths ----

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


# ---- Bash parsing ----

SEPARATORS = {";", "&&", "||", "|", "&"}
REDIRECT_OP = re.compile(r"&>>?|[<>]+&?|>\|")
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


# Unquoted glob characters are swapped for private-use marks before parsing, so a parsed word still says whether
# its "*", "?" or "[" is one the shell expands ("'*'" and "\*" are literal).
GLOB_MARKS = {"*": "", "?": "", "[": ""}
UNMARK = str.maketrans({v: k for k, v in GLOB_MARKS.items()})


def mark_globs(cmd):
    masked = mask_quotes(cmd)  # same length as cmd; an unquoted character is unchanged
    return "".join(GLOB_MARKS.get(c, c) if m == c else c for c, m in zip(cmd, masked))


def is_glob_word(word):
    return any(m in word for m in GLOB_MARKS.values())


def glob_pattern(word):
    """A marked word as a Python glob pattern: quoted glob characters escaped, bash's "[^" spelled "[!"."""
    out = []
    for i, c in enumerate(word):
        if c == GLOB_MARKS["["] and word[i + 1 : i + 2] == "^":
            out.append("[!")
        elif c in GLOB_MARKS.values():
            out.append(c.translate(UNMARK))
        elif c in "*?[":
            out.append(f"[{c}]")
        elif c == "^" and i and word[i - 1] == GLOB_MARKS["["]:
            continue  # already written as "!"
        else:
            out.append(c)
    return "".join(out)


GLOB_WORD_LIMIT = 64  # unquoted glob words per command; more is not worth the time it takes to check
GLOBBED = {}  # pattern -> matches, so a pattern named twice is scanned once


def glob_scan(pattern):
    """What glob.glob(pattern) matches, reading the directories here so every entry scanned (not only each match)
    is charged to this call's budget and the deadline is checked as it goes. None once the budget is spent."""
    if pattern in GLOBBED:
        return GLOBBED[pattern]
    if not glob.has_magic(pattern):
        return [pattern] if os.path.lexists(pattern) else []
    dirname, base = os.path.split(pattern)
    parents = glob_scan(dirname) if dirname != pattern and glob.has_magic(dirname) else [dirname]
    if parents is None:
        return None
    out = []
    for d in parents:
        if not glob.has_magic(base):
            if not spend(1):
                return None
            if os.path.lexists(os.path.join(d, base)) if base else os.path.isdir(d):
                out.append(os.path.join(d, base))
            continue
        try:
            with os.scandir(d or os.curdir) as entries:
                for entry in entries:
                    if not spend(1):
                        return None
                    if BUDGET[0] % 256 == 0:
                        check_deadline()
                    # As glob (and bash without dotglob): a leading "." is matched only by a pattern that starts with one.
                    if (entry.name[:1] != "." or base[:1] == ".") and fnmatch.fnmatch(entry.name, base):
                        out.append(os.path.join(d, entry.name))
        except OSError:
            continue  # not a directory, or unreadable: glob skips it too
    GLOBBED[pattern] = out
    return out


def glob_reason(marked, cwd):
    """None unless an unquoted glob word could expand to an option: it starts with "-", it comes after a cd, it holds
    an expansion, or it matches a name starting with "-" in the working directory. Applies in every mode."""
    count = sum(is_glob_word(word) for seg in marked for word in seg)
    if count > GLOB_WORD_LIMIT:
        return f"too many glob patterns ({count}, at most {GLOB_WORD_LIMIT}) to check in time; run it as a human."
    after_cd, done = False, set()
    for seg in marked:
        for word in seg:
            if not is_glob_word(word):
                continue
            check_deadline()
            plain = word.translate(UNMARK)
            if plain.startswith("-"):
                return f"the unquoted glob {plain!r} starts with '-' and the shell could turn it into an option; quote it."
            if after_cd or cwd is None:
                return f"the unquoted glob {plain!r} expands in a directory the guard cannot see (after a cd); quote it or drop the cd."
            if any(c in plain for c in "${}`") or plain.startswith("~"):
                return f"the unquoted glob {plain!r} holds an expansion, so the guard cannot tell what it matches; quote it."
            if word in done:
                continue  # the same word in the same directory matches the same names
            done.add(word)
            matches = glob_scan(os.path.join(glob.escape(cwd), glob_pattern(word)))
            if matches is None:
                return f"the unquoted glob {plain!r} matches too many names to check; narrow it."
            for match in matches:
                if os.path.basename(match).startswith("-"):
                    return (f"the unquoted glob {plain!r} matches {os.path.basename(match)!r}, which the shell would pass "
                            "as an option; quote the glob or rename the file.")
        after_cd = after_cd or command_base(command_words([w.translate(UNMARK) for w in seg])) in CD_COMMANDS
    return None


HEREDOC = re.compile(r"(?<!<)<<(?!<)")  # "<<" and "<<-", not the here-string "<<<"
BRACKET_CLASS = re.compile(r"\[[:=.]")  # "[[:punct:]]", "[[=a=]]", "[[.a.]]": Python's glob reads none of them as bash does


def has_expansion(cmd):
    """True when the shell would expand cmd in a way token inspection cannot see: any unquoted or double-quoted "$",
    any unquoted brace (nested braces defeat pattern matching, so no brace form is tried), or an unquoted bracket
    expression holding a class, an equivalence class or a collating symbol."""
    masked = mask_quotes(cmd)
    return any(c in masked for c in "${}") or bool(BRACKET_CLASS.search(masked))


def mark_fds(line):
    """Prefix FD_MARK to digits glued to a following redirect operator ("2>" yes, "2 >" no)."""
    masked = mask_quotes(line)
    starts = [m.start() for m in re.finditer(r"(?<![^\s;&|()])\d+(?=[<>])", masked)]
    for s in reversed(starts):
        line = line[:s] + FD_MARK + line[s:]
    return line


def has_substitution(cmd):
    """True when cmd holds command or process substitution outside single quotes: "$(", a backtick, or an unquoted "<(" / ">("."""
    q, i = None, 0
    while i < len(cmd):
        c, nxt = cmd[i], cmd[i + 1 : i + 2]
        if q == "'":
            q = None if c == "'" else q
        elif c == "\\":
            i += 1
        elif c == "`" or (c == "$" and nxt == "("):
            return True
        elif q == '"':
            q = None if c == '"' else q
        elif c in "'\"":
            q = c
        elif c in "<>" and nxt == "(":
            return True
        i += 1
    return False


def parse_bash(cmd, strict=True):
    """Split a command line into segments of shell words, or None when it cannot be read safely.

    None means block: unbalanced quotes, substitution, process substitution, subshells and any
    operator other than the plain separators and redirects. strict (advise) also refuses every
    "$" and brace; otherwise they pass here and main() blocks them with its expansion rule.
    """
    if FD_MARK in cmd:
        return None
    if strict and ("$(" in cmd or "`" in cmd or "<(" in cmd or has_expansion(cmd)):
        return None
    if not strict and has_substitution(cmd):
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
            elif tok and all(c in "();<>|&" for c in tok) and not REDIRECT_OP.fullmatch(tok):  # "" is an empty quoted word
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


SCRIPT_ROOTS = ("tools/", "framework/", "fixtures/", "demo/", "ai-context/")


def cwd_bound_reason(segments, root, cwd):
    """None unless a script or pnpm segment runs from elsewhere than the project root.

    Scripts are named relative to the working directory, so a cd (or a payload cwd) into ai-context/ can make
    "tools/index/query.py" resolve to a script the assistant wrote. The script must also resolve, symlinks
    included, under one of SCRIPT_ROOTS.
    """
    after_cd = False
    for seg in segments:
        words = segment_command(seg)
        base = command_base(words)
        if PYTHON.fullmatch(base) or base == "pnpm" or sf_words(seg):
            if cwd != root or after_cd:
                return "scripts, pnpm and the Salesforce CLI run only from the project root, with no cd before them."
            script = next((a for a in words[1:] if not a.startswith("-")), None) if PYTHON.fullmatch(base) else None
            if PYTHON.fullmatch(base) and not ((rel := rel_path(root, script or "")) and rel.startswith(SCRIPT_ROOTS)):
                return f"the script must resolve under {SCRIPT_ROOTS}."
        after_cd = after_cd or command_base(command_words(seg)) in CD_COMMANDS
    return None


def advise_block_reason(cmd, patterns, root=None, cwd=None):
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
    return cwd_bound_reason(segments, root, cwd)


# ---- Bash writers ----

UNKNOWN_WRITE_MSG = "cannot determine what this command writes; run it as a human"
SHELL_KEYWORDS = {"if", "then", "else", "elif", "while", "until", "do", "!", "{", "time"}
CD_COMMANDS = {"cd", "pushd", "popd"}
GLOB_CHARS = re.compile(r"[*?\[]")
PYTHON = re.compile(r"python[0-9.]*|py")
CHMOD_MODE = re.compile(r"[0-7]{3,4}|[ugoa]*[-+=][rwxXst]*(,[ugoa]*[-+=][rwxXst]*)*")
WALK_LIMIT = 20000  # entries one guard call may enumerate (walks and glob matches) before it calls the command unknown
BUDGET = [WALK_LIMIT]  # reset at the start of main()
WALKED = {}  # path -> entries below it, so a tree named twice is walked once
MODELLED = {"cp", "mv", "install", "rm", "rmdir", "mkdir", "touch", "truncate", "chmod", "chown", "chgrp", "dd", "tee", "sed",
            "find", "sort", "uniq", "git", "sf"}
# Per command: single-dash flags that take no value, and single-dash options that take the next word.
# Anything else is an option we do not model, and an unmodelled option can change which files are written.
SHORT_OPTS = {
    "rm": ("rRfivId", ""), "rmdir": ("v", ""), "mkdir": ("pv", "m"), "touch": ("acmh", "dtr"), "truncate": ("co", "sr"),
    "chmod": ("Rvcf", ""), "chown": ("RvcfhHLP", ""), "chgrp": ("RvcfhHLP", ""), "tee": ("aip", ""),
    "cp": ("RrafipvnuLPHxdTbZ", "St"), "mv": ("fivnuTbZ", "St"), "install": ("bCcdDpsTvZ", "mogSt"),
}
# Long options are matched exactly: GNU accepts any unambiguous prefix ("--t=" is --target-directory).
LONG_NOARG = {
    "--force", "--verbose", "--recursive", "--archive", "--interactive", "--no-clobber", "--no-dereference",
    "--dereference", "--remove-destination", "--attributes-only", "--no-target-directory", "--one-file-system",
    "--changes", "--silent", "--quiet", "--preserve-root", "--no-preserve-root", "--dir", "--directory",
    "--compare", "--debug", "--append", "--ignore-interrupts", "--no-create",
}
LONG_OPTARG = {"--preserve", "--backup", "--update", "--output-error", "--reflink"}  # take a value only after "="
SED_LONG = {"--quiet", "--silent", "--regexp-extended", "--separate", "--null-data", "--posix", "--unbuffered",
            "--follow-symlinks", "--debug"}
SED_FLAGS = "nErsuz"


def shell_glob(word, cwd):
    """Absolute matches of a glob word, or the word itself when nothing matches (as the shell leaves it). None once
    the budget is spent."""
    if not GLOB_CHARS.search(word):
        return [word]
    matches = glob_scan(os.path.join(cwd, word))
    return None if matches is None else sorted(matches) or [word]


def spend(n):
    """Take n entries from this call's budget; False once it is spent."""
    BUDGET[0] -= n
    return BUDGET[0] >= 0


def walk_paths(path):
    """Every file and directory below path, or None once this call's budget is spent."""
    if path in WALKED:
        return WALKED[path]
    out = []
    for dirpath, dirs, files in os.walk(path):
        check_deadline()
        if not spend(len(dirs) + len(files)):
            return None
        out += [os.path.join(dirpath, name) for name in dirs + files]
    WALKED[path] = out
    return out


def parse_args(base, args):
    """(operands, options) for a modelled command, or None when it uses an option we do not model.

    Options may sit anywhere among the operands. options maps a short letter or long name to its value;
    -t and --target-directory are both stored as "t".
    """
    flags, values = SHORT_OPTS[base]
    ops, opts, i, done = [], {}, 0, False
    while i < len(args):
        a = args[i]
        i += 1
        if done or a == "-" or not a.startswith("-"):
            ops.append(a)
        elif a == "--":
            done = True
        elif a.startswith("--"):
            name, eq, val = a.partition("=")
            if name == "--target-directory" and base in ("cp", "mv", "install"):
                if not eq:
                    if i >= len(args):
                        return None
                    val, i = args[i], i + 1
                opts["t"] = val
            elif name in LONG_NOARG and not eq:
                opts[name] = True
            elif name in LONG_OPTARG:
                opts[name] = val or True
            else:
                return None
        elif len(a) == 2 and a[1] in values:
            if i >= len(args):
                return None
            opts[a[1]], i = args[i], i + 1
        elif all(c in flags for c in a[1:]):
            opts.update({c: True for c in a[1:]})
        else:
            return None
    return ops, opts


def sed_script_safe(s):
    """False if a sed script holds a w, W or e command or flag (they write files or run programs), or anything unreadable."""
    n = len(s)

    def delimited(i):  # s[i] is a delimiter: index just past its closing mate, or -1
        d, i = s[i], i + 1
        while i < n:
            if s[i] == "\\":
                i += 2
            elif s[i] == d:
                return i + 1
            else:
                i += 1
        return -1

    def to(i, stops):
        while i < n and s[i] not in stops:
            i += 1
        return i

    i = 0
    while i < n:
        c = s[i]
        if c in " \t\n;{}!,+~$" or c.isdigit():
            i += 1
        elif c == "#":
            i = to(i, "\n")
        elif c in "/\\":
            i = delimited(i + 1 if c == "\\" else i) if i + 1 < n else -1
            while 0 <= i < n and s[i] in "IM":
                i += 1
            if i < 0:
                return False
        elif c in "sy":
            j = delimited(i + 1) if i + 1 < n else -1
            j = delimited(j - 1) if j > 0 else -1
            if j < 0:
                return False
            i = j
            while i < n and s[i] not in " \t\n;}#":
                if not (s[i] in "gpiImM" or s[i].isdigit()):
                    return False  # s flags w and e land here
                i += 1
        elif c in "aicrR":
            i = to(i, "\n")
        elif c in ":btT":
            end = to(i, ";\n")
            if re.search(r"\s", s[i + 1 : end].strip()):
                return False  # GNU ends a label at whitespace and reads the rest as the next command
            i = end
        elif c in "pdDgGhHxnNlLq=QzF":
            i += 1
        else:
            return False
    return True


def sed_targets(args):
    """Files sed edits in place, or None when its options or script are not safe to read.

    The backup (file + suffix) is a write too; a suffix with "/" or "*" is unknown.
    A bare -i takes the next word as a BSD suffix only when it is empty or starts with ".": GNU would read
    anything else as the script, and a script starting with "." is invalid for both.
    """
    in_place, suffix, scripts, rest, i, done = False, "", [], [], 0, False
    while i < len(args):
        a = args[i]
        i += 1
        if done or a == "-" or not a.startswith("-"):
            rest.append(a)
        elif a == "--":
            done = True
        elif a.startswith("--"):
            name, eq, val = a.partition("=")
            if name == "--expression":
                if not eq:
                    if i >= len(args):
                        return None
                    val, i = args[i], i + 1
                scripts.append(val)
            elif name == "--in-place":
                in_place, suffix = True, val
            elif name not in SED_LONG or eq:
                return None
        else:
            j = 1
            while j < len(a):
                c = a[j]
                if c in SED_FLAGS:
                    j += 1
                elif c == "i":
                    in_place, suffix = True, a[j + 1 :]
                    if j + 1 == len(a) and i < len(args) and (args[i] == "" or args[i].startswith(".")):
                        suffix, i = args[i], i + 1
                    break
                elif c == "e":
                    val = a[j + 1 :]
                    if not val:
                        if i >= len(args):
                            return None
                        val, i = args[i], i + 1
                    scripts.append(val)
                    break
                else:
                    return None  # -f (script file), -l, and anything unmodelled
    if not scripts:
        if not rest:
            return None
        scripts, rest = rest[:1], rest[1:]
    if not all(sed_script_safe(s) for s in scripts):
        return None
    if not in_place:
        return []
    if "/" in suffix or "*" in suffix:
        return None  # GNU puts the backup wherever the suffix says, and "*" stands for the file name
    return rest + [f + suffix for f in rest] if suffix else rest


def command_words(seg):
    """The command and its arguments: no redirects and no leading shell keywords."""
    words, _ = split_redirects(seg)
    while words and words[0] in SHELL_KEYWORDS:
        words = words[1:]
    return words


def command_base(words):
    return words[0].replace("\\", "/").rsplit("/", 1)[-1].lower() if words else ""


def git_allowed(args, policy):
    """True for an allowlisted git subcommand that cannot write outside .git. -C, -c and every other global option are refused."""
    if args[:1] == ["--no-pager"]:
        args = args[1:]
    if not args or args[0] not in policy["git_allowed"]:
        return False
    sub, rest = args[0], args[1:]
    if sub == "branch":
        return rest == ["--show-current"]
    for a in rest:
        if a == "--":
            break
        name = a.partition("=")[0]
        # git accepts unambiguous prefixes, so "--out" is --output and "--amen" is --amend; "-O" runs a pager command.
        if name.startswith("--output") or (name.startswith("--") and len(name) >= 4 and "--output".startswith(name)):
            return False
        if sub == "commit" and len(name) >= 4 and "--amend".startswith(name):
            return False
        if name.startswith("-O") or name.startswith("--open-files"):
            return False
    return True


def copy_targets(base, ops, opts, cwd, walk=True):
    """Every path cp, mv or install writes: the destination, what lands inside it, and (when walk) each file below a tree."""
    if base == "install" and ("d" in opts or "--directory" in opts):
        return ops
    expanded = []
    for w in ops:
        matches = shell_glob(w, cwd)
        if matches is None:
            return None
        expanded += matches
    ops = expanded
    tdir = opts.get("t")
    if tdir is not None:
        dest, srcs, is_dir = tdir, ops, True
    elif len(ops) < 2:
        return ops
    else:
        dest, srcs = ops[-1], ops[:-1]
        is_dir = len(srcs) > 1 or dest.endswith("/") or os.path.isdir(os.path.join(cwd, dest))
    out = [os.path.join(dest, "") if is_dir else dest]
    recursive = walk and (base == "mv" or any(k in opts for k in ("r", "R", "a", "--recursive", "--archive")))
    for src in dict.fromkeys(srcs):
        name = os.path.basename(os.path.normpath(src))
        if name in ("", ".", ".."):
            name = os.path.basename(os.path.realpath(os.path.join(cwd, src)))
        top = os.path.join(dest, name) if is_dir else dest
        out.append(top)
        full = os.path.join(cwd, src)
        if base == "mv":
            out.append(src)  # the source is removed
        if recursive and os.path.isdir(full):
            below = walk_paths(full)
            if below is None:
                return None
            for p in below:
                out.append(os.path.join(top, os.path.relpath(p, full)))
                if base == "mv":
                    out.append(p)
    return out


TAR_LIST = re.compile(r"-t[vzjJaf]*")
# No leading "-" (an option), no ":" (host:file opens a remote shell), nothing the shell would rewrite.
TAR_OPERAND = re.compile(r"[A-Za-z0-9_./@%+=,][A-Za-z0-9_./@%+=,-]*")


def tar_list_only(args):
    """True for "tar -t[vzjJaf]* operand...": list mode with no option that runs a program (--to-command, --checkpoint-action, -I)."""
    return bool(args) and bool(TAR_LIST.fullmatch(args[0])) and all(TAR_OPERAND.fullmatch(a) for a in args[1:])


SF_DIR_FLAGS = ("--output-dir", "-d")
# -f and --file name an input on most commands; treating them as writes is conservative (an input under ai-context/ still passes).
SF_PATH_FLAGS = SF_DIR_FLAGS + ("--output-file", "--file", "-f")


def sf_targets(words):
    """Paths an sf command writes through its output and file flags, or None when they cannot be known.

    A generate or convert command writes into --output-dir/-d; without one the CLI picks a default
    under the current directory, so that counts as unknown. So does a code-analyzer config file.
    """
    args, writes = words[1:], any(w in ("generate", "convert") for w in words[1:4])
    analyzer = words[1:3] == ["code-analyzer", "run"]
    out, has_dir, i = [], False, 0
    while i < len(args):
        a = args[i]
        i += 1
        name, eq, val = a.partition("=")
        if analyzer and (name == "--config-file" or (a[:1] == "-" and a[:2] == "-c")):
            return None
        if name in SF_PATH_FLAGS:
            if not eq:
                if i >= len(args):
                    return None
                val, i = args[i], i + 1
            out.append(val)
            has_dir = has_dir or name in SF_DIR_FLAGS
        elif a[:1] == "-" and a[:2] in ("-d", "-f"):
            out.append(a[2:].lstrip("="))  # -dVALUE and -fVALUE
            has_dir = has_dir or a[:2] == "-d"
        elif writes and name in ("-n", "--name"):
            if not eq:
                if i >= len(args):
                    return None
                val, i = args[i], i + 1
            # A name that is a path would move the generated files out of --output-dir.
            if "/" in val or "\\" in val or ".." in val:
                return None
    return None if writes and not has_dir else out


PNPM_WRITE_FLAGS = {"--write", "-w", "--fix"}
# Options that load code or config from a path we do not model.
PNPM_LOADERS = ("--config", "--plugin", "--rulesdir", "--resolve-plugins-relative-to")
PNPM_OUT_FLAGS = ("--output-file", "-o", "--cache-location")
JEST_TOOLS = ("jest", "sfdx-lwc-jest")
# yargs-parser rewrites flag names (case, kebab, "_", doubled dashes), so jest flags are an exact-spelling allowlist, not a denylist.
JEST_FLAGS = ("--coverage", "--ci", "--silent", "--verbose", "--json", "--runInBand", "--passWithNoTests", "--no-cache",
              "--bail", "--detectOpenHandles", "--colors", "-i", "-b", "-e")
JEST_VALUE_FLAGS = ("--maxWorkers", "--bail", "--testNamePattern", "-t", "-w")
JEST_PATH_FLAGS = ("--coverageDirectory", "--outputFile", "--cacheDirectory")


def jest_targets(opts):
    """Paths a jest or sfdx-lwc-jest run writes, or None when a flag is off the allowlist.

    Operands are test path patterns; running a test file the assistant wrote is an acknowledged limit.
    """
    out, i = [], 0
    while i < len(opts):
        a = opts[i]
        i += 1
        name, eq, val = a.partition("=")
        if a == "--" or not a.startswith("-"):
            continue
        if a in JEST_FLAGS:
            continue
        valued = name in JEST_VALUE_FLAGS or name in JEST_PATH_FLAGS
        if not valued or (eq and (not val or not name.startswith("--"))):
            return None
        if not eq:
            # A value never starts with "-": yargs would read that word as the next flag, so it is checked as one.
            if i >= len(opts) or opts[i].startswith("-"):
                return None
            val, i = opts[i], i + 1
        if name in JEST_PATH_FLAGS:
            out.append(val)
    return out


def pnpm_targets(args):
    """Paths "pnpm exec <tool>" or "pnpm test" writes, or None when unknown.

    With --write, -w or --fix (or --write=X) every non-option operand is a target (a directory recursively).
    A config or plugin option can run any code; -c is --check for prettier but --config elsewhere.
    jest and sfdx-lwc-jest go through jest_targets.
    What a package.json script does stays an acknowledged limit, but flags after "--" on "pnpm test" go to jest.
    """
    if any(any(c in a for c in "${}") or a.startswith("~") for a in args):
        return None
    if args[:1] == ["exec"] and len(args) > 1:
        tool, opts = args[1], args[2:]
    elif args[:1] in (["test"], ["run"]) and "test" in args[:2] and "--" in args:
        tool, opts = "jest", args[args.index("--") + 1:]
    else:
        return [], False
    if tool in JEST_TOOLS:
        found = jest_targets(opts)
        return None if found is None else (found, False)
    out, operands, write, i = [], [], False, 0
    while i < len(opts):
        a = opts[i]
        i += 1
        name, eq, val = a.partition("=")
        if a == "--":
            operands += opts[i:]
            break
        if name in PNPM_LOADERS or name.startswith("--plugin") or (a[:2] == "-c" and tool != "prettier"):
            return None
        if tool == "eslint" and (name == "--format" or a[:2] == "-f" and a[:3] != "--f"):
            fmt = val if eq else (a[2:] if a[:2] == "-f" and a != "-f" else (opts[i] if i < len(opts) else ""))
            if not eq and (a in ("-f", "--format")):
                i += 1
            if "/" in fmt or "\\" in fmt or fmt.endswith((".js", ".cjs", ".mjs")):
                return None
            continue
        if name in PNPM_OUT_FLAGS:
            if not eq:
                if i >= len(opts):
                    return None
                val, i = opts[i], i + 1
            out.append(val)
        elif name in PNPM_WRITE_FLAGS:
            write = True
            if eq:
                operands.append(val)
        elif not a.startswith("-"):
            operands.append(a)
    return (out + operands, True) if write else (out, False)


SCRIPT_FLAGS = {  # argparse options of the framework scripts that choose where they write: name -> takes a value
    "build_index.py": {"--root": True, "--out": True, "--version": False, "--help": False},
    "write_report.py": {"--id": True, "--slug": True, "--classified": True, "--root": True, "--help": False},
    "write_story.py": {"--id": True, "--slug": True, "--draft": True, "--root": True, "--help": False},
}
STORY_OUTPUTS = {  # files the --id/--slug writers put in ai-context/<--id>-<--slug>/
    "write_report.py": ("impact.json", "impact.md"),
    "write_story.py": ("story.json", "story.md"),
}


def script_flag_values(args, flags):
    """{option: [values]} for a script's argparse options, abbreviations included (argparse accepts any unique
    prefix), or None when a value is missing or the shell rewrites it. Other words make argparse exit before writing."""
    vals = {name: [] for name in flags}
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            break
        name, eq, val = a.partition("=")
        if not name.startswith("--"):
            continue
        hits = [f for f in flags if f.startswith(name)]
        if name in flags:
            hits = [name]
        if not any(flags[f] for f in hits):
            continue  # unknown or ambiguous: argparse exits; a no-value flag writes nothing
        if len(hits) > 1:
            return None
        if not eq:
            if i >= len(args):
                return None
            val, i = args[i], i + 1
        if any(c in val for c in "${}*?[") or val.startswith("~"):
            return None
        vals[hits[0]].append(val)
    return vals


def script_targets(script, args):
    """(paths a framework script writes through its flags, False), or None when unknown. Other scripts: ([], False).

    build_index.py writes <--root>/<--out>/{metadata,inventory}.json. write_report.py writes
    ai-context/<--id>-<--slug>/{impact.json,impact.md} under --root, and runs <--root>/tools/index/query.py, so a --root other
    than "." is unknown. write_story.py writes ai-context/<--id>-<--slug>/{story.json,story.md} under --root and
    reads the index and register from it; a --root other than "." is unknown for it too. query.py prints to
    stdout only.
    """
    name = script.replace("\\", "/").rsplit("/", 1)[-1]
    if name not in SCRIPT_FLAGS:
        return [], False
    vals = script_flag_values(args, SCRIPT_FLAGS[name])
    if vals is None:
        return None
    out = []
    if name == "build_index.py":
        for root in vals["--root"] or ["."]:
            for sub in vals["--out"] or ["index"]:
                d = os.path.join(root, sub)
                out += [os.path.join(d, ""), os.path.join(d, "metadata.json"), os.path.join(d, "inventory.json")]
        return out, False
    if any(os.path.normpath(r) != "." for r in vals["--root"]):
        return None
    if any("/" in v or "\\" in v or ".." in v for v in vals["--id"] + vals["--slug"]):
        return None
    for i in vals["--id"]:
        for s in vals["--slug"]:
            d = os.path.join("ai-context", f"{i}-{s}")
            out += [os.path.join(d, "")] + [os.path.join(d, f) for f in STORY_OUTPUTS[name]]
    return out, False


def command_targets(words, policy, cwd, walk=True):
    """(paths the command writes, whether directories among them are written recursively), or None when unknown.
    walk=False skips walking below directories: the lexical pass that runs before any walk."""
    name, args = words[0], words[1:]
    if any(c in name for c in "${}*?") or ("[" in name and name != "[") or name.startswith(("~", "=")) or name == "-":
        return None  # the shell decides which program runs
    base = command_base(words)
    if base == "tar" and tar_list_only(args):
        return [], False
    if base in policy["unknown_writers"]:
        return None
    if PYTHON.fullmatch(base):
        # Code on the command line, on stdin or in a module is invisible; a script file is Task 5's allowlist.
        i = 0
        while i < len(args):
            a = args[i]
            i += 1
            if a == "-" or (a.startswith("-") and not a.startswith("--") and ("c" in a or "m" in a)):
                return None
            if a in ("-W", "-X"):
                i += 1
            elif not a.startswith("-"):
                return script_targets(a, args[i:])
        return None
    if base == "pnpm":
        return pnpm_targets(args)
    if base not in MODELLED:
        return [], False
    # A word the shell rewrites can be an option or a path that we never see: the whole segment is unknown.
    # main() has already blocked every "$" and brace outside single quotes, so any left in a word are literal.
    for a in args:
        if a.startswith("~") or (GLOB_CHARS.search(a) and ".." in a.split("/")):
            return None
    if base == "sf":
        found = sf_targets(words)
        return None if found is None else (found, False)
    if base == "git":
        return ([], False) if git_allowed(args, policy) else None
    if base == "find":
        bad = ("-delete", "-exec", "-execdir", "-ok", "-okdir")
        return None if any(a in bad or a.startswith(("-fprint", "-fls")) for a in args) else ([], False)
    if base == "sort":
        return None if any(re.match(r"-[A-Za-z]*o|--o", a) for a in args) else ([], False)
    if base == "uniq":
        return None if len([a for a in args if not a.startswith("-")]) > 1 else ([], False)
    if base == "sed":
        found = sed_targets(args)
        return None if found is None else (found, False)
    if base == "dd":
        return [a[3:] for a in args if a.startswith("of=")], False
    parsed = parse_args(base, args)
    if parsed is None:
        return None
    ops, opts = parsed
    recursive = any(k in opts for k in ("r", "R", "--recursive"))
    if base in ("cp", "mv", "install"):
        found = copy_targets(base, ops, opts, cwd, walk)
        return None if found is None else (found, False)
    if base == "chmod":
        return (ops[1:] if ops and CHMOD_MODE.fullmatch(ops[0]) else ops), recursive
    if base in ("chown", "chgrp"):
        return ops[1:], recursive
    return ops, recursive  # rm, mkdir, touch, truncate, tee


def expand_targets(targets, recursive, cwd):
    """Absolute targets as written, plus what their globs match now and, if recursive, each file below a directory.

    None once the call's budget is spent. The unexpanded form is kept so the allowed-prefix check still sees the pattern.
    """
    out = []
    for t in dict.fromkeys(targets):
        full = os.path.join(cwd, t)
        out.append(full)
        matches = glob_scan(full) if GLOB_CHARS.search(t) else []
        if matches is None:
            return None
        matches = sorted(matches)
        out += matches
        if recursive:
            for p in matches or [full]:
                if os.path.isdir(p):
                    below = walk_paths(p)
                    if below is None:
                        return None
                    out += below
    return out


def write_targets(seg, policy, cwd, walk=True):
    """Absolute paths one segment writes to (globs expanded), or None when they cannot be known. walk=False: no walk."""
    words, redirects = split_redirects(seg)
    redirect_targets = []
    for op, target in redirects:
        if ">" not in op:
            continue  # input redirects and here-documents only read
        if target is None:
            return None
        if (op.endswith("&") and (target.isdigit() or target == "-")) or target == "/dev/null":
            continue
        # The shell rewrites these after we looked, so the real path is unknown.
        if any(c in target for c in "${}") or target.startswith("~") or (GLOB_CHARS.search(target) and ".." in target.split("/")):
            return None
        redirect_targets.append(target)
    words = command_words(seg)
    found = ([], False)
    if words:
        if ASSIGNMENT.match(words[0]):
            return None  # GIT_CONFIG_*, PYTHONPATH and friends change what the command does
        found = command_targets(words, policy, cwd, walk)
        if found is None:
            return None
    a = expand_targets(redirect_targets, False, cwd)
    b = expand_targets(found[0], found[1] and walk, cwd)
    return None if a is None or b is None else a + b


def protected_overlap(rel, policy):
    """The always-blocked path that rel is an ancestor of (or equal to), else None.

    write_block_reason only looks at prefixes, so "rm -r tools" or "mv ." would take tools/guard with them.
    """
    parts = [c for c in rel.lower().split("/") if c not in ("", ".")]
    for p in policy["always_blocked_writes"]:
        pparts = p.lower().strip("/").split("/")
        n = min(len(parts), len(pparts))
        if parts[:n] == pparts[:n]:
            return p
    return None


# ---- Salesforce CLI ----

UNPARSABLE_MSG = "the command cannot be parsed safely (unbalanced quote, substitution or subshell)."
HEREDOC_MSG = ("a heredoc (<<) is not allowed in any mode: the shell expands its body in ways the guard cannot see. "
               "Write the text to a file under ai-context/ and point the command at it.")
EXPANSION_MSG = ("the command holds a $, a brace or a [[:class:]] bracket outside single quotes, so the guard cannot see what "
                 "the shell expands it to. Quote that text in single quotes, or put it in a file (for a commit message: "
                 "git commit -F ai-context/<file>).")
SF_NAMES = {"sf", "sf.cmd", "sf.exe"}


def sf_words(seg):
    """The words of a segment that runs the Salesforce CLI (shell keywords and assignments before it skipped), else None."""
    words = command_words(seg)
    while words and ASSIGNMENT.match(words[0]):
        words = words[1:]
    return words if command_base(words) in SF_NAMES else None


SF_ORG_LONG = {"--target-org", "--targetdevhubusername", "--from-org", "--source-org", "--targetusername", "--target-dev-hub", "--target-dev-hub-username"}
SF_ORG_SHORT = ("-o", "-u", "-v")
SF_WORD = re.compile(r"[a-z][a-z0-9-]*")


def sf_org_values(words):
    """Every org named by an org flag, in the forms "-o X", "--target-org X", "--target-org=X", "-o=X" and "-oX".

    None stands for a flag with no value.
    """
    orgs = []
    for i, w in enumerate(words):
        name, eq, val = w.partition("=")
        if w in SF_ORG_LONG or w in SF_ORG_SHORT:
            orgs.append(words[i + 1] if i + 1 < len(words) else None)
        elif name in SF_ORG_LONG and eq:
            orgs.append(val)
        elif w[:2] in SF_ORG_SHORT:
            orgs.append(w[2:].lstrip("="))
    return orgs


def sf_help_only(words):
    """True for exactly "sf <plain words> -h" or "--help": no flag, no "--", no quoted word, so nothing else can run."""
    return len(words) >= 3 and words[-1] in ("-h", "--help") and all(re.fullmatch(r"[a-z][a-z-]*", w) for w in words[1:-1])


def sf_block_reason(words, mode, policy):
    """None if this Salesforce CLI command may run in this mode, else the reason. Write targets are checked separately."""
    sf = policy["sf"]
    if words[0] != "sf":
        return "run the Salesforce CLI as plain 'sf', not as a path or another spelling."
    text = " ".join(words)
    if any(re.fullmatch(p, text) for p in sf["always_blocked"]):
        return "this Salesforce CLI command is always blocked: it changes an org, a credential or org data. Hand it to a human."
    if any(w == "--flags-dir" or w.startswith("--flags-dir=") for w in words):
        return "this Salesforce CLI command is always blocked: --flags-dir reads flags from files the guard cannot see."
    for w in words[1:]:
        name = w.partition("=")[0]
        # Defence in depth: the CLI may accept an abbreviation or alias that we do not list ("--targe").
        bare = name.lstrip("-").lower()
        abbreviation = name.startswith("--") and len(bare) >= 2 and any(f[2:].startswith(bare) for f in SF_ORG_LONG)
        if (name.startswith("-") and name not in SF_ORG_LONG and name not in SF_ORG_SHORT
                and (abbreviation or any(k in bare for k in ("target", "org", "username")))):
            return f"flag {name!r} looks like an org flag but is not a known one; use --target-org with an alias in sf.allowed_orgs."
    # The words that name the command, up to the first flag. "topic:command" spellings and the force topic reach commands the patterns do not describe.
    named = []
    for w in words[1:]:
        if w.startswith("-"):
            break
        named.append(w)
    if any(not SF_WORD.fullmatch(w) for w in named) or named[:1] == ["force"]:
        return "Salesforce CLI command words must be plain lowercase words: no 'topic:command' spelling, no force topic, no quoted words."
    order = sf["level_order"]
    level = sf["mode_level"].get(mode)
    if level not in order:
        level = order[0]  # an unknown level or mode gets the lowest one
    hits = [lv for lv in order[: order.index(level) + 1] if any(re.fullmatch(p, text) for p in sf["levels"][lv])]
    if not hits and not (sf_help_only(words) and level != order[0]):
        return f"Salesforce CLI command not allowed at level {level} (tools/guard/policy.json sf.mode_level)"
    orgs = sf_org_values(words)
    if any(lv in sf["org_levels"] for lv in hits):
        if not orgs or any(o not in sf["allowed_orgs"] for o in orgs):
            return "org commands need --target-org with an alias listed in sf.allowed_orgs"
    elif orgs:
        return "org flags are only allowed on org-level commands, with an alias listed in sf.allowed_orgs"
    return None


# ---- Per-mode Bash checks ----

def allowlist_block_reason(segments, mode, policy, root, cwd):
    """None if every segment is on the mode's allowlist, else the reason. A segment that passed the sf checks counts as listed."""
    groups = policy["modes"].get(mode, {}).get("bash_allow")
    msg = f"command not on the {mode} allowlist (tools/guard/policy.json)"
    if groups is None:
        return msg
    patterns = [p for g in groups for p in policy["bash_groups"][g]]
    for seg in segments:
        words = sf_words(seg)
        if not (words and words[0] == "sf") and not segment_matches(seg, patterns):
            return msg
    return cwd_bound_reason(segments, root, cwd)


def bash_block_reason(segments, mode, policy, scope, root, cwd):
    """None if the command may run in this mode (not advise), else the reason: sf checks, then write targets, then the allowlist."""
    for seg in segments:
        words = sf_words(seg)
        if words and (reason := sf_block_reason(words, mode, policy)):
            return reason
    return bash_write_block_reason(segments, mode, policy, scope, root, cwd) or allowlist_block_reason(segments, mode, policy, root, cwd)


def target_block_reason(t, mode, policy, scope, root):
    rel = rel_path(root, t)
    if rel is None:
        return f"write to {t!r} is on a different drive from the repo."
    # A directory is written as a prefix of its contents, so "docs" must read as "docs/".
    reason = write_block_reason(rel + "/" if t.endswith("/") or os.path.isdir(t) else rel, mode, policy, scope)
    # A glob that matched nothing stays a pattern; only concrete paths can be ancestors.
    if reason is None and not GLOB_CHARS.search(rel) and (hit := protected_overlap(rel, policy)):
        reason = f"write to {rel!r} would take {hit!r} with it, which is never allowed. Guard, settings, CI and git internals change by human-applied patch."
    return reason


def bash_write_block_reason(segments, mode, policy, scope, root, cwd):
    """None if every write the command makes is allowed in this mode, else the reason. cwd is where Bash runs.

    Two passes over every segment: first the targets as written (and what their globs match), so an always-blocked
    target blocks before any time goes into walking; then what recursive commands reach below directories.
    Each target is checked once.
    """
    seen = set()
    for walk in (False, True):
        after_cd = False
        for seg in segments:
            targets = write_targets(seg, policy, cwd, walk)
            # After a cd the targets no longer resolve against cwd.
            if targets is None or (after_cd and targets):
                return UNKNOWN_WRITE_MSG
            for t in targets:
                if t in seen:
                    continue
                seen.add(t)
                if len(seen) % 1000 == 0:
                    check_deadline()
                reason = target_block_reason(t, mode, policy, scope, root)
                if reason:
                    return reason
            after_cd = after_cd or command_base(command_words(seg)) in CD_COMMANDS
    return None


GIT_COMMIT = re.compile(r"(?<![\w./-])git\s+commit\b")
COMMIT_ADVICE = (" A commit message with $, braces or a substitution cannot be checked: write it to a file under ai-context/ "
                 "and run git commit -F ai-context/<file>.")


def with_commit_advice(reason, cmd, mode, policy):
    """reason, plus the -F advice when the line runs git commit with $, braces or backticks and the mode allows commits."""
    patterns = [p for g in policy["modes"].get(mode, {}).get("bash_allow", []) for p in policy["bash_groups"][g]]
    if GIT_COMMIT.search(cmd) and any(c in cmd for c in "${}`") and segment_matches(["git", "commit", "-F", "x"], patterns):
        return reason.rstrip(".") + "." + COMMIT_ADVICE
    return reason


# ---- Main ----

def main():
    DEADLINE[0] = time.monotonic() + DEADLINE_SECONDS
    BUDGET[0] = WALK_LIMIT
    WALKED.clear()
    GLOBBED.clear()
    policy = load_policy(POLICY_PATH)
    if len(sys.argv) > 1:
        if sys.argv[1:] != ["--rebaseline"]:
            block("unknown arguments; the only one is --rebaseline.")
        rebaseline(project_dir())
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
        if any(m in cmd for m in GLOB_MARKS.values()):
            block(UNPARSABLE_MSG)  # the glob marks would be read as unquoted glob characters
        # One non-strict parse serves every check that needs words ("$" and braces pass it; the expansion rule below blocks them).
        marked = parse_bash(mark_globs(cmd), strict=False)
        if marked is None:
            block(with_commit_advice(UNPARSABLE_MSG, cmd, mode, policy))
        segments = [[w.translate(UNMARK) for w in seg] for seg in marked]
        reason = guard_token_reason(segments) or git_block_reason(root, segments)
        if reason:
            block(reason)
        # Every mode: an expansion can turn into an option or a path the guard never sees ("--o${U}ut", "{--out,x}").
        if has_expansion(cmd):
            block(EXPANSION_MSG)
        # In a heredoc body "'" is an ordinary character, so the masker would hide a "$(...)" that the shell runs.
        if HEREDOC.search(mask_quotes(cmd)):
            block(HEREDOC_MSG)
        # Claude Code keeps the shell's cwd between calls; the hook payload says where it is now.
        cwd = payload.get("cwd")
        cwd = root if cwd is None else (os.path.realpath(cwd) if isinstance(cwd, str) else None)
        reason = glob_reason(marked, cwd)
        if reason:
            block(reason)
        if advise_block_reason(cmd, policy["bash_groups"]["read_only"], root, cwd):
            check_deadline()
            reason = tripwire_reason(root, policy)
            if reason:
                block(reason)
        if mode == "advise":
            patterns = [p for g in policy["modes"]["advise"]["bash_allow"] for p in policy["bash_groups"][g]]
            reason = advise_block_reason(cmd, patterns, root, cwd)
            if reason:
                block(f"framework is in ADVISE mode: {reason} Output recommendations, do not act.")
        else:
            if cwd is None:
                block("hook input has a non-string cwd; failing closed")
            if cwd != root and not cwd.startswith(root + os.sep):
                block(f"the shell's working directory {cwd!r} is outside the project; run it as a human.")
            reason = bash_block_reason(segments, mode, policy, active_scope(root), root, cwd)
            if reason:
                block(with_commit_advice(reason, cmd, mode, policy) if reason == UNKNOWN_WRITE_MSG else reason)

    elif isinstance(inp, dict) and "command" in inp:
        # Before read_only and MCP names: an unmodelled shell (a PowerShell or Monitor tool, an MCP shell) would skip
        # every Bash rule, whatever its name says.
        block(f"tool {tool!r} runs a command the guard does not model, in any mode. Use Bash, or hand it to a human.")

    elif tool in WRITE_TOOLS:
        # NotebookEdit names its file notebook_path; every path field present is checked.
        paths = [p.replace("\\", "/") for p in (inp.get("file_path"), inp.get("notebook_path"), inp.get("path")) if p] or [""]
        rels = [rel_path(root, path) for path in paths]
        for path, rel in zip(paths, rels):
            if rel is None:
                block(f"write to {path!r} is on a different drive from the repo.")
        reason = tripwire_reason(root, policy)
        if reason:
            block(reason)
        for rel in rels:
            reason = write_block_reason(rel, mode, policy, active_scope(root))
            if reason:
                block(reason)

    elif tool == "WebFetch":
        url = inp.get("url", "")
        try:
            host = (urllib.parse.urlsplit(url).hostname or "").lower()
        except ValueError:
            host = ""
        if not host:
            block(f"fetch URL {url!r} has no host; failing closed.")
        allowlist = policy["fetch_allowlist"]
        if not any(host == h or host.endswith("." + h) for h in allowlist):
            block(f"fetch to {host!r} is not on the allowlist {tuple(allowlist)}.")

    elif tool in policy["tools"]["read_only"]:
        pass  # no path or command effect

    elif tool.startswith("mcp__"):
        if mode == "advise":
            block(f"framework is in ADVISE mode: MCP tool {tool!r} is not allowed. Output recommendations, do not act.")
        # Whole name segments ("_", "-" or camelCase), so get_dataset and settings do not read as "set".
        parts = re.split(r"[_-]+|(?<=[a-z0-9])(?=[A-Z])", tool.rsplit("__", 1)[-1])
        if any(re.fullmatch(policy["tools"]["mcp_write_pattern"], seg) for seg in parts):
            block(f"MCP tool {tool!r} looks like it writes or acts (tools.mcp_write_pattern in tools/guard/policy.json). "
                  "Hand the action to a human.")

    elif mode == "advise":
        block(f"framework is in ADVISE mode: tool {tool!r} is not on tools.read_only. Output recommendations, do not act.")

    check_deadline()
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        block("internal error; failing closed")
