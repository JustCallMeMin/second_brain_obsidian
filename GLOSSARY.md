# Engineering Second Brain

A personal engineering knowledge base in an Obsidian vault. Claude turns captured material into linked knowledge and answers questions from it with citations.

## Language

### Material that comes in

**Capture**:
Anything dropped into `inbox/`.
_Avoid_: Inbox item, input, import

**Original**:
The byte-identical file of a text capture: still in `inbox/` until ingestion is finalized, then kept in `inbox/processed/`. For a binary capture the original is the binary itself, moved into `sources/`; no second file is kept.
_Avoid_: Backup, raw file

**Source**:
The record of a capture in `sources/`: for text, a copy with provenance (the original's name and hash); for a binary, the moved file itself. Its body is never edited, except by approved recovery.
_Avoid_: Reference, clipping

**Companion source**:
A Markdown source written for a binary capture when useful; it names the binary in `sources/` and carries its hash. No second file is kept for the binary.
_Avoid_: Sidecar, metadata file

**Text capture** and **Binary capture**:
A text capture is a `.md` or `.txt` file in valid UTF-8; it gets a source copy and an original. A binary capture is any other capture, even if its bytes are valid UTF-8; it is moved into `sources/` as it is.
_Avoid_: Plain capture, attachment

**Interrupted ingest**:
An ingest that wrote a source but stopped before the capture was finalized, including a partially ingested capture with a skipped part. Retrying resumes it, applies only the missing contributions, and never creates a second source.
_Avoid_: Partial import

**Source recovery**:
Rebuilding a damaged text source from an original (in `inbox/processed/`, or still pending in `inbox/`) whose hash matches the one stored in the source, shown as a diff and written only after approval.
_Avoid_: Restore, repair (a companion is repaired, not recovered)

**Resume**:
Continuing a capture that has a source but is not finalized. Each contribution is checked on its own target: present (cited and complete), missing (absent), or unclear (a human decides). Only missing ones are applied.
_Avoid_: Retry-from-scratch, redo

**Finalize**:
The last step of an ingest: the capture's original moves to `inbox/processed/` (a binary into `sources/`). It happens only when every contribution is present and validation passed.
_Avoid_: Complete, commit

**Baseline**:
The lint findings recorded just before a capture's first write, so only new errors count against that capture. It never excuses an error in a file the capture created.
_Avoid_: Snapshot (that is the dirty-tree record)

**Contribution**:
One piece of knowledge a capture adds to one knowledge note: a new note, an addition, a progress entry or a conflict callout. It always cites its source.
_Avoid_: Edit, change

**Needs attention**:
The part of an ingest report listing what was skipped or left unresolved, such as a conflict that could not be marked. Nothing in the vault records it.
_Avoid_: Warnings, todo

**Ingest**:
Turn a capture into a source and, only when it contributes reusable knowledge or learning progress, into knowledge notes.
_Avoid_: Import, process

### Knowledge that Claude and the user keep

**Knowledge note**:
A file of type `note`, `topic`, `decision` or `project`. A source is never a knowledge note.
_Avoid_: Page, entry, document

**Hub**:
A topic note that mainly links other knowledge notes.
_Avoid_: Index page, MOC

**Project overview**:
The project file named after its project; it lists the technology stack, related knowledge, and any decisions and project-specific lessons.
_Avoid_: Project page

**Decision**:
A choice with real alternatives and reusable rationale, kept as its own file; other decisions stay in the project overview.
_Avoid_: ADR (that term is reserved for design records in `docs/adr/`)

**Lesson**:
Something learned from a project. A reusable one becomes a knowledge note; a project-specific one stays in the project overview.
_Avoid_: Takeaway, retro item

**Progress**:
Dated entries under a topic note's `## Progress` section recording how far the user has got in learning that subject. It counts as useful knowledge.
_Avoid_: Learning log, status

### Quality of the knowledge

**Citation**:
A link to a knowledge note or source, or to a heading in it, that supports a statement.
_Avoid_: Reference, footnote

**Conflict**:
Two claims that contradict each other. When both are in knowledge notes, both notes carry a callout citing the other (and the source of the claim); when one is only in a source, the knowledge note carries a callout citing that source. Neither claim is removed until the user resolves it.
_Avoid_: Contradiction, inconsistency

**Orphan**:
A knowledge note that nothing links to and that is not a topic (hubs included), a project overview, or marked standalone.
_Avoid_: Dangling note

**Standalone**:
A knowledge note deliberately left without inbound links and marked as such.
_Avoid_: Exempt note

**Stale**:
A knowledge note (a decision included) whose knowledge text or links, not whitespace, formatting or metadata, have not changed for the configured review period. It means a human should look at it, not that it is obsolete or wrong. Sources are never stale.
_Avoid_: Outdated, expired
