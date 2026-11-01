#!/usr/bin/env python3
"""Prove the guard blocks. Run in CI (Linux + Windows) and once per laptop at onboarding.

Each case is a synthetic hook payload and the exit code we require. Every case runs
in a throwaway git repo, so nothing depends on the checkout the tests live in.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import importlib.util
import tempfile
import time
from dataclasses import dataclass, field, replace

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(HERE, "guard.cmd" if os.name == "nt" else "guard.sh")
CORE_FILES = ("trace_core.py", "scope_core.py")  # WS8: guard-owned cores the guard loads by path from its own folder
INTERPRETERS = ("python3", "python", "py")


def registered_hook_command():
    """The hook command string exactly as .claude/settings.json registers it (two levels above this directory)."""
    with open(os.path.join(HERE, "..", "..", ".claude", "settings.json"), encoding="utf-8") as f:
        return json.load(f)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


HOOK_COMMAND = registered_hook_command()
# Per invocation, so a global commit.gpgsign or hooksPath cannot break the harness and nothing lands in the temp repo's .git/config.
GIT = ["git", "-c", "user.name=guard-test", "-c", "user.email=guard-test@example.com", "-c", "commit.gpgsign=false",
       "-c", "core.hooksPath=/dev/null"]


@dataclass
class Case:
    name: str
    payload: dict | str  # a str is sent raw, so malformed input can be tested
    want: int
    committed_mode: str = "normal"
    env_mode: str | None = None
    dirty: tuple[str, ...] = ()
    files: dict[str, str | None] = field(default_factory=dict)
    stderr_has: str = ""
    policy: dict = field(default_factory=dict)  # deep-merged into a copy of policy.json; the guard runs from that copy
    # What Task 4 (write-target checks alone) expected, for a case whose result Task 5's allowlist changed.
    # The "no allowlist" pass in main() re-runs every older Bash case against this.
    legacy: int | None = None
    git: bool = True  # False: no git init and no commit, so the tripwire cannot verify anything
    git_append: dict[str, str] = field(default_factory=dict)  # text appended to .git/ files after the baseline is recorded
    pre_git: dict[str, str] = field(default_factory=dict)  # the same, before the baseline (so it is part of it)
    pre_remove: tuple[str, ...] = ()  # .git/ paths removed before the baseline
    after: tuple[tuple[str, ...], ...] = ()  # git commands run in the project after the dirty files are written
    worktree: bool = False  # run from a linked worktree, whose .git is a file
    env: dict[str, str] = field(default_factory=dict)  # extra environment for the guard
    # WS8: files written after the commit and before `after` (None removes one), so they are in the work tree but
    # not at HEAD: an untracked ai-context/.active-story, or a working-copy edit to a committed file.
    post_files: dict[str, str | None] = field(default_factory=dict)
    stderr_lacks: str = ""  # WS8: text the guard's message must not contain


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def write(path, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": path}}


def fetch(url):
    return {"tool_name": "WebFetch", "tool_input": {"url": url}}


ORG_META = {"sf": {"mode_level": {"normal": "org-metadata"}, "allowed_orgs": ["dev1"]}}
ORG_DATA = {"sf": {"mode_level": {"normal": "org-data"}, "allowed_orgs": ["dev1"]}}
# Every mode allows every command: leaves only the write-target checks (Task 4) and the sf checks.
OPEN = {"bash_groups": {"any": ["(?s).*"]},
        "modes": {m: {"bash_allow": ["any"]} for m in ("normal", "build", "maintain")}}


def expand_prefixes(pattern):
    """Command prefixes an always_blocked pattern stands for: the trailing ( .*)? dropped, each (a|b) group expanded."""
    out = [pattern.removesuffix("( .*)?")]
    while any("(" in s for s in out):
        nxt = []
        for s in out:
            m = re.search(r"\(([^()]*)\)", s)
            nxt += [s[: m.start()] + alt + s[m.end():] for alt in m.group(1).split("|")] if m else [s]
        out = nxt
    return out


def sf_deny_prefixes():
    """Derived from policy.json so the settings deny list cannot drift from it."""
    with open(os.path.join(HERE, "policy.json"), encoding="utf-8") as f:
        return [p for pat in json.load(f)["sf"]["always_blocked"] for p in expand_prefixes(pat)]

CASES = [
    Case("sf org login is blocked", bash("sf org login web -a uat"), 2),
    Case("sfdx deploy is blocked", bash("sfdx force:source:deploy -p force-app"), 2),
    Case("git push is blocked", bash("git push origin feature/x"), 2),
    Case("curl is blocked", bash("curl https://example.com"), 2),
    Case("git status is allowed", bash("git status"), 0),
    Case("query helper is allowed", bash("python3 tools/index/query.py stamp"), 0),
    Case("write under ai-context is allowed", write("ai-context/123-x/impact.md"), 0),
    Case("write under force-app is blocked", write("force-app/main/default/classes/A.cls"), 2),
    Case("write escaping ai-context via .. is blocked", write("ai-context/../force-app/main/default/classes/A.cls"), 2),
    Case("write escaping ai-context via ..\\ is blocked", write("ai-context\\..\\force-app\\main\\default\\classes\\A.cls", "Edit"), 2),
    Case("write under ./ai-context is allowed", write("./ai-context/123-x/impact.md"), 0),
    Case("fetch to salesforce docs is allowed", fetch("https://help.salesforce.com/s/"), 0),
    Case("fetch to a blog is blocked", fetch("https://someblog.example/post"), 2),
    Case("advise mode blocks writes", write("ai-context/x/y.md"), 2, committed_mode="normal", env_mode="advise"),
    Case("advise mode allows git status", bash("git status"), 0, committed_mode="normal", env_mode="advise"),
    Case("malformed hook JSON fails closed", "not json", 2, stderr_has="failing closed"),
    Case("committed advise beats local maintain", write("docs/x.md"), 2, committed_mode="advise", env_mode="maintain"),
    Case("committed advise beats local normal", write("ai-context/x.md"), 2, committed_mode="advise", env_mode="normal"),
    Case("local maintain may write docs", write("docs/x.md"), 0, env_mode="maintain"),
    Case("local maintain may write rendered skills", write(".claude/skills/a/SKILL.md"), 0, env_mode="maintain"),
    Case("maintain may write tools/index", write("tools/index/x.py"), 0, env_mode="maintain"),
    Case("maintain may not write tools/guard", write("tools/guard/guard.py"), 2, env_mode="maintain"),
    Case("maintain may not write workflows", write(".github/workflows/ci.yml"), 2, env_mode="maintain"),
    Case("maintain may not write force-app", write("force-app/main/default/classes/A.cls"), 2, env_mode="maintain"),
    Case("no mode may write settings.local.json", write(".claude/settings.local.json"), 2, env_mode="maintain"),
    Case("no mode may write .git/hooks", write(".git/hooks/pre-commit"), 2, env_mode="maintain"),
    Case("normal may not write docs", write("docs/x.md"), 2),
    Case("build without active story may not write force-app", write("force-app/main/default/classes/A.cls"), 2,
         env_mode="build", stderr_has="no active story scope"),
    Case("build may write ai-context", write("ai-context/1-x/change.md"), 0, env_mode="build"),
    Case("unknown local mode fails closed", write("ai-context/x.md"), 2, env_mode="yolo", stderr_has="unknown AI_FRAMEWORK_MODE"),
    Case("committed build is treated as advise", write("ai-context/x.md"), 2, committed_mode="build"),
    Case("unreadable settings.json is treated as advise", write("ai-context/x.md"), 2,
         files={".claude/settings.json": "{not json"}),
    Case("committed unknown value is treated as advise", write("ai-context/x.md"), 2, committed_mode="yolo"),
    Case("absent settings.json is treated as advise", write("ai-context/x.md"), 2, files={".claude/settings.json": None}),
    Case("maintain may not write docs/CODEOWNERS", write("docs/CODEOWNERS"), 2, env_mode="maintain"),
    Case("maintain may not write nested CODEOWNERS", write("framework/x/CODEOWNERS"), 2, env_mode="maintain"),
    Case("maintain may not write lowercase nested codeowners", write("docs/codeowners"), 2, env_mode="maintain"),
    Case("maintain may not write root CODEOWNERS", write("CODEOWNERS"), 2, env_mode="maintain"),
    Case("maintain may not write .github/CODEOWNERS", write(".github/CODEOWNERS"), 2, env_mode="maintain"),
    Case("maintain may not write settings.json", write(".claude/settings.json"), 2, env_mode="maintain"),
    Case("maintain may not write .github/hooks", write(".github/hooks/x"), 2, env_mode="maintain"),
    Case("always-blocked folds case: Tools/Guard", write("Tools/Guard/guard.py"), 2, env_mode="maintain"),
    Case("always-blocked folds case: .GIT", write(".GIT/hooks/pre-commit"), 2, env_mode="maintain"),
    Case("prefix boundary: tools/guardX is not tools/guard/", write("tools/guardX/x.py"), 0, env_mode="maintain"),
    Case("prefix boundary: tools/guard itself is blocked", write("tools/guard"), 2, env_mode="maintain"),
    Case("advise: chained rm after git status blocked", bash("git status; rm -rf x"), 2, env_mode="advise"),
    Case("advise: && touch blocked", bash("ls && touch force-app/A.cls"), 2, env_mode="advise"),
    Case("advise: pipe to head allowed", bash("git log --oneline | head -5"), 0, env_mode="advise"),
    Case("advise: quoted pipe in grep is one segment", bash("grep 'a|b;c' README.md"), 0, env_mode="advise"),
    Case("advise: redirect to file blocked", bash("git diff > ai-context/x.patch"), 2, env_mode="advise"),
    Case("advise: redirect to /dev/null allowed", bash("ls nope 2>/dev/null"), 0, env_mode="advise"),
    Case("advise: command substitution blocked", bash("echo $(rm -rf x)"), 2, env_mode="advise"),
    Case("advise: find -delete blocked", bash("find . -name x -delete"), 2, env_mode="advise"),
    Case("advise: find -exec blocked", bash("find . -exec rm {} ;"), 2, env_mode="advise"),
    Case("advise: unbalanced quote blocked", bash("cat 'x"), 2, env_mode="advise"),
    Case("advise: git checkout blocked", bash("git checkout -- README.md"), 2, env_mode="advise"),
    Case("advise: 2>&1 allowed", bash("git status 2>&1 | head"), 0, env_mode="advise"),
    Case("advise: >&2 allowed", bash("echo hi >&2"), 0, env_mode="advise"),
    Case("advise: >&file blocked", bash("echo hi >& out.txt"), 2, env_mode="advise"),
    Case("advise: append redirect blocked", bash("echo hi >> out.txt"), 2, env_mode="advise"),
    Case("advise: backtick blocked", bash("echo `rm -rf x`"), 2, env_mode="advise"),
    Case("advise: process substitution blocked", bash("diff <(ls) <(ls)"), 2, env_mode="advise"),
    Case("advise: newline chains a second command", bash("ls\nrm -rf x"), 2, env_mode="advise"),
    Case("advise: background & chains a second command", bash("ls & rm -rf x"), 2, env_mode="advise"),
    Case("advise: mid-word # is not a comment", bash("ls a#b; rm -rf x"), 2, env_mode="advise"),
    Case("advise: env prefix blocked", bash("GIT_EXTERNAL_DIFF=./x git diff"), 2, env_mode="advise"),
    Case("advise: subshell blocked", bash("(rm -rf x)"), 2, env_mode="advise"),
    Case("advise: pipe-stderr operator blocked", bash("ls |& rm x"), 2, env_mode="advise"),
    Case("advise: git log --output blocked", bash("git log --output=x.txt"), 2, env_mode="advise"),
    Case("advise: sort -o blocked", bash("sort -o x.txt y.txt"), 2, env_mode="advise"),
    Case("advise: rg --pre blocked", bash("rg --pre ./x foo"), 2, env_mode="advise"),
    Case("advise: uniq with output file blocked", bash("uniq in.txt out.txt"), 2, env_mode="advise"),
    Case("advise: find -fprint blocked", bash("find . -fprint out.txt"), 2, env_mode="advise"),
    Case("advise: git branch --show-current allowed", bash("git branch --show-current"), 0, env_mode="advise"),
    Case("advise: git branch -D blocked", bash("git branch -D x"), 2, env_mode="advise"),
    Case("advise: query helper allowed", bash("py -3 tools/index/query.py stamp"), 0, env_mode="advise"),
    Case("advise: redirect before command to file blocked", bash("> x.txt ls"), 2, env_mode="advise"),
    Case("advise: ${X:--delete} expansion in find blocked", bash("find . -name x ${X:--delete}"), 2, env_mode="advise"),
    Case("advise: brace expansion hides -delete", bash("find . {-delete,-name} x"), 2, env_mode="advise"),
    Case("advise: brace expansion hides git --output", bash("git diff {--output=out.txt,HEAD}"), 2, env_mode="advise"),
    Case("advise: ${X:---output} expansion in git diff blocked", bash("git diff ${X:---output=out.txt}"), 2, env_mode="advise"),
    Case("advise: ${X:--oout.txt} expansion in sort blocked", bash("sort y.txt ${X:--oout.txt}"), 2, env_mode="advise"),
    Case("advise: ${X:---pre} expansion in rg blocked", bash("rg ${X:---pre=./x} foo"), 2, env_mode="advise"),
    Case("advise: brace expansion in uniq blocked", bash("uniq {in,out}"), 2, env_mode="advise"),
    Case("advise: sequence brace expansion blocked", bash("cat {a..c}"), 2, env_mode="advise"),
    Case("advise: $NAME blocked", bash("cat $F"), 2, env_mode="advise"),
    Case("advise: ANSI-C quote blocked", bash("cat $'a'"), 2, env_mode="advise"),
    Case("advise: single-quoted $ allowed", bash("echo '$HOME'"), 0, env_mode="advise"),
    Case("advise: double-quoted $ blocked", bash('echo "$HOME"'), 2, env_mode="advise"),
    Case("advise: single-quoted braces allowed", bash("echo '{a,b}'"), 0, env_mode="advise"),
    Case("advise: find -exec {} braces without comma allowed to parse (still blocked by -exec)", bash("find . -exec cat {} ;"), 2, env_mode="advise"),
    Case("advise: glob allowed", bash("ls force-app/*/*.cls"), 0, env_mode="advise"),
    Case("advise: spaced digit is an argument, not an fd", bash("sort y.txt 2 >/dev/null"), 0, env_mode="advise"),
    Case("advise: spaced digit then file redirect blocked", bash("cat a 2 > out.txt"), 2, env_mode="advise"),
    Case("advise: uniq not read-only", bash("uniq a b"), 2, env_mode="advise"),
    Case("advise: uniq -- form blocked", bash("uniq -- -in out"), 2, env_mode="advise"),
    Case("advise: 1> file blocked", bash("ls 1>out.txt"), 2, env_mode="advise"),
    Case("advise: &> file blocked", bash("ls &>out.txt"), 2, env_mode="advise"),
    Case("advise: > file without space blocked", bash("ls >out.txt"), 2, env_mode="advise"),
    Case("advise: >> file without space blocked", bash("ls >>out.txt"), 2, env_mode="advise"),
    Case("advise: nested brace hides git --output", bash("git diff {--output=out.txt,{HEAD}}"), 2, env_mode="advise"),
    Case("advise: nested brace hides sort -o", bash("sort y.txt {-oout.txt,{y}}"), 2, env_mode="advise"),
    Case("advise: nested brace hides rg --pre", bash("rg -F {--pre=./x,{x}} ."), 2, env_mode="advise"),
    Case("advise: nested brace hides find -delete", bash("find . -name z {-delete,{x}}"), 2, env_mode="advise"),
    Case("advise: lone { blocked", bash("echo {"), 2, env_mode="advise"),
    Case("advise: lone } blocked", bash("echo }"), 2, env_mode="advise"),
    Case("advise: double-quoted braces allowed", bash('echo "{a,b}"'), 0, env_mode="advise"),
    Case("advise: escaped braces allowed", bash("echo \\{a,b\\}"), 0, env_mode="advise"),
    Case("advise: blocked_commands still apply to whole line", bash("echo 'git push'"), 2, env_mode="advise"),
    Case("maintain: sed -i on force-app blocked", bash("sed -i '' s/a/b/ force-app/main/default/classes/A.cls"), 2, env_mode="maintain"),
    Case("maintain: redirect into docs allowed", bash("echo hi > docs/x.md"), 0, env_mode="maintain"),
    Case("maintain: redirect into tools/guard blocked", bash("echo x >> tools/guard/policy.json"), 2, env_mode="maintain"),
    Case("maintain: cp into force-app blocked", bash("cp docs/a.cls force-app/main/default/classes/A.cls"), 2, env_mode="maintain"),
    Case("maintain: mv out of tools/guard blocked", bash("mv tools/guard/guard.py docs/g.py"), 2, env_mode="maintain"),
    Case("maintain: tee into settings.local blocked", bash("echo {} | tee .claude/settings.local.json"), 2, env_mode="maintain"),
    Case("maintain: python -c blocked", bash("python3 -c \"open('x','w')\""), 2, env_mode="maintain"),
    Case("maintain: sh -c blocked", bash("sh -c 'touch force-app/A.cls'"), 2, env_mode="maintain"),
    Case("maintain: xargs rm blocked", bash("ls | xargs rm"), 2, env_mode="maintain"),
    Case("maintain: write after cd blocked", bash("cd force-app && touch A.cls"), 2, env_mode="maintain"),
    Case("maintain: git apply blocked", bash("git apply x.patch"), 2, env_mode="maintain"),
    Case("maintain: mkdir under demo allowed", bash("mkdir -p demo/org/force-app"), 0, env_mode="maintain"),
    Case("normal: redirect into ai-context allowed", bash("python3 tools/index/query.py stamp > ai-context/s.json"), 0),
    Case("normal: redirect into force-app blocked", bash("python3 tools/index/query.py stamp > force-app/s.json"), 2),
    Case("maintain: touch with ${X} target blocked", bash("touch docs/${X}.md"), 2, env_mode="maintain", stderr_has="single quotes"),
    Case("maintain: touch with brace expansion blocked", bash("touch docs/{a,b}.md"), 2, env_mode="maintain"),
    Case("maintain: double-quoted $ in a non-target argument blocked (R1)", bash('echo "$HOME" > docs/x.md'), 2, env_mode="maintain"),
    Case("maintain: rm glob inside docs allowed", bash("rm docs/*.md"), 0, env_mode="maintain"),
    Case("maintain: command substitution blocked", bash("echo $(id) > docs/x"), 2, env_mode="maintain"),
    Case("maintain: backtick blocked", bash("echo `id` > docs/x"), 2, env_mode="maintain"),
    Case("maintain: substitution in double quotes blocked", bash('echo "$(id)" > docs/x'), 2, env_mode="maintain"),
    Case("maintain: process substitution into tee blocked", bash("echo a | tee >(cat) docs/x"), 2, env_mode="maintain"),
    Case("maintain: single-quoted substitution text allowed", bash("echo '$(id)' > docs/x"), 0, env_mode="maintain"),
    Case("normal: $VAR in target blocked", bash("echo a > $OUT"), 2),
    Case("normal: double-quoted $ in an echo argument blocked (R1)", bash('echo "$HOME"'), 2),
    Case("maintain: tools/* glob blocked (would match tools/guard)", bash("rm -r tools/*"), 2, env_mode="maintain"),
    Case("maintain: rm -rf tools (parent of tools/guard) blocked", bash("rm -rf tools"), 2, env_mode="maintain"),
    Case("maintain: mv tools blocked", bash("mv tools docs/old-tools"), 2, env_mode="maintain"),
    Case("maintain: rm -rf . blocked", bash("rm -rf ."), 2, env_mode="maintain"),
    Case("maintain: glob with .. blocked", bash("rm docs/*/../../force-app/x"), 2, env_mode="maintain"),
    Case("maintain: .. climbs out of docs blocked", bash("touch docs/../force-app/A.cls"), 2, env_mode="maintain"),
    Case("maintain: tilde target blocked", bash("touch ~/x"), 2, env_mode="maintain"),
    Case("maintain: absolute path outside project blocked", bash("touch /etc/x"), 2, env_mode="maintain"),
    Case("maintain: /dev/null redirect allowed", bash("ls nope > /dev/null 2>&1"), 0, env_mode="maintain"),
    Case("maintain: >| into force-app blocked", bash("echo a >| force-app/x"), 2, env_mode="maintain"),
    Case("maintain: &> into force-app blocked", bash("ls &> force-app/x"), 2, env_mode="maintain"),
    Case("maintain: >& file into force-app blocked", bash("ls >& force-app/x"), 2, env_mode="maintain"),
    Case("maintain: 2> into force-app blocked", bash("ls 2>force-app/x"), 2, env_mode="maintain"),
    Case("maintain: redirect with no target blocked", bash("ls >"), 2, env_mode="maintain"),
    Case("maintain: input redirect is not a write", bash("cat < force-app/x"), 0, env_mode="maintain"),
    Case("maintain: sed -i.bak on force-app blocked", bash("sed -i.bak s/a/b/ force-app/x"), 2, env_mode="maintain"),
    Case("maintain: sed -i -e on force-app blocked", bash("sed -i -e s/a/b/ force-app/x"), 2, env_mode="maintain"),
    Case("maintain: sed -ni on force-app blocked", bash("sed -ni s/a/b/p force-app/x"), 2, env_mode="maintain"),
    Case("maintain: sed --in-place on force-app blocked", bash("sed --in-place s/a/b/ force-app/x"), 2, env_mode="maintain"),
    Case("maintain: sed -i on docs allowed", bash("sed -i '' s/a/b/ docs/x.md"), 0, env_mode="maintain"),
    Case("maintain: sed without -i is read-only", bash("sed s/a/b/ force-app/x"), 0, env_mode="maintain"),
    Case("maintain: cp -t into force-app blocked", bash("cp -t force-app docs/a"), 2, env_mode="maintain"),
    Case("maintain: install into force-app blocked", bash("install -m 644 docs/a force-app/a"), 2, env_mode="maintain"),
    Case("maintain: install -d force-app blocked", bash("install -d force-app/new"), 2, env_mode="maintain"),
    Case("maintain: ln into force-app blocked", bash("ln -s ../docs/a force-app/a"), 2, env_mode="maintain"),
    Case("maintain: ln is an unknown writer even into docs", bash("ln -s ../demo/a docs/a"), 2, env_mode="maintain"),
    Case("maintain: chmod is off the allowlist", bash("chmod 755 docs/x.sh"), 2, env_mode="maintain", stderr_has="allowlist", legacy=0),
    Case("maintain: chmod +x on force-app blocked", bash("chmod +x force-app/x.sh"), 2, env_mode="maintain"),
    Case("maintain: chmod -x on force-app blocked", bash("chmod -x force-app/x.sh"), 2, env_mode="maintain"),
    Case("maintain: chown is off the allowlist", bash("chown me docs/x"), 2, env_mode="maintain", stderr_has="allowlist", legacy=0),
    Case("maintain: chmod --reference unknown", bash("chmod --reference=docs/a force-app/x"), 2, env_mode="maintain"),
    Case("maintain: truncate -s on force-app blocked", bash("truncate -s 0 force-app/x"), 2, env_mode="maintain"),
    Case("maintain: truncate is off the allowlist", bash("truncate -s 0 docs/x"), 2, env_mode="maintain", stderr_has="allowlist", legacy=0),
    Case("maintain: touch -d value is not a path", bash("touch -d yesterday docs/x"), 0, env_mode="maintain"),
    Case("maintain: dd of= force-app blocked", bash("dd if=docs/a of=force-app/a"), 2, env_mode="maintain"),
    Case("maintain: dd is off the allowlist", bash("dd if=docs/a of=docs/b"), 2, env_mode="maintain", stderr_has="allowlist", legacy=0),
    Case("maintain: rm -- force-app blocked", bash("rm -f -- force-app/x"), 2, env_mode="maintain"),
    Case("maintain: path-qualified rm blocked", bash("/bin/rm force-app/x"), 2, env_mode="maintain"),
    Case("maintain: env prefix does not hide the command", bash("X=1 rm force-app/x"), 2, env_mode="maintain"),
    Case("maintain: command word from a variable blocked", bash("$RM force-app/x"), 2, env_mode="maintain"),
    Case("maintain: command word glob blocked", bash("/bin/r? force-app/x"), 2, env_mode="maintain"),
    Case("maintain: then-branch write is checked", bash("if true; then rm force-app/x; fi"), 2, env_mode="maintain"),
    Case("maintain: do-branch write is checked", bash("for f in a; do touch force-app/x; done"), 2, env_mode="maintain"),
    Case("maintain: write after pipe is checked", bash("echo a | tee force-app/x"), 2, env_mode="maintain"),
    Case("maintain: write after && is checked", bash("ls && rm force-app/x"), 2, env_mode="maintain"),
    Case("maintain: write after newline is checked", bash("ls\nrm force-app/x"), 2, env_mode="maintain"),
    Case("maintain: cd with no later write allowed", bash("cd docs && ls"), 0, env_mode="maintain"),
    Case("maintain: redirect after cd blocked", bash("cd docs && echo a > x.md"), 2, env_mode="maintain"),
    Case("maintain: pushd then write blocked", bash("pushd force-app; touch A.cls"), 2, env_mode="maintain"),
    Case("maintain: bash -c blocked", bash("bash -c 'echo a'"), 2, env_mode="maintain"),
    Case("maintain: eval blocked", bash("eval ls"), 2, env_mode="maintain"),
    Case("maintain: env wrapper blocked", bash("env rm force-app/x"), 2, env_mode="maintain"),
    Case("maintain: nohup blocked", bash("nohup ls"), 2, env_mode="maintain"),
    Case("maintain: perl blocked", bash("perl -pi -e 's/a/b/' force-app/x"), 2, env_mode="maintain"),
    Case("maintain: sudo wrapper blocked", bash("sudo rm force-app/x"), 2, env_mode="maintain"),
    Case("maintain: python script is not -c", bash("python3 tools/index/query.py stamp"), 0, env_mode="maintain"),
    Case("maintain: py -3 -c blocked", bash("py -3 -c 'print(1)'"), 2, env_mode="maintain"),
    Case("maintain: python3 reading a script from stdin blocked", bash("echo 'open(1)' | python3"), 2, env_mode="maintain"),
    Case("maintain: python3 - blocked", bash("python3 - <<EOF\nprint(1)\nEOF"), 2, env_mode="maintain"),
    Case("maintain: git checkout blocked", bash("git checkout -- force-app"), 2, env_mode="maintain"),
    Case("maintain: git -C checkout blocked", bash("git -C docs checkout -- ."), 2, env_mode="maintain"),
    Case("maintain: git restore blocked", bash("git restore force-app"), 2, env_mode="maintain"),
    Case("maintain: git reset blocked", bash("git reset --hard"), 2, env_mode="maintain"),
    Case("maintain: git clean blocked", bash("git clean -fd"), 2, env_mode="maintain"),
    Case("maintain: git stash blocked", bash("git stash"), 2, env_mode="maintain"),
    Case("maintain: git mv blocked", bash("git mv docs/a docs/b"), 2, env_mode="maintain"),
    Case("maintain: git rm blocked", bash("git rm docs/a"), 2, env_mode="maintain"),
    Case("maintain: git worktree blocked", bash("git worktree add ../x"), 2, env_mode="maintain"),
    Case("maintain: git merge blocked", bash("git merge main"), 2, env_mode="maintain"),
    Case("maintain: git -c alias blocked", bash("git -c alias.s=status s"), 2, env_mode="maintain"),
    Case("maintain: git diff --output blocked", bash("git diff --output=force-app/x"), 2, env_mode="maintain"),
    Case("maintain: git status allowed", bash("git status"), 0, env_mode="maintain"),
    Case("maintain: git -C is not allowlisted", bash("git -C docs log --oneline"), 2, env_mode="maintain"),
    Case("maintain: find -delete blocked", bash("find . -name x -delete"), 2, env_mode="maintain"),
    Case("maintain: find -exec blocked", bash("find . -exec rm {} ;"), 2, env_mode="maintain"),
    Case("maintain: find -fprint blocked", bash("find . -fprint force-app/x"), 2, env_mode="maintain"),
    Case("maintain: find plain allowed", bash("find docs -name '*.md'"), 0, env_mode="maintain"),
    Case("maintain: sort -o blocked", bash("sort -o force-app/x y"), 2, env_mode="maintain"),
    Case("maintain: sort plain allowed", bash("sort y"), 0, env_mode="maintain"),
    Case("maintain: uniq with output file blocked", bash("uniq a force-app/x"), 2, env_mode="maintain"),
    Case("maintain: unbalanced quote blocked", bash("echo 'x"), 2, env_mode="maintain"),
    Case("maintain: subshell blocked", bash("(touch force-app/x)"), 2, env_mode="maintain"),
    Case("maintain: tee is off the allowlist", bash("echo a | tee -a docs/x"), 2, env_mode="maintain", stderr_has="allowlist", legacy=0),
    Case("maintain: tee to two files, one forbidden, blocked", bash("echo a | tee docs/x force-app/y"), 2, env_mode="maintain"),
    Case("maintain: mv within docs allowed", bash("mv docs/a docs/b"), 0, env_mode="maintain"),
    Case("maintain: cp from force-app into docs allowed", bash("cp force-app/main/default/classes/A.cls docs/A.cls"), 0, env_mode="maintain"),
    Case("normal: touch in docs blocked", bash("touch docs/x"), 2),
    Case("normal: touch is off the allowlist", bash("touch ai-context/x"), 2, stderr_has="allowlist", legacy=0),
    Case("normal: sh -c blocked", bash("sh -c 'ls'"), 2),
    Case("normal: sed -i on force-app blocked", bash("sed -i s/a/b/ force-app/x"), 2),
    Case("build: no scope blocks force-app redirect", bash("echo a > force-app/x"), 2, env_mode="build", stderr_has="no active story scope"),
    Case("build: ai-context redirect allowed", bash("echo a > ai-context/1-x/y.md"), 0, env_mode="build"),
    Case("advise: ruling - double-quoted $ still blocked", bash('echo "$HOME"'), 2, env_mode="advise"),
    Case("advise: >| blocked", bash("ls >| out.txt"), 2, env_mode="advise"),
    # Fix round 1. A: links and glob aliases.
    Case("A: hard link out of tools/guard blocked", bash("ln tools/guard/guard.py ai-context/g"), 2, env_mode="maintain"),
    Case("A: ln is an unknown writer even into ai-context", bash("ln -s ../docs/a ai-context/a"), 2),
    Case("A: link command blocked", bash("link tools/guard/guard.py ai-context/h"), 2),
    Case("A: cp -l blocked", bash("cp -l tools/guard/guard.py ai-context/h2"), 2),
    Case("A: cp -s blocked", bash("cp -s tools/guard/guard.py ai-context/h2"), 2),
    Case("A: cp --link blocked", bash("cp --link tools/guard/guard.py ai-context/h2"), 2),
    Case("A: symlink then write through it in one command blocked", bash("ln -s ../tools/guard ai-context/lk && cp ai-context/e ai-context/lk/guard.py"), 2),
    Case("A: glob write matching a protected file blocked", bash("echo x > tools/gua*/guard.py"), 2, env_mode="maintain",
         files={"tools/guard/guard.py": "x"}),
    Case("A: glob rm matching a protected file blocked", bash("rm tools/gua*/guard.py"), 2, env_mode="maintain",
         files={"tools/guard/guard.py": "x"}),
    Case("A: glob rm matching CODEOWNERS blocked", bash("rm docs/*"), 2, env_mode="maintain", files={"docs/CODEOWNERS": "x", "docs/a.md": "x"}),
    Case("A: glob rm matching only ordinary files allowed", bash("rm docs/*"), 0, env_mode="maintain", files={"docs/a.md": "x"}),
    Case("I: rm is off the normal allowlist", bash("rm -rf ai-context/tmp/*"), 2, files={"ai-context/tmp/a": "x"}, stderr_has="allowlist", legacy=0),
    # B: expansion in non-target words.
    Case("B: $T carries -t", bash("T=-t; cp $T tools/guard ai-context/e"), 2),
    Case("B: unassigned $T in cp blocked", bash("cp $T tools/guard ai-context/e"), 2),
    Case("B: brace expansion carries -t", bash("cp {-t,tools/guard/} ai-context/e"), 2),
    Case("B: ANSI-C quote carries -t", bash("cp $'-t' tools/guard ai-context/e"), 2),
    Case("B: ${X}= in dd blocked", bash("dd ${X}=tools/guard/guard.py if=ai-context/e"), 2),
    Case("B: $X in sed blocked", bash("sed $X s/a/b/ tools/guard/guard.py"), 2),
    Case("B: double-quoted $ in a non-writer command blocked (R1)", bash('echo "$HOME" > ai-context/ok'), 2),
    # C: GNU long options.
    Case("C: --t= abbreviation of --target-directory", bash("cp --t=tools/guard ai-context/e"), 2),
    Case("C: --in-pl abbreviation of --in-place", bash("sed --in-pl s/a/b/ tools/guard/guard.py"), 2),
    Case("C: install --strip-program takes a value", bash("install ai-context/e tools/guard/guard.py --strip-program ai-context/x"), 2),
    Case("C: cp --sparse takes a value", bash("cp ai-context/e tools/guard/guard.py --sparse auto"), 2),
    Case("C: cluster ending in a value option after operands", bash("cp ai-context/e tools/guard/guard.py -rS ai-context/x"), 2),
    Case("C: --target-directory= into protected path blocked", bash("cp --target-directory=tools/guard ai-context/e"), 2, env_mode="maintain"),
    Case("C: --target-directory into docs allowed", bash("cp --target-directory docs ai-context/e"), 0, env_mode="maintain"),
    Case("C: option after operands is read", bash("cp ai-context/e docs/b --force"), 0, env_mode="maintain"),
    Case("C: known short flags allowed", bash("cp -rfv ai-context/e docs/b"), 0, env_mode="maintain"),
    Case("C: unmodelled long option on rm blocked", bash("rm --preserve-xyz docs/a"), 2, env_mode="maintain"),
    # D: git allowlist and assignments.
    Case("D: git config blocked", bash("git config core.fsmonitor 'touch tools/guard/pwn'"), 2, env_mode="maintain"),
    Case("D: GIT_CONFIG_* env blocked", bash("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor GIT_CONFIG_VALUE_0=x git status"), 2),
    Case("D: git init blocked", bash("git init tools/guard/x"), 2, env_mode="maintain"),
    Case("D: git config hooksPath blocked", bash("git config core.hooksPath docs/hooks"), 2, env_mode="maintain"),
    Case("D: git -C . config blocked", bash("git -C . config core.fsmonitor x"), 2, env_mode="maintain"),
    Case("D: git format-patch -o blocked", bash("git format-patch -o tools/guard HEAD~1"), 2, env_mode="maintain"),
    Case("D: git archive -o blocked", bash("git archive -o tools/guard/x HEAD"), 2, env_mode="maintain"),
    Case("D: git diff --out= abbreviation blocked", bash("git diff --out=tools/guard/x"), 2, env_mode="maintain"),
    Case("D: git grep -O blocked", bash("git grep -Osh foo"), 2),
    Case("D: git log --oneline allowed", bash("git log --oneline"), 0),
    Case("D: git diff --stat allowed", bash("git diff --stat"), 0),
    Case("D: git branch --show-current allowed", bash("git branch --show-current"), 0),
    Case("D: git branch -D blocked", bash("git branch -D x"), 2),
    Case("D: git add allowed", bash("git add docs/x"), 0, env_mode="maintain"),
    Case("D: git -c blocked", bash("git -c core.pager=x log"), 2),
    Case("D: PYTHONPATH assignment blocked", bash("PYTHONPATH=ai-context python3 tools/index/query.py stamp"), 2),
    # E: wrappers and runners.
    Case("E: =cmd blocked", bash("=rm tools/guard/guard.py"), 2),
    Case("E: noglob blocked", bash("noglob rm tools/guard/guard.py"), 2),
    Case("E: nocorrect blocked", bash("nocorrect rm tools/guard/guard.py"), 2),
    Case("E: - precommand blocked", bash("- rm tools/guard/guard.py"), 2),
    Case("E: caffeinate blocked", bash("caffeinate -i rm tools/guard/guard.py"), 2),
    Case("E: alias blocked", bash("alias x='rm tools/guard/guard.py'"), 2),
    Case("E: trap blocked", bash("trap 'touch tools/guard/pwn' EXIT"), 2),
    Case("E: coproc blocked", bash("coproc touch tools/guard/pwn"), 2),
    Case("E: function definition blocked", bash("function f { touch tools/guard/pwn; }; f"), 2),
    Case("E: export blocked", bash("export GIT_CONFIG_COUNT=1; git status"), 2),
    Case("E: python -m blocked", bash("python3 -m zipfile -e ai-context/z.zip tools/"), 2),
    Case("E: unlink blocked", bash("unlink tools/guard/guard.py"), 2),
    Case("E: ed blocked", bash("printf 'w\\n' | ed -s tools/guard/guard.py"), 2),
    Case("E: ditto blocked", bash("ditto ai-context/e tools/guard/guard.py"), 2),
    Case("E: plutil blocked", bash("plutil -convert xml1 tools/guard/policy.json"), 2),
    Case("E: python -W then -c blocked", bash("python3 -W ignore -c 'print(1)'"), 2),
    Case("E: test builtin [ is off the allowlist", bash("[ -f docs/a ] && ls"), 2, stderr_has="allowlist", legacy=0),
    # F: copy into a directory.
    Case("F: cp CODEOWNERS into docs/sub/ blocked", bash("cp ai-context/CODEOWNERS docs/sub/"), 2, env_mode="maintain", files={"ai-context/CODEOWNERS": "x"}),
    Case("F: cp CODEOWNERS into an existing dir blocked", bash("cp ai-context/CODEOWNERS docs"), 2, env_mode="maintain",
         files={"ai-context/CODEOWNERS": "x", "docs/a": "x"}),
    Case("F: cp -r tree holding CODEOWNERS into docs blocked", bash("cp -r ai-context/sub docs/"), 2, env_mode="maintain",
         files={"ai-context/sub/CODEOWNERS": "x"}),
    Case("F: mv CODEOWNERS into docs blocked", bash("mv ai-context/CODEOWNERS docs/"), 2, env_mode="maintain", files={"ai-context/CODEOWNERS": "x"}),
    Case("F: rm -rf docs holding CODEOWNERS blocked", bash("rm -rf docs"), 2, env_mode="maintain", files={"docs/CODEOWNERS": "x"}),
    Case("F: cp ordinary file into docs/sub/ allowed", bash("cp ai-context/a docs/sub/"), 0, env_mode="maintain", files={"ai-context/a": "x"}),
    Case("F: cp into an existing dir that is a protected parent blocked", bash("cp ai-context/a tools"), 2, env_mode="maintain", files={"ai-context/a": "x"}),
    # G: the payload's cwd.
    Case("G: relative redirect from cwd docs lands in docs", {"tool_name": "Bash", "tool_input": {"command": "echo hi > x.md"}, "cwd": "@PROJECT@/docs"}, 0, env_mode="maintain"),
    Case("G: relative redirect from cwd force-app blocked", {"tool_name": "Bash", "tool_input": {"command": "touch A.cls"}, "cwd": "@PROJECT@/force-app"}, 2, env_mode="maintain"),
    Case("G: .. from cwd docs reaching force-app blocked", {"tool_name": "Bash", "tool_input": {"command": "echo hi > ../force-app/x"}, "cwd": "@PROJECT@/docs"}, 2, env_mode="maintain"),
    Case("G: cwd outside the project blocked", {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/"}, 2, env_mode="maintain", stderr_has="outside the project"),
    Case("G: cwd at the project root allowed", {"tool_name": "Bash", "tool_input": {"command": "echo hi > docs/x.md"}, "cwd": "@PROJECT@"}, 0, env_mode="maintain"),
    Case("G: cwd that is not a string fails closed", {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": 5}, 2, env_mode="maintain"),
    # H: sed scripts.
    Case("H: sed w command blocked", bash("sed -n 'w tools/guard/x' ai-context/e"), 2),
    Case("H: sed s///w flag blocked", bash("sed 's/a/b/w tools/guard/x' ai-context/e"), 2),
    Case("H: sed e command blocked", bash("sed 'e id' ai-context/e"), 2),
    Case("H: sed -f script blocked", bash("sed -f ai-context/s.sed ai-context/e"), 2),
    Case("H: sed -e w blocked", bash("sed -n -e 'w tools/guard/x' ai-context/e"), 2),
    Case("H: w inside a regex is not a command (sed is off the normal allowlist)", bash("sed 's/we/x/' ai-context/e"), 2, stderr_has="allowlist", legacy=0),
    Case("H: w inside an address regex is not a command (sed is off the normal allowlist)", bash("sed -n '/w/p' ai-context/e"), 2, stderr_has="allowlist", legacy=0),
    Case("I: BSD sed -i .bak in ai-context (sed is off the normal allowlist)", bash("sed -i .bak 's/a/b/' ai-context/x"), 2, stderr_has="allowlist", legacy=0),
    Case("I: BSD sed -i .bak on force-app blocked", bash("sed -i .bak 's/a/b/' force-app/x"), 2),
    Case("I: GNU sed -i.bak in ai-context (sed is off the normal allowlist)", bash("sed -i.bak 's/a/b/' ai-context/x"), 2, stderr_has="allowlist", legacy=0),
    Case("I: sed -i with script word that is not a suffix is GNU", bash("sed -i 1d force-app/x"), 2),
    Case("I: advise echo '' allowed", bash("echo ''"), 0, env_mode="advise"),
    Case("N1: sed -i suffix with / blocked", bash("sed -i.bak/x 's/a/b/' docs/a.md"), 2, env_mode="maintain"),
    Case("N1: sed -i suffix with * blocked", bash("sed -i'tools/guard/*' 's/x/x/' docs/guard.py"), 2, env_mode="maintain"),
    Case("N1: sed --in-place= suffix with * blocked", bash("sed --in-place='tools/guard/*' 's/x/x/' docs/a.md"), 2, env_mode="maintain"),
    Case("N1: BSD separate suffix with / blocked", bash("sed -i .bak/x 's/a/b/' docs/a.md"), 2, env_mode="maintain"),
    Case("N1: plain .bak suffix allowed", bash("sed -i.bak 's/a/b/' docs/a.md"), 0, env_mode="maintain"),
    Case("N1: --in-place=.bak allowed", bash("sed --in-place=.bak 's/a/b/' docs/a.md"), 0, env_mode="maintain"),
    Case("N1: backup path (target + suffix) is checked", bash("sed -iERS 's/a/b/' docs/CODEOWN"), 2, env_mode="maintain"),
    Case("N2: label with trailing command (:) blocked", bash("sed -n ':a w tools/guard/x' docs/a.md"), 2, env_mode="maintain"),
    Case("N2: label with trailing command (b) blocked", bash("sed -n 'b a w tools/guard/x' docs/a.md"), 2, env_mode="maintain"),
    Case("N2: label with trailing command (t) blocked", bash("sed -n 't a w tools/guard/x' docs/a.md"), 2, env_mode="maintain"),
    Case("N2: plain labels allowed", bash("sed -n ':a;n;ba' docs/a.md"), 0, env_mode="maintain"),
]

NOT_ON_LIST = "allowlist"
# Task 5: per-mode Bash allowlists and Salesforce CLI levels. Not re-run in the "no allowlist" pass.
ALLOWLIST_CASES = [
    Case("normal: arbitrary command blocked", bash("make deploy"), 2, stderr_has=NOT_ON_LIST),
    Case("normal: query helper allowed", bash("python3 tools/index/query.py stamp"), 0),
    Case("normal: skill script allowed", bash("python3 framework/skills/story-impact/scripts/write_report.py --id 1"), 0),
    Case("normal: render blocked", bash("python3 tools/build/render.py"), 2, stderr_has=NOT_ON_LIST),
    Case("normal: git commit blocked", bash("git commit -m x"), 2, stderr_has=NOT_ON_LIST),
    Case("normal: git add blocked", bash("git add docs/x"), 2, stderr_has=NOT_ON_LIST),
    Case("normal: framework scripts allowed", bash("py -3 tools/build/lint.py --all"), 0),
    Case("normal: evals runner allowed", bash("python3 tools/evals/run_skill.py x"), 0),
    Case("normal: test_guard allowed", bash("python3 tools/guard/test_guard.py"), 0),
    Case("normal: scan_data allowed", bash("python3 tools/guard/scan_data.py"), 0),
    Case("normal: guard.py itself is not a framework script", bash("python3 tools/guard/guard.py"), 2, stderr_has="blocked pattern"),
    Case("normal: skill script dir must be lowercase", bash("python3 framework/skills/Story/scripts/w.py"), 2, stderr_has=NOT_ON_LIST),
    Case("normal: arbitrary workspace script blocked", bash("python3 ai-context/x/y.py"), 2, stderr_has=NOT_ON_LIST),
    Case("normal: pnpm exec blocked", bash("pnpm exec eslint ."), 2, stderr_has=NOT_ON_LIST),
    Case("normal: second segment off the list blocks the line", bash("git status && make deploy"), 2, stderr_has=NOT_ON_LIST),
    Case("normal: tar listing off the normal list", bash("tar -tf ai-context/a.tar"), 2, stderr_has=NOT_ON_LIST),
    Case("build: git commit allowed", bash("git commit -m x"), 0, env_mode="build"),
    Case("build: git add allowed", bash("git add ai-context/x"), 0, env_mode="build"),
    Case("build: pnpm test allowed", bash("pnpm test"), 0, env_mode="build"),
    Case("build: pnpm run lint allowed", bash("pnpm run lint"), 0, env_mode="build"),
    Case("build: pnpm exec prettier allowed", bash("pnpm exec prettier --check ."), 0, env_mode="build"),
    Case("build: pnpm exec jest allowed", bash("pnpm exec jest"), 0, env_mode="build"),
    Case("build: pnpm exec sfdx-lwc-jest allowed", bash("pnpm exec sfdx-lwc-jest"), 0, env_mode="build"),
    Case("build: pnpm install blocked", bash("pnpm install"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("build: pnpm add blocked", bash("pnpm add left-pad"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("build: arbitrary command blocked", bash("make deploy"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("build: render blocked", bash("python3 tools/build/render.py"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("build: rm blocked", bash("rm ai-context/x"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("maintain: arbitrary command blocked", bash("make docs"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: trap blocked", bash("trap 'touch docs/x' EXIT"), 2, env_mode="maintain"),
    Case("maintain: cp into docs allowed", bash("cp ai-context/a.md docs/a.md"), 0, env_mode="maintain"),
    Case("maintain: render allowed", bash("python3 tools/build/render.py"), 0, env_mode="maintain"),
    Case("maintain: workspace script allowed", bash("python3 ai-context/ws0/sdd/mkpatch.py a b c"), 0, env_mode="maintain"),
    Case("maintain: git push still blocked", bash("git push"), 2, env_mode="maintain"),
    Case("maintain: diff and cmp allowed", bash("cmp docs/a docs/b && diff docs/a docs/b"), 0, env_mode="maintain"),
    Case("maintain: rmdir allowed in docs", bash("rmdir docs/old"), 0, env_mode="maintain"),
    Case("maintain: rmdir tools/guard blocked", bash("rmdir tools/guard"), 2, env_mode="maintain"),
    Case("maintain: rmdir -p blocked (it climbs)", bash("rmdir -p docs/a/b"), 2, env_mode="maintain"),
    Case("maintain: rmdir off the normal list", bash("rmdir ai-context/old"), 2, stderr_has=NOT_ON_LIST),
    Case("maintain: tar listing allowed", bash("tar -tf ai-context/a.tar"), 0, env_mode="maintain"),
    Case("maintain: tar -tvf allowed", bash("tar -tvf ai-context/a.tar"), 0, env_mode="maintain"),
    Case("maintain: tar extract blocked", bash("tar -xf ai-context/a.tar"), 2, env_mode="maintain"),
    Case("maintain: tar create blocked", bash("tar -cf docs/a.tar docs"), 2, env_mode="maintain"),
    Case("maintain: tar listing with checkpoint action blocked", bash("tar -tf ai-context/a.tar --checkpoint-action=exec=id"), 2, env_mode="maintain"),
    Case("maintain: tar listing with to-command blocked", bash("tar -tf a.tar --to-command=cat"), 2, env_mode="maintain"),
    Case("maintain: tar listing of a remote archive blocked", bash("tar -tf host:a.tar"), 2, env_mode="maintain"),
    Case("maintain: tar listing with an expansion blocked", bash("tar -tf a.tar $X"), 2, env_mode="maintain"),
    Case("maintain: tar listing with -I program blocked", bash("tar -tf a.tar -I id"), 2, env_mode="maintain"),
    Case("maintain: pnpm exec prettier allowed", bash("pnpm exec prettier --check ."), 0, env_mode="maintain"),
    Case("maintain: pnpm exec eslint allowed", bash("pnpm exec eslint ."), 0, env_mode="maintain"),
    Case("maintain: pnpm jest allowed", bash("pnpm exec jest"), 0, env_mode="maintain"),
    Case("maintain: pnpm test is not a maintainer tool", bash("pnpm test"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: pnpm sfdx-lwc-jest is not a maintainer tool", bash("pnpm sfdx-lwc-jest"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: script under tools allowed", bash("python3 tools/index/build_index.py --full"), 0, env_mode="maintain"),
    Case("maintain: script under demo with py -3 allowed", bash("py -3 demo/org/seed.py"), 0, env_mode="maintain"),
    Case("maintain: script under fixtures allowed", bash("python3 fixtures/make_fixture.py"), 0, env_mode="maintain"),
    Case("maintain: script path with .. blocked", bash("python3 tools/../force-app/x.py"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: script path with .. in the middle blocked", bash("python3 ai-context/a/../../x.py"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: script outside the five roots blocked", bash("python3 force-app/x.py"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: absolute script path blocked", bash("python3 /tmp/x.py"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: tools2 is not tools", bash("python3 tools2/x.py"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: x.pyz is not x.py", bash("python3 tools/x.pyz"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: python3 /dev/stdin blocked", bash("python3 /dev/stdin"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: python3 -i script blocked", bash("python3 -i tools/x.py"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: python3 -m blocked", bash("python3 -m tools.x"), 2, env_mode="maintain"),
    Case("maintain: python3 -c after a script word blocked", bash("python3 -c 'import os' tools/x.py"), 2, env_mode="maintain"),
    Case("maintain: py -3 -m blocked", bash("py -3 -m http.server"), 2, env_mode="maintain"),
    # Controller ruling: these must never be admitted by maintainer_tools.
    Case("maintain: gsed not admitted", bash("gsed -i s/a/b/ docs/x"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: gcp not admitted", bash("gcp docs/a docs/b"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: busybox not admitted", bash("busybox cp docs/a docs/b"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: nvim not admitted", bash("nvim -es docs/x"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: emacs not admitted", bash("emacs --batch docs/x"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: yq not admitted", bash("yq -i . docs/x.yaml"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: make not admitted", bash("make docs"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: open not admitted", bash("open docs/x"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: watch not admitted", bash("watch ls"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: flock not admitted", bash("flock docs/lock ls"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: xcrun not admitted", bash("xcrun ls"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: at not admitted", bash("at now"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: pip not admitted", bash("pip install x"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("maintain: path-qualified cp is not the cp pattern", bash("/bin/cp docs/a docs/b"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    # WS2 impact records: register queries are read-only; validate is a framework script; promote and
    # writes under impacts/ are maintain-only (a human promotes a record).
    Case("register query allowed in advise", bash("python3 tools/impacts/register.py view"), 0, env_mode="advise"),
    Case("validate allowed in normal", bash("python3 tools/impacts/validate.py --all"), 0),
    Case("validate blocked in advise", bash("python3 tools/impacts/validate.py --all"), 2, env_mode="advise", stderr_has="ADVISE mode"),
    Case("promote blocked in normal", bash("python3 tools/impacts/promote.py ai-context/X --confirmed-by lead"), 2, stderr_has=NOT_ON_LIST),
    Case("promote blocked in build", bash("python3 tools/impacts/promote.py ai-context/X --confirmed-by lead"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("impacts write blocked in normal", write("impacts/DEMO-1-a/impact.json"), 2),
    Case("impacts write blocked in build", write("impacts/DEMO-1-a/impact.json"), 2, env_mode="build"),
    Case("impacts write allowed in maintain", write("impacts/DEMO-1-a/impact.json"), 0, env_mode="maintain"),
    # WS11 stories: validate_story and check_ac are framework scripts; query.py edge-seeds stays read-only;
    # promote --story is maintain-only, like promote (the product owner confirms a story).
    Case("check_ac allowed in normal", bash("python3 tools/stories/check_ac.py ai-context/DEMO-1-a/story.json"), 0),
    Case("check_ac blocked in advise", bash("python3 tools/stories/check_ac.py ai-context/DEMO-1-a/story.json"), 2, env_mode="advise", stderr_has="ADVISE mode"),
    Case("edge-seeds allowed in advise", bash("python3 tools/index/query.py edge-seeds Case"), 0, env_mode="advise"),
    Case("story promote blocked in normal", bash("python3 tools/impacts/promote.py ai-context/X --story --confirmed-by lead"), 2, stderr_has=NOT_ON_LIST),
    Case("story promote blocked in build", bash("python3 tools/impacts/promote.py ai-context/X --story --confirmed-by lead"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    # WS10 starting points: validate_design and framework_config are framework scripts; onboard is maintain-only
    # (it can write .ai-framework.json and the knowledge stubs).
    Case("validate_design allowed in normal", bash("python3 tools/designs/validate_design.py --all"), 0),
    Case("framework_config allowed in normal", bash("python3 tools/config/framework_config.py source-root"), 0),
    Case("onboard blocked in normal", bash("python3 tools/onboard/onboard.py --starting-point existing"), 2, stderr_has=NOT_ON_LIST),
    # Salesforce CLI levels.
    Case("normal: sf --version allowed", bash("sf --version"), 0),
    Case("build: sf version allowed", bash("sf version"), 0, env_mode="build"),
    Case("maintain: sf help allowed", bash("sf help org"), 0, env_mode="maintain"),
    Case("normal: sf <topic> --help allowed", bash("sf plugins --help"), 0),
    Case("normal: sf generate into ai-context allowed", bash("sf apex generate class --name Foo --output-dir ai-context/x"), 0),
    Case("normal: sf generate into force-app blocked", bash("sf apex generate class --name Foo --output-dir force-app/main/default/classes"), 2),
    Case("normal: sf generate without output dir blocked", bash("sf apex generate class --name Foo"), 2),
    Case("normal: sf generate -d into ai-context allowed", bash("sf project generate --name x -d ai-context/p"), 0),
    Case("normal: sf generate --output-dir= into force-app blocked", bash("sf apex generate class --name Foo --output-dir=force-app"), 2),
    Case("normal: sf generate -dVALUE into force-app blocked", bash("sf apex generate class --name Foo -dforce-app"), 2),
    Case("normal: sf generate -d with no value blocked", bash("sf apex generate class --name Foo -d"), 2),
    Case("normal: sf generate with a path in --name blocked", bash("sf apex generate class --name ../../x --output-dir ai-context/x"), 2),
    Case("normal: sf generate with an expansion blocked", bash("sf apex generate class --name Foo --output-dir ai-context/x $X"), 2),
    Case("normal: sf generate redirect into force-app blocked", bash("sf apex generate class --name Foo -d ai-context/x > force-app/log"), 2),
    Case("normal: sf lightning generate component allowed", bash("sf lightning generate component --name c --type lwc --output-dir ai-context/l"), 0),
    Case("normal: sf static-resource generate without output dir blocked", bash("sf static-resource generate --name r"), 2),
    Case("normal: sf convert into ai-context allowed", bash("sf project convert source --root-dir force-app --output-dir ai-context/out"), 0),
    Case("normal: sf convert without output dir blocked", bash("sf project convert source --root-dir force-app"), 2),
    Case("normal: sf code-analyzer to ai-context allowed", bash("sf code-analyzer run --workspace force-app --output-file ai-context/r.json"), 0),
    Case("normal: sf code-analyzer --output-file into tools/guard blocked", bash("sf code-analyzer run --output-file tools/guard/policy.json"), 2),
    Case("normal: sf code-analyzer -f into tools/guard blocked", bash("sf code-analyzer run -f tools/guard/policy.json"), 2),
    Case("normal: sf code-analyzer without output allowed", bash("sf code-analyzer run --workspace force-app"), 0),
    Case("maintain: sf generate into docs allowed", bash("sf project generate --name x -d docs/p"), 0, env_mode="maintain"),
    Case("maintain: sf generate into tools/guard blocked", bash("sf project generate --name x -d tools/guard/p"), 2, env_mode="maintain"),
    Case("normal: org command blocked at offline level", bash("sf sobject describe --sobject Account --target-org dev1"), 2, stderr_has="not allowed at level offline"),
    Case("normal: unknown sf subcommand blocked", bash("sf plugins install x"), 2, stderr_has="not allowed at level offline"),
    Case("advise: sf --version blocked at level none", bash("sf --version"), 2, env_mode="advise"),
    Case("advise: sf help blocked at level none", bash("sf help"), 2, env_mode="advise"),
    Case("org-metadata: describe with allowed org allowed", bash("sf sobject describe --sobject Account --target-org dev1"), 0, policy=ORG_META),
    Case("org-metadata: --target-org= form allowed", bash("sf sobject list --target-org=dev1"), 0, policy=ORG_META),
    Case("org-metadata: -o form allowed", bash("sf org list metadata --metadata-type ApexClass -o dev1"), 0, policy=ORG_META),
    Case("org-metadata: metadata-types allowed", bash("sf org list metadata-types -o dev1"), 0, policy=ORG_META),
    Case("org-metadata: retrieve preview allowed", bash("sf project retrieve preview -o dev1"), 0, policy=ORG_META),
    Case("org-metadata: org not in allowed_orgs blocked", bash("sf sobject describe --sobject Account --target-org prod"), 2, policy=ORG_META),
    Case("org-metadata: missing target org blocked", bash("sf sobject describe --sobject Account"), 2, policy=ORG_META, stderr_has="allowed_orgs"),
    Case("org-metadata: --target-org with no value blocked", bash("sf sobject describe --sobject Account --target-org"), 2, policy=ORG_META, stderr_has="allowed_orgs"),
    Case("org-metadata: allowed org then another org blocked", bash("sf sobject describe --sobject Account --target-org dev1 -o prod"), 2, policy=ORG_META),
    Case("org-metadata: attached -oVALUE for another org blocked", bash("sf sobject describe --sobject Account -o dev1 -oprod"), 2, policy=ORG_META),
    Case("org-metadata: org name only in a quoted value does not count", bash("sf sobject describe --sobject '-o dev1'"), 2, policy=ORG_META, stderr_has="allowed_orgs"),
    Case("org-metadata: empty allowed_orgs blocks everything", bash("sf sobject describe --sobject Account -o dev1"), 2,
         policy={"sf": {"mode_level": {"normal": "org-metadata"}}}, stderr_has="allowed_orgs"),
    Case("org-metadata: offline commands need no org", bash("sf --version"), 0, policy=ORG_META),
    Case("org-metadata: data query blocked", bash("sf data query --query 'SELECT Id FROM Account' -o dev1"), 2, policy=ORG_META),
    Case("org-metadata: build mode stays offline", bash("sf sobject describe --sobject Account -o dev1"), 2, env_mode="build", policy=ORG_META),
    Case("org-data: data query allowed", bash("sf data query --query 'SELECT Id FROM Account' -o dev1"), 0, policy=ORG_DATA),
    Case("org-data: levels are cumulative", bash("sf sobject describe --sobject Account -o dev1"), 0, policy=ORG_DATA),
    Case("org-data: data query without org blocked", bash("sf data query --query 'SELECT Id FROM Account'"), 2, policy=ORG_DATA, stderr_has="allowed_orgs"),
    Case("org-data: data query redirect into force-app blocked", bash("sf data query --query 'SELECT Id FROM Account' -o dev1 > force-app/x"), 2, policy=ORG_DATA),
    Case("org-data: deploy always blocked", bash("sf project deploy start -o dev1"), 2, policy=ORG_DATA, stderr_has="always blocked"),
    Case("org-data: org display always blocked", bash("sf org display -o dev1"), 2, policy=ORG_DATA, stderr_has="always blocked"),
    Case("org-data: apex run always blocked", bash("sf apex run -f x.apex -o dev1"), 2, policy=ORG_DATA, stderr_has="always blocked"),
    Case("org-data: data delete always blocked", bash("sf data delete record -s Account -i x -o dev1"), 2, policy=ORG_DATA, stderr_has="always blocked"),
    Case("org-data: retrieve start always blocked", bash("sf project retrieve start -o dev1"), 2, policy=ORG_DATA, stderr_has="always blocked"),
    Case("always blocked beats --help", bash("sf org login web --help"), 2, stderr_has="always blocked"),
    Case("always blocked in advise", bash("sf auth web login"), 2, env_mode="advise"),
    Case("always blocked in build", bash("sf deploy metadata"), 2, env_mode="build", stderr_has="always blocked"),
    Case("always blocked in maintain", bash("sf data bulk upsert"), 2, env_mode="maintain", stderr_has="always blocked"),
    Case("always blocked: sf retrieve", bash("sf retrieve metadata"), 2, stderr_has="always blocked"),
    Case("always blocked: sf login", bash("sf login"), 2, stderr_has="always blocked"),
    Case("always blocked: sf org assign permset", bash("sf org assign permset --name x"), 2, stderr_has="always blocked"),
    Case("always blocked: sf project delete", bash("sf project delete source"), 2, stderr_has="always blocked"),
    Case("sf: later segment is checked", bash("git status && sf org login web"), 2, stderr_has="always blocked"),
    Case("sf: if condition is checked", bash("if sf org login web; then ls; fi"), 2, stderr_has="always blocked"),
    Case("sf: env assignment before sf blocked", bash("X=1 sf --version"), 2),
    Case("sf: path-qualified sf blocked", bash("/usr/local/bin/sf --version"), 2, stderr_has="plain"),
    Case("sf: upper-case SF blocked", bash("SF --version"), 2, stderr_has="plain"),
    Case("sf: wrapped in env blocked", bash("env sf --version"), 2),
    Case("sf: wrapped in xargs blocked", bash("echo x | xargs sf --version"), 2),
    Case("sf: word sf as an argument is not a command", bash("echo sf org login"), 0),
    Case("sf: word sf in a query helper argument is not a command", bash("python3 tools/index/query.py sf"), 0),
    Case("sfdx still blocked", bash("sfdx force:org:list"), 2, env_mode="maintain"),
    Case("sfdx blocked as an argument too", bash("echo sfdx"), 2),
]


def at(cwd, cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "@PROJECT@/" + cwd}


SUB = {"ai-context/x/.keep": ""}
QUERY_ACCOUNT = '-q "SELECT Id FROM Account"'
# Fix round 1 (review findings C1, C2, I1, I2, I4, M2). Every bypass payload expects 2; the positives must still pass.
FIX_CASES = [
    # C1: help is only the exact token form; topic:command spellings and the force topic are blocked.
    Case("C1: --file value ending in -h", bash(f'sf data query {QUERY_ACCOUNT} -o prod --file "ai-context/q -h"'), 2),
    Case("C1: -- -h after an org flag", bash(f"sf data query {QUERY_ACCOUNT} -o prod -- -h"), 2),
    Case("C1: apex:run topic spelling", bash('sf apex:run -o prod --file "ai-context/x.apex -h"'), 2),
    Case("C1: apex run with a quoted -h", bash('sf apex run -o prod --file "ai-context/x.apex -h"'), 2),
    Case("C1: project:deploy:start --help", bash("sf project:deploy:start -o dev1 --help"), 2),
    Case("C1: project deploy start --help stays always blocked", bash("sf project deploy start -o dev1 --help"), 2, stderr_has="always blocked"),
    Case("C1: data:query topic spelling", bash(f"sf data:query {QUERY_ACCOUNT} -o prod"), 2),
    Case("C1: org:display topic spelling", bash("sf org:display -o dev1"), 2),
    Case("C1: force topic", bash("sf force apex execute -o dev1 -f x.apex -h"), 2),
    Case("C1: plugins install with a quoted -h", bash('sf plugins install evil "x -h"'), 2),
    Case("C1: plugins install with -- -h", bash("sf plugins install evil -- -h"), 2),
    Case("C1: config set with -- -h", bash("sf config set target-org=prod -- -h"), 2),
    Case("C1: --help=x is not the help form", bash("sf org display --help=x"), 2),
    Case("C1: help with a flag before -h is not the help form", bash("sf data query -q x -h"), 2),
    Case("C1: data query --help allowed", bash("sf data query --help"), 0),
    Case("C1: data query -h allowed", bash("sf data query -h"), 0),
    Case("C1: org list auth -h allowed", bash("sf org list auth -h"), 0),
    Case("C1: help is not allowed at level none", bash("sf data query --help"), 2, env_mode="advise"),
    # C2: any org flag needs an org-level command and an allowed alias.
    Case("C2: --from-org at offline", bash("sf project generate manifest --from-org prod -d ai-context/x"), 2),
    Case("C2: --from-org= at offline", bash("sf project generate manifest --from-org=prod -d ai-context/x"), 2),
    Case("C2: --from-org with an allowed alias still needs an org-level command", bash("sf project generate manifest --from-org dev1 -d ai-context/x"), 2, policy=ORG_META),
    Case("C2: --source-org at offline", bash("sf apex generate class --name Foo -d ai-context/x --source-org prod"), 2),
    Case("C2: -u at offline", bash("sf apex generate class --name Foo -d ai-context/x -u prod"), 2),
    Case("C2: --targetusername= at offline", bash("sf apex generate class --name Foo -d ai-context/x --targetusername=prod"), 2),
    Case("C2: -v at offline", bash("sf apex generate class --name Foo -d ai-context/x -v prod"), 2),
    Case("C2: --target-dev-hub at offline", bash("sf apex generate class --name Foo -d ai-context/x --target-dev-hub prod"), 2),
    Case("C2: --target-dev-hub-username at offline", bash("sf apex generate class --name Foo -d ai-context/x --target-dev-hub-username prod"), 2),
    Case("C2: attached -oVALUE at offline", bash("sf apex generate class --name Foo -d ai-context/x -oprod"), 2),
    Case("C2: generate manifest without an org flag allowed", bash("sf project generate manifest -d ai-context/x --source-dir force-app"), 0),
    Case("C2: -o dev1 with an allowed alias at org-metadata", bash("sf sobject describe -s Account -o dev1"), 0, policy=ORG_META),
    Case("C2: --from-org on an org command with an allowed alias", bash("sf sobject describe -s Account --from-org dev1"), 0, policy=ORG_META),
    Case("C2: a second org flag naming another org", bash("sf sobject describe -s Account -o dev1 -u prod"), 2, policy=ORG_META),
    Case("C2: --targetusername naming another org", bash("sf sobject describe -s Account -o dev1 --targetusername prod"), 2, policy=ORG_META),
    Case("C2: -v naming another org", bash("sf sobject describe -s Account -o dev1 -v prod"), 2, policy=ORG_META),
    Case("C2: --target-dev-hub-username= naming another org", bash("sf sobject describe -s Account -o dev1 --target-dev-hub-username=prod"), 2, policy=ORG_META),
    Case("C2: --flags-dir blocked on an org command", bash(f"sf data query {QUERY_ACCOUNT} -o dev1 --flags-dir ai-context/f"), 2, policy=ORG_DATA, stderr_has="always blocked"),
    Case("C2: --flags-dir= blocked at offline", bash("sf code-analyzer run --flags-dir=ai-context/f"), 2, stderr_has="always blocked"),
    # I1: scripts and pnpm run only from the project root, and the script must resolve under the allowed roots.
    Case("I1: cd then query helper", bash("cd ai-context/x && python3 tools/index/query.py stamp"), 2, files=SUB, stderr_has="project root"),
    Case("I1: cd then skill script", bash("cd ai-context/x; python3 framework/skills/a/scripts/b.py"), 2, files=SUB, stderr_has="project root"),
    Case("I1: payload cwd in ai-context then query helper", at("ai-context/x", "python3 tools/index/query.py stamp"), 2, files=SUB, stderr_has="project root"),
    Case("I1: cd then pnpm test in build", bash("cd ai-context/x && pnpm test"), 2, env_mode="build", files=SUB, stderr_has="project root"),
    Case("I1: payload cwd then pnpm test in build", at("ai-context/x", "pnpm test"), 2, env_mode="build", files=SUB, stderr_has="project root"),
    Case("I1: payload cwd then workspace script in maintain", at("ai-context/x", "python3 ai-context/ws0/sdd/mkpatch.py a"), 2, env_mode="maintain", files=SUB),
    Case("I1: pushd then script", bash("pushd ai-context/x; python3 tools/index/query.py stamp"), 2, env_mode="maintain", files=SUB),
    Case("I1: cd in advise then query helper", bash("cd ai-context/x && python3 tools/index/query.py stamp"), 2, env_mode="advise", files=SUB),
    Case("I1: payload cwd in advise then query helper", at("ai-context/x", "python3 tools/index/query.py stamp"), 2, env_mode="advise", files=SUB),
    Case("I1: payload cwd at the root in advise allowed", at("", "python3 tools/index/query.py stamp"), 0, env_mode="advise"),
    Case("I1: query helper from the root allowed", bash("python3 tools/index/query.py stamp"), 0),
    Case("I1: cd later in the line does not affect an earlier script", bash("python3 tools/index/query.py stamp && cd docs"), 0, env_mode="maintain"),
    Case("I1: cd then a non-script command still allowed", bash("cd docs && ls"), 0, env_mode="maintain"),
    # I2: pnpm tools write where --write, -w or --fix say; config and plugin options load code.
    Case("I2: prettier --write tools/guard", bash("pnpm exec prettier --write tools/guard/guard.py"), 2, env_mode="build"),
    Case("I2: prettier --write tools/guard in maintain", bash("pnpm exec prettier --write tools/guard/guard.py"), 2, env_mode="maintain"),
    Case("I2: eslint --fix tools/guard", bash("pnpm exec eslint --fix tools/guard/guard.py"), 2, env_mode="build"),
    Case("I2: prettier --write settings.json", bash("pnpm exec prettier --write .claude/settings.json"), 2, env_mode="build"),
    Case("I2: prettier -w tools/guard", bash("pnpm exec prettier -w tools/guard/guard.py"), 2, env_mode="build"),
    Case("I2: prettier --write after --", bash("pnpm exec prettier --write -- tools/guard/guard.py"), 2, env_mode="build"),
    Case("I2: prettier --write glob onto tools/guard", bash('pnpm exec prettier --write "tools/gua*/guard.py"'), 2, env_mode="build", files={"tools/guard/guard.py": "x"}),
    Case("I2: prettier --write . reaches tools/guard", bash("pnpm exec prettier --write ."), 2, env_mode="maintain", files={"tools/guard/guard.py": "x"}),
    Case("I2: prettier --write with an expansion", bash("pnpm exec prettier --write $F"), 2, env_mode="build"),
    Case("I2: prettier --write into ai-context allowed", bash("pnpm exec prettier --write ai-context/x/a.md"), 0, env_mode="build"),
    Case("I2: prettier --check . stays allowed", bash("pnpm exec prettier --check ."), 0, env_mode="build"),
    Case("I2: prettier -c is --check", bash("pnpm exec prettier -c ."), 0, env_mode="build"),
    Case("I2: eslint -c loads a config", bash("pnpm exec eslint -c ai-context/x/c.js ."), 2, env_mode="build"),
    Case("I2: eslint --config loads a config", bash("pnpm exec eslint --config=ai-context/x/c.js ."), 2, env_mode="build"),
    Case("I2: eslint --plugin loads code", bash("pnpm exec eslint --plugin x ."), 2, env_mode="build"),
    Case("I2: eslint --rulesdir loads code", bash("pnpm exec eslint --rulesdir ai-context/r ."), 2, env_mode="build"),
    Case("I2: eslint --resolve-plugins-relative-to", bash("pnpm exec eslint --resolve-plugins-relative-to ai-context/r ."), 2, env_mode="build"),
    Case("I2: prettier --config loads code", bash("pnpm exec prettier --config ai-context/x/p.js --check ."), 2, env_mode="build"),
    Case("I2: eslint -o output file in tools/guard", bash("pnpm exec eslint -o tools/guard/out.txt ."), 2, env_mode="build"),
    Case("I2: eslint --output-file into ai-context allowed", bash("pnpm exec eslint --output-file ai-context/x/out.txt ."), 0, env_mode="build"),
    # I4: file and output flags on every sf command are write targets.
    Case("I4: -f onto tools/guard at org-data", bash("sf org list metadata -m ApexClass -o dev1 -f tools/guard/policy.json"), 2, policy=ORG_DATA),
    Case("I4: --file onto tools/guard", bash(f"sf data query {QUERY_ACCOUNT} -o dev1 --file tools/guard/policy.json"), 2, policy=ORG_DATA),
    Case("I4: -fVALUE onto tools/guard", bash("sf org list metadata -m ApexClass -o dev1 -ftools/guard/policy.json"), 2, policy=ORG_DATA),
    Case("I4: --output-file onto tools/guard", bash("sf org list metadata -m ApexClass -o dev1 --output-file tools/guard/policy.json"), 2, policy=ORG_DATA),
    Case("I4: --file= onto force-app", bash(f"sf data query {QUERY_ACCOUNT} -o dev1 --file=force-app/q.soql"), 2, policy=ORG_DATA),
    Case("I4: -f with no value", bash("sf org list metadata -m ApexClass -o dev1 -f"), 2, policy=ORG_DATA),
    Case("I4: -f from ai-context still allowed", bash("sf org list metadata -m ApexClass -o dev1 -f ai-context/in.json"), 0, policy=ORG_DATA),
    Case("I4: --file from ai-context still allowed", bash("sf data query --file ai-context/q.soql -o dev1"), 0, policy=ORG_DATA),
    # M2: a code-analyzer config file can name anything to load.
    Case("M2: --config-file", bash("sf code-analyzer run --config-file ai-context/c.yml"), 2),
    Case("M2: --config-file=", bash("sf code-analyzer run --config-file=ai-context/c.yml"), 2),
    Case("M2: -c", bash("sf code-analyzer run -c ai-context/c.yml"), 2),
]

# Fix round 2 (re-review New-1 .. New-5).
FIX2_CASES = [
    # New-1: pnpm tools need "exec".
    Case("New-1: bare pnpm prettier --write", bash("pnpm prettier --write tools/guard/guard.py"), 2, env_mode="build", stderr_has="blocked pattern"),
    Case("New-1: bare pnpm eslint --fix", bash("pnpm eslint --fix tools/guard/x.js"), 2, env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("New-1: bare pnpm jest", bash("pnpm jest"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("New-1: bare pnpm sfdx-lwc-jest", bash("pnpm sfdx-lwc-jest"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("New-1: pnpm exec prettier --check src/x.js allowed", bash("pnpm exec prettier --check src/x.js"), 0, env_mode="build"),
    # New-2: every sf segment runs from the project root.
    Case("New-2: sf code-analyzer run from the root allowed", bash("sf code-analyzer run"), 0),
    Case("New-2: sf code-analyzer run from ai-context/x", at("ai-context/x", "sf code-analyzer run"), 2, files=SUB, stderr_has="project root"),
    Case("New-2: cd then sf code-analyzer run", bash("cd ai-context/x && sf code-analyzer run"), 2, files=SUB, stderr_has="project root"),
    Case("New-2: sf --version from a subdirectory", at("ai-context/x", "sf --version"), 2, files=SUB, stderr_has="project root"),
    Case("New-2: sf generate from a subdirectory", at("ai-context/x", "sf apex generate class --name Foo -d ai-context/x"), 2, files=SUB, stderr_has="project root"),
    Case("New-2: pushd then sf", bash("pushd ai-context/x; sf --version"), 2, env_mode="maintain", files=SUB),
    # New-3: jest output paths are write targets; root and update options are unknown.
    Case("New-3: jest --coverageDirectory tools/guard", bash("pnpm exec jest --coverageDirectory tools/guard --coverage"), 2, env_mode="build"),
    Case("New-3: jest --coverageDirectory= tools/guard", bash("pnpm exec jest --coverageDirectory=tools/guard --coverage"), 2, env_mode="build"),
    Case("New-3: jest --outputFile tools/guard", bash("pnpm exec jest --outputFile tools/guard/x.json --json"), 2, env_mode="build"),
    Case("New-3: jest --cacheDirectory tools/guard", bash("pnpm exec jest --cacheDirectory tools/guard"), 2, env_mode="build"),
    Case("New-3: pnpm test -- --coverageDirectory", bash("pnpm test -- --coverageDirectory tools/guard --coverage"), 2, env_mode="build"),
    Case("New-3: pnpm run test -- --outputFile", bash("pnpm run test -- --outputFile tools/guard/x.json"), 2, env_mode="build"),
    Case("New-3: sfdx-lwc-jest -- --coverageDirectory", bash("pnpm exec sfdx-lwc-jest -- --coverageDirectory tools/guard"), 2, env_mode="build"),
    Case("New-3: jest -u", bash("pnpm exec jest -u"), 2, env_mode="build"),
    Case("New-3: jest --updateSnapshot", bash("pnpm exec jest --updateSnapshot"), 2, env_mode="build"),
    Case("New-3: pnpm run test -- -u", bash("pnpm run test -- -u"), 2, env_mode="build"),
    Case("New-3: jest --rootDir", bash("pnpm exec jest --rootDir ai-context/x"), 2, env_mode="build"),
    Case("New-3: jest --roots", bash("pnpm exec jest --roots ai-context/x"), 2, env_mode="build"),
    Case("New-3: jest --config", bash("pnpm exec jest --config ai-context/j.js"), 2, env_mode="build"),
    Case("New-3: jest --coverage allowed (default coverage/ dir is a documented limit)", bash("pnpm exec jest --coverage"), 0, env_mode="build"),
    Case("New-3: jest --coverageDirectory into ai-context allowed", bash("pnpm exec jest --coverageDirectory ai-context/x/cov"), 0, env_mode="build"),
    Case("New-3: pnpm test allowed", bash("pnpm test"), 0, env_mode="build"),
    Case("New-3: pnpm test -- --coverage allowed", bash("pnpm test -- --coverage"), 0, env_mode="build"),
    # New-4: odd org-ish flag names on sf commands.
    Case("New-4: --target", bash("sf sobject describe -s Account -o dev1 --target prod"), 2, policy=ORG_META),
    Case("New-4: --targe", bash("sf sobject describe -s Account -o dev1 --targe prod"), 2, policy=ORG_META),
    Case("New-4: --targetdevhubusername", bash("sf sobject describe -s Account -o dev1 --targetdevhubusername prod"), 2, policy=ORG_META),
    Case("New-4: --targetdevhubusername at offline", bash("sf apex generate class --name Foo -d ai-context/x --targetdevhubusername prod"), 2),
    Case("New-4: --username", bash("sf sobject describe -s Account -o dev1 --username prod"), 2, policy=ORG_META),
    Case("New-4: --organization", bash("sf sobject describe -s Account -o dev1 --organization prod"), 2, policy=ORG_META),
    Case("New-4: a known org flag is not caught by the name rule", bash("sf sobject describe -s Account --target-org dev1"), 0, policy=ORG_META),
    # New-5: --write= and --fix= forms; no extra arguments on pnpm scripts.
    Case("New-5: --write=", bash("pnpm exec prettier --write=tools/guard/x.js"), 2, env_mode="build"),
    Case("New-5: --fix=", bash("pnpm exec eslint --fix=tools/guard/x.js"), 2, env_mode="build"),
    Case("New-5: pnpm test --dir", bash("pnpm test --dir ai-context/x"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("New-5: pnpm -C dir test", bash("pnpm -C ai-context/x test"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("New-5: pnpm lint --fix", bash("pnpm lint --fix"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("New-5: pnpm run format extra args", bash("pnpm run format tools/guard"), 2, env_mode="build", stderr_has=NOT_ON_LIST),
    Case("New-5: pnpm lint alone allowed", bash("pnpm lint"), 0, env_mode="build"),
    Case("New-5: pnpm run format alone allowed", bash("pnpm run format"), 0, env_mode="build"),
]

# Fix round 3 (re-review R1): jest accepts kebab-case and short-flag groups.
FIX3_CASES = [Case(f"R1: {cmd}", bash(cmd), 2, env_mode="build") for cmd in (
    "pnpm exec jest --coverage-directory tools/guard --coverage",
    "pnpm exec jest --coverage-directory=tools/guard --coverage",
    "pnpm exec jest --output-file tools/guard/x.json --json",
    "pnpm exec jest --cache-directory tools/guard",
    "pnpm exec jest --root-dir ai-context/x",
    "pnpm exec jest --update-snapshot",
    "pnpm exec jest --updateSnapshot=true",
    "pnpm exec jest -ui",
    "pnpm exec jest -iu",
    "pnpm exec jest --ci=false -u",
    "pnpm exec jest --coverageDirectory=tools/guard --coverage",
    "pnpm exec jest --coverageDirectory ./tools/guard",
    "pnpm exec jest --coverageDirectory force-app/x",
    "pnpm exec jest --watchman=false --cacheDirectory=tools/guard",
    "pnpm exec sfdx-lwc-jest --coverage -- --coverageDirectory tools/guard",
    "pnpm exec sfdx-lwc-jest -- --coverage-directory tools/guard",
    "pnpm exec sfdx-lwc-jest -u",
    "pnpm exec sfdx-lwc-jest --update-snapshot",
    "pnpm test -- --coverage-directory tools/guard",
    "pnpm test -- --coverageDirectory=tools/guard",
    "pnpm test -- --cacheDirectory tools/guard",
    "pnpm test -- -u",
    "pnpm test -- -ui",
    "pnpm run test -- --rootDir x",
    "pnpm run test -- --root-dir x",
    # Options that load code.
    "pnpm exec jest --reporters ai-context/r.js",
    "pnpm exec jest --setupFiles ai-context/s.js",
    "pnpm exec jest --setup-files ai-context/s.js",
    "pnpm exec jest --setupFilesAfterEnv ai-context/s.js",
    "pnpm exec jest --setupFilesAfterEach ai-context/s.js",
    "pnpm exec jest --globalSetup ai-context/s.js",
    "pnpm exec jest --global-setup ai-context/s.js",
    "pnpm exec jest --globalTeardown ai-context/s.js",
    "pnpm exec jest --testRunner ai-context/r.js",
    "pnpm exec jest --test-runner ai-context/r.js",
    "pnpm exec jest --transform ai-context/t.js",
    "pnpm exec jest --testResultsProcessor ai-context/p.js",
    "pnpm exec jest --test-results-processor ai-context/p.js",
    "pnpm exec jest --projects ai-context/x",
    "pnpm exec jest --config ai-context/j.js",
    "pnpm exec jest -c ai-context/j.js",
    "pnpm test -- --setup-files ai-context/s.js",
    "pnpm exec eslint --format ai-context/f.js force-app",
    "pnpm exec eslint --format=ai-context/f force-app",
    "pnpm exec eslint -f custom.cjs force-app",
    "pnpm exec eslint --format x.mjs force-app",
)] + [
    Case("R1: jest --coverage allowed", bash("pnpm exec jest --coverage"), 0, env_mode="build"),
    Case("R1: jest -i allowed", bash("pnpm exec jest -i"), 0, env_mode="build"),
    # Round 4 ruling: only exact spellings are allowed, so these kebab forms are now blocked.
    Case("R1: jest --coverage-directory into ai-context blocked (kebab spelling)", bash("pnpm exec jest --coverage-directory ai-context/x/cov"), 2, env_mode="build"),
    Case("R1: jest --run-in-band blocked (kebab spelling)", bash("pnpm exec jest --run-in-band"), 2, env_mode="build"),
    Case("R1: eslint --format stylish allowed", bash("pnpm exec eslint --format stylish force-app"), 0, env_mode="build"),
    Case("R1: eslint -f stylish allowed", bash("pnpm exec eslint -f stylish force-app"), 0, env_mode="build"),
]

# Fix round 4: jest and sfdx-lwc-jest flags are an exact-spelling allowlist (yargs rewrites names).
FIX4_CASES = [Case(f"R4: {cmd}", bash(cmd), 2, env_mode="build") for cmd in (
    "pnpm exec jest --COVERAGE-DIRECTORY tools/guard",
    "pnpm exec jest --coverage--directory tools/guard",
    "pnpm exec jest --coverage_directory- tools/guard",
    "pnpm exec jest --coverage-_directory tools/guard",
    "pnpm exec jest --Coverage-Directory tools/guard --coverage",
    "pnpm exec jest --coverage_directory tools/guard --coverage",
    "pnpm exec jest --CACHE-DIRECTORY tools/guard",
    "pnpm exec jest --cache--directory tools/guard",
    "pnpm exec jest --SETUP-FILES ai-context/s.js",
    "pnpm exec jest --global--setup ai-context/s.js",
    "pnpm exec jest --UPDATE-SNAPSHOT",
    "pnpm exec jest -u1",
    "pnpm exec jest -u=true",
    "pnpm exec jest --coverageDirectory.x tools/guard",
    "pnpm exec sfdx-lwc-jest -- --COVERAGE-DIRECTORY tools/guard",
    "pnpm test -- -- --coverage-directory tools/guard",
    "pnpm test -- --coverage -- --coverage-directory tools/guard",
    "pnpm exec jest --coverage-directory ai-context/x/cov",
    "pnpm exec jest --run-in-band",
    "pnpm exec jest --ci=false",
    "pnpm exec jest -t",
    "pnpm exec jest -t --coverage-directory tools/guard",
    "pnpm exec jest --testNamePattern --coverage-directory tools/guard",
    "pnpm exec jest -w 2 --watch",
    "pnpm exec jest -ib",
    "pnpm exec jest --Coverage",
)] + [
    Case("R4: jest --coverageDirectory still a write target", bash("pnpm exec jest --coverageDirectory ai-context/a --coverageDirectory tools/guard"), 2, env_mode="build"),
] + [Case(f"R4: {cmd} allowed", bash(cmd), 0, env_mode="build") for cmd in (
    "pnpm exec jest --coverage",
    "pnpm exec jest -i",
    "pnpm exec jest --coverageDirectory ai-context/x/cov --coverage",
    "pnpm exec jest --runInBand --ci",
    "pnpm test",
    "pnpm test -- --coverage",
    "pnpm exec sfdx-lwc-jest -- --coverage",
    "pnpm exec jest force-app/lwc/x",
    "pnpm exec jest --no-cache --coverage --silent --verbose --json --passWithNoTests --detectOpenHandles --colors",
    "pnpm exec jest --maxWorkers=2 --bail=1 --testNamePattern=foo",
    "pnpm exec jest --maxWorkers 50% --testNamePattern foo force-app/lwc/x",
    "pnpm exec jest -t foo -w 2 -b -e",
    "pnpm exec jest --outputFile=ai-context/x/r.json --json --cacheDirectory ai-context/x/c",
)]

# A payload the guard ALLOWS, so exit 2 can only come from the wrapper's fail-closed branch.
TRIPWIRE_CASES = [
    Case("tripwire: edited guard blocks writes", write("ai-context/x.md"), 2, dirty=("tools/guard/guard.py",), stderr_has="commit or revert"),
    Case("tripwire: new file in tools/guard blocks", write("ai-context/x.md"), 2, dirty=("tools/guard/evil.py",)),
    Case("tripwire: edited settings blocks maintain", write("docs/x.md"), 2, env_mode="maintain", dirty=(".claude/settings.json",)),
    Case("tripwire: edited workflow blocks", bash("make docs"), 2, env_mode="maintain", dirty=(".github/workflows/ci.yml",)),
    Case("tripwire: edited workflow blocks an allowed bash command", bash("git add docs/x"), 2, env_mode="maintain",
         dirty=(".github/workflows/ci.yml",), stderr_has="commit or revert"),
    Case("tripwire: read-only bash still allowed", bash("git status"), 0, dirty=("tools/guard/guard.py",)),
    Case("tripwire: read-only bash allowed in advise too", bash("ls"), 0, env_mode="advise", dirty=("tools/guard/guard.py",)),
    Case("tripwire: dirty file elsewhere does not trip", write("ai-context/x.md"), 0, dirty=("docs/x.md",)),
    Case("tripwire: CODEOWNERS blocks writes", write("ai-context/x.md"), 2, dirty=("CODEOWNERS",)),
    Case("tripwire: names the dirty file", write("ai-context/x.md"), 2, dirty=("tools/guard/evil.py",), stderr_has="tools/guard/evil.py"),
    Case("tripwire: webfetch is not a write", fetch("https://help.salesforce.com/x"), 0, dirty=("tools/guard/guard.py",)),
    Case("tripwire: changed .git/config blocks", write("ai-context/x.md"), 2, dirty=(".git/config",), stderr_has="rebaseline"),
    Case("tripwire: changed .git/config blocks bash", bash("git add docs/x"), 2, env_mode="maintain", dirty=(".git/config",)),
    Case("tripwire: new git hook blocks", write("ai-context/x.md"), 2, dirty=(".git/hooks/pre-commit",)),
    Case("tripwire: edited sample hook blocks", write("ai-context/x.md"), 2, dirty=(".git/hooks/pre-commit.sample",)),
    Case("tripwire: missing baseline blocks", write("ai-context/x.md"), 2, files={".git/ai-guard-baseline": None}, stderr_has="rebaseline"),
    Case("tripwire: unreadable baseline blocks", write("ai-context/x.md"), 2, files={".git/ai-guard-baseline": "garbage"}),
    Case("tripwire: outside a git checkout fails closed", write("ai-context/x.md"), 2, git=False, stderr_has="cannot verify"),
    Case("tripwire: outside a git checkout still allows read-only bash", bash("ls"), 0, git=False),
    Case("tripwire: clean tree allows writes", write("ai-context/x.md"), 0),
]
FSMON = "[core]\n\tfsmonitor = touch PWNED; false\n"
REMOTE = '[remote "origin"]\n\turl = https://example.com/x.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
UPSTREAM = '[branch "main"]\n\tremote = origin\n\tmerge = refs/heads/main\n\trebase = true\n'
REBASELINE_CASES = [
    # C1: even read-only git runs a planted core.fsmonitor, so no git while .git cannot be trusted
    Case("C1: git status with a planted fsmonitor blocked", bash("git status"), 2, git_append={".git/config": FSMON}, stderr_has="rebaseline"),
    Case("C1: git diff with a planted fsmonitor blocked", bash("git diff"), 2, git_append={".git/config": FSMON}, stderr_has="rebaseline"),
    Case("C1: git log in advise with a planted fsmonitor blocked", bash("git log"), 2, env_mode="advise", git_append={".git/config": FSMON}),
    Case("C1: git status in maintain with a planted fsmonitor blocked", bash("git status"), 2, env_mode="maintain", git_append={".git/config": FSMON}),
    Case("C1: git after ls in a chain blocked", bash("ls && git status"), 2, git_append={".git/config": FSMON}),
    Case("C1: ls with a planted fsmonitor still allowed", bash("ls"), 0, git_append={".git/config": FSMON}),
    Case("C1: git status with no baseline blocked", bash("git status"), 2, files={".git/ai-guard-baseline": None}, stderr_has="rebaseline"),
    Case("C1: git status outside a checkout blocked", bash("git status"), 2, git=False, stderr_has="cannot verify"),
    Case("C1: git status in a clean checkout allowed", bash("git status"), 0),
    # C2: the assistant cannot run guard.py at all
    Case("C2: rebaseline in maintain blocked", bash("python3 tools/guard/guard.py --rebaseline"), 2, env_mode="maintain"),
    Case("C2: rebaseline via py -3 in maintain blocked", bash("py -3 tools/guard/guard.py --rebaseline"), 2, env_mode="maintain"),
    Case("C2: rebaseline in build blocked", bash("python3 tools/guard/guard.py --rebaseline"), 2, env_mode="build"),
    Case("C2: rebaseline in normal blocked", bash("python3 tools/guard/guard.py --rebaseline"), 2),
    Case("C2: rebaseline after another script blocked", bash("python3 tools/evil.py && python3 tools/guard/guard.py --rebaseline"), 2, env_mode="maintain"),
    Case("C2: rebaseline from inside tools/guard blocked", bash("cd tools/guard && python3 guard.py --rebaseline"), 2, env_mode="maintain"),
    Case("C2: rebaseline through a glob blocked", bash("python3 tools/guard/gu?rd.py --rebaseline"), 2, env_mode="maintain"),
    Case("C2: rebaseline in advise blocked", bash("python3 tools/guard/guard.py --rebaseline"), 2, env_mode="advise"),
    Case("C2: any run of guard.py blocked", bash("python3 tools/guard/guard.py"), 2, env_mode="maintain"),
    Case("C2: test_guard.py is not guard.py", bash("python3 tools/guard/test_guard.py"), 0),
    # I1: a linked worktree has a .git file
    Case("I1: worktree clean write allowed", write("ai-context/x.md"), 0, worktree=True),
    Case("I1: worktree read-only git allowed", bash("git status"), 0, worktree=True),
    Case("I1: worktree edited guard blocks", write("ai-context/x.md"), 2, worktree=True, dirty=("tools/guard/guard.py",), stderr_has="commit or revert"),
    Case("I1: worktree with a changed common config blocks git", bash("git status"), 2, worktree=True, git_append={".git/config": FSMON}),
    Case("I1: worktree with a changed common config blocks writes", write("ai-context/x.md"), 2, worktree=True, git_append={".git/config": FSMON},
         stderr_has="rebaseline"),
    # I2: includes and hooksPath are part of the baseline
    Case("I2: include target unchanged allowed", write("ai-context/x.md"), 0,
         files={"docs/inc.cfg": "[x]\n\ta = 1\n"}, pre_git={".git/config": "[include]\n\tpath = ../docs/inc.cfg\n"}),
    Case("I2: changed include target blocks", write("ai-context/x.md"), 2, dirty=("docs/inc.cfg",), stderr_has="rebaseline",
         files={"docs/inc.cfg": "[x]\n\ta = 1\n"}, pre_git={".git/config": "[include]\n\tpath = ../docs/inc.cfg\n"}),
    Case("I2: changed includeIf target blocks", write("ai-context/x.md"), 2, dirty=("docs/inc.cfg",),
         files={"docs/inc.cfg": "[x]\n\ta = 1\n"}, pre_git={".git/config": '[includeIf "gitdir:/"]\n\tpath = ../docs/inc.cfg\n'}),
    Case("I2: include target created later blocks", write("ai-context/x.md"), 2, git_append={".git/config": "[include]\n\tpath = ../docs/new.cfg\n"}),
    Case("I2: hooksPath file unchanged allowed", write("ai-context/x.md"), 0,
         files={".husky/pre-commit": "x"}, pre_git={".git/config": "[core]\n\thooksPath = .husky\n"}),
    Case("I2: changed file under hooksPath blocks", write("ai-context/x.md"), 2, dirty=(".husky/pre-commit",),
         files={".husky/pre-commit": "x"}, pre_git={".git/config": "[core]\n\thooksPath = .husky\n"}),
    Case("I2: new file under hooksPath blocks", write("ai-context/x.md"), 2, dirty=(".husky/post-commit",),
         files={".husky/pre-commit": "x"}, pre_git={".git/config": "[core]\n\thooksPath = .husky\n"}),
    Case("I2: unparseable config fails closed", write("ai-context/x.md"), 2, git_append={".git/config": "[core\n"}, stderr_has="cannot verify"),
    # I3: the keys git rewrites itself do not trip the wire
    Case("I3: adding a remote url allowed", write("ai-context/x.md"), 0, git_append={".git/config": REMOTE}),
    Case("I3: setting an upstream allowed", write("ai-context/x.md"), 0, git_append={".git/config": REMOTE + UPSTREAM}),
    Case("I3: remote uploadpack blocks", write("ai-context/x.md"), 2, git_append={".git/config": '[remote "x"]\n\tuploadpack = evil\n'}),
    Case("I3: remote receivepack blocks", write("ai-context/x.md"), 2, git_append={".git/config": REMOTE + "\treceivepack = evil\n"}),
    Case("I3: other branch keys block", write("ai-context/x.md"), 2, git_append={".git/config": '[branch "main"]\n\tpushremote = evil\n'}),
    # minors
    Case("missing hooks directory counts as empty", write("ai-context/x.md"), 0, pre_remove=(".git/hooks",)),
    Case("skip-worktree on a dirty guard file blocks", write("ai-context/x.md"), 2, dirty=("tools/guard/.keep",), stderr_has="skip-worktree",
         after=(("update-index", "--skip-worktree", "tools/guard/.keep"),)),
    Case("assume-unchanged on a dirty workflow blocks", write("ai-context/x.md"), 2, dirty=(".github/workflows/.keep",), stderr_has="assume-unchanged",
         after=(("update-index", "--assume-unchanged", ".github/workflows/.keep"),)),
    Case("GIT_DIR in the environment does not blind the tripwire", write("ai-context/x.md"), 0, env={"GIT_DIR": "/nonexistent"}),
    Case("GIT_DIR in the environment does not hide a dirty file", write("ai-context/x.md"), 2, dirty=("tools/guard/guard.py",), env={"GIT_DIR": "/nonexistent"}),
]
ROUND2_CASES = [
    Case("C2: quoted guard.py token blocked", bash("python3 tools/guard/guard''.py --rebasel''ine"), 2, env_mode="maintain"),
    Case("C2: split-quoted guard.py token blocked", bash('python3 tools/guard/gu"ard".py'), 2, env_mode="maintain"),
    Case("C2: quoted --rebaseline blocked", bash("python3 tools/x.py --rebasel''ine"), 2, env_mode="maintain"),
    Case("C2: backslashed --rebaseline blocked", bash("python3 tools/x.py \\-\\-rebaseline"), 2, env_mode="maintain"),
    Case("C2: quoted guard.py in build blocked", bash("cat tools/guard/guard''.py"), 2, env_mode="build"),
]
for _name, _cfg in (
        ("trailing comment", "path = ../ai-context/k.cfg ; note"),
        ("quoted with hash comment", 'path = "../ai-context/k.cfg"#x'),
        ("partly quoted", 'path = ../ai-context/"k.cfg"'),
        ("backslash", "path = ..\\ai-context\\k.cfg"),
        ("hash comment", "path = ../ai-context/k.cfg # note")):
    for _tool, _payload in (("write", write("ai-context/x.md")), ("git status", bash("git status"))):
        ROUND2_CASES.append(Case(f"I2: include.path {_name} fails closed ({_tool})", _payload, 2, files={"ai-context/k.cfg": "[core]\n\tfsmonitor = x\n"},
                                 git_append={".git/config": f"[include]\n\t{_cfg}\n"}, stderr_has="simplify"))
for _tool, _payload in (("write", write("ai-context/x.md")), ("git status", bash("git status"))):
    ROUND2_CASES += [
        Case(f"I2: includeIf path with a comment fails closed ({_tool})", _payload, 2,
             git_append={".git/config": '[includeIf "gitdir:/"]\n\tpath = ../ai-context/k.cfg ; note\n'}, stderr_has="simplify"),
        Case(f"I2: hooksPath with a comment fails closed ({_tool})", _payload, 2,
             git_append={".git/config": "[core]\n\thooksPath = ai-context/hk ; husky\n"}, stderr_has="simplify"),
        Case(f"I2: quoted hooksPath fails closed ({_tool})", _payload, 2,
             git_append={".git/config": '[core]\n\thooksPath = "ai-context/hk"\n'}, stderr_has="simplify"),
    ]
def tool(name, **inp):
    return {"tool_name": name, "tool_input": inp}


DASH_O = {"ai-context/-o": "", "ai-context/s.json": "{}\n"}
PRE_SH = {"ai-context/--pre=sh": "", "ai-context/evil": ""}
DASH_DELETE = {"ai-context/-delete": ""}
WRITE_REPORT = "python3 framework/skills/story-impact/scripts/write_report.py"
WRITE_STORY = "python3 framework/skills/story-refine/scripts/write_story.py"
WRITE_DESIGN = "python3 framework/skills/solution-design/scripts/write_design.py"
WRITE_CHANGE = "python3 framework/skills/implement-story/scripts/write_change.py"
BUILD_INDEX = "python3 tools/index/build_index.py"
# Final review fix wave (C1, I1-I5, minors, extras). C2 has its own runner (check_walk_budget, check_deadline).
FINAL_CASES = [
    # C1: an unquoted glob word can expand to an option.
    Case("C1: cd then sort -[o] onto settings.local.json", bash("cd ai-context && sort -[o] ../.claude/settings.local.json s.json"), 2, files=DASH_O),
    Case("C1: sort -[o] from payload cwd ai-context", at("ai-context", "sort -[o] ../.claude/settings.local.json s.json"), 2, files=DASH_O),
    Case("C1: rg x * with --pre=sh in cwd (normal)", at("ai-context", "rg x *"), 2, files=PRE_SH),
    Case("C1: rg x * with --pre=sh in cwd (advise)", at("ai-context", "rg x *"), 2, env_mode="advise", files=PRE_SH),
    Case("C1: cd then find .. -delet[e] (advise)", bash("cd ai-context && find .. -delet[e]"), 2, env_mode="advise", files=DASH_DELETE),
    Case("C1: cd then find .. -delet[e] (normal)", bash("cd ai-context && find .. -delet[e]"), 2, files=DASH_DELETE),
    Case("C1: dash glob word blocked with no matching file", bash("grep -r --include=*.py foo ai-context"), 2, stderr_has="quote"),
    Case("C1: dash glob word blocked in advise", bash("sort -[o] x y"), 2, env_mode="advise"),
    Case("C1: glob matching a dash file at the root", bash("ls *"), 2, files={"-rf": ""}),
    Case("C1: [^a]* matches a dash file as bash would", at("ai-context", "sort [^a]* s.json"), 2, files=DASH_O),
    Case("C1: glob after cd blocked even with no dash files", bash("cd ai-context && ls *.md"), 2, files={"ai-context/a.md": ""}),
    Case("C1: glob after pushd blocked", bash("pushd ai-context; ls *.md"), 2, env_mode="maintain", files={"ai-context/a.md": ""}),
    Case("C1: glob word with an expansion blocked", bash("ls $D*"), 2),
    Case("C1: harmless glob allowed", bash("ls ai-context/*.md"), 0, files={"ai-context/a.md": ""}),
    Case("C1: harmless glob allowed in advise", bash("ls ai-context/*.md"), 0, env_mode="advise", files={"ai-context/a.md": ""}),
    Case("C1: path-prefixed glob still blocked when a match is a dash file", bash("ls ai-context/*"), 2, files=DASH_O),
    Case("C1: single-quoted dash glob is literal", at("ai-context", "find . -name '-*'"), 0, env_mode="advise", files=DASH_O),
    Case("C1: double-quoted glob is literal", at("ai-context", 'grep -r "x*" .'), 0, files=PRE_SH),
    Case("C1: escaped glob is literal", at("ai-context", "grep -r x\\* ."), 0, files=PRE_SH),
    # I1: git accepts an unambiguous prefix of --amend.
    Case("I1: git commit --amen blocked", bash("git commit --amen -m x"), 2, env_mode="build"),
    Case("I1: git commit --am''end blocked", bash("git commit --am''end -m x"), 2, env_mode="build"),
    Case("I1: git commit --am blocked", bash("git commit --am -m x"), 2, env_mode="build"),
    Case("I1: git commit --ame= blocked", bash("git commit --ame=x -m y"), 2, env_mode="maintain"),
    Case("I1: git commit --amen in maintain blocked", bash("git commit --amen -m x"), 2, env_mode="maintain"),
    Case("I1: git commit --all allowed", bash("git commit --all -m x"), 0, env_mode="build"),
    # I2: guard-token and git checks see the non-strict parse, so "$" no longer hides them.
    Case("I2: quoted guard.py --rebaseline with $X blocked", bash("python3 tools/guard/gu''ard.py --rebasel''ine $X"), 2, env_mode="maintain"),
    Case("I2: quoted guard.py with $X blocked in normal", bash("python3 tools/guard/gu''ard.py $X"), 2),
    Case("I2: git with $X while .git is untrusted blocked", bash("git log $X"), 2, git_append={".git/config": FSMON}, stderr_has="rebaseline"),
    Case("I2: git with $X while .git is untrusted blocked (advise)", bash("git log $X"), 2, env_mode="advise", git_append={".git/config": FSMON}),
    # I3: framework-script flags that name a write target.
    Case("I3: build_index --out tools/guard blocked", bash(f"{BUILD_INDEX} --out tools/guard"), 2),
    Case("I3: build_index --out= force-app blocked", bash(f"{BUILD_INDEX} --out=force-app"), 2),
    Case("I3: build_index --ou abbreviation blocked", bash(f"{BUILD_INDEX} --ou tools/guard"), 2),
    Case("I3: build_index --root joins --out", bash(f"{BUILD_INDEX} --root tools --out guard"), 2),
    Case("I3: build_index --r abbreviation joins --out", bash(f"{BUILD_INDEX} --r=tools --o guard"), 2),
    Case("I3: build_index --out with an expansion blocked", bash(f"{BUILD_INDEX} --out $X"), 2),
    Case("I3: build_index --out with no value blocked", bash(f"{BUILD_INDEX} --out"), 2),
    Case("I3: build_index default allowed", bash(BUILD_INDEX), 0),
    Case("I3: build_index smoke-test form allowed", bash(f"{BUILD_INDEX} --root fixtures --out ../index"), 0, files={"fixtures/.keep": ""}),
    Case("I3: build_index into ai-context allowed", bash(f"{BUILD_INDEX} --out ai-context/idx"), 0),
    Case("build_index --from-config allowed in normal", bash(f"{BUILD_INDEX} --from-config"), 0),
    Case("build_index --from-config with --out blocked", bash(f"{BUILD_INDEX} --from-config --out ai-context/idx"), 2),
    Case("build_index --from abbreviation with --root blocked", bash(f"{BUILD_INDEX} --from --root ai-context/x"), 2),
    Case("I3: write_report slug traversal blocked", bash(f"{WRITE_REPORT} --id 1 --slug ../../tools/guard --classified ai-context/c.json"), 2),
    Case("I3: write_report slug with / blocked", bash(f"{WRITE_REPORT} --id 1 --slug a/b --classified ai-context/c.json"), 2),
    Case("I3: write_report slug with backslash blocked", bash(f"{WRITE_REPORT} --id 1 --slug 'a\\b' --classified ai-context/c.json"), 2),
    Case("I3: write_report id with .. blocked", bash(f"{WRITE_REPORT} --id .. --slug x --classified ai-context/c.json"), 2),
    Case("I3: write_report --sl= abbreviation blocked", bash(f"{WRITE_REPORT} --id 1 --sl=../x --classified ai-context/c.json"), 2),
    Case("I3: write_report --root elsewhere blocked", bash(f"{WRITE_REPORT} --id 1 --slug x --classified ai-context/c.json --root ai-context/x"), 2),
    Case("I3: write_report ordinary run allowed", bash(f"{WRITE_REPORT} --id 1 --slug risk-rating --classified ai-context/c.json"), 0),
    Case("write_story with --root elsewhere blocked", bash(f"{WRITE_STORY} --id 1 --slug x --draft ai-context/d.json --root ai-context/x"), 2),
    Case("write_story slug traversal blocked", bash(f"{WRITE_STORY} --id 1 --slug ../../tools/guard --draft ai-context/d.json"), 2),
    Case("write_story allowed in normal", bash(f"{WRITE_STORY} --id 1 --slug risk-rating --draft ai-context/d.json"), 0),
    Case("write_design with --root elsewhere blocked", bash(f"{WRITE_DESIGN} --id 1 --slug x --draft ai-context/d.json --root ai-context/x"), 2),
    Case("write_design allowed in normal", bash(f"{WRITE_DESIGN} --id 1 --slug risk-rating --draft ai-context/d.json"), 0),
    Case("write_change allowed in build", bash(f"{WRITE_CHANGE} --id DEMO-1 --slug risk-rating --draft ai-context/d.json"), 0, env_mode="build"),
    Case("write_change with --root elsewhere blocked", bash(f"{WRITE_CHANGE} --id DEMO-1 --slug x --draft ai-context/d.json --root ai-context/x"), 2, env_mode="build"),
    Case("I3: query.py has no write flags", bash("python3 tools/index/query.py stamp --index tools/guard --root ."), 0),
    # I4: every tool goes through the guard.
    Case("I4: mcp write tool on tools/guard blocked", tool("mcp__filesystem__write_file", path="tools/guard/x"), 2),
    Case("I4: mcp send tool blocked in normal", tool("mcp__claude_ai_Gmail__send_message", to="a@example.com"), 2),
    Case("I4: mcp verb match is case-insensitive", tool("mcp__x__CreateIssue"), 2),
    Case("I4: mcp read tool allowed in normal", tool("mcp__filesystem__read_file", path="README.md"), 0),
    Case("I4: mcp read tool blocked in advise", tool("mcp__filesystem__read_file", path="README.md"), 2, env_mode="advise"),
    Case("I4: Read allowed in advise", tool("Read", file_path="README.md"), 0, env_mode="advise"),
    Case("I4: Grep allowed in advise", tool("Grep", pattern="x"), 0, env_mode="advise"),
    Case("I4: unknown tool blocked in advise", tool("Foo"), 2, env_mode="advise"),
    Case("I4: unknown tool allowed in normal", tool("Foo"), 0),
    Case("I4: NotebookEdit notebook_path in ai-context allowed", tool("NotebookEdit", notebook_path="ai-context/x.ipynb"), 0),
    Case("I4: NotebookEdit notebook_path in force-app blocked", tool("NotebookEdit", notebook_path="force-app/x.ipynb"), 2),
    Case("I4: NotebookEdit blocked in advise", tool("NotebookEdit", notebook_path="ai-context/x.ipynb"), 2, env_mode="advise"),
    # I5: the tripwire watches workflows, hooks and CODEOWNERS only.
    Case("I5: changed .github/instructions does not trip", write("docs/x.md"), 0, env_mode="maintain", dirty=(".github/instructions/x.md",)),
    Case("I5: changed .github/instructions allows git add", bash("git add docs/x"), 0, env_mode="maintain", dirty=(".github/instructions/x.md",)),
    Case("I5: changed .github/hooks still trips", write("docs/x.md"), 2, env_mode="maintain", dirty=(".github/hooks/x",), stderr_has="commit or revert"),
    Case("I5: changed .github/CODEOWNERS still trips", write("docs/x.md"), 2, env_mode="maintain", dirty=(".github/CODEOWNERS",)),
    # Commit-message usability.
    Case("commit with single-quoted $ in the message allowed (R1)", bash("git commit -m 'fix $5 bug'"), 0, env_mode="build"),
    Case("commit with substitution suggests -F", bash("git commit -m \"$(cat ai-context/m)\""), 2, env_mode="build", stderr_has="git commit -F ai-context/"),
    Case("commit with single-quoted braces allowed (R1)", bash("git commit -m 'a {b}'"), 0, env_mode="maintain"),
    Case("commit -F from ai-context allowed", bash("git commit -F ai-context/msg.txt"), 0, env_mode="build"),
    # Cheap extras.
    Case("eslint formatter with a backslash is a path", bash("pnpm exec eslint -f 'ai-context\\fmt' force-app"), 2, env_mode="build"),
    Case("eslint --format= with a backslash is a path", bash("pnpm exec eslint --format='ai-context\\fmt' force-app"), 2, env_mode="build"),
    Case("WebFetch ?-suffix host trick blocked", fetch("https://evil.example?.help.salesforce.com"), 2),
    Case("WebFetch #-suffix host trick blocked", fetch("https://evil.example#.help.salesforce.com"), 2),
    Case("WebFetch userinfo host trick blocked", fetch("https://help.salesforce.com@example.org/x"), 2),
    Case("WebFetch with no host blocked", fetch("https:///x"), 2),
    Case("WebFetch with no scheme blocked", fetch("help.salesforce.com/x"), 2),
    Case("WebFetch upper-case host allowed", fetch("https://HELP.salesforce.com/x"), 0),
    Case("WebFetch host with a port allowed", fetch("https://developer.salesforce.com:443/docs"), 0),
    Case("git grep is not allowlisted for writes either", bash("git grep foo"), 2, policy=OPEN),
]
R1_FILES = dict(DASH_O, **{"ai-context/evil": "touch PWNED\n"})
MD_FILE = {"ai-context/a.md": ""}
# Owner-approved extra round: R1 (shell expansion blocks in every mode), R3 (tool names). R2 timing is in WALK_CASES.
EXTRA_CASES = [
    # R1: "$", braces and [[:class:]] brackets outside single quotes block in every mode.
    Case("R1: sort [[:punct:]]o from cwd ai-context blocked", at("ai-context", "sort [[:punct:]]o ../.claude/settings.local.json s.json"), 2,
         files=R1_FILES, stderr_has="single quotes"),
    Case("R1: sort [[:punct:]]o blocked in maintain", at("ai-context", "sort [[:punct:]]o ../.claude/settings.local.json s.json"), 2,
         env_mode="maintain", files=R1_FILES),
    Case("R1: rg x {--pre=sh,evil} blocked", at("ai-context", "rg x {--pre=sh,evil}"), 2, files=R1_FILES),
    Case("R1: rg x --pr${U}e=sh blocked", at("ai-context", "rg x --pr${U}e=sh evil"), 2, files=R1_FILES),
    Case("R1: rg x --pr$@e=sh blocked", at("ai-context", "rg x --pr$@e=sh evil"), 2, files=R1_FILES),
    Case("R1: build_index --o${U}ut blocked", bash(f"{BUILD_INDEX} --o${{U}}ut tools/guard"), 2),
    Case("R1: build_index --o${U}ut blocked in maintain", bash(f"{BUILD_INDEX} --o${{U}}ut tools/guard"), 2, env_mode="maintain"),
    Case("R1: build_index {--out,tools/guard} blocked", bash(f"{BUILD_INDEX} {{--out,tools/guard}}"), 2),
    Case("R1: build_index {--out,tools/guard} blocked in maintain", bash(f"{BUILD_INDEX} {{--out,tools/guard}}"), 2, env_mode="maintain"),
    Case("R1: [[=a=]] equivalence class blocked", bash("ls ai-context/[[=a=]]*"), 2, files=MD_FILE),
    Case("R1: [[.a.]] collating symbol blocked", bash("ls ai-context/[[.a.]]*"), 2, files=MD_FILE),
    Case("R1: double-quoted $ blocked with the -F advice", bash('git commit -m "fix $5 bug"'), 2, env_mode="build",
         stderr_has="git commit -F ai-context/"),
    Case("R1: double-quoted $ blocked in maintain", bash('echo "$HOME" > ai-context/x.txt'), 2, env_mode="maintain"),
    Case("R1: unquoted brace blocked in normal", bash("echo {a,b} > ai-context/x.txt"), 2),
    Case("R1: private marker character in the command blocked", bash("ls ai-context/\ue000"), 2, stderr_has="parsed"),
    Case("R1: single-quoted braces allowed", bash("echo '{a,b}' > ai-context/x.txt"), 0, env_mode="build"),
    Case("R1: single-quoted braces allowed in normal", bash("echo '{a,b}' > ai-context/x.txt"), 0),
    Case("R1: double-quoted braces are literal", bash('echo "{a,b}" > ai-context/x.txt'), 0),
    Case("R1: escaped $ is literal", bash("echo \\$HOME > ai-context/x.txt"), 0),
    Case("R1: single-quoted [[:punct:]] is literal", bash("grep '[[:punct:]]' ai-context/a.md"), 0, files=MD_FILE),
    # R1 class, beyond the literal ruling: in a heredoc body "'" is not a quote, so "$(...)" and backticks run.
    Case("R1: heredoc with a substitution in its body blocked", bash("cat <<-X\necho '`touch PWNED`'\npwd"), 2, stderr_has="heredoc"),
    Case("R1: heredoc blocked in maintain", bash("cat <<X\necho '$(touch PWNED)'\nX"), 2, env_mode="maintain", stderr_has="heredoc"),
    Case("R1: heredoc with a quoted delimiter blocked too", bash("cat <<'X'\nhello\nX"), 2, stderr_has="heredoc"),
    Case("R1: here-string allowed", bash("cat <<< 'x'"), 0),
    Case("R1: commit -F allowed in maintain", bash("git commit -F ai-context/msg.txt"), 0, env_mode="maintain"),
    # R2: the glob-word cap (timed probes are in WALK_CASES).
    Case("R2: 64 glob words allowed", bash("ls" + " ai-context/*.md" * 64), 0, files=MD_FILE),
    Case("R2: 65 glob words blocked", bash("ls" + " ai-context/*.md" * 65), 2, files=MD_FILE, stderr_has="too many glob patterns"),
    Case("R2: the cap counts words across segments", bash("ls ai-context/*.md; " * 65), 2, files=MD_FILE, stderr_has="too many glob patterns"),
    # R3: MCP verbs match whole name segments; task tools are read-only; an unmodelled shell tool blocks.
    Case("R3: mcp copy tool blocked", tool("mcp__fs__copy_file", source="a", destination="tools/guard/x"), 2),
    Case("R3: mcp upsert tool blocked", tool("mcp__db__upsert_record"), 2),
    Case("R3: mcp save tool blocked", tool("mcp__x__save_note"), 2),
    Case("R3: mcp store tool blocked", tool("mcp__x__store"), 2),
    Case("R3: mcp commit tool blocked", tool("mcp__git__commit"), 2),
    Case("R3: mcp merge tool blocked", tool("mcp__git__merge_branch"), 2),
    Case("R3: mcp mkdir tool blocked", tool("mcp__fs__mkdir"), 2),
    Case("R3: mcp get_dataset allowed (set is not a segment)", tool("mcp__x__get_dataset"), 0),
    Case("R3: mcp settings allowed (set is not a segment)", tool("mcp__x__settings"), 0),
    Case("R3: mcp camelCase getDataset allowed", tool("mcp__x__getDataset"), 0),
    Case("R3: mcp camelCase setValue blocked", tool("mcp__x__setValue"), 2),
    Case("R3: TaskCreate allowed in advise", tool("TaskCreate", subject="x"), 0, env_mode="advise"),
    Case("R3: SendMessage allowed in advise", tool("SendMessage", to="a", message="x"), 0, env_mode="advise"),
    Case("R3: PowerShell command blocked in normal", tool("PowerShell", command="Remove-Item tools/guard -Recurse"), 2),
    Case("R3: PowerShell command blocked in maintain", tool("PowerShell", command="Get-ChildItem"), 2, env_mode="maintain"),
    Case("R3: unknown tool with a command blocked in advise", tool("Shell", command="ls"), 2, env_mode="advise"),
    Case("R3: unknown tool without a command still allowed in normal", tool("Foo", query="x"), 0),
    # Follow-up rulings: the command rule runs before read_only and MCP names; more MCP write verbs.
    Case("R3f: Monitor with a command blocked in normal", tool("Monitor", command="touch tools/guard/x", description="x"), 2, stderr_has="command"),
    Case("R3f: Monitor with a command blocked in advise", tool("Monitor", command="touch tools/guard/x", description="x"), 2, env_mode="advise"),
    Case("R3f: read-named MCP tool with a command blocked", tool("mcp__x__get_status", command="ls"), 2, stderr_has="command"),
    Case("R3f: mcp untrash blocked", tool("mcp__gmail__untrash_message"), 2),
    Case("R3f: mcp cancel blocked", tool("mcp__vercel__cancel_deployment"), 2),
    Case("R3f: mcp form_input blocked", tool("mcp__chrome__form_input"), 2),
    Case("R3f: mcp camelCase restoreBackup blocked", tool("mcp__x__restoreBackup"), 2),
    Case("R3f: mcp get_dataset still allowed", tool("mcp__x__get_dataset"), 0),
]
NO_PYTHON_CASE = Case("no interpreter fails closed", bash("git status"), 2, stderr_has="no Python interpreter found")
FAKE_PYTHON_CASES = [
    (1, Case("python3 exiting 1 fails closed", bash("git status"), 2)),
    (127, Case("python3 exiting 127 fails closed", bash("git status"), 2)),
]
NO_GUARD_PY_CASE = Case("missing guard.py fails closed", bash("git status"), 2, stderr_has="guard.py not found or unreadable")
EMPTY_PATH_CASE = Case("empty PATH fails closed", bash("git status"), 2, stderr_has="no Python interpreter found")
# The guard allows this payload when its policy is present, so exit 2 can only come from the missing file.
NO_POLICY_CASE = Case("missing policy fails closed", bash("git status"), 2, stderr_has="policy")
# A payload the guard blocks, with nowhere to write the message: the exit code must still be 2.
BAD_STDERR_CASES = [
    ("closed", Case("block with stderr closed still exits 2", bash("curl https://example.com"), 2)),
    ("broken", Case("block with stderr a broken pipe still exits 2", bash("curl https://example.com"), 2)),
]
# Run from a project whose ai-context/ holds symlinks into force-app/ (see add_symlinks).
SYMLINK_CASES = [
    Case("write in a temp repo's ai-context is allowed", write("ai-context/x/y.md"), 0, files={"force-app/A.cls": ""}),
    Case("write through a symlinked dir out of ai-context is blocked", write("ai-context/fa/A.cls"), 2, files={"force-app/A.cls": ""}),
    Case("edit of a symlinked file out of ai-context is blocked", write("ai-context/link.cls", "Edit"), 2, files={"force-app/A.cls": ""}),
    Case("A: glob through a symlinked dir into tools/guard blocked", bash("echo x > ai-context/t*/guard.py"), 2, files={"tools/guard/guard.py": "x"}),
    Case("A: cp through a symlinked dir into tools/guard blocked", bash("cp ai-context/e ai-context/tg/guard.py"), 2, files={"tools/guard/guard.py": "x"}),
    Case("A: rm -rf through a symlinked dir blocked", bash("rm -rf ai-context/tg/"), 2, files={"tools/guard/guard.py": "x"}),
    Case("I1: script symlinked out of ai-context blocked", bash("python3 ai-context/fa/A.py"), 2, env_mode="maintain", files={"force-app/A.py": ""},
         stderr_has="must resolve under"),
]

# ---- WS8: scope lock, tests-first, .active-story and start.py ----
# A synthetic story in a temp repo whose committed sourceRoot is force-app. The package is committed at HEAD; the
# active story file is written after the commit (untracked, as start.py leaves it), and the env names the same story.
S = "ZED-7-sample-change"
S_PKG_PATH = f"impacts/{S}/build-package.json"
S_DIR = "force-app/main/default/classes"
S_CLS = f"{S_DIR}/ZedThing.cls"
S_META = f"{S_CLS}-meta.xml"
S_TEST = f"{S_DIR}/ZedThing_Test.cls"
S_TEST2 = f"{S_DIR}/ZedOther_Test.cls"
S_NEW = f"{S_DIR}/ZedNew.cls"
S_OTHER = f"{S_DIR}/Other.cls"
S_CFG = {"startingPoint": "existing", "sourceRoot": "force-app"}
SKEL = "@IsTest private class ZedThing_Test {\n    // AC-1\n    // AC-2\n}\n"
S_STORY = {"ai-context/.active-story": S + "\n"}
S_ENV = {"AI_FRAMEWORK_STORY": S}


def s_pkg(**over):
    pkg = {
        "schemaVersion": 1, "storyId": "ZED-7", "slug": "sample-change",
        "criteria": [{"id": "AC-1", "given": "g", "when": "w", "then": "t", "examples": []},
                     {"id": "AC-2", "given": "g", "when": "w", "then": "t", "examples": []}],
        "scope": {"modify": [S_CLS], "create": [{"api": "ZedNew", "type": "ApexClass", "path": S_NEW}], "tests": [S_TEST]},
        "rules": [], "done": [],
    }
    pkg.update(over)
    return pkg


def s_scope(**over):
    scope = {"modify": [S_CLS], "create": [{"api": "ZedNew", "type": "ApexClass", "path": S_NEW}], "tests": [S_TEST]}
    scope.update(over)
    return scope


def s_files(pkg=None, cfg=S_CFG, skeleton=SKEL, extra=None):
    """Committed files: the config (dict or raw text; None omits it), the package (default s_pkg()) and the test file."""
    files = {S_CLS: "public with sharing class ZedThing {}\n", S_OTHER: "public with sharing class Other {}\n"}
    if cfg is not None:
        files[".ai-framework.json"] = cfg if isinstance(cfg, str) else json.dumps(cfg)
    pkg = s_pkg() if pkg is None else pkg
    files[S_PKG_PATH] = pkg if isinstance(pkg, str) else json.dumps(pkg)
    if skeleton is not None:
        files[S_TEST] = skeleton
    files.update(extra or {})
    return files


def sc(name, payload, want, files=None, post=None, env=None, env_mode="build", **kw):
    """A build-mode case with the synthetic story committed, skeletons in place and the story active."""
    return Case(f"WS8 {name}", payload, want, env_mode=env_mode, files=s_files() if files is None else files,
                post_files=S_STORY if post is None else post, env=S_ENV if env is None else env, **kw)


def edits(path, tool):
    return {"tool_name": tool, "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}


BIG_TESTS = [f"{S_DIR}/ZedBig{n}_Test.cls" for n in range(9)]  # nine files of just over 2 MB: past the 16 MB read cap
CHECK_TRACE = "python3 tools/code/check_trace.py"
CHECK_RULES = "python3 tools/code/check_rules.py"
START = "python3 tools/impacts/start.py"

SCOPE_CASES = [
    # Source root and active story
    sc("build: no active story, write under source root", write(S_CLS), 2, post={}, env={}, stderr_has="no active story scope"),
    sc("build: docs/x.md gets the outside message, not no-scope", write("docs/x.md"), 2, stderr_has="outside",
       stderr_lacks="no active story"),
    sc("build: docs/x.md with no active story gets the outside message", write("docs/x.md"), 2, post={}, env={},
       stderr_has="outside", stderr_lacks="no active story"),
    Case("WS8 build: write ai-context/x.md with no config and no story", write("ai-context/x.md"), 0, env_mode="build"),
    sc("build: .ai-framework.json missing blocks a source write (no '.' default)", write(S_CLS), 2,
       files=s_files(cfg=None), stderr_has="no source root"),
    sc("build: sourceRoot with .. blocks", write(S_CLS), 2, files=s_files(cfg={"sourceRoot": "../force-app"}), stderr_has="'..'"),
    sc("build: absolute sourceRoot blocks", write(S_CLS), 2, files=s_files(cfg={"sourceRoot": "/force-app"}), stderr_has="absolute"),
    sc("build: sourceRoot that is not a folder blocks", write(S_CLS), 2, files=s_files(cfg={"sourceRoot": "nowhere"}),
       stderr_has="not a directory"),
    sc("build: config with an unknown key blocks", write(S_CLS), 2,
       files=s_files(cfg={"sourceRoot": "force-app", "sourceRoots": ["x"]}), stderr_has="unknown key"),
    sc("build: sourceRoot changed only in the work tree is ignored (HEAD wins)", write(S_CLS), 2,
       files=s_files(cfg={"sourceRoot": "docs"}, extra={"docs/.keep": ""}),
       post=dict(S_STORY, **{".ai-framework.json": json.dumps(S_CFG)}), stderr_has="outside"),
    sc("build: .active-story names an unknown story", write(S_CLS), 2, post={"ai-context/.active-story": "ZED-9-other-thing\n"},
       env={"AI_FRAMEWORK_STORY": "ZED-9-other-thing"}, stderr_has="not committed"),
    sc("build: .active-story value with ..", write(S_CLS), 2, post={"ai-context/.active-story": "ZED-7-../x\n"},
       env={"AI_FRAMEWORK_STORY": "ZED-7-../x"}, stderr_has="is not <storyId>-<slug>"),
    sc("build: .active-story value with /", write(S_CLS), 2, post={"ai-context/.active-story": "ZED-7-a/b\n"},
       env={"AI_FRAMEWORK_STORY": "ZED-7-a/b"}, stderr_has="is not <storyId>-<slug>"),
    sc("build: two impacts folders match the id", write(S_CLS), 2,
       files=s_files(extra={"impacts/ZED-7-other-change/build-package.json": json.dumps(s_pkg(slug="other-change"))}),
       stderr_has="two or more"),
    sc("build: package in the tree but not at HEAD", write(S_CLS), 2,
       after=(("rm", "-q", "--cached", S_PKG_PATH), ("commit", "-q", "-m", "x")), stderr_has="commit"),
    sc("build: package invalid JSON", write(S_CLS), 2, files=s_files(pkg="{not json"), stderr_has="not valid JSON"),
    sc("build: package missing scope", write(S_CLS), 2, files=s_files(pkg={k: v for k, v in s_pkg().items() if k != "scope"}),
       stderr_has="scope is not an object"),
    sc("build: package entry with ..", write(S_CLS), 2,
       files=s_files(pkg=s_pkg(scope=s_scope(modify=[S_CLS, "force-app/../tools/x.cls"]))), stderr_has="'..'"),
    sc("build: package entry outside sourceRoot", write(S_CLS), 2,
       files=s_files(pkg=s_pkg(scope=s_scope(modify=[S_CLS, "docs/x.cls"]))), stderr_has="outside sourceRoot"),
    sc("build: package entry under impacts/", write(S_CLS), 2,
       files=s_files(pkg=s_pkg(scope=s_scope(modify=[S_CLS, f"impacts/{S}/notes.md"]))), stderr_has="reserved"),
    # Scope lock
    sc("build: write to a scope.tests file before any skeleton", write(S_TEST), 0, files=s_files(skeleton=None)),
    sc("build: write to a scope.modify file after skeletons exist", write(S_CLS), 0),
    sc("build: write to a scope.create path after skeletons exist", write(S_NEW), 0),
    sc("build: Edit on an in-scope file", edits(S_CLS, "Edit"), 0),
    sc("build: MultiEdit on an in-scope file", edits(S_CLS, "MultiEdit"), 0),
    sc("build: write to a source file not in scope", write(S_OTHER), 2, stderr_has="scope request"),
    sc("build: A.cls in scope, A.cls-meta.xml not: write the meta", write(S_META), 2, stderr_has="scope request"),
    sc("build: A.cls in scope: write A.clsX (prefix-match regression)", write(S_CLS + "X"), 2, stderr_has="scope request"),
    sc("build: in-scope path spelled with ./", write("./" + S_CLS), 0),
    sc("build: in-scope path spelled with a/../", write(f"{S_DIR}/../classes/ZedThing.cls"), 0),
    sc("build: a scope entry that is always-blocked rejects the package", write(S_CLS), 2,
       files=s_files(cfg={"sourceRoot": "."}, pkg=s_pkg(scope=s_scope(modify=[S_CLS, "tools/guard/x.py"]))), stderr_has="reserved"),
    sc("build: working-tree edit widening the committed package is ignored", write(S_OTHER), 2,
       post=dict(S_STORY, **{S_PKG_PATH: json.dumps(s_pkg(scope=s_scope(modify=[S_CLS, S_OTHER])))}), stderr_has="scope request"),
    sc("normal: in-scope path still blocked (the lock binds build only)", write(S_CLS), 2, env_mode=None, stderr_has="outside"),
    sc("maintain: in-scope path under force-app still blocked", write(S_CLS), 2, env_mode="maintain", stderr_has="outside"),
    sc("committed advise + local build + in-scope write", write(S_CLS), 2, committed_mode="advise", stderr_has="ADVISE"),
    # Tests first
    sc("build: non-test in-scope write before any skeleton names the missing ids", write(S_CLS), 2,
       files=s_files(skeleton=None), stderr_has="missing: AC-1, AC-2"),
    sc("build: one of two criteria referenced", write(S_CLS), 2, files=s_files(skeleton="// AC-1\n"), stderr_has="missing: AC-2"),
    sc("build: AC-10 present, AC-1 required", write(S_CLS), 2, files=s_files(skeleton="// AC-10\n// AC-2\n"),
       stderr_has="missing: AC-1"),
    sc("build: all ids referenced across scope.tests files", write(S_CLS), 0,
       files=s_files(pkg=s_pkg(scope=s_scope(tests=[S_TEST, S_TEST2])), skeleton="// AC-1\n", extra={S_TEST2: "// AC-2\n"})),
    sc("build: ids referenced only in an out-of-scope file", write(S_CLS), 2,
       files=s_files(skeleton="// none yet\n", extra={f"{S_DIR}/Notes.cls": "// AC-1 AC-2\n"}), stderr_has="tests first"),
    sc("build: ids referenced in a *_Test file outside scope.tests", write(S_CLS), 2,
       files=s_files(skeleton=None, extra={S_TEST2: "// AC-1 AC-2\n"}), stderr_has="tests first"),
    # check_trace.py excludes -meta.xml from coverage (trace_core.source_test_paths); the guard must agree.
    sc("build: tests-first ignores meta files", write(S_CLS), 2,
       files=s_files(pkg=s_pkg(scope=s_scope(tests=[S_TEST, S_TEST + "-meta.xml"])), skeleton=None,
                     extra={S_TEST + "-meta.xml": "<x>AC-1 AC-2</x>\n"}), stderr_has="missing: AC-1, AC-2"),
    sc("build: tests-first with a meta companion in scope.tests passes once the test names the ids", write(S_CLS), 0,
       files=s_files(pkg=s_pkg(scope=s_scope(tests=[S_TEST, S_TEST + "-meta.xml"])),
                     extra={S_TEST + "-meta.xml": "<x/>\n"})),
    sc("build: package with empty criteria[] is invalid", write(S_TEST), 2, files=s_files(pkg=s_pkg(criteria=[])),
       stderr_has="criteria"),
    # .active-story, AI_FRAMEWORK_STORY and robustness
    sc("build: AI_FRAMEWORK_STORY differs from .active-story", write(S_CLS), 2, env={"AI_FRAMEWORK_STORY": "ZED-8-other"},
       stderr_has="does not match"),
    sc("build: AI_FRAMEWORK_STORY not set", write(S_CLS), 2, env={}, stderr_has="not set"),
    sc("build: package blob over the size cap", write(S_CLS), 2, files=s_files(pkg=s_pkg(pad="x" * (1024 * 1024))),
       stderr_has="1048576"),
    sc("build: tests-first reading over the 16 MB cap blocks", write(S_CLS), 2,
       files=s_files(pkg=s_pkg(scope=s_scope(tests=BIG_TESTS))),
       post=dict(S_STORY, **{p: "// AC-1 AC-2\n" + "x" * (2 * 1024 * 1024) for p in BIG_TESTS}), stderr_has="16 MB"),
    sc("build: the outside message in build does not say the build is read-only", write("docs/x.md"), 2,
       stderr_has="outside the committed sourceRoot", stderr_lacks="read-only"),
    Case("WS8 maintain: write tools/guard/scope_core.py blocked", write("tools/guard/scope_core.py"), 2, env_mode="maintain",
         stderr_has="never allowed"),
    Case("WS8 maintain: write tools/guard/trace_core.py blocked", write("tools/guard/trace_core.py"), 2, env_mode="maintain",
         stderr_has="never allowed"),
    Case("WS8 tripwire: an edited scope core blocks writes", write("ai-context/x.md"), 2, dirty=("tools/guard/scope_core.py",),
         stderr_has="guard files changed"),
    Case("WS8 tripwire: an edited trace core blocks writes", write("ai-context/x.md"), 2, dirty=("tools/guard/trace_core.py",),
         stderr_has="guard files changed"),
] + [Case(f"WS8 {m or 'normal'}: Write ai-context/.active-story blocked", write("ai-context/.active-story"), 2, env_mode=m,
          stderr_has="never allowed") for m in (None, "build", "maintain")]

# Bash cases. Each also runs with every allowlist opened (no_allowlist_variants), so the write-target layer is tested
# alone; legacy is what that pass expects when only the allowlist blocks.
SCOPE_BASH_CASES = [
    sc("build: echo into a scope.tests file", bash(f"echo x > {S_TEST}"), 0),
    sc("build: echo into an out-of-scope source file", bash(f"echo x > {S_OTHER}"), 2, stderr_has="scope request"),
    sc("build: redirect into a non-test scope file before skeletons", bash(f"echo x > {S_CLS}"), 2, files=s_files(skeleton=None),
       stderr_has="tests first"),
    sc("build: prettier --write an in-scope file", bash(f"pnpm exec prettier --write {S_CLS}"), 0),
    sc("build: prettier --write the source folder", bash("pnpm exec prettier --write force-app"), 2),
    sc("build: sf apex generate into the source folder", bash(f"sf apex generate class --name A -d {S_DIR}"), 2),
    sc("build: sed -i on an in-scope file (allowlist)", bash(f"sed -i s/a/b/ {S_TEST}"), 2, stderr_has=NOT_ON_LIST, legacy=0),
    sc("build: cp onto an in-scope file (allowlist)", bash(f"cp ai-context/a {S_TEST}"), 2, stderr_has=NOT_ON_LIST, legacy=0),
    sc("build: check_trace allowed", bash(f"{CHECK_TRACE} ZED-7"), 0),
    sc("build: check_trace --skeletons allowed", bash(f"{CHECK_TRACE} --skeletons ZED-7"), 0),
    sc("build: check_rules --from-config allowed", bash(f"{CHECK_RULES} --from-config"), 0),
    sc("build: check_rules --compare-baseline allowed", bash(f"{CHECK_RULES} --from-config --compare-baseline base/tools/code/baseline.json"), 0),
    sc("build: check_trace with --core blocked", bash(f"{CHECK_TRACE} --core ai-context/x.py ZED-7"), 2, stderr_has=NOT_ON_LIST, legacy=0),
    sc("build: cd then check_trace blocked", bash(f"cd ai-context/x && {CHECK_TRACE} ZED-7"), 2,
       files=s_files(extra=SUB), stderr_has="project root"),
    Case("WS8 normal: check_trace allowed", bash(f"{CHECK_TRACE} --skeletons ZED-7"), 0),
    Case("WS8 normal: py -3 check_trace allowed", bash("py -3 tools/code/check_trace.py ZED-7"), 0),
    Case("WS8 normal: check_rules allowed", bash(f"{CHECK_RULES} --from-config --compare-baseline base/tools/code/baseline.json"), 0),
    Case("WS8 normal: check_rules with an unlisted flag blocked", bash(f"{CHECK_RULES} --write-baseline"), 2, stderr_has=NOT_ON_LIST, legacy=0),
    Case("WS8 normal: check_rules --compare-baseline with a dash value blocked",
         bash(f"{CHECK_RULES} --from-config --compare-baseline --write-baseline"), 2, stderr_has=NOT_ON_LIST, legacy=0),
    Case("WS8 normal: check_trace with --core blocked", bash(f"{CHECK_TRACE} --core ai-context/x.py ZED-7"), 2, stderr_has=NOT_ON_LIST, legacy=0),
    Case("WS8 normal: check_trace with --root blocked", bash(f"{CHECK_TRACE} ZED-7 --root ai-context/x"), 2, stderr_has=NOT_ON_LIST, legacy=0),
    Case("WS8 normal: cd then check_trace blocked", bash(f"cd ai-context/x && {CHECK_TRACE} ZED-7"), 2, files=SUB, stderr_has="project root"),
    Case("WS8 normal: write_design with --source-root allowed",
         bash(f"{WRITE_DESIGN} --id 1 --slug x --draft ai-context/d.json --source-root demo/org"), 0),
    Case("WS8 normal: write_design --s ambiguous blocked",
         bash(f"{WRITE_DESIGN} --id 1 --slug x --draft ai-context/d.json --s demo"), 2, stderr_has="cannot determine"),
] + [Case(f"WS8 {m or 'normal'}: echo into ai-context/.active-story blocked", bash("echo X > ai-context/.active-story"), 2,
          env_mode=m, stderr_has="never allowed") for m in (None, "build", "maintain")] + [
    Case(f"WS8 {m or 'normal'}: start.py blocked (models settings.local.json and .active-story)", bash(f"{START} ZED-7"), 2,
         env_mode=m, stderr_has="never allowed") for m in (None, "build", "maintain")] + [
    Case("WS8 maintain: py -3 start.py with --root blocked", bash("py -3 tools/impacts/start.py ZED-7 --root ai-context/x"), 2,
         env_mode="maintain", stderr_has="never allowed"),
]

# ---- Publish: the live eval runner is owner-run ----
# tools/evals/run_all.py starts `claude -p` runs on the owner's account. It matches no allowlist group in any mode;
# maintain's generic script pattern carries a case-insensitive negative lookahead for it, as for start.py. These run
# under the normal allowlist only (not through no_allowlist_variants): the runner models no write target, so with
# every allowlist opened it would be allowed.
RUN_ALL = "python3 tools/evals/run_all.py --case story-impact/004-escalation-hops-3"
PUBLISH_CASES = [
    Case(f"publish {m or 'normal'}: run_all.py blocked (live runs are owner-run)", bash(RUN_ALL), 2, env_mode=m,
         stderr_has="" if m == "advise" else NOT_ON_LIST) for m in (None, "advise", "build", "maintain")] + [
    Case("publish maintain: py -3 run_all.py blocked", bash("py -3 tools/evals/run_all.py --case story-impact/x --n 1"), 2,
         env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("publish maintain: run_all.py with no arguments blocked", bash("python3 tools/evals/run_all.py"), 2,
         env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("publish maintain: run_all.py in another case blocked", bash("python3 tools/Evals/RUN_ALL.py --case story-impact/x"), 2,
         env_mode="maintain", stderr_has=NOT_ON_LIST),
    Case("publish maintain: the comparer still runs", bash("python3 tools/evals/consistency.py ai-context/a ai-context/b"), 0,
         env_mode="maintain"),
]


def s_project(files=None, story=True):
    """A committed project with the synthetic story (and, when story, its .active-story file). Returns the realpath."""
    project = make_project("normal", s_files() if files is None else files)
    if story:
        put(project, "ai-context/.active-story", S + "\n")
    return os.path.realpath(project)


def guard_policy():
    with open(os.path.join(HERE, "policy.json"), encoding="utf-8") as f:
        return json.load(f)


def checker():
    """(check, results): check(name, good, detail) prints one line and records it."""
    results = []

    def check(name, good, detail=""):
        print(f"[{'PASS' if good else 'FAIL'}] {name}{'' if good else ' ' + str(detail)}")
        results.append(bool(good))
    return check, results


def guarded(check, name, fn):
    """Run one direct check; an exception (a guard without the WS8 change) is a FAIL, never a crash."""
    try:
        fn()
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {e}")


def check_scope_lazy():
    """Read-only commands, and writes inside the mode's paths, build no scope: no file read, no git call."""
    g = guard_module()
    check, results = checker()
    project = s_project()
    saved_run, calls = subprocess.run, []

    def spy(cmd, *a, **kw):
        calls.append(cmd)
        return saved_run(cmd, *a, **kw)

    def body():
        policy = guard_policy()
        g.DEADLINE[0] = time.monotonic() + 60
        subprocess.run = spy
        scope = g.Scope(project, S)
        segs = g.parse_bash(f"ls {S_DIR} && cat {S_CLS} && git status", strict=False)
        r1 = g.bash_block_reason(segs, "build", policy, scope, project, project)
        r2 = g.write_block_reason("ai-context/x.md", "build", policy, scope)
        check("WS8 lazy scope: read-only Bash and an ai-context write run no git and load no scope",
              r1 is None and r2 is None and not calls and scope._src is None and scope._pkg is None,
              f"{r1!r} {r2!r} calls={calls} src={scope._src!r}")
        r3 = g.write_block_reason(S_CLS, "build", policy, scope)
        n = len(calls)
        r4 = g.write_block_reason(S_CLS, "build", policy, scope)
        check("WS8 lazy scope: an in-scope write loads the scope once (memoised)", r3 is None and r4 is None and n > 0 and len(calls) == n,
              f"{r3!r} {r4!r} calls {n} then {len(calls)}")

    try:
        guarded(check, "WS8 lazy scope", body)
    finally:
        subprocess.run = saved_run
        drop(project)
    return all(results)


