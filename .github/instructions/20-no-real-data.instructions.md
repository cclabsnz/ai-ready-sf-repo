---
applyTo: "**"
---
# No real data

- Org exports go in `data/` and user inputs in `ai-context/**/inputs/`; both are git-ignored.
- `tools/guard/scan_data.py` runs pre-commit and in CI. A hit blocks the commit.
- Fixtures and eval cases are synthetic. Record names, IDs and emails in them must not match any real record.
