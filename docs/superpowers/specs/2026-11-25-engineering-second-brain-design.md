# Engineering Second Brain: Design (v5)

Date: 2026-11-25. Status: **draft, awaiting approval**. Nothing has been built or created in the vault.
Tags: **(user)** = decided by the user. **(my call)** = decided by me, please check. **(open)** = ambiguity I did not resolve, see section 10.

## 1. Intent

An Obsidian vault at `~/Documents/dev/second_brain/` that works as a personal engineering knowledge base, with Claude Code as the assistant. In a month it should do five things:

- **Capture**: dump anything into `inbox/` with no rules.
- **Organize**: Claude ingests captures, and turns them into linked knowledge notes only where there is something reusable.
- **Retrieve**: answer questions such as "What have I learned about Playwright authentication?" or "Which projects use PostgreSQL?" with citations.
- **Connect**: backlinks between concepts, technologies, projects and decisions.
- **Maintain**: find broken links, duplicates, missing metadata and stale information.

Scope: technical learning (Go, TypeScript, Java, Playwright, Selenium, testing, backend, databases, DevOps), project context and decisions, research and references, personal learning progress.

## 2. Vocabulary **(user)**

The canonical terms live in `GLOSSARY.md`. In short:

- **Capture**: anything dropped into `inbox/`.
- **Original**: the byte-identical file kept in `inbox/processed/`.
- **Source**: the record of a capture in `sources/`.
- **Knowledge note**: a `note`, `topic`, `decision` or `project` file. A source is not a knowledge note. Prompts say "knowledge note" wherever sources are excluded.
- **Hub**: a topic note that mainly links other notes.

## 3. Goals, non-goals, anti-goals

**Goals**
- Minimal: few folders, few metadata fields, no mandatory workflow.
- Plain Markdown in a normal Obsidian vault, usable with Claude switched off.
- Claude does judgement work (ingesting, linking, synthesis, semantic duplicates, conflicts). One small script does mechanical work (validation, search, backlinks).
- Ingestion is idempotent, additive and non-destructive.
- Answers always say what comes from the vault and what does not.

**Non-goals**
- Databases, embeddings, vector search, MCP servers, frameworks, plugins.
- Migrating or modifying the existing vault `~/Documents/dev/cowork`.
- Scores, priorities, schedules or spaced repetition.
- A separate citation engine or an ingestion manifest (deferred).
- A progress type or a separate learning log.

**Anti-goals** (failures even if the code works)
- Claude silently rewriting or deleting the user's text.
- A knowledge note created for every capture.
- A secret copied into a tracked file or printed to a terminal.
- Source text and synthesized knowledge becoming indistinguishable.
- Process overhead the user must remember in order to capture something.
- A conflict between two knowledge notes resolved silently.

## 4. Constraints

- `scripts/kb.py`: Python standard library only, `argparse` subcommands `lint`, `search`, `backlinks`. Machine has Python 3.15.2; code targets 3.10+ **(my call)**. Tests use `unittest`.
- Shell commands on this machine print a harmless "Unable to locate a Java Runtime" line. Ignore it.
- `.obsidian/` is app-managed. Never hand-edit it.
- No git remote. Claude never commits, pushes, resets or cleans unless asked.
- Nothing is implemented until this document and the plan are approved.

## 5. Approaches

| | Approach | Trade-off | Outcome |
|---|---|---|---|
| A | Pure prompts, no script | Simplest, but checks and search depend on Claude's attention and are not repeatable | Rejected |
| **B** | **Prompts + one small deterministic script** | Mechanical checks are testable; Claude keeps all judgement | **Chosen (user)** |
| C | Adopt a claude-obsidian-style framework | Faster start, but imposes its conventions and dependencies | Rejected |
| D | B plus semantic search | Better recall on fuzzy questions, but needs embeddings | Deferred until grep-style recall demonstrably fails |

## 6. Design

### 6.1 Layout

```
second_brain/
  CLAUDE.md                 conventions for Claude (replaces the placeholder text)
  GLOSSARY.md               canonical vocabulary
  index.md                  optional navigation, maintained by the user (type: topic)
  inbox/                    captures; no rules; git-ignored
    processed/              originals of ingested text captures; git-ignored
  sources/                  flat (no subfolders): text copies with frontmatter (kebab-case .md), moved binaries, companion sources
  notes/                    flat; knowledge notes of type note | topic
  projects/<Name>/<Name>.md project overview; decision files only when justified
  scripts/kb.py             lint | search | backlinks
  scripts/tests/            unittest suite for kb.py
  docs/                     design, plan, adr/0001-*.md, adr/0002-*.md (not scanned by kb.py)
  .claude/commands/         ingest, ask, lint, review, maintain
  .gitignore
```

`kb.py` scans only `inbox/` (recursively, excluding `processed/` and hidden files), `sources/`, `notes/`, `projects/` and `index.md`. Hidden files (`.gitkeep`, `.DS_Store`) are ignored in every scanned folder. Root `CLAUDE.md` and `GLOSSARY.md`, `docs/`, `scripts/`, `.claude/`, `.obsidian/` and `inbox/processed/` is scanned only for secrets (W07) and is otherwise ignored.