def check_scope_git_failure():
    """git missing, failing or timing out while the scope loads blocks (in-process: an empty PATH would stop the wrapper first)."""
    g = guard_module()
    check, results = checker()
    project = s_project()
    saved_run = subprocess.run

    def body():
        policy = guard_policy()
        g.DEADLINE[0] = time.monotonic() + 60
        check("WS8 scope git: the in-scope write is allowed when git works",
              g.write_block_reason(S_CLS, "build", policy, g.Scope(project, S)) is None)
        for label, exc in (("timeout", subprocess.TimeoutExpired("git", 3)), ("git missing", FileNotFoundError("git"))):
            def fake(cmd, *a, _exc=exc, **kw):
                raise _exc
            subprocess.run = fake
            try:
                reason = g.write_block_reason(S_CLS, "build", policy, g.Scope(project, S))
            finally:
                subprocess.run = saved_run
            check(f"WS8 scope git: {label} while loading the scope fails closed", reason is not None and "failing closed" in reason,
                  repr(reason))

    try:
        guarded(check, "WS8 scope git", body)
    finally:
        subprocess.run = saved_run
        drop(project)
    return all(results)


def check_scope_git_gate():
    """The scope's own gate: with the git config changed since the baseline (a planted core.fsmonitor), Scope runs no
    git at all. In-process, because through the wrapper the tripwire stops such a write before Scope is reached."""
    g = guard_module()
    check, results = checker()
    project = s_project()

    def body():
        policy = guard_policy()
        g.DEADLINE[0] = time.monotonic() + 60
        append(project, ".git/config", FSMON)
        src, reason = g.Scope(project, S).source_root()
        check("WS8 scope git gate: sourceRoot is not read while git state differs from the baseline",
              src is None and "build scope is not read" in (reason or ""), f"{src!r} {reason!r}")
        reason = g.write_block_reason(S_CLS, "build", policy, g.Scope(project, S))
        check("WS8 scope git gate: an in-scope write is refused while git state differs from the baseline",
              reason is not None and "build scope is not read" in reason, repr(reason))
        check("WS8 scope git gate: the planted fsmonitor did not run", not os.path.exists(os.path.join(project, "PWNED")))

    try:
        guarded(check, "WS8 scope git gate", body)
    finally:
        drop(project)
    return all(results)


