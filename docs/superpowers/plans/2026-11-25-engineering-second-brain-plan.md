# Engineering Second Brain: Implementation Plan (v5, draft)

Status: draft, awaiting approval. Prerequisite: approved design v5. `kb.py` is built test-first (`unittest`, stdlib). Criteria numbers refer to design section 7 (1-15 automated, 16-42 manual). Nothing touches `.obsidian/` or `~/Documents/dev/cowork`.

## M0. Scaffold (no commit)
- Creates **only** these files: `.git/` (`git init`, no remote), `.gitignore`, `GLOSSARY.md`, `index.md` (`type: topic`, no wikilinks), `inbox/.gitkeep`, `sources/.gitkeep`, `notes/.gitkeep`, `projects/.gitkeep`, `docs/superpowers/specs/2026-11-25-engineering-second-brain-design.md`, `docs/superpowers/plans/2026-11-25-engineering-second-brain-plan.md`, `docs/adr/0001-hash-idempotency-without-manifest.md`, `docs/adr/0002-originals-not-in-git.md`. Modifies no existing file.
- **Collision guard, before anything is written:** check every listed target, case-insensitively and NFC-normalized, counting a dangling symlink as present; (a file where a file is to be created, an existing `.git`, a file where a directory is needed). If any exists, write nothing at all, report **all** collisions, and ask for explicit direction. Never overwrite, merge or silently rename. An existing directory is not a collision.
- **`index.md`** has complete valid frontmatter: `type: topic`, `created` and `updated` both set to the M0 run date (`date +%F`), plus a short navigation body, so it raises no E02 when lint exists.
- Files are written with no-clobber semantics, so a file appearing after the check is never overwritten.
- **Never commits, stages or pushes.** On completion it reports `git status`, every created and modified file, and the relevant diff (`git diff --no-index -- /dev/null <file>` per file; this command exits 1 when files differ, which is not a failure). A first commit is a separate operation that needs your explicit approval.
- Until you commit, every file created so far is untracked, and the dirty-tree rule requires explicit approval **naming each file** before a later milestone modifies it. There is no exception for files an earlier milestone created. Each milestone below lists the untracked files it will modify; before writing, I ask for approval naming them, record their hashes, and keep the hash verification and external-modification detection unchanged. Files a milestone newly creates need no approval. Test fixtures live inside `scripts/tests/test_kb.py` (built in temporary directories), so no separate untracked fixture files exist. Any other untracked file (`.gitignore`, the ADRs, the `docs/superpowers` copies, `index.md`) needs named approval before any edit; none is expected. Committing between milestones (only if you decide to) removes the need.
- **Verify (manual, because `kb.py` does not exist yet):** only the listed files were **created** (`.obsidian/` and `CLAUDE.md` already exist and are untouched); `git rev-parse --verify HEAD` fails (no commit); `git diff --cached` is empty; `git check-ignore` behaves as criterion 14 says; nothing under `.obsidian/` or `cowork` changed (criterion 15). Collision guard (criterion 42): in a temporary copy with two pre-created targets, M0 writes nothing and reports both; with none, exactly the listed files exist. `index.md` has `type: topic` and today's `created`/`updated`.

## M1. Parsing core
- **Approvals:** none; creates `scripts/kb.py` and `scripts/tests/test_kb.py` (new files, no approval needed).
- Vault walker (scan scope; hidden files ignored everywhere; tolerates missing `inbox/processed/` or `inbox/`; reads bytes, never crashes on non-UTF-8), YAML-subset parser (present / missing / malformed), wikilink and embed extractor (skips code, includes frontmatter links), heading extractor, NFC name normalization, basename-rule validator, finding `id` with occurrence counter.
- **Verify:** unit tests for every accepted and rejected YAML case, CRLF/BOM, unterminated frontmatter, quoted wikilinks, code fences; criteria 2, 4, 6, 7 (fresh-clone part), including the basename-rule validator.