Provenance stays apart from synthesis **(user)**: sources hold captured input as received (external material or the user's own raw thoughts); knowledge notes hold distilled knowledge. Claude never edits a source body, except by approved `/maintain` source recovery (6.9). Source frontmatter changes only through `/maintain` with an approved diff.

### 6.2 Git and write safety

- `git init` at implementation time, no remote. Claude makes a commit only on explicit approval, as a separate operation. **M0 never commits** (see 6.13); until the user commits, every existing file counts as untracked under the dirty-tree rule.
- **Tracked:** `CLAUDE.md`, `GLOSSARY.md`, `index.md`, `notes/`, `projects/`, `sources/` (including moved binaries), `scripts/`, `docs/` (including `docs/adr/`), `.claude/commands/`. **(user)**
- **Ignored:** `inbox/*` (so `inbox/` and `inbox/processed/` contents) except `inbox/.gitkeep`, plus `.env*`, `*.pem`, `*.key`, `/credentials*`, `/secrets*` (anchored at the repo root **(my call)**, so a note such as `notes/Secrets management.md` is not ignored on macOS's case-insensitive git), `.claude/settings.local.json`, `.obsidian/workspace*.json`, `.obsidian/cache`, `.DS_Store`, `__pycache__/`. **(user)**
- Originals in `inbox/processed/` have no git history; a fresh clone has none (6.6 step 2, section 9, ADR 0002).

**Mechanical write baseline (dirty-tree rule)** **(user)**. It applies to every command that writes: `/ingest`, the `/ask` save, `/maintain`.

1. **Snapshot.** Before a run's first write, and again whenever a new target appears, Claude records in a snapshot file in the session scratchpad (never in the vault) the output of `git status --porcelain` for the target and the target's sha256, or `absent`. Targets are every file the run will create, edit or move: knowledge notes, sources, conflict partners, and the capture itself. Git-ignored paths (`inbox/`) get a hash but are never "dirty".
2. **Dirty or untracked targets.** A target that is modified, staged or untracked at snapshot time and was not written by this run is **never modified without explicit approval naming that file**. Claude may offer a checkpoint commit to make targets clean. Approval requests and diff headers list every dirty or untracked target so one approval can name them, and the end-of-run report offers a checkpoint commit (never automatic). Without approval or a commit, that part of the work is skipped and reported (for example a conflict whose partner note is dirty gets no callouts at all).
3. **Run-owned files.** After the run writes a file it records the new sha256 as the last recorded version. Before any further change to that file it verifies the current sha256 equals the last recorded version.
4. **External modification.** Obsidian autosave counts. If a file **this run already wrote** no longer matches its last recorded hash, Claude stops before writing and the run stops (run-level, 6.6). If a not-yet-written target, or the capture, no longer matches its snapshot, or a file appears where `absent` was recorded, Claude writes nothing to it, treats the dependent part as skipped (isolated), names the file and asks.
5. **No destructive git.** Never `reset`, `checkout --`, `restore`, `clean`, `stash`, `rebase`, force options, or any command that discards changes, to resolve any of this.
6. Edits to existing knowledge notes are exact-string edits, never whole-file rewrites.
7. Without a git repo (before `git init`) steps 1, 3, 4 and 6 still apply; step 2 cannot be evaluated.

Consequence **(user)**: output of a previous run that was never committed is "dirty at start" for the next run, so updating it needs a checkpoint commit or per-file approval. This is intentionally strict.

### 6.3 Names **(user)**

- Knowledge notes and topics: human-readable titles, e.g. `Page Object Model.md`.
- Sources: kebab-case, e.g. `playwright-auth-docs.md`.
- Project folder and overview use the project name, e.g. `projects/Automation Core/Automation Core.md`.
- Decision files: `projects/<Name>/<Name> - <decision title>.md` **(my call)**.
- **Basenames are unique across the vault**, compared case-insensitively and Unicode-NFC-normalized (macOS is case-insensitive) **(my call)**. Non-Markdown files compare by full filename.
- Characters `# ^ [ ] |` are forbidden in knowledge filenames **(my call)**.
- Claude checks collisions before creating any file, never overwrites, never renames an existing file automatically.
- **Processed name** **(my call)**: `YYYY-MM-DD-<capture name>`, content byte-identical. Derivation: replace each `/`, `\`, `:`, control and bidirectional-control character in the capture name with `-`; strip leading and trailing whitespace (Unicode White_Space) and trailing `.`; if the result is not within 255 UTF-8 bytes with the date prefix, truncate the stem (never inside a character, extension kept). If the name is taken by any file in `inbox/processed/` or `sources/` (so a text source's `original` can never equal the name of a binary in `sources/`), insert `-<first 8 hex of sha256>` **before the extension**. The date is the ingestion date, which is also the source's `created`. If the result still violates the basename rule, this capture is blocked (isolated).
- **Kebab-case** **(my call)**: lowercase; runs of characters that are not Unicode letters or digits become one `-`; trim `-` at both ends; extension kept lowercase. Unicode letters are kept, not transliterated. If the stem is empty, use `capture-<first 8 hex of sha256>`. The stem is truncated so the full name fits 255 UTF-8 bytes with any suffix; if it still violates the basename rule the capture is blocked (isolated). A binary moved into `sources/` is renamed this way on the move; a text source's name is the kebab-cased stem plus `.md`. A collision suffix is also inserted before the extension.
- Bare wikilinks must resolve to exactly one file. A frontmatter alias does not resolve a link.

**Basename rule** **(user)**. Applies to `original` values, processed names, planned and final source filenames. A valid basename is a string that:
1. is non-empty, at most 255 UTF-8 bytes, and is not exactly `.` or `..` (names merely containing `..`, such as `v1..2.pdf`, are valid);
2. contains no `/` or `\`, so it can never be a path, an absolute path or a traversal;
3. contains no `:` and does not begin with a drive-letter pattern (`C:`), so it has no platform-specific path meaning;
4. has no leading or trailing whitespace and does not end with `.`;
5. contains no control character (Unicode category Cc) and none of the bidirectional override or isolate characters (U+202A to U+202E, U+2066 to U+2069).
Unicode is preserved: no transliteration or ASCII folding. Names are written NFC-normalized and compared NFC-normalized; file operations use the name exactly as it is on disk. Lint applies this rule to `original` (E02) and nowhere else, and E08 performs no filesystem access for an `original` that fails it. Claude applies it when it creates names. Not covered: Windows reserved characters and device names (the vault is macOS/POSIX), listed in section 10. A hidden name (`.x`) is a valid basename but is never a capture or a source (hidden files are ignored).

### 6.4 Metadata

Required on every scanned Markdown file outside `inbox/` **that has frontmatter**:

| Field | Rule |
|---|---|
| `type` | one of `note`, `topic`, `project`, `decision`, `source` |
| `created` | `YYYY-MM-DD`; set once, never changed |
| `updated` | `YYYY-MM-DD`; must be >= `created`; set by Claude (see below) |
| `sha256` | required when `type: source`; 64 lowercase hex of the **original's bytes** |
| `original` | required when `type: source` (every Markdown source) **(user)**; must satisfy the basename rule. **Text source:** the processed name of its original (`YYYY-MM-DD-<name>`); lint never checks that the file exists, because `inbox/processed/` is git-ignored and absent in a fresh clone **(user)**. **Companion source:** the exact filename of its binary in `sources/`, e.g. `playwright-guide.pdf`; lint checks it (E08). See 6.6 |

Optional: `tags` (filter facets only, never technology identity **(user)**), `aliases`, `sources` (list of quoted wikilinks to sources), `url`, `confidence` (`shaky` | `ok` | `solid`), `standalone` (`true` only). Unknown keys are allowed if they parse.

**Frontmatter present vs missing** **(user)**:

- **Missing entirely** (no leading `---` block) is a **warning** (W10). The file is unclassified: type-based exemptions do not apply, `updated`-based checks are skipped, links and secrets are still checked.
- **Present but malformed, incomplete or invalid** is an **error** (E01, E02).
- `/maintain` may propose adding or completing frontmatter as a diff. It never changes a file without approval. Ingest and every other command also never add frontmatter to an existing file.

**`updated` semantics** **(user)**. `updated` is the date of the last change to a knowledge note's **knowledge text or links**. It is *not* the last review or access. Claude sets it. Lint does not verify it (no git-based enforcement **(user)**) but documents it in `lint --help` and in the R01 message.

| Change | Moves `updated`? |
|---|---|
| Text added, edited or removed | yes |
| Link added, removed or retargeted (incl. fixing a broken link) | yes |
| Conflict callout added or removed | yes (it is text) |
| `## Progress` entry added | yes (it is text) |
| Whitespace or formatting only | no |
| Metadata only (`tags`, `aliases`, `confidence`, `standalone`) | no |
| `sources:` field edited (it adds or removes a link) | yes |
| Frontmatter completion by `/maintain` | not applicable: `created` = file creation date and `updated` = max(`created`, file modification date), both labeled as estimates in the diff. A text source's `sha256` is never derived from a candidate original (that would make recovery verification circular), so a lost `sha256` stays missing and recovery stops |
| Source frontmatter (`url`, `original`, anything else) | no; a source's `updated` always equals its `created` |

**Supported YAML subset** (anything else is E01; full YAML is not supported):
- Frontmatter is the first block, delimited by lines that are exactly `---`. UTF-8, LF or CRLF, optional BOM. An opening `---` with no closing line is E01.
- Top-level `key: value` only. No nesting, multi-line scalars, anchors, comments or duplicate keys.
- Scalars: plain, single-quoted, double-quoted (only the escapes `\"` and `\\`), `true`/`false`, `YYYY-MM-DD`. Claude always writes `original` and `url` double-quoted so a `#` or `:` cannot be misread by Obsidian's YAML parser. Lists: block (`- item`) or inline (`[a, b]`).
- A value containing a wikilink must be quoted: `"[[Note]]"`.
- A file whose first line is `---` is treated as having frontmatter. A note that opens with a horizontal rule and has another `---` later gets E01; start such a note with a blank line or a heading.
- Obsidian's Properties editor stays inside this subset for text, list, checkbox and date fields. Date-time properties are not supported.

### 6.5 Links

- Parsed: `[[Name]]`, `[[Name|text]]`, `[[Name#Heading]]`, `![[Name]]`, in body and frontmatter values. Ignored inside code.
- Whole-note (`[[Note]]`) and heading (`[[Note#Heading]]`) citations are both supported **(user)**. Lint verifies the note and heading exist (heading match is case-insensitive, whitespace collapsed). Whether the cited text supports the claim is Claude's job.
- Anchors on non-Markdown targets (e.g. `#page=3`) are not validated. Block references (`#^id`) are not verified (W09).
- Standard Markdown links are not parsed.

### 6.6 Ingestion (`/ingest`)

Idempotency key: **SHA-256 of the original's bytes**, stored in the source's `sha256` field for text captures and companions, and computed on scan for binaries in `sources/` (ADR 0001). No manifest. Every text capture gets a source, including the user's own raw thoughts **(user)**. A knowledge note is created or updated only when the capture contributes reusable knowledge or learning progress; progress qualifies **(user)**.

**Classification policy** **(exact)**. "Binary capture" means *not a text capture*, even when the bytes are valid UTF-8.

| Capture | Class | Parsed as Markdown | Secret scan | Source | Original |
|---|---|---|---|---|---|
| `.md` / `.MD` (extension compared case-insensitively), valid UTF-8 | text | the source body is kept verbatim and never link-checked | yes | `sources/<kebab>.md` copy with frontmatter | byte-identical file in `inbox/processed/` |
| `.txt`, valid UTF-8 | text | not Markdown; its content is stored verbatim as the body of a `.md` source (never reflowed or converted) | yes | same as above (the extension becomes `.md`) | byte-identical `.txt` in `inbox/processed/` |
| `.md`, not valid UTF-8 | **blocked**, user must intervene; never converted | no | not scanned | none | stays in `inbox/` |
| any other extension that decodes as UTF-8 (`.json`, `.csv`, `.html`, `.markdown`, code) | binary | no (no frontmatter, links or headings read by lint) | **yes** (any file that decodes) | the file itself, moved to `sources/` (kebab-case name, extension kept) | the moved file itself; no copy |
| `.txt` not valid UTF-8; undecodable (`.pdf`, images, archives) | binary | no | **never scanned** (does not decode; known gap) | the file itself, moved to `sources/` | the moved file itself; no copy |

Edge inputs **(my call)**: an extension-less file is blocked as unsupported (isolated; the user adds an extension), because a binary needs an extension for `--pending` and wikilinks; `.markdown` is binary; a zero-byte capture is blocked as empty (isolated); a symlink is not followed, skipped and reported; nested folders in `inbox/` are walked and each file is its own capture; a capture that cannot be read or hashed is an isolated failure. UTF-8 `.txt` as text and UTF-8 `.json`/`.csv` as binary are my calls too.

Any capture can contribute knowledge. For a binary capture that happens only through knowledge notes Claude writes after reading the file; they cite the planned `sources/` filename, and the file itself is never rewritten or converted. An optional **companion source** (a Markdown source for the binary) may be created when useful; its format is below. **Non-UTF-8 `.txt` as binary is my call (open).**

**Companion source** **(user)**. `sources/<kebab-name>.md` with `type: source`, `created`, `updated` (= created), `sha256` = sha256 of the binary, `original` = the exact final filename of the binary in `sources/` (basename rule, extension kept, e.g. `playwright-guide.pdf`), body embeds `![[playwright-guide.pdf]]`. No second file is created for the binary's original: the binary in `sources/` **is** its original.
- *Locating:* `sources/<original>` (flat folder), matched NFC-normalized and case-insensitively like every other name. A Markdown source is a companion when its `original` has an extension (compared case-insensitively) other than `.md`/`.txt` (including none), or names an existing non-Markdown file in `sources/`. Consequence **(open)**: a companion for a non-UTF-8 `.txt` binary looks like a text source until the binary has moved, so before the move it raises no E08; after the move E08 checks it.
- *Validation:* lint E08 on the existence, non-Markdown type and hash equality. Because the binary is tracked, this works in a fresh clone.
- *Pre-move:* the companion is written before the binary moves, so its E08 and the notes' E04 refer to the same planned filename; `--pending <that filename>` tolerates both, counted as one target.
- *Retry:* a companion whose `sha256` equals the capture's hash while the binary is not yet in `sources/` marks an **interrupted** ingest; Claude reuses it. After a rollback the companion remains and reports E08 until a retry succeeds.
- *Rename caveat:* renaming the binary in Obsidian updates links but not `original`, so lint reports E08 until `/maintain` fixes it.

**Failure isolation** **(user)**. Independent capture failures are isolated. Any failure that makes the vault state, or the integrity of later writes, uncertain stops the whole run.

| Isolated: blocks only that capture (or only the dependent part); the run continues | Run-level: stop the entire run |
|---|---|
| W07 suspected secret in the capture | `kb.py lint` cannot run or exits 2 (unreadable or non-vault root, internal error) |
| `.md` capture that is not valid UTF-8; empty capture; extension-less file; symlink; unreadable capture; a created name that still violates the basename rule | a file **this run already wrote** (or the snapshot file) changed since its last recorded hash, including a conflict partner written earlier in the run: someone else is editing the vault |
| duplicate capture (skipped and reported) | a write, move or verification (`cmp`, hash) that fails or leaves partial state, including disk, permission or snapshot-file errors, or `git status` failing in a repo |
| corrupt source for this capture; a retry whose planned filename is now taken by another file (points to `/maintain`) | a rollback or undo that fails or cannot be verified, including a first conflict note that changed before its undo |
| a not-yet-written target that was dirty or untracked at start and is not approved, or changed since its snapshot: the dependent part is skipped | any new ERROR or new W10 outside the files written for the current capture (cause uncertain), including in a file written by an earlier capture of this run |
| a skipped conflict, including one whose second note changed between the two edits **when the undo of the first callout succeeds and verifies** | |
| a post-move validation failure whose rollback succeeded and verified (binary back in `inbox/`, notes and companion kept) | |
| this capture's file changed after it was hashed | |
| validation failure confined to this capture's own writes, which are all known, reported and left in place | |
| a resume that finds an unresolved ERROR, W10 or E07 from a previous attempt in the capture's own files: the capture stops and the user is directed to `/maintain`; nothing is deleted or rolled back | |

**Partial completion** **(my call)**: when any knowledge part of a capture is skipped (dirty or changed target, skipped conflict), the capture is **not finalized**: its source stays, the capture stays in `inbox/` and is reported as partially ingested, so a later run takes the resume path and retries only the missing part (after a checkpoint commit, for instance). Before that the vault holds the source and the finished notes only.

On a run-level stop no further capture is processed or moved. The report lists the captures completed, the capture that failed, every file written, the captures still pending, and **every Needs attention entry accumulated so far** (skipped conflicts are recorded nowhere else). Nothing is cleaned up automatically. A suspected secret never appears in any report. `/maintain` and the `/ask` save are single operations: any failed write or verification stops them with a report.

**Run level, once:** list the files the run expects to write and apply the 6.2 dirty-tree rule; re-apply it to any target that appears later.

**Per capture, in order:**

1. **Baseline and secrets.** Immediately before this capture's first write, run `kb.py lint --json`. If it cannot run, that is a run-level stop. The result is the **baseline** (earlier captures of the same run are already in it). Each finding has a stable `id` (`code|path|detail|n`: no line number; `n` numbers repeats). If the capture has a W07 finding, do not open or ingest it, report file and line, ask for review. Never redact, delete or modify it; never print the suspected value. There is no override: the user edits or removes the flagged content and re-runs **(open)**.
2. **Already ingested, interrupted, or corrupt?** Compute `shasum -a 256` of the capture and record it (6.2 step 1).
   - *Text capture.* If a source has that `sha256`:
     - its body does not match the capture (`cmp`, unwrapped if needed): **corrupt**;
     - body matches and the source's `original` file is in `inbox/processed/`: completed earlier. Duplicate; report and ask before moving it;
     - body matches but that original is not in `inbox/processed/`: **interrupted** (also what a duplicate dropped into a fresh clone looks like **(open)**). Follow the **resume procedure** below, with the source's stored `original` as the processed name. Never create a second source.
   - **Corrupt** means (a) same `sha256` but the body does not match, or (b) a source whose `original` is this capture's name under any date prefix (ignoring a collision suffix or truncation, Claude's judgement **(open)**) and whose `sha256` is missing or unreadable. This capture stops. For (a), `/maintain` source recovery (6.9) can rebuild the source from this capture or from the original in `inbox/processed/`, after the hash is verified; the user is not asked to delete anything. For (b) there is no stored hash to verify, so the fallback is the user restoring the source from git history or deleting it.
   - *Binary capture.* A binary in `sources/`, or a companion, with the same sha256 whose binary is in `sources/`: duplicate; report and ask before moving it. A companion with that sha256 whose binary is not yet in `sources/`: interrupted; reuse the companion, and the binary's final name is the companion's `original`. If that name is now taken by a different file, this capture fails (isolated) and Claude points to `/maintain` (E08 repair); source frontmatter is never changed by ingest. Neither: look for knowledge notes that already link the planned `sources/` filename (`kb.py backlinks <filename>` works on dangling targets) and apply the **resume procedure** to them.
**Resume procedure (deterministic, no manifest)** **(user)**. It applies whenever a capture has a source but is not finalized (interrupted, partially ingested, or after a fresh clone), for text and binary captures alike. Its steps are called R1 to R6; "ingest step N" means the numbered steps of 6.6.
- **R1. Re-read** the source (for a binary: the binary and its companion).
- **R2. Unresolved errors first.** The capture's files are the source, the companion if any, every knowledge note that cites the source (`kb.py backlinks <source>`, which also scans a note with malformed frontmatter as raw text, and `sources:` lists) and every note whose Conflict callout cites one of those. Run `kb.py lint --json` (binary capture: with `--pending <planned filename>`, which tolerates only that one target's E04/E08 left by a verified rollback). Any ERROR, W10 or E07 in those files is an **unresolved failure of a previous attempt and is never treated as baseline**: the capture stops (isolated), the report lists each finding and the user is directed to `/maintain`. Nothing is deleted or rolled back to clear it. A pre-existing knowledge note the capture edited stops it too, because its error cannot be told apart from the capture's own mistake. For E07 `/maintain` names file and line only, prints no diff, and the user edits the note by hand; nothing is redacted. Only when those files are clean is this attempt's baseline taken (ingest step 1).
- **R3. Reconstruct** the expected contributions from the re-read source with the ingest step 5 rules: for each, the target path, the kind (new note, additive update, progress entry, conflict callout, hub, decision) and the expected content.
- **R4. Check each target independently, in both directions.** A contribution is **present** only when its target both cites the source at the place of the contribution and contains its content; **missing** when the target path does not exist or the target has no citation of the source for it; otherwise **unclear** (partly present, reworded, edited since, or undecidable). Reverse check: every knowledge note that cites the source must map to a reconstructed contribution; one that does not (renamed in Obsidian, or reconstructed differently) makes the related contribution **unclear**, never missing.
- **R5. Apply only the missing contributions**, under the normal dirty-tree rule. Present contributions are not touched (their files keep the same hash), so nothing is duplicated. If any contribution is unclear, or the contributions cannot be reconstructed reliably, Claude shows the evidence, **asks the user**, and writes nothing for it; it never guesses.
- **R6. Finalize** (ingest step 7) only when every contribution is present and ingest step 6 passes.