def check_scope_fsmonitor():
    """With a planted core.fsmonitor and an active story, neither a read-only command nor a scoped write runs it."""
    check, results = checker()
    for payload, want in ((bash(f"ls {S_DIR}"), 0), (write(S_CLS), 2), (bash(f"echo x > {S_TEST}"), 2)):
        project = s_project()
        try:
            append(project, ".git/config", FSMON)
            code, err = send(WRAPPER, payload, case_env(project, "build", S_ENV), project)
            ran = os.path.exists(os.path.join(project, "PWNED"))
            name = payload["tool_input"].get("command") or payload["tool_input"].get("file_path")
            check(f"WS8 planted fsmonitor not run in build with an active story: {name}", not ran and code == want,
                  f"ran={ran} exit {code} (want {want}) {err.strip()!r}")
        finally:
            drop(project)
    return all(results)


def check_scope_symlink():
    """A symlink inside the source root that points at an out-of-scope file is judged by its target."""
    check, results = checker()
    project = s_project()
    try:
        link = f"{S_DIR}/Link.cls"
        try:
            os.symlink(os.path.join(project, *S_OTHER.split("/")), os.path.join(project, *link.split("/")))
        except OSError as e:
            print(f"[SKIP] WS8 build: symlink inside the source root: cannot create symlinks here ({e})")
            return True
        code, err = send(WRAPPER, write(link), case_env(project, "build", S_ENV), project)
        check("WS8 build: symlink inside the source root to an out-of-scope file blocked", code == 2 and "scope request" in err,
              f"exit {code} {err.strip()!r}")
    finally:
        drop(project)
    return all(results)


