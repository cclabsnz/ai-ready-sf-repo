#!/usr/bin/env python3
"""Render the impact register as one static, self-contained HTML page.

Usage:
  render_register.py [--root .] [--out ai-context/register/register.html]

The page shows the HEAD short commit, the components that two or more in-flight stories
list (conflicts first), every story on record, and the files that failed validation.
It has inline CSS only: no scripts and no external URLs. All text is HTML-escaped.

--out defaults to <root>/ai-context/register/register.html; a relative --out resolves
against --root. The tool refuses (exit 2, nothing written) when the out file's folder
resolves outside <root>/ai-context/ or the out file is a symlink.

Prints the written path on stdout. Exit codes: 0 ok, 2 bad usage or refused path.
Stdlib only. Data comes from --root; code never does.
"""
import argparse
import html
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from register import CONFLICT_TYPES, component_map, load_register, register_commit  # noqa: E402


def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def resolve_out(root, out):
    """Return the absolute out path, or None when it is refused."""
    base = os.path.realpath(root)
    ctx = os.path.join(base, "ai-context")
    if os.path.realpath(os.path.join(root, "ai-context")) != ctx:
        return None
    if out is None:
        out = os.path.join("ai-context", "register", "register.html")
    if not os.path.isabs(out):
        out = os.path.join(root, out)
    folder = os.path.realpath(os.path.dirname(out))
    if folder != ctx and not folder.startswith(ctx + os.sep):
        return None
    if os.path.islink(out):
        return None
    return os.path.join(folder, os.path.basename(out))


def write_nofollow(path, text):
    """Write text to path, never through a symlink. O_NOFOLLOW where the platform has it
    (not Windows); the caller's islink check covers the rest."""
    if os.path.islink(path):
        raise OSError("%s is a symlink" % path)
    flags = (os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))


def shared_rows(cmap):
    """Components listed by two or more stories: (kind, api, entries), conflicts first."""
    rows = []
    for api, entries in cmap.items():
        stories = {e["storyId"] for e in entries}
        if len(stories) < 2:
            continue
        changers = {e["storyId"] for e in entries if e["changeType"] in CONFLICT_TYPES}
        kind = "conflict" if len(changers) >= 2 else "watch"
        rows.append((kind, api, entries))
    rows.sort(key=lambda r: (0 if r[0] == "conflict" else 1, r[1]))
    return rows


