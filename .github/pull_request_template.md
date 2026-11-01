## What and why

<!-- One or two sentences. Link the issue. -->

## Checklist

- [ ] `python3 tools/build/render.py` run, and the rendered output is committed with its source
- [ ] `python3 tools/build/render.py --check` passes
- [ ] `python3 tools/build/lint.py` passes
- [ ] `python3 tools/guard/scan_data.py --all` passes (exit code checked directly, not piped)
- [ ] Tests for every touched tool pass
- [ ] A behaviour change adds or updates an eval case or a guard case (`tools/guard/test_guard.py`)
      that fails without the change
- [ ] Fixtures, eval cases and examples are synthetic
- [ ] `docs/DESIGN.md` updated if a layer's behaviour changed
- [ ] Commit messages use `area: lowercase summary`

## Owner patches

<!--
Changes to tools/guard/, .claude/settings.json, .github/workflows/, .github/hooks/ or CODEOWNERS
arrive as patch files a human applies. List the patches this PR adds or depends on, with their
APPLY.md, or write "none".
-->

- [ ] None needed, or listed here:

## Review

Control-path changes need a second reviewer. Until this repository has a second maintainer, that
rule is not enforced here (see CONTRIBUTING.md, "Review rules").