def check_scope_hardlink():
    """An in-scope target that is a hard link (link count above 1) is refused: the write would change the other path too."""
    check, results = checker()
    project = s_project()
    try:
        try:
            os.link(os.path.join(project, *S_CLS.split("/")), os.path.join(project, "ai-context", "linked.cls"))
        except (OSError, AttributeError) as e:
            print(f"[SKIP] WS8 build: hard-linked in-scope target: cannot create hard links here ({e})")
            return True
        for payload in (write(S_CLS), bash(f"echo x > {S_CLS}")):
            code, err = send(WRAPPER, payload, case_env(project, "build", S_ENV), project)
            name = payload["tool_input"].get("command") or payload["tool_input"].get("file_path")
            check(f"WS8 build: hard-linked in-scope target refused: {name}", code == 2 and "hard link" in err,
                  f"exit {code} {err.strip()!r}")
        os.remove(os.path.join(project, "ai-context", "linked.cls"))
        code, err = send(WRAPPER, write(S_CLS), case_env(project, "build", S_ENV), project)
        check("WS8 build: the same target is allowed once the link is gone", code == 0, f"exit {code} {err.strip()!r}")
    finally:
        drop(project)
    return all(results)


def check_start_modelled():
    """start.py writes settings.local.json and .active-story (as modelled), and matches no allowlist group in any mode."""
    g = guard_module()
    check, results = checker()

    def body():
        policy = guard_policy()
        root = os.path.realpath(os.getcwd())
        got = g.script_targets("tools/impacts/start.py", ["ZED-7"], root)
        want = {".claude/settings.local.json", "ai-context/.active-story"}
        check("WS8 start.py targets include settings.local.json and .active-story", got is not None and want <= set(got[0]), repr(got))
        for words in (["python3", "tools/impacts/start.py", "ZED-7"], ["py", "-3", "tools/impacts/start.py", "ZED-7"],
                      ["python3", "tools/impacts/start.py"]):
            for mode, cfg in policy["modes"].items():
                patterns = [p for grp in cfg["bash_allow"] for p in policy["bash_groups"][grp]]
                check(f"WS8 start.py matches no {mode} allowlist group: {' '.join(words)}", not g.segment_matches(words, patterns))
        maintain = [p for grp in policy["modes"]["maintain"]["bash_allow"] for p in policy["bash_groups"][grp]]
        check("WS8 maintain still runs other tools/impacts scripts", g.segment_matches(["python3", "tools/impacts/starter.py"], maintain))

    guarded(check, "WS8 start.py modelled", body)
    return all(results)


