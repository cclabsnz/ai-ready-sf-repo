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
import glob
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
    "$" and brace; otherwise they pass and write_targets judges the words that name a path.
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


UNKNOWN_WRITE_MSG = "cannot determine what this command writes; run it as a human"
SHELL_KEYWORDS = {"if", "then", "else", "elif", "while", "until", "do", "!", "{", "time"}
CD_COMMANDS = {"cd", "pushd", "popd"}
GLOB_CHARS = re.compile(r"[*?\[]")
PYTHON = re.compile(r"python[0-9.]*|py")
CHMOD_MODE = re.compile(r"[0-7]{3,4}|[ugoa]*[-+=][rwxXst]*(,[ugoa]*[-+=][rwxXst]*)*")
WALK_LIMIT = 20000  # entries a recursive command may be expanded to before we give up and call it unknown
MODELLED = {"cp", "mv", "install", "rm", "mkdir", "touch", "truncate", "chmod", "chown", "chgrp", "dd", "tee", "sed",
            "find", "sort", "uniq", "git"}
# Per command: single-dash flags that take no value, and single-dash options that take the next word.
# Anything else is an option we do not model, and an unmodelled option can change which files are written.
SHORT_OPTS = {
    "rm": ("rRfivId", ""), "mkdir": ("pv", "m"), "touch": ("acmh", "dtr"), "truncate": ("co", "sr"),
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
    """Absolute matches of a glob word, or the word itself when nothing matches (as the shell leaves it)."""
    if not GLOB_CHARS.search(word):
        return [word]
    return sorted(glob.glob(os.path.join(cwd, word))) or [word]


def walk_paths(path):
    """Every file and directory below path, or None past WALK_LIMIT."""
    out = []
    for dirpath, dirs, files in os.walk(path):
        for name in dirs + files:
            out.append(os.path.join(dirpath, name))
            if len(out) > WALK_LIMIT:
                return None
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
        # git accepts unambiguous prefixes, so "--out" is --output; "-O" runs a pager command in grep.
        if name.startswith("--output") or (name.startswith("--") and len(name) >= 4 and "--output".startswith(name)):
            return False
        if name.startswith("-O") or name.startswith("--open-files"):
            return False
    return True


def copy_targets(base, ops, opts, cwd):
    """Every path cp, mv or install writes: the destination, what lands inside it, and for trees each file below."""
    if base == "install" and ("d" in opts or "--directory" in opts):
        return ops
    ops = [p for w in ops for p in shell_glob(w, cwd)]
    tdir = opts.get("t")
    if tdir is not None:
        dest, srcs, is_dir = tdir, ops, True
    elif len(ops) < 2:
        return ops
    else:
        dest, srcs = ops[-1], ops[:-1]
        is_dir = len(srcs) > 1 or dest.endswith("/") or os.path.isdir(os.path.join(cwd, dest))
    out = [os.path.join(dest, "") if is_dir else dest]
    recursive = base == "mv" or any(k in opts for k in ("r", "R", "a", "--recursive", "--archive"))
    for src in srcs:
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


def command_targets(words, policy, cwd):
    """(paths the command writes, whether directories among them are written recursively), or None when unknown."""
    name, args = words[0], words[1:]
    if any(c in name for c in "${}*?") or ("[" in name and name != "[") or name.startswith(("~", "=")) or name == "-":
        return None  # the shell decides which program runs
    base = command_base(words)
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
                return [], False
        return None
    if base not in MODELLED:
        return [], False
    # A word the shell rewrites can be an option or a path that we never see: the whole segment is unknown.
    for a in args:
        if any(c in a for c in "${}") or a.startswith("~") or (GLOB_CHARS.search(a) and ".." in a.split("/")):
            return None
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
        found = copy_targets(base, ops, opts, cwd)
        return None if found is None else (found, False)
    if base == "chmod":
        return (ops[1:] if ops and CHMOD_MODE.fullmatch(ops[0]) else ops), recursive
    if base in ("chown", "chgrp"):
        return ops[1:], recursive
    return ops, recursive  # rm, mkdir, touch, truncate, tee


def expand_targets(targets, recursive, cwd):
    """Absolute targets as written, plus what their globs match now and, if recursive, each file below a directory.

    None past WALK_LIMIT. The unexpanded form is kept so the allowed-prefix check still sees the pattern.
    """
    out = []
    for t in targets:
        full = os.path.join(cwd, t)
        out.append(full)
        matches = sorted(glob.glob(full)) if GLOB_CHARS.search(t) else []
        out += matches
        if recursive:
            for p in matches or [full]:
                if os.path.isdir(p):
                    below = walk_paths(p)
                    if below is None:
                        return None
                    out += below
    return out


def write_targets(seg, policy, cwd):
    """Absolute paths one segment writes to (globs expanded), or None when they cannot be known."""
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
        found = command_targets(words, policy, cwd)
        if found is None:
            return None
    a = expand_targets(redirect_targets, False, cwd)
    b = expand_targets(found[0], found[1], cwd)
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


def bash_write_block_reason(cmd, mode, policy, scope, root, cwd):
    """None if every write the command makes is allowed in this mode, else the reason. cwd is where Bash runs."""
    segments = parse_bash(cmd, strict=False)
    if segments is None:
        return "the command cannot be parsed safely (unbalanced quote, substitution or subshell)."
    after_cd = False
    for seg in segments:
        targets = write_targets(seg, policy, cwd)
        # After a cd the targets no longer resolve against cwd.
        if targets is None or (after_cd and targets):
            return UNKNOWN_WRITE_MSG
        for t in targets:
            rel = rel_path(root, t)
            if rel is None:
                return f"write to {t!r} is on a different drive from the repo."
            # A directory is written as a prefix of its contents, so "docs" must read as "docs/".
            reason = write_block_reason(rel + "/" if t.endswith("/") or os.path.isdir(t) else rel, mode, policy, scope)
            # A glob that matched nothing stays a pattern; only concrete paths can be ancestors.
            if reason is None and not GLOB_CHARS.search(rel) and (hit := protected_overlap(rel, policy)):
                reason = f"write to {rel!r} would take {hit!r} with it, which is never allowed. Guard, settings, CI and git internals change by human-applied patch."
            if reason:
                return reason
        after_cd = after_cd or command_base(command_words(seg)) in CD_COMMANDS
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
        else:
            # Claude Code keeps the shell's cwd between calls; the hook payload says where it is now.
            cwd = payload.get("cwd")
            if cwd is None:
                cwd = root
            elif not isinstance(cwd, str):
                block("hook input has a non-string cwd; failing closed")
            cwd = os.path.realpath(cwd)
            if cwd != root and not cwd.startswith(root + os.sep):
                block(f"the shell's working directory {cwd!r} is outside the project; run it as a human.")
            reason = bash_write_block_reason(cmd, mode, policy, active_scope(root), root, cwd)
            if reason:
                block(reason)

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
