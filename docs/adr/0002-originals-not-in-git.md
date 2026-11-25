---
status: proposed
---
# Keeping original captures out of Git

Date: 2026-11-25

## Context

`inbox/` receives arbitrary material: clippings, logs, files that may hold secrets or private data, and large binaries. Git history is effectively permanent unless rewritten. Each text capture also gets a tracked source holding its text verbatim, its `sha256` and the name of its original.

## Decision

`inbox/*` is git-ignored (except `inbox/.gitkeep`), so neither pending captures nor `inbox/processed/` originals are tracked. The tracked source is the recoverable record. `original` is required in every Markdown source and must be a valid basename. For a text source it names the git-ignored original and is never checked for existence. For a companion source it names the binary in `sources/`, which is tracked, so lint does verify it. A binary needs no second original file.

## Consequences

- A raw capture, including one that holds a secret, is not committed by itself. The tracked text source would carry it, so the protection is blocking a capture that lint flags (W07); regex scanning can miss secrets.
- Originals have no git history; their safety depends on Obsidian Sync or the user's own backups.
- A fresh clone has sources but no originals. Lint stays clean because it does not check `original` for existence. A re-dropped capture takes the resume path and restores the original. `/maintain` source recovery from `inbox/processed/` is unavailable there and reports it; it can still use a capture that is pending in `inbox/`. Companions keep validating because their binary is tracked.
- Byte-level details of the original (encoding quirks, line endings, a wrapped frontmatter block) are only reproducible from the original, not from git.
- Binaries are different: they are moved into the tracked `sources/`, so large binaries can bloat the repository.

## Alternatives considered

- **Track `inbox/processed/`**: rejected. Secrets and bulky files would enter permanent history.
- **Track originals with Git LFS**: rejected. Adds infrastructure for a personal vault.
- **Keep no originals**: rejected. Hash verification and source recovery need the byte-identical file.
- **Keep originals outside the vault**: rejected. Breaks locality of `original` and needs a configured path.