def check_run_all_refused():
    """tools/evals/run_all.py matches no allowlist group in any mode, in any letter case; maintain still runs the
    other tools/evals scripts."""
    g = guard_module()
    check, results = checker()

    def body():
        policy = guard_policy()
        for words in (["python3", "tools/evals/run_all.py", "--case", "story-impact/x"], ["py", "-3", "tools/evals/run_all.py"],
                      ["python", "tools/evals/run_all.py", "--n", "1"], ["python3", "TOOLS/EVALS/Run_All.py"]):
            for mode, cfg in policy["modes"].items():
                patterns = [p for grp in cfg["bash_allow"] for p in policy["bash_groups"][grp]]
                check(f"publish run_all.py matches no {mode} allowlist group: {' '.join(words)}", not g.segment_matches(words, patterns))
        maintain = [p for grp in policy["modes"]["maintain"]["bash_allow"] for p in policy["bash_groups"][grp]]
        for words in (["python3", "tools/evals/consistency.py", "ai-context/a"], ["python3", "tools/evals/test_run_all.py"],
                      ["python3", "tools/evals/run_all_notes.py"]):
            check(f"publish maintain still runs {words[1]}", g.segment_matches(words, maintain))

    guarded(check, "publish run_all.py refused", body)
    return all(results)


