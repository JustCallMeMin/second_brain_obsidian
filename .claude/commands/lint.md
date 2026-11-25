---
description: Run kb.py lint and explain the result
argument-hint: [--stale-days N] [--inbox-days N]
---

Run `python3 scripts/kb.py lint $ARGUMENTS` (add `--json` if you need to filter).

Summarize in prose, one section per level, never merging them:
- **ERROR** (exit code 1): what is broken and where.
- **WARNING**: group by code; remember orphans, uncited sources, old captures, missing frontmatter (W10) and non-UTF-8 files (W11) are not errors.
- **REVIEW**: stale knowledge notes (decisions included; sources never) and unnecessary standalone markers. Stale means a human should review it, not that it is obsolete or wrong; `updated` is the last knowledge-text or link change, not the last review.

Never print matched secret values; report file and line only. Change nothing. For W10 or incomplete frontmatter, offer `/maintain` to propose the metadata as a diff; for E08 (companion mismatch) offer `/maintain` companion repair. Do not edit files, delete, or archive anything because of a warning or review item.
