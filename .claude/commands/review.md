---
description: Prose review of the vault's knowledge quality (no edits)
argument-hint: [topic or folder]
---

Review the vault. Follow CLAUDE.md. Scope: $ARGUMENTS (default: whole vault).

Use `kb.py lint --json` and `kb.py search` as inputs, then judge. Write a prose report, with no scores, priorities, schedules or rankings, covering:
- knowledge notes marked `confidence: shaky`
- stale knowledge notes, decisions included (R01); `updated` is the last knowledge-text or link change, and stale means "a human should review it", not "wrong"
- topics that need an overview or hub
- unresolved conflicts: `kb.py search "[!warning] Conflict" --limit 500`; a callout that cites another knowledge note must be answered by one citing it back (report one-sided ones); a callout that cites a source is legitimately single; plus other potential contradictions
- reusable knowledge buried in project overviews
- knowledge notes that need updating
- sources never cited

Do not edit anything. Offer `/maintain` for any finding the user wants acted on.
