---
description: Answer a question from the vault, with citations
argument-hint: <question>
---

Answer from the vault. Follow CLAUDE.md and GLOSSARY.md. Question: $ARGUMENTS

1. Run `python3 scripts/kb.py search "<terms>"` with several phrasings; use `--type` and `--tag` to narrow. Use `kb.py backlinks "<name>"` for relationships ("which projects use X" = backlinks of the X knowledge note, filtered to project overviews). Read the hits and follow their links; there is no hop limit.
2. Answer in three labeled parts, omitting empty ones:
   - **In the vault**: cite `[[Note]]` or `[[Note#Heading]]`. Cite only headings you actually read.
   - **Synthesized from several knowledge notes**: cite every contributing note.
   - **Outside the vault**: your own knowledge, uncited, labeled as such.
3. A claim supported only by a source is source material, not established knowledge: say so and cite the source.
4. If nothing relevant exists, say so plainly.
5. **Offer to save**, once, after answering, and only if the answer synthesizes one or more knowledge notes. No offer for an answer that rests only on external knowledge or only on sources. Never save without an explicit yes.
   - First search for an existing knowledge note that already covers the same ground. If one does, say so and offer an additive update or a link instead of a new note.
   - Save only the vault-derived synthesis: claims that come from knowledge notes. Never include your own external knowledge, and leave out claims backed only by sources (cite them in the answer only); say what was left out.
   - On yes: show the draft; apply the CLAUDE.md dirty-tree rule and a name-collision check; write one `type: note` file in `notes/` with `created` and `updated` = today and citations as wikilinks (`sources:` only for sources actually cited); compare `kb.py lint --json` with a baseline taken before the write, and report the file. The note is an orphan until linked: offer to link it from a relevant topic as an additive diff, never automatically.