CSS = """
:root{
  --panel:#E4E7E3;--plate:#F4F5F2;--ink:#121614;--muted:#4F5753;--rule:#C3C8C2;
  --red:#B3261E;--amber:#8A5A00;--red-tint:#F6E3E0;--amber-tint:#F3EAD6;
  --display:"DIN Alternate",Bahnschrift,"DIN 2014","Arial Narrow",sans-serif;
  --body:"Avenir Next","Segoe UI","Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  color-scheme:light dark;
}
@media (prefers-color-scheme:dark){:root{
  --panel:#161A19;--plate:#1F2422;--ink:#E6E9E5;--muted:#9AA39E;--rule:#343B38;
  --red:#F2675C;--amber:#E3A93B;--red-tint:#3A1F1C;--amber-tint:#352B17;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--panel);color:var(--ink);font:400 0.9375rem/1.5 var(--body);
  font-variant-numeric:tabular-nums}
main{max-width:72rem;margin:0 auto;padding:3rem 1.5rem 4rem}
code,.mono{font-family:var(--mono);font-size:0.8125rem}
header.top{display:grid;grid-template-columns:1fr auto;gap:0.5rem 2rem;align-items:end;
  padding-bottom:1.75rem;border-bottom:2px solid var(--ink)}
.kicker{font:600 0.75rem/1 var(--mono);text-transform:uppercase;letter-spacing:0.12em;
  color:var(--muted);margin:0 0 0.75rem}
h1{font:700 clamp(2.25rem,7vw,4.5rem)/0.95 var(--display);letter-spacing:-0.02em;margin:0}
.head{text-align:right}
.head .label{font:600 0.75rem/1 var(--mono);text-transform:uppercase;letter-spacing:0.12em;
  color:var(--muted)}
.head .sha{font:700 clamp(1.5rem,4vw,2.25rem)/1.1 var(--mono);margin-top:0.35rem}
.tally{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:0.5rem;margin:1rem 0 0;padding:0;
  list-style:none}
.tally li{display:inline-flex;align-items:baseline;gap:0.4rem;padding:0.3rem 0.6rem;
  border:1px solid var(--rule);border-radius:2px;background:var(--plate);
  font:600 0.75rem/1.2 var(--mono);text-transform:uppercase;letter-spacing:0.08em}
.tally b{font:700 1rem/1 var(--display);letter-spacing:0}
.tally .t-red{border-color:var(--red);color:var(--red)}
.tally .t-amber{border-color:var(--amber);color:var(--amber)}
section{margin-top:3rem}
h2{font:700 1.25rem/1.2 var(--display);letter-spacing:0.01em;margin:0 0 0.25rem}
.note{color:var(--muted);margin:0 0 1rem;max-width:44rem}
.empty{padding:1.25rem;border:1px dashed var(--rule);border-radius:2px;color:var(--muted);
  background:var(--plate);margin:0}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:2px;background:var(--plate)}
table{border-collapse:collapse;width:100%;min-width:40rem}
th{font:600 0.6875rem/1 var(--mono);text-transform:uppercase;letter-spacing:0.12em;
  color:var(--muted);text-align:left;padding:0.75rem 1rem;border-bottom:1px solid var(--rule)}
td{padding:0.85rem 1rem;border-top:1px solid var(--rule);vertical-align:top}
tbody tr:first-child td{border-top:0}
td.lamp{width:7.5rem;border-left:6px solid transparent;font:700 0.75rem/1.3 var(--mono);
  text-transform:uppercase;letter-spacing:0.1em;white-space:nowrap}
tr.conflict td.lamp{border-left-color:var(--red);color:var(--red);background:var(--red-tint)}
tr.watch td.lamp{border-left-color:var(--amber);color:var(--amber);background:var(--amber-tint)}
td.api code{font-size:0.875rem;font-weight:600;overflow-wrap:anywhere}
td.type{color:var(--muted);white-space:nowrap}
.train{display:flex;flex-wrap:wrap;align-items:center;gap:0.35rem}
.claim{display:inline-flex;flex-direction:column;padding:0.3rem 0.55rem;border:1px solid var(--rule);
  border-radius:2px;background:var(--panel);line-height:1.25}
.claim .sid{font:700 0.8125rem/1.2 var(--mono)}
.claim .sub{font-size:0.75rem;color:var(--muted)}
.claim.chg{border-color:var(--ink)}
.coupler{width:0.9rem;height:2px;background:var(--rule)}
ol.stories{list-style:none;margin:0;padding:0;border-top:1px solid var(--rule)}
ol.stories>li{display:grid;grid-template-columns:minmax(8rem,12rem) 1fr auto;gap:0.25rem 1.5rem;
  padding:1rem 0;border-bottom:1px solid var(--rule)}
.s-id{font:700 1.125rem/1.2 var(--mono);overflow-wrap:anywhere}
.s-slug{color:var(--muted);font-size:0.8125rem;overflow-wrap:anywhere}
dl.facts{display:flex;flex-wrap:wrap;gap:0.25rem 1.5rem;margin:0}
dl.facts div{display:flex;gap:0.4rem;align-items:baseline}
dt{font:600 0.6875rem/1 var(--mono);text-transform:uppercase;letter-spacing:0.1em;color:var(--muted)}
dd{margin:0;overflow-wrap:anywhere}
.count{text-align:right;font:700 1.75rem/1 var(--display)}
.count span{display:flex;justify-content:flex-end;font:600 0.6875rem/1.4 var(--mono);
  text-transform:uppercase;letter-spacing:0.1em;color:var(--muted)}
ul.decisions{grid-column:2/-1;margin:0.5rem 0 0;padding:0;list-style:none}
ul.decisions li{padding:0.4rem 0 0.4rem 0.75rem;border-left:2px solid var(--rule);
  margin-top:0.35rem;overflow-wrap:anywhere}
ul.decisions .role{font:600 0.75rem/1 var(--mono);color:var(--muted);margin-right:0.4rem}
#invalid ul{margin:0;padding:0;list-style:none}
#invalid li{padding:0.75rem 1rem;border:1px solid var(--red);border-radius:2px;
  background:var(--plate);margin-top:0.5rem}
#invalid code{overflow-wrap:anywhere}
#invalid .errs{margin:0.35rem 0 0;padding-left:1.1rem;color:var(--muted);overflow-wrap:anywhere}
footer{margin-top:3.5rem;padding-top:1rem;border-top:1px solid var(--rule);color:var(--muted);
  font-size:0.8125rem}
.scroll:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
@media (max-width:40rem){
  main{padding:2rem 1rem 3rem}
  td.lamp{width:5.5rem;padding-left:0.6rem;padding-right:0.6rem}
  header.top{grid-template-columns:1fr}
  .head{text-align:left}
  ol.stories>li{grid-template-columns:1fr auto}
  ol.stories>li>.facts-wrap{grid-column:1/-1;grid-row:2}
  ul.decisions{grid-column:1/-1}
}
"""