def check_source_root_drift():
    """The guard's sourceRoot reading (scope_core via Scope) equals tools/config/framework_config.source_root for a set of
    committed configs. Excluded, by design: a missing file or a missing sourceRoot key (framework_config defaults to ".",
    the guard reads no source root), and startingPoint/impactChecks values, which only framework_config validates."""
    g = guard_module()
    check, results = checker()
    path = os.path.join(HERE, "..", "config", "framework_config.py")

    def body():
        spec = importlib.util.spec_from_file_location("framework_config_for_drift", path)
        fc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fc)
        configs = [{"sourceRoot": "force-app"}, {"sourceRoot": "force-app/"}, {"sourceRoot": "./force-app"}, {"sourceRoot": "."},
                   {"startingPoint": "greenfield", "sourceRoot": "force-app/main"}, {"sourceRoot": "nowhere"},
                   {"sourceRoot": "../x"}, {"sourceRoot": "/abs"}, {"sourceRoot": ""}, {"sourceRoot": 3},
                   {"sourceRoot": "force-app", "extra": 1}, "[1]", '{"sourceRoot": "force-app"', {"sourceRoot": "README.md"}]
        for cfg in configs:
            text = cfg if isinstance(cfg, str) else json.dumps(cfg)
            project = make_project("normal", {".ai-framework.json": text, "README.md": "x\n"})
            try:
                real = os.path.realpath(project)
                try:
                    theirs = os.path.relpath(fc.source_root(real), real).replace(os.sep, "/")
                except ValueError:
                    theirs = None
                ours, _ = g.Scope(real, None).source_root()
                check(f"WS8 drift: sourceRoot reading agrees for {text}", ours == theirs, f"guard {ours!r} framework_config {theirs!r}")
            finally:
                drop(project)
        project = make_project("normal", {"README.md": "x\n"})
        try:
            real = os.path.realpath(project)
            ours, reason = g.Scope(real, None).source_root()
            check("WS8 drift: the documented divergence holds (missing config: guard none, framework_config '.')",
                  ours is None and "no source root" in (reason or "") and os.path.realpath(fc.source_root(real)) == real,
                  f"{ours!r} {reason!r}")
        finally:
            drop(project)

    guarded(check, "WS8 drift: sourceRoot reading", body)
    return all(results)


def check_package_drift():
    """scope_core (beside this file) and tools/impacts/package.py's validate_package give the same verdict, equal to the
    recorded one, over the shared fixtures in tools/impacts/scope_fixtures.json. tools/impacts/test_package.py runs the
    same comparison from the other side. package.py is loaded by path; SKIP when it or the fixtures are absent."""
    check, results = checker()
    impacts = os.path.normpath(os.path.join(HERE, "..", "impacts"))
    pkg_path, fx_path = os.path.join(impacts, "package.py"), os.path.join(impacts, "scope_fixtures.json")
    if not (os.path.isfile(pkg_path) and os.path.isfile(fx_path)):
        print("[SKIP] WS8 drift: package.py vs scope_core: tools/impacts/package.py or scope_fixtures.json absent")
        return True

    def body():
        import copy
        import types
        saved_path, saved_mods = list(sys.path), set(sys.modules)
        try:
            spec = importlib.util.spec_from_file_location("package_for_drift", pkg_path)
            pkg_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pkg_mod)
        finally:
            sys.path[:] = saved_path
            for name in set(sys.modules) - saved_mods:  # package.py's own imports (validate, register, ...) leave again
                sys.modules.pop(name, None)
        core = types.ModuleType("scope_core_for_drift")
        core_path = os.path.join(HERE, "scope_core.py")
        with open(core_path, "rb") as f:
            exec(compile(f.read(), core_path, "exec"), core.__dict__)
        with open(fx_path, encoding="utf-8") as f:
            doc = json.load(f)
        active = f"{doc['storyId']}-{doc['slug']}"
        top = tempfile.mkdtemp(prefix="guard-drift-")
        try:
            os.makedirs(os.path.join(top, "src"))
            os.makedirs(os.path.join(top, "elsewhere"))
            try:
                os.symlink(os.path.join(top, "elsewhere"), os.path.join(top, "src", "link"))
                can_link = True
            except OSError:
                can_link = False
            real = os.path.realpath(top)
            ran = 0
            for case in doc["cases"]:
                if case["name"] == "symlinked-entry" and not can_link:
                    print("[SKIP] WS8 drift: symlinked-entry: cannot create symlinks here")
                    continue
                pkg = copy.deepcopy(case["pkg"])
                fill = case.get("fill")
                if fill:
                    pkg["scope"][fill["key"]] = [fill["pattern"] % n for n in range(fill["count"])]
                src = case["sourceRoot"]
                theirs = pkg_mod.validate_package(copy.deepcopy(pkg), src, root=real) == []
                ours = core._validate(real, src, active, copy.deepcopy(pkg)) is None
                ran += 1
                check(f"WS8 drift: package.py and scope_core agree on {src} {case['name']}",
                      ours == theirs == case["accept"], f"scope_core {ours} package.py {theirs} recorded {case['accept']}")
            check("WS8 drift: the shared fixtures hold accepted and rejected cases",
                  ran >= 10 and any(c["accept"] for c in doc["cases"]) and not all(c["accept"] for c in doc["cases"]))
        finally:
            shutil.rmtree(top, ignore_errors=True)

    guarded(check, "WS8 drift: package.py vs scope_core", body)
    return all(results)