## M2. `lint` errors, W10/W11, companions, `--pending`
- **Approvals (untracked files modified), requested before writing:** `scripts/kb.py`, `scripts/tests/test_kb.py`; plus `index.md` only if its frontmatter check needs a fix (it should not).
- E01-E08 (source-body exemption for E04/E05; inbox exemption for E01/E02/E06), E02 conditions incl. `original` presence and basename rule, companion shape discrimination and E08, W10, W11, levels, `--json`, exit codes (2 for unreadable or non-vault root), `--pending` (one target counted once, covers companion E08, single use, name must have an extension other than `.md`).
- **Verify:** criteria 1 (E-rules), 2, 3, 5, 6, 7, 8, 13; run `kb.py lint` on the scaffold vault: exit 0 and no E02 for `index.md`.

## M3. `lint` warnings, review items, secrets
- **Approvals (untracked files modified), requested before writing:** `scripts/kb.py`, `scripts/tests/test_kb.py`.
- W01-W09, R01 (decisions included, sources exempt), R02, sha256 matching (text frontmatter, companions, hashed binaries), `--stale-days` / `--inbox-days`, secret scanner (any UTF-8 file) with E07 and W07; `--help` text documents `updated` and "stale means review".
- **Verify:** criteria 1 (rest), 9, 10, 13 (help text); W/R findings never change the exit code.

## M4. `search` and `backlinks`
- **Approvals (untracked files modified), requested before writing:** `scripts/kb.py`, `scripts/tests/test_kb.py`.
- Ranking, filters, `--limit`, `N of M shown`, snippet with nearest heading and secret-line withholding; backlinks including frontmatter links, dangling targets, ambiguity.
- **Verify:** criteria 11, 12 (including the raw-text scan of an E01 note).

## M5. Commands and conventions
- **Approvals (untracked files modified), requested before writing:** `CLAUDE.md` (existing, untracked). Also `scripts/kb.py` or `scripts/tests/test_kb.py` if a fix is needed to make a command's flags match, and `GLOSSARY.md` if its text has to change after M0; each is named explicitly. The five `.claude/commands/*.md` files are new, so they need no approval.
- Install `CLAUDE.md` and the five `.claude/commands/*.md` drafts, adjusted to the real flags.
- **Verify:** read-through checklist against the design: each ADR has context, decision, consequences and alternatives and matches design 6.2/6.6; every command references only existing subcommands and flags; vocabulary matches the glossary; the `updated`, dirty-tree, classification, failure-isolation, conflict, progress, basename and recovery rules are consistent in design, CLAUDE.md, `/ingest`, `/maintain`, `/ask`.

## M6. Acceptance on a temporary copy of the vault
- Run manual scenarios 16-42 with fixtures: one capture of every class and edge input (case-variant extensions, empty, symlink, unreadable, nested folder), a companion with two notes citing one pending target plus an unrelated broken link, rollback and retry, the isolated-failure run with the good capture last, the eleven run-level failure runs, conflicts (clean, dirty partner, partner changed before the first edit, between the two edits with a verified undo, first note changed before the undo, source-only), dirty and untracked targets, no-repo run, companion repair after a binary rename, processed-name and kebab-case derivation cases, truncated source with every recovery case (processed original, pending capture, both copies, mismatch, missing, unreadable hash, secret in candidate, damaged frontmatter, changes between diff and write, approval not naming the source, failed write), fresh-clone copy, the unresolved-error retry (criterion 40: E01/E02 note, pending capture, retry stops, `/maintain` repair diff, approval, resume finalizes), the two-note partial resume (criterion 41), and the M0 collision guard (criterion 42). Criterion 15 is re-run here. M6 runs in a temporary copy, so the dirty-tree approvals are exercised there, not on the real vault.
- **Verify:** each scenario ticked with command output; the real vault contains only scaffold files; propose a checkpoint commit and wait. A bug found in M6 loops back through the affected milestone, again with approval naming each untracked file it modifies.

## Files

**Created in the vault (only after approval):** the M0 list above, then `scripts/kb.py`, `scripts/tests/test_kb.py`, `.claude/commands/ingest.md`, `ask.md`, `lint.md`, `review.md`, `maintain.md`.

**Modified, each only after approval naming it (untracked until you commit):** `scripts/kb.py` and `scripts/tests/test_kb.py` (M2 to M4, and M5 only if needed), `CLAUDE.md` (placeholder text replaced, M5), `GLOSSARY.md` only if its text changes after M0.

**Never touched:** `.obsidian/`, `~/Documents/dev/cowork`.