3. **Plan targets, snapshot, collisions.** List every file to create, edit or move and apply the 6.2 dirty-tree rule to each. A new source filename that collides (case-insensitively) with any existing file, including a knowledge note, gets `-<first 8 hex of sha256>`. Never overwrite or rename.
4. **Preserve provenance.**
   - *Text capture:* for a new source, fix the processed name now and write it to `original`; a resume reuses the stored `original`. Build `sources/<kebab-name>.md` with the shell (`printf` the frontmatter: `type: source`, `created`, `updated` = created, `sha256`, `original`, optional `url`; then `cat` the original) and verify the body with `cmp`. If the original has its own frontmatter, keep it verbatim in a fenced `yaml` block at the top of the body.
   - *Binary capture:* moved only after validation passes. Knowledge notes cite its **planned final kebab-case filename**. A companion (above) only when useful.
5. **Knowledge** (only for reusable knowledge or progress; many captures end at the source).
   - Updates are additive. Existing text is never rewritten or deleted without a shown diff and approval. `updated` moves exactly as the 6.4 table says. New knowledge notes cite their source in `sources:`. **Every contribution cites its source**: a wikilink to the source in the added text, bullet, progress entry or callout, or `sources:` in a new note **(my call: this is what makes the resume check possible without a manifest)**.
   - **Decisions**: a separate decision file only with real alternatives and reusable rationale, otherwise a bullet in the overview `## Decisions` **(user)**. **Lessons**: reusable ones become knowledge notes in `notes/`; project-specific ones stay in `## Lessons` of the overview **(user)**.
   - **Progress** **(user)**: `- YYYY-MM-DD: text` appended under `## Progress` of the relevant topic note, dated by the explicit event or completion date in the capture, otherwise the ingestion date. A topic note is created only for a meaningful subject that warrants ongoing tracking; a trivial, isolated activity creates none (the capture ends at its source). No learning log, no progress type. "Meaningful" is Claude's judgement **(open)**.
   - **Hubs**: a project overview that lists a technology needs a knowledge note for it (links must resolve). Claude may create a short topic hub and reports it **(my call)**.
   - **Conflicts** **(user)**:
     - *Both claims in knowledge notes:* reciprocal `> [!warning] Conflict` callouts in **both**, each citing the other (`[[Other#Heading]]`) and also the source of the claim it adds (`[[source]]`, needed for resume), stating both claims, resolving nothing. Both or neither. **Sequence** (also used by `/maintain` when removing a pair): snapshot both notes and dirty-tree-check them. If either is dirty and unapproved, or has changed since its snapshot (for a note this run already wrote, since its last recorded hash: run-level), **write neither callout** (an isolated skip; the capture is not finalized). Otherwise record the first note's hash, edit it, record its new hash; verify the second note's hash; edit the second. If the second step fails or the second note changed, undo the first: verify its current hash equals the recorded post-edit hash, apply the exact reverse edit, verify the result equals the hash recorded before the edit; when that succeeds the conflict is a skipped conflict (isolated). If the first note no longer matches, or the undo cannot be verified, do not undo; that is a run-level stop and the one-sided callout is reported. Best-effort, not transactional **(open)**. Both notes get `updated` moved.
     - *Skipped conflict (neither callout written):* the conflict is **not resolved and is never reported as resolved**. The final report has a **Needs attention** entry naming **both knowledge-note paths** (or the note and the source), the reason (dirty or untracked, or changed unexpectedly) and the words "still requires attention". **No marker is written to the vault** unless the user explicitly approves one **(user)**; Claude may offer to write the callouts after a checkpoint commit.
     - *One claim only in a source:* a single callout in the knowledge note, citing the source (`[[source]]`); if that note is blocked the same Needs attention entry is made. **Never modify a source to add a callout**; the source file's content hash (not its `sha256` field) is recorded before and verified after.