def core_unit_cases(tmp, empty_hooks):
    """The trace_core and scope_core unit tests (staged in WS8 Task 3), loading the cores beside this file by
    explicit path. Nested, so their helpers stay local. Returns {name: function}."""
    TMP, EMPTY_HOOKS = tmp, empty_hooks

    def load(name):
        path = os.path.join(HERE, name + ".py")
        spec = importlib.util.spec_from_file_location("ws8_" + name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


    def trace():
        return load("trace_core")


    def scope():
        return load("scope_core")


    # ---- temp git repos ----

    ACTIVE = "ZED-7-sample-change"
    SRC = "force-app"
    CLS = "force-app/main/default/classes/ZedThing.cls"
    CLS_META = "force-app/main/default/classes/ZedThing.cls-meta.xml"
    TEST = "force-app/main/default/classes/ZedThing_Test.cls"
    NEW = "force-app/main/default/classes/ZedNew.cls"


    def git_env():
        return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


    def git(repo, *args):
        cmd = ["git", "-C", repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com",
               "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + EMPTY_HOOKS, "-c", "core.fsmonitor=false"]
        p = subprocess.run(cmd + list(args), capture_output=True, text=True, env=git_env(), stdin=subprocess.DEVNULL)
        assert p.returncode == 0, (args, p.stdout, p.stderr)
        return p.stdout


    def package(**over):
        pkg = {
            "schemaVersion": 1,
            "storyId": "ZED-7",
            "slug": "sample-change",
            "criteria": [{"id": "AC-1", "given": "g", "when": "w", "then": "t", "examples": []},
                         {"id": "AC-2", "given": "g", "when": "w", "then": "t", "examples": []}],
            "scope": {"modify": [CLS, CLS_META], "create": [{"api": "ZedNew", "type": "ApexClass", "path": NEW}],
                      "tests": [TEST]},
            "rules": [],
            "done": [],
        }
        pkg.update(over)
        return pkg


    def make_repo(files=None, cfg=None, pkg=None, folder=ACTIVE, commit=True, dirs=(SRC + "/main/default/classes",)):
        """A committed temp repo. files: {path: text}. cfg/pkg: dict, raw str, or None to omit."""
        repo = tempfile.mkdtemp(prefix="repo_", dir=TMP)
        git(repo, "init", "-q")
        all_files = {"README.md": "fixture\n"}
        if cfg is not None:
            all_files[".ai-framework.json"] = cfg if isinstance(cfg, str) else json.dumps(cfg)
        if pkg is not None:
            all_files["impacts/%s/build-package.json" % folder] = pkg if isinstance(pkg, str) else json.dumps(pkg)
        all_files.update(files or {})
        for d in dirs:
            os.makedirs(os.path.join(repo, d), exist_ok=True)
            all_files.setdefault(d + "/.keep", "")
        for rel, text in all_files.items():
            write(repo, rel, text)
        if commit:
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "fixture")
        return repo


    def write(repo, rel, text):
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)


    CFG = {"startingPoint": "existing", "sourceRoot": SRC}


    def read(repo, active=ACTIVE):
        return scope().read_package(repo, active)


    def rejects(repo, needle, active=ACTIVE):
        pkg, err = read(repo, active)
        assert pkg is None, pkg
        assert err and needle in err, (needle, err)


    def rejects_pkg(needle, cfg=CFG, **over):
        rejects(make_repo(cfg=cfg, pkg=package(**over)), needle)


    def with_scope(**kw):
        s = {"modify": [CLS], "create": [], "tests": [TEST]}
        s.update(kw)
        return s


    # ---- trace_core ----

    def test_prefix_ids_not_confused():
        t = trace()
        assert t.missing_criteria(["AC-1"], {"a": "covers AC-10 and AC-11"}) == ["AC-1"]
        assert t.missing_criteria(["AC-1"], {"a": "covers AC-1."}) == []
        assert t.missing_criteria(["AC-10"], {"a": "covers AC-1"}) == ["AC-10"]
        assert t.missing_criteria(["AC-1"], {"a": "XAC-1 and AC-1_x and AC-1a"}) == ["AC-1"]


    def test_boundaries_reject_unicode_letters_and_dash_digit():
        t = trace()
        for text in ["ÄAC-1", "éAC-1", "1AC-1", "AC-1-2", "AC-1-0 only", "AC-1é", "AC-1٣"]:
            assert t.missing_criteria(["AC-1"], {"a": text}) == ["AC-1"], text
            assert t.unknown_refs([], {"a": text}) == [], text
        for text in ["AC-1-x", "AC-1 - 2", "(AC-1)", "AC-1: x", "«AC-1»", "AC-1."]:
            assert t.missing_criteria(["AC-1"], {"a": text}) == [], text


    def test_missing_criteria_sorted_unique():
        t = trace()
        assert t.missing_criteria(["EC-1", "AC-10", "AC-2", "AC-2"], {}) == ["AC-2", "AC-10", "EC-1"]
        # an id that is not AC-n / EC-n can never be referenced: always missing, never raises
        assert t.missing_criteria(["OQ-1", "AC-1"], {"a": "AC-1 OQ-1"}) == ["OQ-1"]


    def test_trace_core_is_linear_in_text():
        t = trace()
        import time
        # Worst case: no package id is referenced, so a per-id search would scan every byte once per id.
        line = "".join("    System.assertEquals(1, x); // AC-%d EC-%d\n" % (i, i) for i in range(2001, 6001))
        body = (line * (t.MAX_READ // len(line) + 1))[:t.MAX_READ]
        texts = {"f%d" % i: body for i in range(10)}
        ids = ["AC-%d" % i for i in range(1, 2001)]
        start = time.monotonic()
        missing = t.missing_criteria(ids, texts)
        unknown = t.unknown_refs(ids, texts)
        took = time.monotonic() - start
        assert len(missing) == 2000 and len(unknown) == 8000, (len(missing), len(unknown))
        assert took < 2.0, "2000 ids x 10 files of 2 MB took %.2f s" % took


    def test_criteria_problem_matches_scope_core():
        t = trace()
        cases = [[{"id": "AC-1"}, {"id": "EC-2"}], [], "AC-1", None, [{"id": "AC-1"}, {"id": "AC-1"}], [{"id": "OQ-1"}],
                 [{"id": "AC-1 "}], [{"id": "AC-1\n"}], ["AC-1"], [{"id": 1}], [{}], [{"id": "ac-1"}], [{"id": "AC-"}]]
        for crit in cases:
            mine = t.criteria_problem(crit)
            pkg, err = read(make_repo(cfg=CFG, pkg=package(criteria=crit)))
            assert (mine is None) == (err is None), (crit, mine, err)
            if err is not None:
                assert "criteri" in err, (crit, err)


    def test_missing_criteria_order_and_union():
        t = trace()
        texts = {"a": "// AC-2", "b": "EC-3 here"}
        assert t.missing_criteria(["AC-1", "AC-2", "EC-3", "AC-4"], texts) == ["AC-1", "AC-4"]
        assert t.missing_criteria(["AC-1"], {}) == ["AC-1"]
        assert t.missing_criteria([], {"a": "AC-1"}) == []


    def test_unknown_ref_fails():
        t = trace()
        texts = {"a": "AC-1 AC-3 EC-2", "b": "AC-3 and AC-10"}
        assert t.unknown_refs(["AC-1"], texts) == ["AC-3", "AC-10", "EC-2"]
        assert t.unknown_refs(["AC-1", "AC-3", "AC-10", "EC-2"], texts) == []
        assert t.unknown_refs(["AC-1"], {"a": "OQ-1 is not a criterion"}) == []


    def test_unknown_refs_same_boundary_as_matching():
        t = trace()
        # "-" before the id is not a boundary in either function: X-AC-1 is neither a ref nor a match.
        assert t.unknown_refs([], {"a": "X-AC-1 ZAC-2 AC-3_b"}) == []
        assert t.missing_criteria(["AC-1"], {"a": "X-AC-1"}) == ["AC-1"]


    def test_id_in_out_of_scope_file_ignored():
        t = trace()
        repo = make_repo(files={TEST: "// nothing yet\n", "force-app/main/default/classes/Other_Test.cls": "// AC-1\n"},
                         cfg=CFG)
        texts = t.read_tests(repo, [TEST])
        assert list(texts) == [TEST], texts
        assert t.missing_criteria(["AC-1"], texts) == ["AC-1"]


    def test_read_tests_skips_missing_dirs_and_symlinks():
        t = trace()
        repo = make_repo(files={TEST: "AC-1\n", "outside.txt": "AC-2\n"}, cfg=CFG)
        link = "force-app/main/default/classes/Link_Test.cls"
        os.symlink(os.path.join(repo, "outside.txt"), os.path.join(repo, link))
        texts = t.read_tests(repo, [TEST, "force-app/nope_Test.cls", "force-app", link])
        assert list(texts) == [TEST], texts


    def test_read_tests_cap_and_replace():
        t = trace()
        cap = t.MAX_READ
        assert cap == 2 * 1024 * 1024, cap
        repo = make_repo(cfg=CFG)
        path = os.path.join(repo, TEST)
        with open(path, "wb") as fh:
            fh.write(b"\xff\xfe AC-1 " + b"x" * cap + b" AC-2")
        texts = t.read_tests(repo, [TEST])
        assert t.missing_criteria(["AC-1", "AC-2"], texts) == ["AC-2"], "past the cap must not count"
        assert "�" in texts[TEST]


    def test_read_tests_rejects_escaping_paths():
        t = trace()
        repo = make_repo(files={TEST: "AC-1\n"}, cfg=CFG)
        texts = t.read_tests(repo, ["../x", "/etc/hosts", "a/../" + TEST])
        assert texts == {}, texts


    def test_source_test_paths_drops_meta_companions():
        t = trace()
        meta = TEST + "-meta.xml"
        assert t.META_SUFFIX == "-meta.xml"
        assert t.source_test_paths([meta, TEST, "a/x-meta.xmlX", 3, "b/Y_Test.cls"]) == [TEST, "a/x-meta.xmlX", "b/Y_Test.cls"]
        assert t.source_test_paths([]) == []
        repo = make_repo(files={TEST: "// AC-1\n", meta: "<x>AC-2</x>\n"}, cfg=CFG)
        texts = t.read_tests(repo, t.source_test_paths([TEST, meta]))
        assert list(texts) == [TEST], texts
        assert t.missing_criteria(["AC-1", "AC-2"], texts) == ["AC-2"], "an id only in a -meta.xml covers nothing"


    # ---- scope_core: happy path ----

    def test_scope_core_reads_valid_package():
        repo = make_repo(cfg=CFG, pkg=package())
        pkg, err = read(repo)
        assert err is None, err
        assert pkg["scope"]["modify"] == [CLS, CLS_META]
        assert [c["id"] for c in pkg["criteria"]] == ["AC-1", "AC-2"]


    def test_scope_core_source_root_from_head():
        s = scope()
        assert s.source_root_from_head(make_repo(cfg=CFG)) == (SRC, None)
        assert s.source_root_from_head(make_repo(cfg={"sourceRoot": "force-app/"}))[0] == SRC
        assert s.source_root_from_head(make_repo(cfg={"sourceRoot": "."}))[0] == "."


    def test_scope_core_missing_config_is_no_source_root():
        s = scope()
        src, err = s.source_root_from_head(make_repo())
        assert src is None and "no source root" in err, err
        src, err = s.source_root_from_head(make_repo(cfg={"startingPoint": "existing"}))
        assert src is None and "no source root" in err, err
        rejects(make_repo(pkg=package()), "no source root")


    def test_scope_core_rejects_bad_config():
        s = scope()
        for cfg, needle in [("[1]", "not a JSON object"), ("{", "not valid JSON"), ({"sourceRoot": SRC, "x": 1}, "unknown key"),
                            ({"sourceRoot": ""}, "non-empty string"), ({"sourceRoot": 3}, "non-empty string"),
                            ({"sourceRoot": "../x"}, ".."), ({"sourceRoot": "/abs"}, "absolute"),
                            ({"sourceRoot": "force-app\\x"}, "backslash"), ({"sourceRoot": "nope"}, "not a directory"),
                            ('{"sourceRoot": "a", "sourceRoot": "force-app"}', "duplicate key")]:
            src, err = s.source_root_from_head(make_repo(cfg=cfg))
            assert src is None and err and needle in err, (cfg, needle, err)


    def test_scope_core_rejects_source_root_symlink_outside():
        outside = tempfile.mkdtemp(prefix="outside_", dir=TMP)
        repo = make_repo(cfg={"sourceRoot": "linked"})
        os.symlink(outside, os.path.join(repo, "linked"))
        src, err = scope().source_root_from_head(repo)
        assert src is None and "outside the repo" in err, err


    # ---- scope_core: rejections ----

    def test_scope_core_rejects_dotdot():
        rejects_pkg("..", scope=with_scope(modify=["force-app/main/../../tools/x.cls"]))


    def test_scope_core_rejects_absolute():
        rejects_pkg("absolute", scope=with_scope(modify=["/force-app/main/default/classes/ZedThing.cls"]))


    def test_scope_core_rejects_outside_source_root():
        rejects_pkg("outside sourceRoot", scope=with_scope(modify=["docs/x.md"]))


    def test_scope_core_rejects_under_impacts():
        # sourceRoot "." makes every path "source", so only the reserved-prefix rule can fire.
        for path in ["impacts/ZED-7-sample-change/build-package.json", "tools/guard/x.py", "Tools/Guard/x.py",
                     "framework/rules/x.md", ".claude/settings.json", ".github/workflows/ci.yml",
                     "ai-context/.active-story", ".ai-framework.json", "a/.git/config", "docs/CODEOWNERS"]:
            rejects_pkg("reserved", cfg={"sourceRoot": "."}, scope=with_scope(modify=[path]))


    def test_scope_core_dot_source_root_allows_plain_paths():
        repo = make_repo(cfg={"sourceRoot": "."}, pkg=package())
        pkg, err = read(repo)
        assert err is None, err


    def test_scope_core_rejects_bad_entry_syntax():
        for entry, needle in [("force-app\\a.cls", "backslash"), ("force-app/*.cls", "glob"), ("force-app/a?.cls", "glob"),
                              ("force-app/[a].cls", "glob"), ("", "empty"), ("force-app//a.cls", "empty"),
                              ("force-app/./a.cls", "'.'"), ("force-app/main/", "empty"), (3, "string"),
                              (SRC, "outside sourceRoot"), ("force-app/a\nb.cls", "control")]:
            rejects_pkg(needle, scope=with_scope(modify=[entry]))


    def test_scope_core_rejects_duplicate_entry():
        rejects_pkg("duplicate", scope=with_scope(modify=[CLS, CLS]))


    def test_scope_core_rejects_symlinked_entry():
        repo = make_repo(cfg=CFG, pkg=package(scope=with_scope(modify=["force-app/link/ZedThing.cls"])))
        os.symlink(os.path.join(repo, "force-app/main/default/classes"), os.path.join(repo, "force-app/link"))
        rejects(repo, "symlink")


    def test_scope_core_rejects_create_shape():
        rejects_pkg("object", scope=with_scope(create=[NEW]))
        rejects_pkg("path", scope=with_scope(create=[{"api": "ZedNew", "type": "ApexClass"}]))
        rejects_pkg("api", scope=with_scope(create=[{"type": "ApexClass", "path": NEW}]))
        rejects_pkg("outside sourceRoot", scope=with_scope(create=[{"api": "X", "type": "ApexClass", "path": "docs/X.cls"}]))


    def test_scope_core_rejects_bad_shape():
        rejects_pkg("scope", scope=None)
        rejects_pkg("scope.tests", scope={"modify": [CLS], "create": []})
        rejects_pkg("scope.modify", scope=with_scope(modify="force-app/a.cls"))
        rejects_pkg("schemaVersion", schemaVersion=2)
        rejects(make_repo(cfg=CFG, pkg="[1]"), "not a JSON object")


    def test_scope_core_rejects_criteria():
        rejects_pkg("duplicate criterion", criteria=[{"id": "AC-1"}, {"id": "AC-1"}])
        rejects_pkg("criteria", criteria=[])
        rejects_pkg("criteria", criteria="AC-1")
        rejects_pkg("criterion id", criteria=[{"id": "OQ-1"}])
        rejects_pkg("criterion id", criteria=[{"id": "AC-1 "}])
        rejects_pkg("criterion", criteria=["AC-1"])


    def test_scope_core_rejects_story_mismatch():
        rejects_pkg("storyId", storyId="ZED-8")
        rejects_pkg("slug", slug="other-change")


    def test_scope_core_rejects_invalid_json():
        rejects(make_repo(cfg=CFG, pkg="{not json"), "not valid JSON")
        rejects(make_repo(cfg=CFG, pkg='{"storyId": "ZED-7", "storyId": "ZED-7"}'), "duplicate key")


    def test_scope_core_rejects_invalid_utf8():
        repo = make_repo(cfg=CFG, pkg=package())
        path = os.path.join(repo, "impacts", ACTIVE, "build-package.json")
        with open(path, "wb") as fh:
            fh.write(b'{"x": "\xff"}')
        git(repo, "commit", "-q", "-am", "bad utf8")
        rejects(repo, "UTF-8")


    def test_scope_core_rejects_not_at_head():
        repo = make_repo(cfg=CFG)
        write(repo, "impacts/%s/build-package.json" % ACTIVE, json.dumps(package()))
        rejects(repo, "commit")
        # in the tree, removed from the index and HEAD
        repo = make_repo(cfg=CFG, pkg=package())
        git(repo, "rm", "-q", "--cached", "impacts/%s/build-package.json" % ACTIVE)
        git(repo, "commit", "-q", "-m", "x")
        assert os.path.exists(os.path.join(repo, "impacts", ACTIVE, "build-package.json"))
        rejects(repo, "commit")


    def test_scope_core_rejects_two_matching_folders():
        repo = make_repo(cfg=CFG, pkg=package(),
                         files={"impacts/ZED-7-other-change/build-package.json": json.dumps(package(slug="other-change"))})
        rejects(repo, "two or more")
        # ZED-70-* does not match ZED-7
        repo = make_repo(cfg=CFG, pkg=package(), files={"impacts/ZED-70-sample-change/notes.md": "x\n"})
        pkg, err = read(repo)
        assert err is None, err


    def test_scope_core_rejects_oversize():
        big = package(pad="x" * (1024 * 1024))
        rejects(make_repo(cfg=CFG, pkg=big), "1048576")
        many = ["force-app/main/default/classes/C%d.cls" % i for i in range(2001)]
        rejects_pkg("2000", scope=with_scope(modify=many))


    def test_scope_core_rejects_invalid_active():
        repo = make_repo(cfg=CFG, pkg=package())
        for active in ["ZED-7", "ZED-7-../x", "ZED-7-a/b", "zed-7-x", "ZED-7-X", "ZED-7-a b", "ZED-7-a\nHEAD:x", "", None]:
            rejects(repo, "active story", active=active)


    def test_scope_core_unknown_story():
        rejects(make_repo(cfg=CFG, pkg=package()), "commit", active="ZED-9-sample-change")


    def test_scope_core_reads_head_not_worktree():
        # 1. a work-tree edit widening the committed package is ignored
        repo = make_repo(cfg=CFG, pkg=package())
        wide = package(scope=with_scope(modify=[CLS, "force-app/main/default/classes/Wide.cls"]))
        write(repo, "impacts/%s/build-package.json" % ACTIVE, json.dumps(wide))
        pkg, err = read(repo)
        assert err is None and pkg["scope"]["modify"] == [CLS, CLS_META], (err, pkg)
        # 2. a work-tree edit to sourceRoot is ignored
        repo = make_repo(cfg=CFG, pkg=package(), dirs=(SRC + "/main/default/classes", "docs"))
        write(repo, ".ai-framework.json", json.dumps({"sourceRoot": "docs"}))
        assert scope().source_root_from_head(repo) == (SRC, None)
        pkg, err = read(repo)
        assert err is None, err
        # 3. a package deleted from the work tree is still read from HEAD
        repo = make_repo(cfg=CFG, pkg=package())
        os.remove(os.path.join(repo, "impacts", ACTIVE, "build-package.json"))
        pkg, err = read(repo)
        assert err is None and pkg["storyId"] == "ZED-7", err


    def test_scope_core_ignores_git_env():
        repo = make_repo(cfg=CFG, pkg=package())
        old = dict(os.environ)
        try:
            os.environ["GIT_DIR"] = os.path.join(TMP, "no-such-git-dir")
            os.environ["GIT_CONFIG_PARAMETERS"] = "'core.fsmonitor'='false'"
            pkg, err = read(repo)
        finally:
            os.environ.clear()
            os.environ.update(old)
        assert err is None, err


    def test_scope_core_git_failure_is_an_error():
        repo = make_repo(cfg=CFG, pkg=package())
        old = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = os.path.join(TMP, "empty-path")
            pkg, err = read(repo)
        finally:
            os.environ["PATH"] = old
        assert pkg is None and "git" in err, err
        pkg, err = scope().read_package(repo, ACTIVE, timeout=0.000001)
        assert pkg is None and err, err


    def test_scope_core_schema_version_exact_int():
        for bad in [True, 1.0, "1", 2, None]:
            rejects_pkg("schemaVersion", schemaVersion=bad)
        # schemaVersion absent
        pkg = package()
        del pkg["schemaVersion"]
        rejects(make_repo(cfg=CFG, pkg=pkg), "schemaVersion")


    BAD_CHARS = ["\x00", "\x1f", "\x7f", "\x85", "\x9f", "‪", "‮", "⁦", "⁩"]


    def test_scope_core_source_root_control_chars_no_exception():
        s = scope()
        for ch in BAD_CHARS:
            cfg = {"sourceRoot": "force" + ch + "app"}
            src, err = s.source_root_from_head(make_repo(cfg=cfg))
            assert src is None and err and "control character" in err, (repr(ch), err)
            rejects(make_repo(cfg=cfg, pkg=package()), "control character")


    def test_scope_core_entry_control_chars():
        for ch in BAD_CHARS:
            rejects_pkg("control character", scope=with_scope(modify=["force-app/main/default/classes/A" + ch + ".cls"]))
            rejects_pkg("control character", scope=with_scope(
                create=[{"api": "A", "type": "ApexClass", "path": "force-app/main/default/classes/B" + ch + ".cls"}]))
        # an ordinary non-ASCII letter is not a control character
        repo = make_repo(cfg=CFG, pkg=package(scope=with_scope(modify=["force-app/main/default/classes/Zé.cls"])))
        pkg, err = read(repo)
        assert err is None, err


    def test_scope_core_public_functions_never_raise():
        s = scope()
        pkg, err = s.read_package(None, ACTIVE)
        assert pkg is None and err == "read_package failed: TypeError", err
        src, err = s.source_root_from_head(None)
        assert src is None and err == "source_root_from_head failed: TypeError", err
        pkg, err = s.read_package(make_repo(cfg=CFG, pkg=package()), ACTIVE, timeout="soon")
        assert pkg is None and err.startswith("read_package failed: "), err


    def test_scope_core_git_env():
        s = scope()
        old = dict(os.environ)
        try:
            os.environ["GIT_DIR"] = "/nowhere"
            os.environ["GIT_NO_LAZY_FETCH"] = "0"
            env = s._git_env()
        finally:
            os.environ.clear()
            os.environ.update(old)
        assert env["GIT_NO_LAZY_FETCH"] == "1", env.get("GIT_NO_LAZY_FETCH")
        assert sorted(k for k in env if k.startswith("GIT_")) == ["GIT_NO_LAZY_FETCH"], env


    def test_scope_core_no_commits_yet():
        repo = make_repo(cfg=CFG, pkg=package(), commit=False)
        rejects(repo, "commit")

    return {n: f for n, f in locals().items() if n.startswith("test_") and callable(f)}


def check_core_units():
    """The trace_core and scope_core unit tests, against the cores beside this file."""
    check, results = checker()
    tmp = tempfile.mkdtemp(prefix="guard-cores-")
    try:
        hooks = os.path.join(tmp, "_nohooks")
        os.makedirs(hooks)
        try:
            cases = core_unit_cases(tmp, hooks)
        except Exception as e:
            check("WS8 core unit tests load", False, f"{type(e).__name__}: {e}")
            return False
        probe = os.path.join(tmp, "probe")
        try:
            os.symlink(tmp, probe)
            can_link = True
        except OSError:
            can_link = False
        for name in sorted(cases):
            if "symlink" in name and not can_link:
                print(f"[SKIP] WS8 core {name}: cannot create symlinks here")
                continue
            try:
                cases[name]()
                check(f"WS8 core {name}", True)
            except Exception as e:
                check(f"WS8 core {name}", False, f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return all(results)


def git(project, *args):
    subprocess.run(GIT + list(args), cwd=project, check=True, capture_output=True)


def put(project, rel, text):
    path = os.path.join(project, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


WORKTREE = "guard-wt"
_GUARD_MODULE = []


def guard_module():
    """guard.py loaded as a module, only to record baselines: the CLI needs a terminal, which a harness has no use for."""
    if not _GUARD_MODULE:
        spec = importlib.util.spec_from_file_location("guard_under_test", os.path.join(HERE, "guard.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GUARD_MODULE.append(mod)
    return _GUARD_MODULE[0]


def git_base(project):
    """Where the real .git lives: the project, or the main checkout when project is a linked worktree."""
    return os.path.dirname(project) if os.path.basename(project) == WORKTREE else project


def real_path(project, rel):
    base = git_base(project) if rel.startswith(".git/") else project
    return os.path.join(base, *rel.split("/"))


def drop(project):
    shutil.rmtree(git_base(project), ignore_errors=True)


def append(project, rel, text):
    path = real_path(project, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def make_project(committed_mode, files, git_init=True, pre_git=None, pre_remove=(), worktree=False):
    """A throwaway committed git repo shaped like the real one, with its .git baseline recorded."""
    project = tempfile.mkdtemp(prefix="guard-proj-")
    try:
        if git_init:
            subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)
        put(project, ".claude/settings.json", json.dumps({"env": {"AI_FRAMEWORK_MODE": committed_mode}}))
        for rel, text in files.items():
            if rel.startswith(".git/"):
                continue  # applied after the baseline exists
            if text is None:  # None means the file must be absent
                os.remove(os.path.join(project, *rel.split("/")))
            else:
                put(project, rel, text)
        for d in ("ai-context", "index", "force-app/main/default/classes"):
            os.makedirs(os.path.join(project, *d.split("/")), exist_ok=True)
        for keep in ("tools/guard/.keep", ".github/workflows/.keep"):
            put(project, keep, "")
        if git_init:
            git(project, "add", "-A")
            git(project, "commit", "-q", "-m", "init")
            for rel, text in (pre_git or {}).items():
                append(project, rel, text)
            for rel in pre_remove:
                path = real_path(project, rel)
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            if worktree:
                git(project, "worktree", "add", "-q", os.path.join(project, WORKTREE))
                project = os.path.join(project, WORKTREE)
            guard_module().write_baseline(project)
        for rel, text in files.items():
            if rel.startswith(".git/"):
                if text is None:
                    os.remove(real_path(project, rel))
                else:
                    put(git_base(project), rel, text)
    except BaseException:
        shutil.rmtree(git_base(project), ignore_errors=True)
        raise
    return project


def make_dirty(project, dirty):
    for rel in dirty:
        append(project, rel, "dirty\n")


def case_env(project, env_mode, extra=None):
    env = dict(os.environ)
    env.pop("AI_FRAMEWORK_MODE", None)
    env.pop("AI_FRAMEWORK_STORY", None)  # only a case's own extra environment may name a story
    env.update(extra or {})
    env["CLAUDE_PROJECT_DIR"] = project
    if env_mode is not None:
        env["AI_FRAMEWORK_MODE"] = env_mode
    return env


def send(wrapper, payload, env, cwd):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([wrapper], input=data.encode(), capture_output=True, env=env, cwd=cwd)
    return p.returncode, p.stderr.decode()


def merge(base, over):
    """Deep-merge dict over into base: dicts merge, anything else (lists included) is replaced."""
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            merge(base[key], val)
        else:
            base[key] = val
    return base


def guard_copy(policy):
    """A temp copy of the wrapper and guard.py next to a policy.json merged with `policy`. Returns (dir, wrapper)."""
    copy = tempfile.mkdtemp(prefix="guard-policy-")
    try:
        for name in (os.path.basename(WRAPPER), "guard.py") + CORE_FILES:
            shutil.copy(os.path.join(HERE, name), os.path.join(copy, name))
        wrapper = os.path.join(copy, os.path.basename(WRAPPER))
        os.chmod(wrapper, 0o755)
        with open(os.path.join(HERE, "policy.json"), encoding="utf-8") as f:
            merged = merge(json.load(f), policy)
        with open(os.path.join(copy, "policy.json"), "w", encoding="utf-8") as f:
            json.dump(merged, f)
    except BaseException:
        shutil.rmtree(copy, ignore_errors=True)
        raise
    return copy, wrapper


def run_case(case):
    project = make_project(case.committed_mode, case.files, case.git, case.pre_git, case.pre_remove, case.worktree)
    copy = None
    try:
        for rel, text in case.git_append.items():
            append(project, rel, text)
        make_dirty(project, case.dirty)
        for rel, text in case.post_files.items():
            if text is None:
                os.remove(os.path.join(project, *rel.split("/")))
            else:
                put(project, rel, text)
        for args in case.after:
            git(project, *args)
        payload = case.payload
        if isinstance(payload, dict) and isinstance(payload.get("cwd"), str):
            payload = dict(payload, cwd=payload["cwd"].replace("@PROJECT@", os.path.realpath(project)))
        wrapper = WRAPPER
        if case.policy:
            copy, wrapper = guard_copy(case.policy)
        return send(wrapper, payload, case_env(project, case.env_mode, case.env), project)
    finally:
        drop(project)
        if copy:
            shutil.rmtree(copy, ignore_errors=True)


def no_allowlist_variants(cases):
    """Task 4's Bash cases again with every mode's allowlist opened, so the write-target checks stay tested
    on their own: with the allowlist on, many of them are blocked for a different reason first."""
    for c in cases:
        p = c.payload
        if (isinstance(p, dict) and p.get("tool_name") == "Bash" and c.env_mode != "advise"
                and c.committed_mode == "normal" and not c.policy):
            changed = c.legacy is not None
            yield replace(c, name=f"{c.name} [no allowlist]", policy=OPEN,
                          want=c.legacy if changed else c.want, stderr_has="" if changed else c.stderr_has)


def check_settings_deny():
    """.claude/settings.json (two levels above this directory) denies every always-blocked sf prefix and no longer denies all of sf."""
    path = os.path.join(HERE, "..", "..", ".claude", "settings.json")
    name = "settings deny rules cover always-blocked sf commands"
    try:
        with open(path, encoding="utf-8") as f:
            deny = json.load(f)["permissions"]["deny"]
    except Exception as e:
        print(f"[FAIL] {name}: cannot read {path}: {e}")
        return False
    prefixes = sf_deny_prefixes()
    missing = [p for p in prefixes if f"Bash({p}*)" not in deny] + ([] if len(prefixes) >= 26 else ["<too few prefixes derived>"])
    kept = [d for d in ("Bash(sfdx *)", "Bash(git push*)", "Bash(curl *)", "Bash(wget *)", "WebFetch(*)") if d not in deny]
    ok = not missing and not kept and "Bash(sf *)" not in deny
    detail = "" if ok else f" missing={missing} dropped={kept} blanket_sf_rule_present={'Bash(sf *)' in deny}"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{detail}")
    return ok


def add_symlinks(project):
    """ai-context/fa -> force-app/, ai-context/link.cls -> force-app/A.cls and ai-context/tg -> tools/guard/."""
    os.symlink(os.path.join(project, "force-app"), os.path.join(project, "ai-context", "fa"), target_is_directory=True)
    os.symlink(os.path.join(project, "force-app", "A.cls"), os.path.join(project, "ai-context", "link.cls"))
    os.symlink(os.path.join(project, "tools", "guard"), os.path.join(project, "ai-context", "tg"), target_is_directory=True)


def run_symlink_case(case):
    project = make_project(case.committed_mode, case.files)
    try:
        add_symlinks(project)
        return send(WRAPPER, case.payload, case_env(project, case.env_mode), project)
    finally:
        shutil.rmtree(project, ignore_errors=True)


def run_without_python(case):
    """Run the wrapper with an empty directory as PATH: no Python, and no shell tools either."""
    shim = tempfile.mkdtemp(prefix="guard-nopy-")
    project = make_project(case.committed_mode, case.files)
    try:
        # The shim stays empty: guard.sh uses only shell builtins, and on Windows `where` cannot resolve.
        found = [py for py in INTERPRETERS if shutil.which(py, path=shim)]
        if found:
            return None, f"test setup invalid: {found} still on PATH"
        env = dict(case_env(project, case.env_mode), PATH=shim)
        return send(WRAPPER, case.payload, env, project)
    finally:
        shutil.rmtree(shim, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


def run_with_empty_path(case):
    """Run the wrapper with PATH set to the empty string: `env` cannot find `sh`, so the shebang must not use it."""
    project = make_project(case.committed_mode, case.files)
    try:
        return send(WRAPPER, case.payload, dict(case_env(project, case.env_mode), PATH=""), project)
    finally:
        shutil.rmtree(project, ignore_errors=True)


def run_fake_python(case, status):
    """PATH holds only a `python3` that exits `status`: the wrapper must not pass that status through."""
    shim = tempfile.mkdtemp(prefix="guard-fakepy-")
    project = make_project(case.committed_mode, case.files)
    try:
        fake = os.path.join(shim, "python3")
        with open(fake, "w") as f:
            f.write(f"#!/bin/sh\nexit {status}\n")
        os.chmod(fake, 0o755)
        return send(WRAPPER, case.payload, dict(case_env(project, case.env_mode), PATH=shim), project)
    finally:
        shutil.rmtree(shim, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


def run_without_guard_py(case):
    """Copy only the wrapper, so guard.py is missing next to it."""
    copy = tempfile.mkdtemp(prefix="guard-nogpy-")
    project = make_project(case.committed_mode, case.files)
    try:
        wrapper = os.path.join(copy, os.path.basename(WRAPPER))
        shutil.copy(WRAPPER, wrapper)
        os.chmod(wrapper, 0o755)
        return send(wrapper, case.payload, case_env(project, case.env_mode), project)
    finally:
        shutil.rmtree(copy, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


HOOK_COMMAND_CASE = Case("registered hook command blocks sf on this OS", bash("sf org login web"), 2, stderr_has="BLOCKED")


def hook_shell():
    """argv prefix that runs HOOK_COMMAND, or None when no suitable shell exists here.
    Inferred, not Confirmed (docs unreachable): Claude Code runs hook commands through a POSIX shell, and on
    Windows through Git Bash, which expands "$CLAUDE_PROJECT_DIR". On POSIX we use sh -c (bash would behave the
    same for this string). On Windows prefer Git for Windows' bash, never the WSL launcher: it must report Msys."""
    if os.name != "nt":
        return ["sh", "-c"]
    git_bash = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe")
    bash_exe = git_bash if os.path.exists(git_bash) else shutil.which("bash")
    if not bash_exe:
        return None
    try:
        p = subprocess.run([bash_exe, "-c", "uname -o"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return [bash_exe, "-c"] if b"msys" in p.stdout.lower() else None


def run_hook_command(case, mode=None, command=None):
    """Run the registered command string itself, in a throwaway project that carries tools/guard/ so
    $CLAUDE_PROJECT_DIR/tools/guard/guard.sh resolves inside it. `mode` sets guard.sh's file mode (the copy keeps
    its source mode otherwise). Returns None if there is no shell to use."""
    shell = hook_shell()
    if shell is None:
        return None
    project = make_project(case.committed_mode, case.files)
    try:
        dest = os.path.join(project, "tools", "guard")
        for name in ("guard.sh", "guard.cmd", "guard.py", "policy.json") + CORE_FILES:
            shutil.copy(os.path.join(HERE, name), os.path.join(dest, name))
        if mode is not None:
            os.chmod(os.path.join(dest, "guard.sh"), mode)
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "guard files")
        guard_module().write_baseline(project)
        data = json.dumps(case.payload).encode()
        p = subprocess.run(shell + [command or HOOK_COMMAND], input=data, capture_output=True,
                           env=case_env(project, case.env_mode), cwd=project)
        return p.returncode, p.stderr.decode()
    finally:
        shutil.rmtree(project, ignore_errors=True)


HOOK_NO_EXEC_CASE = Case("registered hook command blocks sf with guard.sh not executable (mode 0644)", bash("sf org login web"), 2, stderr_has="BLOCKED")
GITATTRIBUTES_RULES = ("*.sh text eol=lf", "*.cmd text eol=crlf", "tools/guard/*.json text eol=lf", "tools/guard/*.py text eol=lf")


def check_gitattributes():
    """.gitattributes (two levels above this directory) pins guard.sh to LF: a CRLF shebang breaks it on Windows."""
    name = ".gitattributes pins guard line endings"
    try:
        with open(os.path.join(HERE, "..", "..", ".gitattributes"), encoding="utf-8") as f:
            lines = [" ".join(ln.split("#")[0].split()) for ln in f]
    except OSError as e:
        print(f"[FAIL] {name}: {e}")
        return False
    missing = [r for r in GITATTRIBUTES_RULES if r not in lines]
    print(f"[{'FAIL' if missing else 'PASS'}] {name}" + (f": missing {missing}" if missing else ""))
    return not missing


def run_without_policy(case):
    """Copy the wrapper and guard.py, but not policy.json, and run that copy."""
    copy = tempfile.mkdtemp(prefix="guard-nopolicy-")
    project = make_project(case.committed_mode, case.files)
    try:
        for name in (os.path.basename(WRAPPER), "guard.py"):
            shutil.copy(os.path.join(HERE, name), os.path.join(copy, name))
        wrapper = os.path.join(copy, os.path.basename(WRAPPER))
        os.chmod(wrapper, 0o755)
        return send(wrapper, case.payload, case_env(project, case.env_mode), project)
    finally:
        shutil.rmtree(copy, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


def run_bad_stderr(case, kind):
    """Run a blocking payload with stderr closed, or a pipe whose read end is closed."""
    project = make_project(case.committed_mode, case.files)
    r = w = None
    try:
        kwargs = {}
        if kind == "closed":
            kwargs["preexec_fn"] = lambda: os.close(2)
        else:
            r, w = os.pipe()
            os.close(r)
            kwargs["stderr"] = w
        data = json.dumps(case.payload).encode()
        p = subprocess.run([WRAPPER], input=data, stdout=subprocess.PIPE, env=case_env(project, None), cwd=project, **kwargs)
        return p.returncode, ""
    finally:
        if w is not None:
            os.close(w)
        shutil.rmtree(project, ignore_errors=True)


def run_tty(args, cwd, env):
    """Run args with a pseudo-terminal as stdin: what a human at a keyboard looks like to isatty()."""
    master, slave = os.openpty()
    try:
        return subprocess.run(args, stdin=slave, cwd=cwd, env=env, capture_output=True).returncode
    finally:
        os.close(master)
        os.close(slave)


def check_rebaseline_cli():
    """--rebaseline needs a terminal and a git work tree; the hook cannot supply either."""
    ok = True
    guard = [sys.executable, "-I", os.path.join(HERE, "guard.py")]

    def check(name, got, want):
        nonlocal ok
        good = got == want
        print(f"[{'PASS' if good else 'FAIL'}] --rebaseline {name}: exit {got} (want {want})")
        ok = ok and good

    for name, git_init, args, tty, sub, want in (
            ("without a terminal", True, ["--rebaseline"], False, "", 2),
            ("with a terminal in a work tree", True, ["--rebaseline"], True, "", 0),
            ("with a terminal from a subdirectory", True, ["--rebaseline"], True, "ai-context", 0),
            ("with a terminal outside a work tree", False, ["--rebaseline"], True, "", 2),
            ("with an unknown argument", True, ["--rebaseline", "x"], True, "", 2)):
        if tty and os.name == "nt":
            print(f"[SKIP] --rebaseline {name}: needs a pty (POSIX only)")
            continue
        project = make_project("normal", {}, git_init)
        try:
            env = dict(os.environ)
            env.pop("CLAUDE_PROJECT_DIR", None)
            if not sub:
                env["CLAUDE_PROJECT_DIR"] = project
            cwd = os.path.join(project, sub) if sub else project
            baseline = os.path.join(project, ".git", "ai-guard-baseline")
            if git_init:
                os.remove(baseline)
            if tty:
                code = run_tty(guard + args, cwd, env)
            else:
                code = subprocess.run(guard + args, stdin=subprocess.DEVNULL, cwd=cwd, env=env, capture_output=True).returncode
            check(name, code, want)
            if want == 0:
                check(name + " wrote the baseline", os.path.exists(baseline), True)
        finally:
            shutil.rmtree(project, ignore_errors=True)
    return ok


def check_fsmonitor_not_run():
    """A planted core.fsmonitor must not run, whichever Bash command or write the guard is asked about."""
    ok = True
    for payload in (bash("git status"), bash("git diff"), write("ai-context/x.md")):
        project = make_project("normal", {})
        try:
            append(project, ".git/config", FSMON)
            send(WRAPPER, payload, case_env(project, None), project)
            ran = os.path.exists(os.path.join(project, "PWNED"))
            print(f"[{'FAIL' if ran else 'PASS'}] planted fsmonitor not run by the guard for {payload['tool_name']}")
            ok = ok and not ran
        finally:
            shutil.rmtree(project, ignore_errors=True)
    return ok


def make_big_tree(project, dirs=19, files=1000):
    """ai-context/big/d1..d<dirs>, each holding <files> empty files (left untracked: the tripwire never looks there)."""
    for d in range(1, dirs + 1):
        base = os.path.join(project, "ai-context", "big", f"d{d}")
        os.makedirs(base)
        for n in range(files):
            open(os.path.join(base, str(n)), "w").close()


BIG = "ai-context/big"
BIG_DIRS = " ".join(f"{BIG}/d{d}" for d in range(1, 20))
# C2: every target checked lexically before any walk, targets deduped, one walk budget per call, all well inside the hook timeout.
WALK_CASES = [
    (Case("C2: 30 big trees then tools/guard blocks fast (normal)", bash("rm -r " + " ".join([BIG] * 30) + " tools/guard"), 2, stderr_has="never allowed"), 8.0),
    (Case("C2: 30 big trees then tools/guard blocks fast (maintain)", bash("rm -r " + " ".join([BIG] * 30) + " tools/guard"), 2,
          env_mode="maintain", stderr_has="never allowed"), 8.0),
    (Case("C2: the same big tree ten times is walked once", bash("rm -r " + " ".join([BIG] * 10)), 0, env_mode="maintain"), 8.0),
    (Case("C2: walks of distinct targets share one budget", bash(f"rm -r {BIG_DIRS} {BIG}"), 2, env_mode="maintain",
          stderr_has="cannot determine"), 8.0),
    # R2: glob scanning is charged and capped, so these probes block well inside the hook timeout.
    (Case("R2: 1500 identical glob words then rm tools/guard", bash("ls" + f" {BIG}/*/z?" * 1500 + " ; rm -rf tools/guard"), 2,
          stderr_has="too many glob patterns"), 8.0),
    (Case("R2: 400 identical glob words then rm tools/guard", bash("ls" + f" {BIG}/*/z?" * 400 + " ; rm -rf tools/guard"), 2,
          stderr_has="too many glob patterns"), 8.0),
    (Case("R2: distinct glob words under the cap share the scan budget", bash("ls" + "".join(f" {BIG}/*/{n}?" for n in range(1, 60))), 2,
          stderr_has="too many names"), 8.0),
    (Case("R2: quoted globs in write targets are charged too", bash(f"rm '{BIG}/*/z?' ; " * 1500 + "rm -rf tools/guard"), 2), 8.0),
    (Case("R2: literal names below a glob are charged too", bash("".join(f"rm '{BIG}/*/z{n}' ; " for n in range(1500)) + "ls"), 2,
          env_mode="maintain", stderr_has="cannot determine"), 8.0),
    (Case("R2: quoted globs in cp sources share the scan budget", bash(f"cp '{BIG}/*/1?' '{BIG}/*/2?' ai-context/x"), 2,
          env_mode="maintain", stderr_has="cannot determine"), 8.0),
    (Case("R2: one glob over the big tree is still allowed", bash(f"ls {BIG}/*/1?"), 0), 8.0),
]


def check_walk_budget():
    ok = True
    for case, limit in WALK_CASES:
        project = make_project(case.committed_mode, case.files)
        try:
            make_big_tree(project)
            start = time.monotonic()
            code, err = send(WRAPPER, case.payload, case_env(project, case.env_mode), project)
            took = time.monotonic() - start
        finally:
            drop(project)
        good = report(case, code, err) and took < limit
        print(f"[{'PASS' if took < limit else 'FAIL'}] {case.name}: took {took:.2f}s (limit {limit}s)")
        ok = ok and good
    return ok


def guard_exit(fn, *args):
    """(exit code, stderr) of calling a guard function in-process; 0 when it returns normally."""
    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    try:
        fn(*args)
        code = 0
    except SystemExit as e:
        code = e.code
    finally:
        sys.stderr = old
    return code, err.getvalue()


def check_deadline():
    """Past the internal deadline the guard blocks; git subprocesses get at most 3 s and a timeout is unverifiable."""
    g = guard_module()
    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        print(f"[{'PASS' if good else 'FAIL'}] {name}{'' if good else ' ' + detail}")
        ok = ok and good

    project = make_project("normal", {"ai-context/x/a": ""})
    saved_deadline, saved_run = g.DEADLINE[0], g.subprocess.run
    try:
        g.DEADLINE[0] = time.monotonic() - 1
        code, err = guard_exit(g.walk_paths, os.path.join(project, "ai-context"))
        check("C2: a walk past the deadline blocks", code == 2 and "ran out of time" in err, f"exit {code} {err!r}")
        code, err = guard_exit(g.check_deadline)
        check("C2: the deadline check itself blocks once passed", code == 2 and "failing closed" in err, f"exit {code} {err!r}")
        g.DEADLINE[0] = time.monotonic() + 60
        code, _ = guard_exit(g.check_deadline)
        check("C2: the deadline check passes before the deadline", code == 0, f"exit {code}")
        seen = []

        def fake_run(cmd, **kw):
            seen.append(kw.get("timeout"))
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

        g.subprocess.run = fake_run
        dirty = g.tripwire_dirty(project, ["tools/guard"])
        check("C2: every git subprocess timeout is at most 3 s", bool(seen) and all(t is not None and t <= 3 for t in seen), f"timeouts {seen}")
        check("C2: a git timeout makes the tripwire unverifiable", dirty is None, f"got {dirty!r}")
    finally:
        g.DEADLINE[0], g.subprocess.run = saved_deadline, saved_run
        drop(project)
    return ok


def check_glob_scan():
    """R2: the guard's charged glob matcher finds what glob.glob finds, charges every scanned entry, and stops at the deadline."""
    import glob as globmod
    g = guard_module()
    ok = True

    def check(name, good, detail=""):
        nonlocal ok
        print(f"[{'PASS' if good else 'FAIL'}] {name}{'' if good else ' ' + detail}")
        ok = ok and good

    files = {"a/x.md": "", "a/.h.md": "", "a/-o": "", "a/b/y.md": "", "a/[k]/z": "", "c/x.md": ""}
    project = make_project("normal", {f"ai-context/{k}": v for k, v in files.items()})
    saved_deadline = g.DEADLINE[0]
    g.DEADLINE[0] = time.monotonic() + 60  # the module's own deadline was set when it was imported
    try:
        base = os.path.join(os.path.realpath(project), "ai-context")
        for pat in ("*/*.md", "a/*", "a/.*", "*/", "a/[!x]*", "a/[[]k]/*", "?/b/*", "a/../c/*", "nope/*", "a/b/y.md"):
            full = os.path.join(globmod.escape(base), pat)
            g.BUDGET[0], g.GLOBBED = g.WALK_LIMIT, {}
            got, want = g.glob_scan(full), globmod.glob(full)
            check(f"R2: glob_scan matches glob.glob for {pat!r}", got is not None and sorted(got) == sorted(want), f"{got} != {want}")
        g.BUDGET[0], g.GLOBBED = g.WALK_LIMIT, {}
        g.glob_scan(os.path.join(globmod.escape(base), "a/*.none"))
        check("R2: every scanned entry is charged, not only matches", g.BUDGET[0] == g.WALK_LIMIT - 5, f"budget {g.BUDGET[0]}")
        g.BUDGET[0], g.GLOBBED = 3, {}
        check("R2: glob_scan returns None once the budget is spent", g.glob_scan(os.path.join(globmod.escape(base), "a/*")) is None)
        g.BUDGET[0], g.GLOBBED = g.WALK_LIMIT, {}
        g.DEADLINE[0] = time.monotonic() - 1
        code, err = guard_exit(g.glob_reason, [["ls", "ai-context/a/\ue000"]], os.path.realpath(project))
        check("R2: glob checking past the deadline blocks", code == 2 and "ran out of time" in err, f"exit {code} {err!r}")
        many = os.path.join(base, "many")
        os.makedirs(many)
        for n in range(300):
            open(os.path.join(many, str(n)), "w").close()
        g.BUDGET[0], g.GLOBBED = g.WALK_LIMIT, {}
        code, err = guard_exit(g.glob_scan, os.path.join(globmod.escape(many), "*"))
        check("R2: a long directory scan checks the deadline as it goes", code == 2 and "ran out of time" in err, f"exit {code} {err!r}")
    finally:
        g.DEADLINE[0] = saved_deadline
        g.BUDGET[0], g.GLOBBED = g.WALK_LIMIT, {}
        drop(project)
    return ok


def check_story_outputs():
    """The guard lists every file the --id/--slug writers put in ai-context/<id>-<slug>/ (write_report.py:212-213)."""
    g = guard_module()
    d = os.path.join("ai-context", "1-x")
    got = g.script_targets("framework/skills/story-impact/scripts/write_report.py",
                           ["--id", "1", "--slug", "x", "--classified", "ai-context/c.json"])
    want = ([os.path.join(d, ""), os.path.join(d, "impact.json"), os.path.join(d, "impact.md")], False)
    good = got == want
    print(f"[{'PASS' if good else 'FAIL'}] write_report impact.json path modelled{'' if good else f' {got} != {want}'}")
    return good


def check_design_outputs():
    """write_design.py's files (write_design.py:132-133) and build_index --from-config's <checkout>/index are modelled."""
    g = guard_module()
    d = os.path.join("ai-context", "1-x")
    got = g.script_targets("framework/skills/solution-design/scripts/write_design.py",
                           ["--id", "1", "--slug", "x", "--draft", "ai-context/d.json"])
    want = ([os.path.join(d, ""), os.path.join(d, "design.json"), os.path.join(d, "design.md")], False)
    i = os.path.join(os.path.realpath(os.getcwd()), "index")
    try:
        got_idx = g.script_targets("tools/index/build_index.py", ["--from-config"], os.getcwd())
    except TypeError as e:  # a guard without the cwd argument
        got_idx = f"TypeError: {e}"
    want_idx = ([os.path.join(i, ""), os.path.join(i, "metadata.json"), os.path.join(i, "inventory.json")], False)
    good = got == want and got_idx == want_idx
    note = "" if good else f" {got} != {want} or {got_idx} != {want_idx}"
    print(f"[{'PASS' if good else 'FAIL'}] write_design design.json and --from-config index paths modelled{note}")
    return good


def check_hook_matcher():
    """I4: the hook runs for every tool, so MCP and future tools cannot skip the guard."""
    name = "settings hook matcher covers every tool"
    try:
        with open(os.path.join(HERE, "..", "..", ".claude", "settings.json"), encoding="utf-8") as f:
            matcher = json.load(f)["hooks"]["PreToolUse"][0]["matcher"]
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        return False
    good = matcher == ".*"
    print(f"[{'PASS' if good else 'FAIL'}] {name}" + ("" if good else f": matcher is {matcher!r}"))
    return good


def hook_command_results():
    """The two registered-hook-command cases. A missing Msys bash is a SKIP on a laptop but a FAIL under CI."""
    hook = run_hook_command(HOOK_COMMAND_CASE)
    if hook is None:
        if os.environ.get("CI"):
            print("[FAIL] 2 registered hook command cases: no Git for Windows bash (Msys) on this CI runner")
            return [False]
        print("[SKIP] 2 registered hook command cases: no Git for Windows bash (Msys) here")
        return []
    return [report(HOOK_COMMAND_CASE, *hook), report(HOOK_NO_EXEC_CASE, *run_hook_command(HOOK_NO_EXEC_CASE, mode=0o644))]


def report(case, code, err):
    ok = code == case.want and case.stderr_has in err and not (case.stderr_lacks and case.stderr_lacks in err)
    note = "" if ok else f" stderr: {err.strip()!r}"
    print(f"[{'PASS' if ok else 'FAIL'}] {case.name}: exit {code} (want {case.want}){note}")
    return ok


def main():
    results = []
    for case in (CASES + ALLOWLIST_CASES + FIX_CASES + FIX2_CASES + FIX3_CASES + FIX4_CASES + TRIPWIRE_CASES + REBASELINE_CASES
                 + ROUND2_CASES + FINAL_CASES + EXTRA_CASES + list(no_allowlist_variants(CASES))
                 + SCOPE_CASES + SCOPE_BASH_CASES + list(no_allowlist_variants(SCOPE_BASH_CASES)) + PUBLISH_CASES):
        results.append(report(case, *run_case(case)))
    results.append(check_core_units())
    results.append(check_source_root_drift())
    results.append(check_package_drift())
    results.append(check_scope_lazy())
    results.append(check_scope_git_failure())
    results.append(check_scope_git_gate())
    results.append(check_scope_fsmonitor())
    results.append(check_scope_symlink())
    results.append(check_scope_hardlink())
    results.append(check_start_modelled())
    results.append(check_run_all_refused())
    results.append(check_settings_deny())
    results.append(check_hook_matcher())
    results.append(check_walk_budget())
    results.append(check_deadline())
    results.append(check_glob_scan())
    results.append(check_story_outputs())
    results.append(check_design_outputs())
    results.append(check_rebaseline_cli())
    results.append(check_fsmonitor_not_run())
    results.append(report(NO_PYTHON_CASE, *run_without_python(NO_PYTHON_CASE)))
    results.append(report(NO_POLICY_CASE, *run_without_policy(NO_POLICY_CASE)))
    results.append(check_gitattributes())
    results += hook_command_results()
    if os.name == "nt":  # fake interpreters and the sh wrapper are POSIX only
        print("[SKIP] 3 wrapper status cases: POSIX only")
    else:
        for status, case in FAKE_PYTHON_CASES:
            results.append(report(case, *run_fake_python(case, status)))
        results.append(report(NO_GUARD_PY_CASE, *run_without_guard_py(NO_GUARD_PY_CASE)))
    if os.name == "nt":  # an empty PATH on Windows breaks cmd itself, not the wrapper's shebang
        print("[SKIP] empty PATH fails closed: POSIX only")
    else:
        results.append(report(EMPTY_PATH_CASE, *run_with_empty_path(EMPTY_PATH_CASE)))
    skipped = 0
    if os.name == "nt":  # needs fd-level stderr control that Windows subprocess cannot give
        skipped += len(BAD_STDERR_CASES)
        print(f"[SKIP] {len(BAD_STDERR_CASES)} bad-stderr cases: POSIX only")
    else:
        for kind, case in BAD_STDERR_CASES:
            results.append(report(case, *run_bad_stderr(case, kind)))
    probe = tempfile.mkdtemp(prefix="guard-link-probe-")
    try:
        os.symlink(probe, os.path.join(probe, "probe"))
        can_link = True
    except OSError as e:  # Windows without Developer Mode or admin cannot create symlinks
        can_link = False
        skipped += len(SYMLINK_CASES)
        print(f"[SKIP] {skipped} symlink cases: cannot create symlinks here ({e})")
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    if can_link:
        for case in SYMLINK_CASES:
            results.append(report(case, *run_symlink_case(case)))
    failures = results.count(False)
    print(f"\n{len(results) - failures} passed, {failures} failed" + (f", {skipped} skipped" if skipped else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
