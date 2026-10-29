#!/usr/bin/env python3
"""Prove the guard blocks. Run in CI (Linux + Windows) and once per laptop at onboarding.

Each case is a synthetic hook payload and the exit code we require. Every case runs
in a throwaway git repo, so nothing depends on the checkout the tests live in.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
WRAPPER = os.path.join(HERE, "guard.cmd" if os.name == "nt" else "guard.sh")
INTERPRETERS = ("python3", "python", "py")
GIT = ["git", "-c", "user.name=guard-test", "-c", "user.email=guard-test@example.com"]


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


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def write(path, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": path}}


def fetch(url):
    return {"tool_name": "WebFetch", "tool_input": {"url": url}}


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
    Case("maintain: touch with ${X} target blocked", bash("touch docs/${X}.md"), 2, env_mode="maintain", stderr_has="cannot determine what this command writes"),
    Case("maintain: touch with brace expansion blocked", bash("touch docs/{a,b}.md"), 2, env_mode="maintain"),
    Case("maintain: $ in a non-target argument allowed", bash('echo "$HOME" > docs/x.md'), 0, env_mode="maintain"),
    Case("maintain: rm glob inside docs allowed", bash("rm docs/*.md"), 0, env_mode="maintain"),
    Case("maintain: command substitution blocked", bash("echo $(id) > docs/x"), 2, env_mode="maintain"),
    Case("maintain: backtick blocked", bash("echo `id` > docs/x"), 2, env_mode="maintain"),
    Case("maintain: substitution in double quotes blocked", bash('echo "$(id)" > docs/x'), 2, env_mode="maintain"),
    Case("maintain: process substitution into tee blocked", bash("echo a | tee >(cat) docs/x"), 2, env_mode="maintain"),
    Case("maintain: single-quoted substitution text allowed", bash("echo '$(id)' > docs/x"), 0, env_mode="maintain"),
    Case("normal: $VAR in target blocked", bash("echo a > $OUT"), 2),
    Case("normal: $ in an echo argument allowed", bash('echo "$HOME"'), 0),
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
    Case("maintain: chmod mode is not a path", bash("chmod 755 docs/x.sh"), 0, env_mode="maintain"),
    Case("maintain: chmod +x on force-app blocked", bash("chmod +x force-app/x.sh"), 2, env_mode="maintain"),
    Case("maintain: chmod -x on force-app blocked", bash("chmod -x force-app/x.sh"), 2, env_mode="maintain"),
    Case("maintain: chown owner is not a path", bash("chown me docs/x"), 0, env_mode="maintain"),
    Case("maintain: chmod --reference unknown", bash("chmod --reference=docs/a force-app/x"), 2, env_mode="maintain"),
    Case("maintain: truncate -s on force-app blocked", bash("truncate -s 0 force-app/x"), 2, env_mode="maintain"),
    Case("maintain: truncate -s on docs allowed", bash("truncate -s 0 docs/x"), 0, env_mode="maintain"),
    Case("maintain: touch -d value is not a path", bash("touch -d yesterday docs/x"), 0, env_mode="maintain"),
    Case("maintain: dd of= force-app blocked", bash("dd if=docs/a of=force-app/a"), 2, env_mode="maintain"),
    Case("maintain: dd of= docs allowed", bash("dd if=docs/a of=docs/b"), 0, env_mode="maintain"),
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
    Case("maintain: tee -a docs allowed", bash("echo a | tee -a docs/x"), 0, env_mode="maintain"),
    Case("maintain: tee to two files, one forbidden, blocked", bash("echo a | tee docs/x force-app/y"), 2, env_mode="maintain"),
    Case("maintain: mv within docs allowed", bash("mv docs/a docs/b"), 0, env_mode="maintain"),
    Case("maintain: cp from force-app into docs allowed", bash("cp force-app/main/default/classes/A.cls docs/A.cls"), 0, env_mode="maintain"),
    Case("normal: touch in docs blocked", bash("touch docs/x"), 2),
    Case("normal: touch in ai-context allowed", bash("touch ai-context/x"), 0),
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
    Case("I: rm -rf ai-context/tmp/* allowed in normal", bash("rm -rf ai-context/tmp/*"), 0, files={"ai-context/tmp/a": "x"}),
    # B: expansion in non-target words.
    Case("B: $T carries -t", bash("T=-t; cp $T tools/guard ai-context/e"), 2),
    Case("B: unassigned $T in cp blocked", bash("cp $T tools/guard ai-context/e"), 2),
    Case("B: brace expansion carries -t", bash("cp {-t,tools/guard/} ai-context/e"), 2),
    Case("B: ANSI-C quote carries -t", bash("cp $'-t' tools/guard ai-context/e"), 2),
    Case("B: ${X}= in dd blocked", bash("dd ${X}=tools/guard/guard.py if=ai-context/e"), 2),
    Case("B: $X in sed blocked", bash("sed $X s/a/b/ tools/guard/guard.py"), 2),
    Case("B: $ in a non-writer command still allowed", bash('echo "$HOME" > ai-context/ok'), 0),
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
    Case("E: test builtin [ is not a glob", bash("[ -f docs/a ] && ls"), 0),
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
    Case("H: w inside a regex is not a command", bash("sed 's/we/x/' ai-context/e"), 0),
    Case("H: w inside an address regex is not a command", bash("sed -n '/w/p' ai-context/e"), 0),
    Case("I: BSD sed -i .bak allowed in ai-context", bash("sed -i .bak 's/a/b/' ai-context/x"), 0),
    Case("I: BSD sed -i .bak on force-app blocked", bash("sed -i .bak 's/a/b/' force-app/x"), 2),
    Case("I: GNU sed -i.bak allowed in ai-context", bash("sed -i.bak 's/a/b/' ai-context/x"), 0),
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

# A payload the guard ALLOWS, so exit 2 can only come from the wrapper's fail-closed branch.
NO_PYTHON_CASE = Case("no interpreter fails closed", bash("git status"), 2, stderr_has="no Python interpreter found")
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
]


def git(project, *args):
    subprocess.run(GIT + list(args), cwd=project, check=True, capture_output=True)


def put(project, rel, text):
    path = os.path.join(project, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_project(committed_mode, files):
    """A throwaway committed git repo shaped like the real one."""
    project = tempfile.mkdtemp(prefix="guard-proj-")
    try:
        subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)
        put(project, ".claude/settings.json", json.dumps({"env": {"AI_FRAMEWORK_MODE": committed_mode}}))
        for rel, text in files.items():
            if text is None:  # None means the file must be absent
                os.remove(os.path.join(project, *rel.split("/")))
            else:
                put(project, rel, text)
        for d in ("ai-context", "index", "force-app/main/default/classes"):
            os.makedirs(os.path.join(project, *d.split("/")), exist_ok=True)
        for keep in ("tools/guard/.keep", ".github/workflows/.keep"):
            put(project, keep, "")
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "init")
    except BaseException:
        shutil.rmtree(project, ignore_errors=True)
        raise
    return project


def make_dirty(project, dirty):
    for rel in dirty:
        path = os.path.join(project, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("dirty\n")


def case_env(project, env_mode):
    env = dict(os.environ)
    env.pop("AI_FRAMEWORK_MODE", None)
    env["CLAUDE_PROJECT_DIR"] = project
    if env_mode is not None:
        env["AI_FRAMEWORK_MODE"] = env_mode
    return env


def send(wrapper, payload, env, cwd):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([wrapper], input=data.encode(), capture_output=True, env=env, cwd=cwd)
    return p.returncode, p.stderr.decode()


def run_case(case):
    project = make_project(case.committed_mode, case.files)
    try:
        make_dirty(project, case.dirty)
        payload = case.payload
        if isinstance(payload, dict) and isinstance(payload.get("cwd"), str):
            payload = dict(payload, cwd=payload["cwd"].replace("@PROJECT@", os.path.realpath(project)))
        return send(WRAPPER, payload, case_env(project, case.env_mode), project)
    finally:
        shutil.rmtree(project, ignore_errors=True)


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
    """Run the wrapper with a PATH that holds the shell tools it needs and no Python."""
    shim = tempfile.mkdtemp(prefix="guard-nopy-")
    project = make_project(case.committed_mode, case.files)
    try:
        if os.name != "nt":
            # guard.sh needs sh (via its /usr/bin/env shebang) and dirname; link only those.
            for tool in ("sh", "dirname"):
                os.symlink(shutil.which(tool), os.path.join(shim, tool))
        # On Windows the shim stays empty: `where` cannot resolve, so guard.cmd falls through.
        found = [py for py in INTERPRETERS if shutil.which(py, path=shim)]
        if found:
            return None, f"test setup invalid: {found} still on PATH"
        env = dict(case_env(project, case.env_mode), PATH=shim)
        return send(WRAPPER, case.payload, env, project)
    finally:
        shutil.rmtree(shim, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)


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


def report(case, code, err):
    ok = code == case.want and case.stderr_has in err
    note = "" if ok else f" stderr: {err.strip()!r}"
    print(f"[{'PASS' if ok else 'FAIL'}] {case.name}: exit {code} (want {case.want}){note}")
    return ok


def main():
    results = []
    for case in CASES:
        results.append(report(case, *run_case(case)))
    results.append(report(NO_PYTHON_CASE, *run_without_python(NO_PYTHON_CASE)))
    results.append(report(NO_POLICY_CASE, *run_without_policy(NO_POLICY_CASE)))
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