6. **Validate.** Run `kb.py lint --json` (binary: add `--pending <planned filename>`). Compare with the baseline **by `id`, counting repeats**. **Pass** = (a) no ERROR whose `id` is absent from the baseline anywhere in the vault, and no new W10; and (b) **no ERROR, W10 or E07 at all in any file this capture created in any attempt** (the source, the companion, new knowledge notes), whether or not it is in the baseline, so an unresolved error of an earlier attempt can never pass as baseline state. For a pre-existing note this capture edited on its first attempt only (a) applies; on a later attempt the resume procedure's step 2 has already stopped the capture if that note has an error. Pre-existing errors elsewhere do not block but are reported. Other warnings, REVIEW and PENDING findings never block. A new E07 blocks (reported loudly, nothing is redacted). A new error confined to this capture's own writes: isolated failure (the capture is not finalized; fix mistakes in files written in this attempt and re-run lint). A new ERROR or new W10 outside the files written for the current capture, including in a file written by an earlier capture of this run: run-level stop.
   - **Binary tolerance** **(user)**: `--pending <filename>` reclassifies E04 (and the companion's E08) as PENDING only for the **target** equal to that filename (final path component, NFC-normalized, case-insensitive; `#anchor`, `|text`, `!` and a folder prefix ignored). **One unresolved target is permitted, counted by unique target, however many links point at it.** Only the binary being ingested may be named; it must be a non-Markdown filename (otherwise exit 2); the flag is accepted once. Every other unresolved target stays an ERROR.
7. **Finalize.** If any knowledge part was skipped, validation (step 6) did not pass, or an ERROR, W10 or E07 remains in a file this capture created in any attempt, stop here: the capture stays in `inbox/` (partial completion) and a later run uses the resume procedure. Otherwise re-verify the capture's recorded hash (changed since step 2: isolated, stop this capture). Text: create `inbox/processed/` if absent (`mkdir -p`; it is git-ignored, so M0 does not create it) and move the original to the fixed processed name. Binary: move it to `sources/` (kebab-case) and run lint **without** `--pending`: no new ERROR, and no E04 or E08 for the planned filename.
   - **Rollback** **(user)**: on failure move the binary back to `inbox/` under its original name. Knowledge notes and the companion are never deleted and no edit is reverted; they keep the reference to the planned filename (E04 or E08 until a retry succeeds; step 2 reuses them). If moving back fails or cannot be verified, that is a run-level stop; leave the binary in `sources/` and report both paths.
   - Any earlier failure: the capture stays in `inbox/`.
8. **Report** (run-level, once after the last capture, or at a run-level stop): every file created, edited, moved; completed, blocked and skipped captures with reasons; **Needs attention** (skipped conflicts; captures stopped on an unresolved error, each finding with the `/maintain` direction; new E07; baseline errors left alone); then an offer of a checkpoint commit (never automatic).

### 6.7 Retrieval (`/ask`)

Claude runs `kb.py search`, reads hits, follows links with no hop limit, and uses `kb.py backlinks` for inbound relations ("which projects use PostgreSQL" = backlinks of the PostgreSQL note, filtered to project overviews). Answers are split into:

1. **In the vault**: cited `[[Note]]` or `[[Note#Heading]]`. Cite only headings actually read.
2. **Synthesized from several knowledge notes**: every contributing note cited.
3. **Outside the vault**: Claude's own knowledge, uncited, labeled.

Claims backed only by a source are reported as source material, not as established knowledge. If nothing is found, say so.

**Saving an answer** **(user)**: Claude offers to save only when the answer **synthesizes one or more knowledge notes**. No offer when the answer rests only on external knowledge or only on sources (that would blur source and knowledge). For a mixed answer, only the vault-derived synthesis is saved, meaning claims that come from knowledge notes; external model knowledge is never included, and claims backed only by sources are cited in the answer but left out of the saved note **(my call: keeps source and knowledge apart)**. Claude says what was left out. Before proposing, Claude searches for an existing knowledge note that already covers the same ground; if one does, it proposes an additive update or a link instead of a new note (what counts as a duplicate is Claude's judgement **(open)**). Only on explicit approval: show the draft, apply the 6.2 dirty-tree rule and a collision check, write one `type: note` file in `notes/` with citations as wikilinks, run lint and compare with a baseline taken before the write, report. Never automatic. The saved note starts as an orphan (W01) unless the user wants it linked from a topic, which Claude then proposes as an additive diff.

### 6.8 `scripts/kb.py`

**Common:** vault root = parent of `scripts/` unless `--root`. Exit codes: `0` success; `1` lint found errors, or `backlinks` target not found and has no inbound links; `2` usage or internal error (unreadable or non-vault root, bad flags, crash). A non-UTF-8 file or an unreadable file in `inbox/` never causes exit 2 (W11); an unreadable file anywhere else does. `--json` on `lint` and `search`.

**`lint [--stale-days N] [--inbox-days N] [--pending FILENAME] [--json]`** (defaults 365 and 14 **(user)**). Never modifies files. Levels, always shown separately: **ERROR**, **WARNING**, **REVIEW**, and **PENDING** (only with `--pending`). Exit 1 iff any ERROR. Every finding has `code`, `level`, `path`, `line`, `detail`, `id` (`code|path|detail|n`, no line number, `n` = occurrence of that code, path and detail so a second identical problem gets a new id). The thresholds only produce warnings or review items; they never trigger edits, deletion or archiving **(user)**.

| Code | Level | Rule |
|---|---|---|
| E01 | ERROR | (outside `inbox/`) Frontmatter present but malformed or outside the supported YAML subset (incl. unterminated) |
| E02 | ERROR | (outside `inbox/`) Frontmatter present but incomplete or invalid: missing `type`/`created`/`updated`, unsupported `type`, bad date, non-boolean `standalone`, bad `confidence`, missing `sha256` or `original` on a Markdown source, or an `original` that violates the basename rule (each condition tested separately) |
| E03 | ERROR | `updated` < `created` |
| E04 | ERROR | Broken wikilink or embed in a scanned file: target missing, ambiguous, or matches only an alias. With `--pending`, an unresolved target equal to the given filename is PENDING instead (counted by unique target; the flag is accepted once; it also covers the E08 reference of a companion that names that file; the name must have an extension other than `.md`, compared case-insensitively). **Source bodies are exempt** (they are verbatim and never edited); links in a source's frontmatter are checked |
| E05 | ERROR | Heading anchor not found (Markdown targets only; source bodies exempt) |
| E06 | ERROR | Duplicate basename among scanned files outside `inbox/` (case/NFC-insensitive; captures use W08) or forbidden filename character |
| E07 | ERROR | Possible secret in a scanned file outside `inbox/` (committed to git, hence an error) **(my call)**. `kb.py` does not call git |
| E08 | ERROR | Companion source mismatch. A Markdown source is a **companion** when its `original` has an extension other than `.md`/`.txt`, or names an existing non-Markdown file in `sources/`. Error if `sources/<original>` is missing (PENDING with `--pending` for that name) or its sha256 differs from `sha256` |
| W01 | WARNING | Orphan: no inbound link from another scanned file. Exempt: `index.md`, `topic`, `project`, `source` (see W04), and `standalone: true` |
| W02 | WARNING | Duplicate alias, or alias equal to another file's basename |
| W03 | WARNING | Exact duplicate content (normalized body, frontmatter excluded) among knowledge notes and sources |
| W04 | WARNING | Source (text or binary) with no inbound link from a knowledge note. Expected for captures with no reusable knowledge |
| W05 | WARNING | Capture whose sha256 matches an existing source (text: frontmatter; binary: hashed during lint) |
| W06 | WARNING | Capture older than `--inbox-days` |
| W07 | WARNING | Possible secret in a capture. Unlike other warnings it stops ingestion of that capture until reviewed |
| W08 | WARNING | Capture whose basename collides with a scanned file |
| W09 | WARNING | Unverified block reference |
| W10 | WARNING | Markdown file outside `inbox/` with no frontmatter at all |
| W11 | WARNING | Content checks were skipped for a file: a `.md` that is not valid UTF-8 (in `inbox/` or any scanned folder; binary files and non-UTF-8 `.txt` do not warn), or any file in `inbox/` (including `inbox/processed/`) that cannot be read, such as a permission error. Lint never crashes on either and the unreadable file is never opened, scanned or hashed **(my call: so a bad capture cannot abort the baseline run; an unreadable capture is an isolated failure, never a run-level stop)**. An unreadable file outside `inbox/` is not W11: lint exits 2 |
| R01 | REVIEW | `updated` older than `--stale-days` (types `note`, `topic`, `project`, `decision`; sources are exempt **(user)**). Message states: `updated` is the last knowledge-text or link change, and stale means "needs human review", not "obsolete or incorrect" |
| R02 | REVIEW | `standalone: true` on a note that already has inbound links |

Non-Markdown files in `sources/` have no frontmatter and are exempt from E01/E02/W10; they count for E06 (full filename), W04 and W05. `standalone: true` is valid only on Markdown knowledge notes and only where W01 would be a false alarm **(user)**.

**`search <query> [--type T] [--tag T] [--limit N=10] [--json]`**: case-insensitive, over `sources/`, `notes/`, `projects/`, `index.md`. Matches filename/title, aliases, tags, headings, body, frontmatter values; weighting title > alias > tag > heading > body. Each hit: path, type (`(none)` if no frontmatter), matched field, nearest heading, snippet. Text output ends with `N of M shown` when truncated. A snippet from a line matching a secret pattern is withheld **(my call)**.

**`backlinks "<name>"`**: lists every inbound wikilink or embed (body or frontmatter) as `file:line`, with link text and heading if any. A file whose frontmatter is malformed (E01) is additionally scanned as raw text for the name, and those hits are marked `raw`, so a broken note is still found by resume. Accepts a basename, filename or vault-relative path. A name that resolves to no file still lists links that point at it (needed for binary retry, 6.6 step 2). Ambiguous name: lists candidates, exit 1. There is no `--backlinks` flag on `search` **(user)**.

**Secret scanning** covers every scanned file that decodes as UTF-8, whatever its extension (`.json`, `.csv`, `.html` included), including `inbox/`, non-Markdown files in `sources/` and `inbox/processed/` (always, so a recovery candidate can be checked **(my call)**; a hit there is W07); files that do not decode are not scanned. It uses a short regex set (private-key headers, AWS key IDs, GitHub/Slack/Stripe-style tokens, JWTs, `key|secret|token|password` assignments with long values). **It is a safety net, not comprehensive secret detection**, and cannot read binaries. Findings report file, line and pattern name only; matched text never appears in output, JSON or logs. Never auto-redact or delete **(user)**.

### 6.9 Review and maintenance

- `/lint`: runs `kb.py lint`, explains it in prose by level, changes nothing, offers `/maintain`.
- `/review`: prose report, no scores, priorities or schedules, no edits. Covers shaky knowledge notes, stale knowledge notes (decisions included), topics needing an overview, unresolved conflict callouts (a callout citing another knowledge note must be answered by one citing it back, whether or not it also cites a source; a callout citing only a source is legitimately single), reusable knowledge buried in project overviews, knowledge notes needing updates, sources never cited.
- `/maintain` **(my call: the "separate maintenance workflow")**: proposes consolidation, correction, restructuring, metadata completion, conflict resolution and source recovery, **always as a diff, and writes nothing until approved**. Git safety (6.2) applies. `updated` moves per the 6.4 table. Before proposing, it runs `kb.py lint --json` as a baseline and compares afterwards like ingest step 6.
- **Source recovery** **(user)**: a damaged text source (for example a truncated body) may be rebuilt from a verified original. Candidates: (a) the file named by the source's `original` in `inbox/processed/` (ingest completed), and (b) a capture still in `inbox/` whose sha256 equals the source's stored `sha256` (ingest interrupted before the move; lint W05 identifies it). **Verification:** `shasum -a 256` of the candidate must equal the stored `sha256`; a candidate that does not match is ignored. If both copies verify they are byte-identical; the one in `inbox/processed/` is used and the diff header names it **(my call)**. **Secret check:** if the candidate has a W07 finding (lint scans pending captures and, for this check, `inbox/processed/`), recovery stops and reports; nothing is printed. **Frontmatter:** recovery rebuilds the body only. If the source's own frontmatter is invalid or missing a required field, it is completed first by a separate approved `/maintain` diff (metadata completion); a lost `original` is restored from the candidate's processed name when the candidate is in `inbox/processed/`, or re-derived from the source's `created` date and the capture's name when the candidate is still pending; if `created` is also lost the user is asked. Steps: rebuild with the ingest step 4 procedure (`printf` the source's existing frontmatter fields, then `cat` the candidate), `cmp` the rebuilt body against the candidate, snapshot the target's hash, show the full replacement as a diff. **Nothing is written until explicit approval naming the source file** (this also satisfies the dirty-tree rule for a dirty or untracked source; Claude offers a checkpoint commit first). **Immediately before writing, re-hash the candidate (must still equal the stored `sha256`) and the target (must equal the snapshot).** The replacement is built once into a hidden temporary file in `sources/` (a snapshotted target recorded as `absent`, ignored by lint) and `cmp`-verified against the candidate **before** anything is replaced; its hash is shown in the diff. A copy of the damaged source is kept in the scratchpad. After the final re-hash check, `mv` replaces the source (same folder, atomic) and the result is `cmp`-verified again. Any mismatch before the `mv`: no write. A failure after it: stop, report, and offer to put the kept copy back only with a new approval; never retry without one. If no verified candidate exists (original missing as in a fresh clone, hash mismatch, stored `sha256` unreadable), Claude stops and reports and **never overwrites**; the fallback is the user restoring the source from git history (unavailable before the first commit). The user never has to delete the damaged source first when a verified candidate exists. After recovery from a pending capture, `/ingest` is re-run and takes the resume path. Encodings are never converted. Removing a pair of conflict callouts uses the 6.6 step 5 both-or-neither sequence; a skipped removal is reported under **Needs attention**, and `/maintain`'s final report lists every file changed.
- **Companion repair** **(my call)**: a companion's E08 (for example after the binary was renamed in Obsidian, or `sha256` missing) is repaired by `/maintain`: it locates the binary through the companion's `original` if that file exists, else through the `![[...]]` embed in its body, else by sha256 when that is still readable, else it asks the user to name the binary; it proposes the corrected `original` and, if needed, `sha256` computed from that binary (for a companion the binary is its own original, so this is not circular) as a diff, and writes only after approval naming the companion. A companion's body is authored, so it is never "recovered" from the binary.
- Ingestion itself stays additive.

### 6.10 Citation verification **(user)**

Lint confirms every cited note and heading exists (E04, E05). Claude owns semantic verification. No separate citation engine.

### 6.11 Project overviews

```
---
type: project
created: 2026-11-25
updated: 2026-11-25
---
## Technology stack
- [[PostgreSQL]]
## Related knowledge
- [[Page Object Model]]
## Decisions        (optional; bullets, or links to decision files)
## Lessons          (optional; project-specific only)
```

Technology relationships are wikilinks and backlinks, not tags **(user)**. Section names are a template, not enforced by lint.

### 6.12 Architecture decision records **(user)**

Two ADRs are in scope, written to `docs/adr/` after approval, each with context, decision, consequences and alternatives considered:
- `0001-hash-idempotency-without-manifest.md`
- `0002-originals-not-in-git.md`

Drafts: `draft/docs/adr/`. "ADR" is reserved for these records; project choices are "decisions" (GLOSSARY).

### 6.13 Scaffold (M0), implementation approvals and the first commit **(user)**

**Targets.** M0 creates exactly these files, after the user approves the plan: `.git/` (`git init`, no remote), `.gitignore`, `GLOSSARY.md`, `index.md`, `inbox/.gitkeep`, `sources/.gitkeep`, `notes/.gitkeep`, `projects/.gitkeep`, `docs/superpowers/specs/2026-11-25-engineering-second-brain-design.md`, `docs/superpowers/plans/2026-11-25-engineering-second-brain-plan.md`, `docs/adr/0001-hash-idempotency-without-manifest.md`, `docs/adr/0002-originals-not-in-git.md`. It modifies no existing file.

**Collision guard.** Before creating anything, M0 checks **every** target, comparing names case-insensitively and NFC-normalized (macOS), counting a dangling symlink as present (test both existence and link), for: a file where a file is to be created, an existing `.git`, a file where a directory is needed. Files are then written with no-clobber semantics (for example `set -o noclobber`), so a file appearing between check and write is never overwritten. If any exists, M0 **writes nothing at all**, reports **all** collisions, and asks for explicit user direction. It never overwrites, merges or silently renames. An existing directory is not a collision.

**`index.md`.** Complete valid frontmatter: `type: topic`, `created` and `updated` both set to the date M0 runs (`date +%F`), followed by a short navigation body with no wikilinks (a link to a missing note would raise E04). The `docs/superpowers` filenames carry the fixed design date 2026-11-25, while `index.md` carries the run date. It must raise no E02 once lint exists; M2 runs `kb.py lint` on the scaffold and expects exit 0.

**No commit.** M0 never commits, stages or pushes. When it finishes it reports `git status`; every created and modified file; and the relevant diff (for untracked files `git diff --no-index -- /dev/null <file>` per file, which stages nothing and exits 1 when files differ, which is not a failure). A first commit is a separate operation that happens only on explicit user approval.

**Untracked files stay protected.** Until the user commits, every file M0 or a later milestone created is untracked, so the dirty-tree rule (6.2) requires explicit approval **naming each such file** before it is modified. There is no exception for files created by an earlier milestone. Each milestone in the plan lists the untracked files it will modify, requests that approval, and records their hashes before writing; hash verification and external-modification detection are unchanged. New files a milestone creates need no approval. A file the user has committed is clean and needs none.

## 7. Success criteria

**Automated (`unittest` on `kb.py`)**
1. Every rule E01-E08, W01-W11, R01-R02 fires on a purpose-built bad file; each E02 condition has its own case; clean vault exits 0, one error exits 1.
2. W10 (no frontmatter) is a warning and exits 0; an empty, half-complete or unterminated frontmatter block is an error and exits 1; E01/E02 never fire inside `inbox/`; a non-UTF-8 `.md` in `inbox/` or `notes/`, or an unreadable file in `inbox/`, yields W11, never exit 2, and lint does not crash (an unreadable file in `notes/`, `sources/` or `projects/` exits 2); a PDF or non-UTF-8 `.txt` yields no W11; hidden files (`.gitkeep`, `.DS_Store`) in every scanned folder raise nothing, so a bare scaffold lints clean, and the M0 `index.md` (`type: topic`, valid dates) raises no E02.
3. `--pending X.pdf` turns E04 into PENDING for every link form of that target (`[[X.pdf]]`, `![[X.pdf]]`, `[[X.pdf#page=2]]`, `[[X.pdf|text]]`, `[[sources/X.pdf]]`, different case), in one note or several, and a companion's E08 for `X.pdf` into PENDING, all counted as one target; every other unresolved target or companion reference stays an ERROR; `--pending x.txt` is accepted; `--pending Foo` (no extension), `--pending Foo.md`, `--pending Foo.MD` and a second `--pending` exit 2.
4. A finding's `id` is unchanged when lines shift, and a second identical problem in the same file gets a different `id`.
5. A source whose verbatim body contains `[[missing]]` raises no E04/E05; a broken link in its frontmatter does.
6. **Basename rule on `original`.** Accepted: `2026-11-25-notes.md`, `v1..2.pdf`, `a...b.md`, `..foo`, `日本語 ノート.md`, a 255-byte name, an NFD name equal to its NFC form. Rejected with E02: empty, `.`, `..`, `a/b`, `a\b`, `/abs`, `C:x`, `a:b`, trailing `.` or space, a leading space or U+3000, a control character, U+202E, U+2066, a 256-byte name, a name under 255 characters but over 255 UTF-8 bytes. A missing `original` is E02. A double-quoted `original` containing `#` and `\"` parses to the intended value.
7. **Existence and clone.** A text source whose `original` file does not exist raises nothing; a vault without `inbox/processed/` (and one without `inbox/`) lints cleanly and `search` and `backlinks` run. A binary source without frontmatter is exempt.
8. **Companion.** A companion whose `original` names an existing non-Markdown file in `sources/` with equal sha256 passes, also in a vault without `inbox/processed/`; a missing binary and a sha256 mismatch each raise E08; shape discrimination is tested both ways (extension other than `.md`/`.txt` compared case-insensitively, existing non-Markdown file); a text source whose processed name carries a collision suffix before the extension (`x-1a2b3c4d.md`) is not a companion; matching is NFC and case-insensitive; an invalid `original` such as `../x` makes E08 touch no file outside `sources/` (a decoy outside is never read).
9. R01 fires for an old `decision`, `note`, `topic` and `project`, never for a `source`; the message says stale means needs review, not obsolete.
10. A planted fake secret is detected and never appears in text output, JSON or a forced traceback, in `.md`, `.json` and `.csv` captures and in a file in `inbox/processed/` (W07); `search` withholds that line; an undecodable file is not scanned.
11. `search` is case-insensitive, ranks title above body, honors `--limit` (default 10), prints `N of M shown` when truncated, filters by `--type` and `--tag`.
12. `backlinks` lists `file:line` for body and frontmatter links, works for a dangling target, exits 1 on an unknown name with no links, and finds a citation inside a note with malformed frontmatter (E01) through the raw-text scan, marked `raw`.
13. Exit code 2 (not 0 or 1) for a non-vault or unreadable root and for bad flags; `lint --help` and the R01 message state the `updated` rule.
14. `git check-ignore` matches `inbox/x.md`, `inbox/processed/x.md` and a root-level `credentials.json`, and does **not** match `notes/Secrets management.md` or `notes/credentials-rotation.md`; `sources/`, `notes/` and `docs/adr/` are trackable.
15. No file under `.obsidian/` or `~/Documents/dev/cowork` is modified.

**Manual acceptance (Claude following the commands on a temporary copy of the vault)**
16. Same text capture ingested twice: one source, no second knowledge note; the second run reports a duplicate and asks before moving it.
17. Own raw thought: a source with `sha256` and `original` is created; a knowledge note only if reusable.
18. Interrupted text ingest resumes without duplicating knowledge edits; a truncated source is reported as corrupt and nothing is auto-repaired.
19. Fresh-clone simulation (copy without `inbox/processed/`): a re-dropped ingested capture takes the resume path, creates no second source or duplicate knowledge, restores the original; lint raises nothing about `original`; a companion in that copy still validates.
20. A pre-existing broken link elsewhere does not block ingest; a new one, including a second identical one in the same file, does.
21. Ingest editing a knowledge note with incomplete frontmatter (baseline E02) or none (W10) is not blocked on the first attempt and leaves its frontmatter alone; ingest that creates a file without frontmatter is blocked (never finalized). If that capture is later retried, the resume procedure stops it on that same note until `/maintain` has repaired it (criterion 40).
22. **Classification walk-through.** One capture of each class: `.md`, `.MD` and `.txt` (valid UTF-8) get a `.md` source and an original in `inbox/processed/` (the `.txt` body stored verbatim); a non-UTF-8 `.md` is blocked with bytes unchanged and no conversion; a `.json` with a planted fake secret (blocked by W07) and a clean `.csv` are binary: moved as-is, no copy, scanned; a non-UTF-8 `.txt` and a `.pdf` are binary and moved but never scanned; an extension-less file and an empty file are blocked; a symlink is skipped and reported; an unreadable file is an isolated failure; a nested-folder capture is ingested on its own; a binary yields no knowledge note that fails to cite its planned filename.
23. **Companion and pending target.** A binary with a companion, cited from two notes (one unique target), plus an unrelated broken link: pre-move validation fails only on the unrelated link (the companion E08 and the two E04 are PENDING); once removed, validation passes; after the move lint passes including the sha256 equality; `original` in the companion equals the binary's final filename and no second original file exists.
24. **Binary rollback and retry.** A forced post-move failure moves the binary back and deletes neither the notes nor the companion; the capture is an isolated failure (the run continues and the next capture is still processed); the retry detects the interrupted ingest through the companion's `sha256`, creates no second companion, uses the companion's `original` as the final name, and passes only if no E04 or E08 remains; the resume lint uses `--pending <planned filename>` and tolerates only that target. If that name was taken by another file the capture fails (isolated) and Claude points to `/maintain`.
25. A capture with a planted fake secret: blocked, its bytes unchanged, no report, log or terminal output contains the secret; a false positive is cleared only by the user editing or removing the content.
26. Progress capture: an explicit date is preserved; without one the ingestion date is used; a meaningful ongoing subject gets or updates a topic note with a dated `## Progress` entry; a trivial isolated activity creates no topic note; no learning log and no progress type appear.
27. Contradiction between two clean knowledge notes: reciprocal callouts in both, both `updated` moved, nothing else changed.
28. **Skipped conflict.** (a) One partner dirty and unapproved; (b) a partner modified after its snapshot but before the first edit: in both, neither callout is written, the run continues, the capture is **not finalized** (it stays in `inbox/`, partially ingested, and a later run resumes and retries the conflict), and the final report has a Needs attention entry with both note paths, the reason and the words "still requires attention"; the conflict is never described as resolved; `git status` shows no new marker file or edit. (c) The second partner changes between the two edits and the undo of the first callout verifies: same outcome as (a). (d) The first note changes before the undo: the run stops (run-level) and the one-sided callout is reported. (e) The partner was written earlier in the same run and then changed: run-level.
29. Contradiction where one claim exists only in a source: a single callout in the knowledge note citing the source; the source file's content hash is identical before and after; `/review` does not flag it as one-sided; if that knowledge note is dirty and unapproved the callout is skipped and reported as Needs attention.
30. **Dirty-tree rule and M0.** M0 creates only the listed files, reports `git status`, the created and modified files and the diff, and leaves no commit (`git rev-parse --verify HEAD` fails) and nothing staged (`git diff --cached` empty); with no git repo the hash checks work and the dirty check is skipped; after `git init` with no commit every existing target needs approval naming it and the run offers a checkpoint commit; a dirty or untracked target at start is not modified without approval; the command log contains no `reset`, `checkout --`, `restore`, `clean`, `stash` or `rebase`; commits happen only after approval. Per milestone, the plan lists every untracked file the milestone will modify (for example `scripts/kb.py`, `scripts/tests/test_kb.py`), approval naming each is obtained before the write, there is no exception for files an earlier milestone created, and hash verification and external-modification detection still run.
31. **Isolated failures.** One run with the good capture **last**: a planted secret, a non-UTF-8 `.md`, a corrupt source, a capture whose only target is dirty and unapproved, a capture with some knowledge written and one part skipped (it stays in `inbox/`, partially ingested), a capture edited after it was hashed, an empty file, a symlink, an unreadable file, and a capture whose validation failure is confined to its own writes. The good capture is ingested, every other stays in `inbox/` unchanged, and the report lists each with its reason.
32. **Run-level failures** (each in its own run with three captures, the failure hitting the second): `kb.py lint` exiting 2; a note written earlier in the run edited externally; a forced write failure on a read-only target; a `cmp` verification mismatch after a write; a failed move; an unwritable snapshot file; `git status` failing; a failed rollback (original name taken in `inbox/`); a new ERROR in a file written by the first capture; a new ERROR in a file the run did not write; a new W10 in a file the run did not write. Each stops the run: the first capture stays completed, the second is reported as the failure, the third is untouched and still in `inbox/`, the report lists the files written and the captures pending, and a Needs attention entry created by the first capture (a skipped conflict) is still in the report.
33. `updated`: a `tags`-only edit and a whitespace-only edit leave it unchanged; a link-only edit and a `sources:` edit move it.
34. Decision with alternatives becomes its own file; one without stays a bullet; reusable lesson goes to `notes/`, project-specific stays in the overview.
35. `/ask`: the two example questions return cited answers. A mixed answer offers a save containing only claims from knowledge notes (no external text, no source-only claims); source-only and external-only answers get no offer; a near-duplicate note makes Claude propose an update or link instead; nothing is written before approval; a failed write stops the save with a report.
36. `/lint` explains each level separately and offers `/maintain` for E08 and W10; `/review` lists a stale decision, flags a one-sided callout between knowledge notes (also when it additionally cites a source), and ignores a callout that cites only a source.
37. `/maintain`: metadata completion, conflict resolution (a skipped removal is listed under Needs attention) and **companion repair** (binary renamed in Obsidian, or missing `sha256`) each show a diff and change nothing until approved; the repair locates the binary through `original`, the body embed, sha256, or by asking.
38. **Source recovery.** Damaged text source with the original in `inbox/processed/`, and with the original still in `inbox/` (then `/ingest` resumes): verified, diff, approval naming the source, temp-file write, `cmp` check. Both copies present: the processed copy is used and named. No write and a report for each of: original modified so its hash differs; original missing; stored `sha256` unreadable; a W07 finding on the candidate (nothing printed); original changed between diff and write; source changed between diff and write; approval that does not name the source; a failed write; the replacement failing its pre-write `cmp` (nothing replaced); a lost `sha256` (never derived from the candidate). One of two copies verifies and the other does not: the verified one is used. A damaged frontmatter is completed first by its own diff. A dirty or untracked source needs the approval to name it. The user is never asked to delete the source first when a verified original exists.
39. **Name derivation.** Processed names and kebab-case names for: a capture name with `:`, a trailing dot, leading whitespace, a 250-byte name, a Unicode name, an empty kebab stem, a name already taken (suffix before the extension, including a name taken in `sources/`), a kebab name over 255 bytes, a name that still violates the rule (capture blocked, isolated); each resulting `original` passes lint.

40. **Unresolved error survives a retry.** (1) A capture creates a knowledge note whose frontmatter is invalid (E01 or E02; a fixture forces the invalid frontmatter). (2) The capture stays pending in `inbox/` (isolated; the run continues with the next capture). (3) A retry (new run) does **not** treat that error as baseline: the resume procedure finds it in the capture's own files, stops the capture, lists the finding, directs the user to `/maintain`, and the capture is still in `inbox/`; nothing is deleted or rolled back. (4) `/maintain` proposes a repair diff and writes nothing until approval naming the note. (5) After the repair, `/ingest` resumes and finalizes only because lint shows no error in the capture's files. Variants: the same error in a pre-existing note the capture edited also stops the retry; an unrelated pre-existing error elsewhere still does not block (criterion 20). Further variants: (6) the invalid note has malformed frontmatter (E01), so its source citation is found only by the raw-text `backlinks` scan; (7) the capture is a binary whose rollback left E04/E08 for its planned filename: the retry tolerates exactly that one target and resumes, but stops on any other error; (8) an E07 in a created note: `/maintain` names file and line only and prints no diff, the user edits by hand, then the retry resumes; (9) the stop is listed in the final report under Needs attention with the `/maintain` direction.
41. **Deterministic partial resume.** One capture must update two knowledge notes. The first update succeeds (it cites the source). The second target is dirty and unapproved, so it is skipped and the capture stays in `inbox/`. After the user commits, a retry re-reads the source, reconstructs two contributions, reports the first as present and the second as missing with the evidence, applies only the second, leaves the first note byte-identical (same hash), and finalizes only after both exist. Variant: the first note's contribution was reworded by the user, so it is unclear: Claude shows the evidence, asks, and writes nothing for it. Variant: the expected contributions cannot be reconstructed reliably: Claude asks and writes nothing. Variant: the first note was renamed in Obsidian, so it cites the source but no reconstructed target matches: the related contribution is unclear, Claude asks, and nothing is duplicated.
42. **M0 collision guard.** In a temporary copy, pre-create two M0 targets (for example `GLOSSARY.md` and `docs/adr/0001-hash-idempotency-without-manifest.md`): M0 writes nothing (no file, no `.git`), reports both collisions, and waits for direction; with an existing `.git` the same. Without collisions, M0 creates exactly the listed files, `index.md` has the three frontmatter fields with today's date, and no commit exists.

## 8. Left to the builder

Exact secret regex set; ranking numbers and snippet length; output formatting; internal structure of `kb.py` (single file); test fixtures; wording of the five prompts; body structure of decision files.

## 9. Known limitations

- Regex secret scanning misses secrets and cannot read undecodable files (PDFs, images, archives); a secret that reaches a knowledge note is caught afterwards by E07.
- Originals are not in git. A fresh clone has sources but no originals, so `original` of a text source names a file that is not there, and recovery from `inbox/processed/` is unavailable (a capture still in `inbox/` or git history are the alternatives). Binaries and companions are tracked and validate normally.
- Binaries in `sources/` are tracked and can bloat the repository; lint hashes them on every run.
- A whitespace-only re-capture has a different hash and becomes a new source; W03 flags the duplicate afterwards.
- Reciprocal callouts are best-effort atomic, not transactional. A skipped conflict leaves no marker (by decision), so `/review` cannot find it later; the run report is the only record.
- A secret false positive has no override; the user edits or removes the content.
- The dirty-tree rule is strict by design: uncommitted output of an earlier run, and every file before the first commit, needs a checkpoint commit or per-file approval before it can be edited.
- Renaming a companion's binary in Obsidian does not update `original`; lint reports E08 until `/maintain` fixes it.
- Heading matching approximates Obsidian's. Nothing mechanically checks that a note's claims match its cited source.
- Obsidian indexes `inbox/` in its graph; the user may add `inbox/processed` to its *Excluded files* setting by hand.

## 10. Remaining ambiguities and my calls to confirm

Nothing below was decided by you. Each default is applied in the documents and tagged **(open)** or **(my call)** there.

1. **Classification edges.** UTF-8 `.txt` is a text capture; non-UTF-8 `.txt`, `.markdown` and UTF-8 `.json`/`.csv`/`.html` are binary (the non-UTF-8 `.txt` is never scanned); an extension-less file and an empty capture are blocked; a symlink is skipped; an unreadable capture is an isolated failure. A non-UTF-8 `.txt` is therefore not blocked, unlike non-UTF-8 `.md`.
2. **Companion for a non-UTF-8 `.txt`** binary looks like a text source until the binary has moved, so it raises no E08 before the move.
3. **Names.** Processed-name derivation, truncation, kebab-case (Unicode letters kept, `capture-<8 hex>` for an empty stem), collision suffix before the extension, and Unicode White_Space for the whitespace rule are my definitions. Windows reserved characters and device names are not covered by the basename rule.
4. **Quoting.** `original` and `url` are always written double-quoted.
5. **Recovery.** Companions are repaired, not recovered. When both candidate originals verify the processed copy is used. `inbox/processed/` is included in the secret scan so a candidate can be checked. Before the first commit there is no git-history fallback.
6. **Failure classes.** An unwritten target that changed since its snapshot is treated like a dirty one (isolated). A run-written file changed externally is run-level. A new ERROR in any file not written for the current capture, including a file written by an earlier capture of the run, is run-level. `/maintain` and the `/ask` save stop on any failure.
7. **Partial completion.** A capture with any skipped knowledge part (dirty target, skipped conflict) is not finalized: it stays in `inbox/` and a later run resumes it. Until then the conflict exists only in the run report and as the pending capture; `/review` cannot find it (no marker, by your decision). Your decision did not say whether such a capture should move to processed; I chose to keep it pending.
8. **Clone versus interrupted.** A duplicate re-dropped into a fresh clone is indistinguishable from an interrupted ingest; resume is idempotent and restores the original.
9. **Judgement calls with no mechanical rule:** a "meaningful subject" for progress; what counts as a duplicate note in `/ask`.
10. **Secret false positives** have no override; the user edits or removes the content.
11. **`/ask` saving** leaves out claims backed only by sources. **W11** (non-UTF-8 `.md` warning) is my addition. `.gitignore` anchors `credentials*` and `secrets*` to the repo root.
12. **Atomicity** of reciprocal callouts is best-effort, not transactional.
13. **Strict dirty-tree rule** means every scaffold file stays untracked, and so needs approval naming it before any later edit, until you make the first commit.
14. **Other defaults I applied:** companion repair locator order; the processed-name date is the ingestion date (= source §created§); a text source's §original§ may never equal a file in §sources/§ (suffix applied); E07 is an ERROR; decision filenames are §<Project> - <title>§; Python 3.10+; processed originals are always secret-scanned; recovery writes through a hidden temp file in §sources/§ and keeps a copy of the damaged source in the scratchpad; matching of §original§ is NFC and case-insensitive although described as the "exact" filename; the M0 diff command §git diff --no-index§ exits 1 when files differ, which is not a failure.
15. **Resume.** (Also: the retry stop covers W10 and E07 as well as ERRORs, because a missing-frontmatter note a capture created is a failed contribution; first-attempt validation rule (a) applies to pre-existing notes only on the first attempt.) Every contribution cites its source (my call; it makes presence checkable without a manifest). "Present" requires a source citation plus matching content; anything else is "unclear" and Claude asks. On a retry, an error in a pre-existing note the capture edited stops the capture even if the error pre-dated the capture, because the two cannot be told apart; this adds friction by design.
16. **Implementation approvals.** Every milestone that modifies an untracked file asks for approval naming it, as the plan lists. Committing between milestones removes the need, but only you decide to commit.
17. **More defaults I applied (implementation approvals, M0, resume).** An existing directory is not an M0 collision; M0 matches names case-insensitively, NFC-normalized, counts a dangling symlink as present and writes with no-clobber; `index.md` has no wikilinks and carries the run date while the `docs/superpowers` filenames keep 2026-11-25; Conflict callouts also cite the source of the claim they add; `backlinks` scans E01 files as raw text; an E07 can only be repaired by the user's own edit (no diff is shown); a pre-existing note's error stops a retry even if it predates the capture; `inbox/processed/` is created by ingest, not by M0; test fixtures live inside `scripts/tests/test_kb.py` (built in temp dirs), so no separate untracked fixture files need approval.
