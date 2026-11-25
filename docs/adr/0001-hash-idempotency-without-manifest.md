---
status: proposed
---
# Hash-based idempotency without a separate manifest

Date: 2026-11-25

## Context

Ingesting a capture must be idempotent: dropping the same file twice, or retrying an interrupted ingest, must not create a second source or duplicate knowledge. The usual way is a manifest mapping capture hashes to sources. The vault is plain Markdown that the user also edits by hand, so any second record can drift from it.

## Decision

The key is the SHA-256 of the capture's bytes. For a text capture it is stored in the source's `sha256` frontmatter. For a binary it is computed on scan of the files in `sources/`, and a companion source carries the same hash in its own `sha256`, so an interrupted binary ingest is recognised before the move. `kb.py lint` matches captures against these (W05), and `/ingest` checks them before writing. There is no manifest. One is added only if scanning is shown to be too slow or unreliable.

## Consequences

- The sources are the single record, and they are tracked in git, so idempotency survives a fresh clone.
- Every lint hashes the binaries in `sources/`, so cost grows with their total size.
- A whitespace-only re-capture has a different hash and becomes a new source; W03 flags the duplicate afterwards.
- A binary without a companion has no record until it moves into `sources/`; an interrupted ingest is then detected through notes that already link its planned filename. With a companion the record exists before the move.
- Damaged source frontmatter can lose the key. If `original` survives, the source is recognised and reported as corrupt; if both `sha256` and `original` are lost, a retry cannot match it and would create a second source, so such damage must be repaired through `/maintain` or git history first.
- Resuming an unfinished ingest needs to know which knowledge contributions already exist. A backlink to the source is not enough, so every contribution cites its source and resume checks each target independently for the citation and the content; anything it cannot decide it asks about. No manifest of contributions is kept.
- An unresolved error from an earlier attempt must not become harmless baseline state on retry, so resume lints the capture's own files first and stops on any error there.

## Alternatives considered

- **Manifest file** (hash to source): rejected. A second source of truth that drifts from the vault and must be kept in sync.
- **Match by filename**: rejected. Names change on capture, kebab-casing and collision suffixes.
- **Hash of normalized content**: rejected. The normalization rules would themselves be ambiguous and would hide real differences.
- **Database or index file**: rejected. Violates the no-database constraint.