def _plural(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def render(reg, commit):
    impacts = sorted(reg["impacts"], key=lambda d: str(d.get("storyId")))
    invalid = reg["invalid"]
    rows = shared_rows(component_map(impacts))
    n_conflict = sum(1 for r in rows if r[0] == "conflict")
    n_watch = len(rows) - n_conflict

    out = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           "<title>Impact register %s</title>" % esc(commit),
           "<style>%s</style>" % CSS, "</head>", "<body>", "<main>"]

    out += ['<header class="top">', "<div>", '<p class="kicker">Track occupancy</p>',
            "<h1>Impact register</h1>", "</div>",
            '<div class="head"><div class="label">HEAD</div>'
            '<div class="sha">%s</div></div>' % esc(commit),
            '<ul class="tally">',
            '<li class="t-red"><b>%d</b> %s</li>' % (n_conflict, "conflict" if n_conflict == 1 else "conflicts"),
            '<li class="t-amber"><b>%d</b> %s</li>' % (n_watch, "watch" if n_watch == 1 else "watches"),
            "<li><b>%d</b> %s</li>" % (len(impacts), "story" if len(impacts) == 1 else "stories"),
            "</ul>" if not invalid else
            '<li class="t-red"><b>%d</b> invalid</li></ul>' % len(invalid),
            "</header>"]

    out += ['<section id="shared">', "<h2>Shared components</h2>",
            '<p class="note">Components that two or more in-flight stories list. A conflict '
            "means at least two of them create, modify or delete it; a watch means the "
            "others only review it. Shipped stories are left out.</p>"]
    if rows:
        out += ['<div class="scroll" role="region" aria-label="Shared components" tabindex="0">'
                "<table>",
                "<thead><tr><th>Signal</th><th>Component</th><th>Type</th>"
                "<th>Stories (squad, change)</th></tr></thead>", "<tbody>"]
        for kind, api, entries in rows:
            types = ", ".join(sorted({str(e["type"]) for e in entries}))
            claims = []
            for e in entries:
                chg = " chg" if e["changeType"] in CONFLICT_TYPES else ""
                claims.append('<span class="claim%s"><span class="sid">%s</span>'
                              '<span class="sub">%s, %s</span></span>' % (
                                  chg, esc(e["storyId"]), esc(e["squad"]), esc(e["changeType"])))
            out.append('<tr class="%s"><td class="lamp">%s</td><td class="api"><code>%s</code></td>'
                       '<td class="type">%s</td><td><div class="train">%s</div></td></tr>' % (
                           kind, kind, esc(api), esc(types),
                           '<span class="coupler"></span>'.join(claims)))
        out += ["</tbody>", "</table></div>"]
    else:
        out.append('<p class="empty">No component is listed by more than one in-flight story.</p>')
    out.append("</section>")

    out += ['<section id="stories">', "<h2>Stories on record</h2>",
            '<p class="note">Promoted, in-flight records in <code>impacts/</code>. Each '
            "decision belongs to the owner role named beside it.</p>"]
    if impacts:
        out.append('<ol class="stories">')
        for d in impacts:
            comps = d.get("components") if isinstance(d.get("components"), list) else []
            n = len([c for c in comps if isinstance(c, dict)])
            facts = [("Squad", d.get("squad")), ("Status", d.get("status")),
                     ("Confirmed by", d.get("confirmedBy")), ("Commit", d.get("_commit"))]
            out.append("<li>")
            out.append('<div><div class="s-id">%s</div><div class="s-slug">%s</div></div>' % (
                esc(d.get("storyId")), esc(d.get("slug"))))
            out.append('<div class="facts-wrap"><dl class="facts">%s</dl></div>' % "".join(
                "<div><dt>%s</dt><dd>%s</dd></div>" % (esc(k), esc(v)) for k, v in facts))
            out.append('<div class="count">%d<span>%s</span></div>' % (
                n, "component" if n == 1 else "components"))
            decs = [x for x in (d.get("decisions") or []) if isinstance(x, dict)]
            if decs:
                out.append('<ul class="decisions">%s</ul>' % "".join(
                    '<li><span class="role">%s</span>%s</li>' % (
                        esc(x.get("ownerRole")), esc(x.get("text"))) for x in decs))
            out.append("</li>")
        out.append("</ol>")
    else:
        out.append('<p class="empty">No promoted in-flight stories on record.</p>')
    out.append("</section>")

    if invalid:
        out += ['<section id="invalid">', "<h2>Files that failed validation</h2>",
                '<p class="note">These records are left out of everything above.</p>', "<ul>"]
        for item in invalid:
            out.append('<li><code>%s</code><ul class="errs">%s</ul></li>' % (
                esc(item.get("path")),
                "".join("<li>%s</li>" % esc(e) for e in item.get("errors", []))))
        out += ["</ul>", "</section>"]

    out += ["<footer>Generated by <code>tools/impacts/render_register.py</code> from "
            "<code>impacts/*/impact.json</code> at %s. Findings only.</footer>" % esc(commit),
            "</main>", "</body>", "</html>"]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the impact register as static HTML.")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--out", default=None)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    path = resolve_out(args.root, args.out)
    if path is None:
        print("refused: --out resolves outside <root>/ai-context/ or is a symlink",
              file=sys.stderr)
        return 2
    page = render(load_register(args.root), register_commit(args.root))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if resolve_out(args.root, path) != path:
        print("refused: output folder changed during the run", file=sys.stderr)
        return 2
    try:
        write_nofollow(path, page)
    except OSError as exc:
        print("cannot write %s: %s" % (path, exc), file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
