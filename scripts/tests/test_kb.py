import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kb  # noqa: E402


class BasenameRule(unittest.TestCase):
    def ok(self, name):
        self.assertIsNone(kb.basename_error(name), name)

    def bad(self, name):
        self.assertIsNotNone(kb.basename_error(name), repr(name))

    def test_accepted(self):
        for name in [
            "2026-11-25-notes.md",
            "v1..2.pdf",
            "a...b.md",
            "..foo",
            "\u65e5\u672c\u8a9e \u30ce\u30fc\u30c8.md",
            "a" * 252 + ".md",
            "e\u0301.md",
            "caf\u00e9.md",
            ".hidden",
        ]:
            self.ok(name)

    def test_255_byte_boundary(self):
        self.assertEqual(len(("a" * 252 + ".md").encode()), 255)
        self.ok("a" * 252 + ".md")
        self.bad("a" * 253 + ".md")

    def test_rejected(self):
        for name in [
            "", ".", "..", "a/b", "a\\b", "/abs", "C:x", "a:b",
            "trailing.", "trailing ", " leading", "\u3000leading", "trailing\u3000",
            "ctl\x00char", "tab\there", "new\nline", "del\x7f", "rtl\u202e.md", "iso\u2066.md",
            "iso\u2069.md", "ovr\u202a.md", "..\\x", "../x",
        ]:
            self.bad(name)

    def test_length_in_bytes_not_characters(self):
        self.bad("a" * 256)
        name = "\u65e5" * 90
        self.assertLess(len(name), 255)
        self.bad(name)
        self.ok("\u65e5" * 85)

    def test_name_containing_dotdot_is_valid(self):
        self.ok("v1..2.pdf")
        self.bad("..")


class NameNormalization(unittest.TestCase):
    def test_nfc_and_case(self):
        self.assertEqual(kb.norm_name("Cafe\u0301.MD"), kb.norm_name("caf\u00e9.md"))
        self.assertNotEqual(kb.norm_name("a.md"), kb.norm_name("b.md"))

    def test_nfc(self):
        self.assertEqual(kb.nfc("e\u0301"), "\u00e9")


class FrontmatterPresence(unittest.TestCase):
    def test_missing(self):
        fm = kb.parse_frontmatter("# Title\n\nbody\n")
        self.assertEqual(fm.status, "missing")
        self.assertEqual(fm.data, {})

    def test_empty_file_is_missing(self):
        self.assertEqual(kb.parse_frontmatter("").status, "missing")

    def test_rule_not_on_first_line_is_missing(self):
        self.assertEqual(kb.parse_frontmatter("\n---\ntype: note\n---\n").status, "missing")

    def test_ok(self):
        fm = kb.parse_frontmatter("---\ntype: note\ncreated: 2026-11-25\n---\nbody\n")
        self.assertEqual(fm.status, "ok")
        self.assertEqual(fm.data, {"type": "note", "created": "2026-11-25"})
        self.assertEqual(fm.body, "body\n")
        self.assertEqual(fm.end_line, 4)

    def test_empty_block_is_ok_and_empty(self):
        fm = kb.parse_frontmatter("---\n---\nbody")
        self.assertEqual(fm.status, "ok")
        self.assertEqual(fm.data, {})

    def test_unterminated_is_malformed(self):
        fm = kb.parse_frontmatter("---\ntype: note\nbody never closes\n")
        self.assertEqual(fm.status, "malformed")
        self.assertIn("unterminated", fm.error)

    def test_only_opening_line_is_malformed(self):
        self.assertEqual(kb.parse_frontmatter("---\n").status, "malformed")

    def test_crlf(self):
        fm = kb.parse_frontmatter("---\r\ntype: note\r\ntags: [a, b]\r\n---\r\nbody\r\n")
        self.assertEqual(fm.status, "ok")
        self.assertEqual(fm.data, {"type": "note", "tags": ["a", "b"]})

    def test_bom(self):
        fm = kb.parse_frontmatter("\ufeff---\ntype: note\n---\n")
        self.assertEqual(fm.status, "ok")
        self.assertEqual(fm.data["type"], "note")

    def test_delimiter_must_be_exact(self):
        self.assertEqual(kb.parse_frontmatter("--- \ntype: note\n---\n").status, "missing")
        self.assertEqual(kb.parse_frontmatter("---\ntype: note\n--- \n").status, "malformed")

    def test_note_opening_with_rule_and_later_rule_is_malformed(self):
        self.assertEqual(kb.parse_frontmatter("---\nSome prose here\n---\n").status, "malformed")


class YamlAccepted(unittest.TestCase):
    def parse(self, body):
        fm = kb.parse_frontmatter("---\n" + body + "\n---\n")
        self.assertEqual(fm.status, "ok", fm.error)
        return fm.data

    def test_plain_scalar(self):
        self.assertEqual(self.parse("type: note"), {"type": "note"})

    def test_booleans(self):
        d = self.parse("standalone: true\nother: false")
        self.assertIs(d["standalone"], True)
        self.assertIs(d["other"], False)

    def test_date_stays_text(self):
        self.assertEqual(self.parse("created: 2026-11-25")["created"], "2026-11-25")

    def test_single_quoted(self):
        self.assertEqual(self.parse("url: 'http://x.y/a#b'")["url"], "http://x.y/a#b")
        self.assertEqual(self.parse("k: 'it''s'")["k"], "it's")

    def test_double_quoted_with_escapes(self):
        self.assertEqual(self.parse('original: "a #b \\"q\\" c"')["original"], 'a #b "q" c')
        self.assertEqual(self.parse('k: "back\\\\slash"')["k"], "back\\slash")

    def test_double_quoted_colon_and_hash(self):
        self.assertEqual(self.parse('url: "https://x.y/z?a=1#frag"')["url"], "https://x.y/z?a=1#frag")

    def test_quoted_wikilink(self):
        self.assertEqual(self.parse('related: "[[Note]]"')["related"], "[[Note]]")

    def test_inline_list(self):
        self.assertEqual(self.parse("tags: [a, b, c]")["tags"], ["a", "b", "c"])
        self.assertEqual(self.parse("tags: []")["tags"], [])

    def test_inline_list_with_quoted_items(self):
        d = self.parse('sources: ["[[A]]", "[[B, C]]"]')
        self.assertEqual(d["sources"], ["[[A]]", "[[B, C]]"])

    def test_block_list(self):
        self.assertEqual(self.parse("tags:\n  - a\n  - b")["tags"], ["a", "b"])

    def test_block_list_unindented(self):
        self.assertEqual(self.parse("tags:\n- a\n- b\nafter: x"), {"tags": ["a", "b"], "after": "x"})

    def test_block_list_quoted_wikilinks(self):
        d = self.parse('sources:\n  - "[[A]]"\n  - "[[B]]"')
        self.assertEqual(d["sources"], ["[[A]]", "[[B]]"])

    def test_key_with_no_value(self):
        self.assertEqual(self.parse("type:")["type"], None)

    def test_unknown_keys_allowed(self):
        self.assertEqual(self.parse("mykey: v")["mykey"], "v")

    def test_blank_lines_ignored(self):
        self.assertEqual(self.parse("type: note\n\ncreated: 2026-11-25"), {"type": "note", "created": "2026-11-25"})

    def test_unicode_value(self):
        self.assertEqual(self.parse("title: \u65e5\u672c\u8a9e")["title"], "\u65e5\u672c\u8a9e")

    def test_property_names_with_space(self):
        self.assertEqual(self.parse("my key: v")["my key"], "v")


class YamlRejected(unittest.TestCase):
    def malformed(self, body):
        fm = kb.parse_frontmatter("---\n" + body + "\n---\n")
        self.assertEqual(fm.status, "malformed", repr(body))
        self.assertTrue(fm.error)

    def test_nesting(self):
        self.malformed("a:\n  b: c")

    def test_comment_line(self):
        self.malformed("# comment\ntype: note")

    def test_inline_comment(self):
        self.malformed("type: note # c")

    def test_duplicate_keys(self):
        self.malformed("type: note\ntype: topic")

    def test_unquoted_wikilink(self):
        self.malformed("related: [[Note]]")
        self.malformed("related: see [[Note]]")
        self.malformed("tags: [[[Note]]]")

    def test_multiline_scalars(self):
        self.malformed("a: |\n  text")
        self.malformed("a: >\n  text")

    def test_anchors_and_tags(self):
        self.malformed("a: &x 1")
        self.malformed("a: *x")
        self.malformed("a: !!str x")

    def test_flow_mapping(self):
        self.malformed("a: {b: c}")

    def test_bad_escape(self):
        self.malformed('a: "tab\\t"')
        self.malformed('a: "uni\\u0041"')

    def test_unterminated_quote(self):
        self.malformed('a: "open')
        self.malformed("a: 'open")

    def test_text_after_closing_quote(self):
        self.malformed('a: "x" y')

    def test_unclosed_inline_list(self):
        self.malformed("a: [x, y")

    def test_nested_inline_list(self):
        self.malformed("a: [x, [y]]")

    def test_plain_colon_space(self):
        self.malformed("a: b: c")

    def test_stray_line(self):
        self.malformed("just some prose")

    def test_list_item_without_key(self):
        self.malformed("- a\n- b")

    def test_empty_list_item(self):
        self.malformed("a:\n  -")

    def test_key_value_then_list_item(self):
        self.malformed("a: b\n  - c")

    def test_empty_key(self):
        self.malformed(": value")


class Dates(unittest.TestCase):
    def test_iso_date(self):
        self.assertTrue(kb.is_iso_date("2026-11-25"))
        self.assertTrue(kb.is_iso_date("2024-02-29"))
        for bad in ["2026-13-01", "2026-02-30", "26-11-25", "2026-1-5", "2026-11-25T10:00", "", "x", None, True]:
            self.assertFalse(kb.is_iso_date(bad), bad)


class Links(unittest.TestCase):
    def names(self, text):
        return [(l.name, l.anchor, l.label, l.embed) for l in kb.extract_links(text)]

    def test_forms(self):
        t = "[[Note]] [[Note|text]] [[Note#Head]] ![[Img.png]] ![[Doc.pdf#page=3]] [[folder/Note]] [[#Self]]"
        self.assertEqual(self.names(t), [
            ("Note", None, None, False),
            ("Note", None, "text", False),
            ("Note", "Head", None, False),
            ("Img.png", None, None, True),
            ("Doc.pdf", "page=3", None, True),
            ("folder/Note", None, None, False),
            ("", "Self", None, False),
        ])

    def test_block_reference(self):
        l = kb.extract_links("[[Note#^abc123]]")[0]
        self.assertEqual((l.name, l.anchor), ("Note", "^abc123"))
        self.assertTrue(l.is_block_ref)

    def test_escaped_pipe_in_tables(self):
        l = kb.extract_links("| [[Note\\|text]] |")[0]
        self.assertEqual((l.name, l.label), ("Note", "text"))

    def test_line_numbers(self):
        ls = kb.extract_links("a\n[[One]]\n\n[[Two]] and [[Three]]\n")
        self.assertEqual([(l.name, l.line) for l in ls], [("One", 2), ("Two", 4), ("Three", 4)])

    def test_fenced_code_skipped(self):
        t = "[[A]]\n```\n[[B]]\n```\n[[C]]\n"
        self.assertEqual([l.name for l in kb.extract_links(t)], ["A", "C"])

    def test_tilde_fence_and_info_string(self):
        t = "~~~python\n[[B]]\n~~~\n[[C]]"
        self.assertEqual([l.name for l in kb.extract_links(t)], ["C"])

    def test_longer_closing_fence_and_nested_shorter(self):
        t = "````\n```\n[[B]]\n```\n````\n[[C]]"
        self.assertEqual([l.name for l in kb.extract_links(t)], ["C"])

    def test_unclosed_fence_runs_to_end(self):
        self.assertEqual([l.name for l in kb.extract_links("[[A]]\n```\n[[B]]\n[[C]]")], ["A"])

    def test_inline_code_skipped(self):
        t = "use `[[B]]` but [[A]] and ``[[C]] with ` tick`` then [[D]]"
        self.assertEqual([l.name for l in kb.extract_links(t)], ["A", "D"])

    def test_frontmatter_links_included(self):
        t = '---\ntype: note\nsources: ["[[Src]]"]\nrelated:\n  - "[[Other#H]]"\n---\nBody [[Body]]\n'
        ls = kb.extract_links(t)
        self.assertEqual([(l.name, l.anchor, l.line) for l in ls], [("Src", None, 3), ("Other", "H", 5), ("Body", None, 7)])

    def test_fence_in_frontmatter_region_does_not_start_code(self):
        t = '---\nk: "```"\n---\n[[A]]'
        self.assertEqual([l.name for l in kb.extract_links(t)], ["A"])

    def test_unterminated_frontmatter_is_not_a_crash(self):
        kb.extract_links('---\nsources: "[[A]]"\nnever closes [[B]]')

    def test_unclosed_and_empty_brackets(self):
        self.assertEqual(self.names("[[ ]] [[unclosed and [[Ok]]"), [("Ok", None, None, False)])

    def test_standard_markdown_links_not_parsed(self):
        self.assertEqual(self.names("[t](other.md) <https://x.y>"), [])

    def test_crlf_line_numbers(self):
        ls = kb.extract_links("a\r\n[[One]]\r\n")
        self.assertEqual((ls[0].line, ls[0].name), (2, "One"))

    def test_whitespace_in_target_is_trimmed(self):
        l = kb.extract_links("[[ Note # Head | text ]]")[0]
        self.assertEqual((l.name, l.anchor, l.label), ("Note", "Head", "text"))


class Headings(unittest.TestCase):
    def test_extract(self):
        t = "# One\ntext\n## Two ##\n###   Three   \n####### seven\n#nospace\n"
        hs = kb.extract_headings(t)
        self.assertEqual([(h.level, h.text, h.line) for h in hs], [(1, "One", 1), (2, "Two", 3), (3, "Three", 4)])

    def test_skips_code_and_frontmatter(self):
        t = "---\ntype: note\n---\n# Real\n```\n# Not\n```\n"
        self.assertEqual([h.text for h in kb.extract_headings(t)], ["Real"])

    def test_indented_up_to_three_spaces(self):
        self.assertEqual([h.text for h in kb.extract_headings("   # A\n    # B\n")], ["A"])

    def test_normalization_for_matching(self):
        self.assertEqual(kb.norm_heading("  Page   Object\tModel "), kb.norm_heading("page object model"))

    def test_heading_matches(self):
        hs = kb.extract_headings("# Page Object Model\n## Setup  Steps\n")
        self.assertTrue(kb.heading_exists("page object model", hs))
        self.assertTrue(kb.heading_exists("Setup Steps", hs))
        self.assertTrue(kb.heading_exists("Page Object Model#Setup Steps", hs))
        self.assertFalse(kb.heading_exists("Missing", hs))


class Findings(unittest.TestCase):
    def test_id_has_no_line_number_and_counts_repeats(self):
        a = kb.Finding("E04", "ERROR", "notes/A.md", 3, "Missing")
        b = kb.Finding("E04", "ERROR", "notes/A.md", 9, "Missing")
        c = kb.Finding("E04", "ERROR", "notes/A.md", 9, "Other")
        kb.assign_ids([a, b, c])
        self.assertEqual(a.id, "E04|notes/A.md|Missing|1")
        self.assertEqual(b.id, "E04|notes/A.md|Missing|2")
        self.assertEqual(c.id, "E04|notes/A.md|Other|1")

    def test_id_unchanged_when_lines_shift(self):
        a1 = kb.Finding("E04", "ERROR", "p.md", 3, "x")
        a2 = kb.Finding("E04", "ERROR", "p.md", 40, "x")
        kb.assign_ids([a1])
        kb.assign_ids([a2])
        self.assertEqual(a1.id, a2.id)

    def test_second_identical_problem_gets_new_id(self):
        fs = [kb.Finding("E04", "ERROR", "p.md", i, "x") for i in (1, 2)]
        kb.assign_ids(fs)
        self.assertNotEqual(fs[0].id, fs[1].id)

    def test_as_dict(self):
        f = kb.Finding("W10", "WARNING", "p.md", 1, "no frontmatter")
        kb.assign_ids([f])
        self.assertEqual(f.as_dict(), {
            "code": "W10", "level": "WARNING", "path": "p.md", "line": 1,
            "detail": "no frontmatter", "id": "W10|p.md|no frontmatter|1"})


class VaultWalker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def touch(self, rel, data=b"x"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def rels(self):
        return sorted(f.rel for f in kb.scan_vault(self.root))

    def test_scope(self):
        for rel in [
            "index.md", "CLAUDE.md", "GLOSSARY.md", "docs/design.md", "scripts/kb.py", ".claude/commands/a.md",
            ".obsidian/app.json", "notes/A.md", "notes/sub/B.md", "sources/s.md", "sources/x.pdf",
            "projects/P/P.md", "inbox/c.md", "inbox/deep/d.txt", "inbox/processed/old.md",
        ]:
            self.touch(rel)
        self.assertEqual(self.rels(), [
            "inbox/c.md", "inbox/deep/d.txt", "index.md", "notes/A.md", "notes/sub/B.md",
            "projects/P/P.md", "sources/s.md", "sources/x.pdf",
        ])

    def test_areas(self):
        for rel in ["index.md", "notes/A.md", "sources/s.md", "projects/P/P.md", "inbox/c.md"]:
            self.touch(rel)
        areas = {f.rel: f.area for f in kb.scan_vault(self.root)}
        self.assertEqual(areas, {"index.md": "index", "notes/A.md": "notes", "sources/s.md": "sources",
                                 "projects/P/P.md": "projects", "inbox/c.md": "inbox"})

    def test_hidden_files_and_folders_ignored_everywhere(self):
        for rel in ["notes/.gitkeep", "notes/.DS_Store", "inbox/.gitkeep", "sources/.gitkeep", "projects/.gitkeep",
                    "notes/.hidden/A.md", "inbox/.x", "notes/ok.md"]:
            self.touch(rel)
        self.assertEqual(self.rels(), ["notes/ok.md"])

    def test_tolerates_missing_folders(self):
        self.assertEqual(self.rels(), [])
        self.touch("notes/A.md")
        self.assertEqual(self.rels(), ["notes/A.md"])

    def test_vault_without_inbox_or_processed(self):
        self.touch("sources/s.md")
        self.assertEqual(self.rels(), ["sources/s.md"])

    def test_processed_excluded_only_directly_under_inbox(self):
        self.touch("inbox/processed/a.md")
        self.touch("inbox/sub/processed/b.md")
        self.assertEqual(self.rels(), ["inbox/sub/processed/b.md"])

    def test_scaffold_scans_clean(self):
        for rel in ["inbox/.gitkeep", "sources/.gitkeep", "notes/.gitkeep", "projects/.gitkeep"]:
            self.touch(rel, b"")
        self.touch("index.md", b"---\ntype: topic\ncreated: 2026-11-25\nupdated: 2026-11-25\n---\n# Index\n")
        self.assertEqual(self.rels(), ["index.md"])

    def test_paths_are_posix_and_sorted(self):
        self.touch("notes/b.md")
        self.touch("notes/a.md")
        self.assertEqual([f.rel for f in kb.scan_vault(self.root)], ["notes/a.md", "notes/b.md"])

    def test_symlinks_are_not_followed_or_scanned(self):
        self.touch("notes/real.md")
        outside = Path(self._tmp.name + "-outside")
        outside.mkdir()
        self.addCleanup(lambda: [p.unlink() for p in outside.iterdir()] or outside.rmdir())
        (outside / "secret.md").write_bytes(b"x")
        os.symlink(outside, self.root / "notes" / "linkdir")
        os.symlink(outside / "secret.md", self.root / "notes" / "link.md")
        self.assertEqual(self.rels(), ["notes/real.md"])


class Reading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_utf8(self):
        p = self.root / "a.md"
        p.write_bytes("h\u00e9llo".encode())
        d = kb.read_file(p)
        self.assertEqual(d.text, "h\u00e9llo")
        self.assertIsNone(d.error)
        self.assertEqual(d.raw, "h\u00e9llo".encode())

    def test_non_utf8_does_not_crash(self):
        p = self.root / "a.md"
        p.write_bytes(b"caf\xe9 [[X]]")
        d = kb.read_file(p)
        self.assertIsNone(d.text)
        self.assertEqual(d.raw, b"caf\xe9 [[X]]")
        self.assertIsNone(d.error)

    def test_bom_is_kept_in_raw_and_stripped_in_text(self):
        p = self.root / "a.md"
        p.write_bytes(b"\xef\xbb\xbfhi")
        d = kb.read_file(p)
        self.assertEqual(d.text, "hi")
        self.assertEqual(d.raw, b"\xef\xbb\xbfhi")

    def test_unreadable_does_not_crash(self):
        d = kb.read_file(self.root / "missing.md")
        self.assertIsNone(d.text)
        self.assertIsNone(d.raw)
        self.assertTrue(d.error)

    def test_sha256_of_bytes(self):
        p = self.root / "a.bin"
        p.write_bytes(b"abc")
        self.assertEqual(kb.sha256_hex(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(kb.read_file(p).sha256, kb.sha256_hex(b"abc"))


# ======================================================================== M2: lint errors

F3 = chr(96) * 3
TICK = chr(96)

import contextlib
import datetime
import hashlib
import io
import json


def doc(body="# T\n", **over):
    fields = {"type": "note", "created": "2026-01-01", "updated": "2026-01-02"}
    fields.update(over)
    lines = ["---"] + [f"{k}: {v}" for k, v in fields.items() if v is not None] + ["---", body]
    return "\n".join(lines)


def src(body="captured text\n", **over):
    base = {"type": "source", "created": "2026-01-01", "updated": "2026-01-01",
            "sha256": "a" * 64, "original": '"2026-01-01-a.md"'}
    base.update(over)
    return doc(body, **base)


def q(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class VaultCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.root = self.base / "vault"
        self.root.mkdir()
        (self.root / "notes").mkdir()

    def put(self, rel, content):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return p

    def lint(self, **kw):
        kw.setdefault("now", NOW)  # fixed clock so staleness never makes these tests drift
        return kb.lint(self.root, **kw)

    M2_CODES = {"E01", "E02", "E03", "E04", "E05", "E06", "E08", "W10", "W11"}

    def m2(self, res):
        """Findings of the M2 rules only, so these tests keep asserting what they always did."""
        return [f for f in res.findings if f.code in self.M2_CODES]

    def found(self, res, code=None, level=None):
        return [(f.code, f.path, f.detail) for f in res.findings
                if (code is None or f.code == code) and (level is None or f.level == level)]

    def codes(self, res, level=None):
        return sorted(f.code for f in res.findings if level is None or f.level == level)

    def assertHas(self, res, code, path=None, text=None, level=None):
        hits = [f for f in res.findings if f.code == code and (path is None or f.path == path)
                and (text is None or text in f.detail) and (level is None or f.level == level)]
        self.assertTrue(hits, f"no {code} {path} {text}; got {[(f.code, f.path, f.detail) for f in res.findings]}")
        return hits[0]

    def assertNone(self, res, code, path=None):
        hits = [f for f in res.findings if f.code == code and (path is None or f.path == path)]
        self.assertFalse(hits, f"unexpected {[(f.code, f.path, f.detail) for f in hits]}")

    def run_cli(self, *args, root=True):
        argv = ["lint"] + (["--root", str(self.root)] if root else []) + list(args)
        out, err = io.StringIO(), io.StringIO()
        real_now = kb._now
        kb._now = lambda: NOW
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    rc = kb.main(argv)
                except SystemExit as exc:
                    rc = exc.code
        finally:
            kb._now = real_now
        return rc, out.getvalue(), err.getvalue()


class CleanVaults(VaultCase):
    def test_empty_scaffold_is_clean(self):
        for rel in ["inbox/.gitkeep", "sources/.gitkeep", "notes/.gitkeep", "projects/.gitkeep"]:
            self.put(rel, b"")
        self.put("index.md", doc("# Index\n", type="topic", created="2026-11-25", updated="2026-11-25"))
        self.put(".DS_Store", b"x")
        res = self.lint()
        self.assertEqual(res.findings, [])
        self.assertEqual(self.run_cli()[0], 0)

    def test_valid_notes_clean_and_exit_0(self):
        self.put("notes/A.md", doc("# T\nSee [[B]]\n"))
        self.put("notes/B.md", doc("See [[A#T]]\n"))
        self.assertEqual(self.lint().findings, [])
        self.assertEqual(self.run_cli()[0], 0)

    def test_vault_without_inbox_or_processed_lints_cleanly(self):
        self.put("sources/s.md", src())
        self.assertEqual(self.m2(self.lint()), [])

    def test_hidden_files_in_every_folder_raise_nothing(self):
        for rel in ["notes/.gitkeep", "notes/.DS_Store", "sources/.gitkeep", "projects/.gitkeep", "inbox/.gitkeep"]:
            self.put(rel, b"")
        self.assertEqual(self.lint().findings, [])

    def test_lint_never_modifies_files(self):
        self.put("notes/A.md", doc("[[Missing]]\n"))
        self.put("notes/B.md", "no frontmatter")
        self.put("sources/x.pdf", b"%PDF")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.lint()
        self.run_cli("--json")
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class E01(VaultCase):
    def test_malformed_frontmatter(self):
        self.put("notes/A.md", "---\ntype: note\ntype: topic\n---\nbody")
        res = self.lint()
        f = self.assertHas(res, "E01", "notes/A.md", level="ERROR")
        self.assertEqual(f.line, 3)
        self.assertNotIn("line 3", f.detail)  # no line number in detail, so ids survive edits
        self.assertEqual(self.run_cli()[0], 1)

    def test_unterminated_is_e01_and_exit_1(self):
        self.put("notes/A.md", "---\ntype: note\nnever closes\n")
        self.assertHas(self.lint(), "E01", "notes/A.md", "unterminated")

    def test_empty_block_is_e02_not_e01(self):
        self.put("notes/A.md", "---\n---\nbody")
        res = self.lint()
        self.assertNone(res, "E01")
        self.assertHas(res, "E02", "notes/A.md", "missing type")

    def test_inbox_exempt(self):
        self.put("inbox/c.md", "---\ntype: note\ntype: topic\n---\n")
        self.put("inbox/d.md", "---\nunterminated")
        res = self.lint()
        self.assertNone(res, "E01")
        self.assertNone(res, "E02")
        self.assertEqual(self.run_cli()[0], 0)

    def test_source_bad_frontmatter_also_e01(self):
        self.put("sources/s.md", "---\ntype: source\nbad line\n---\n")
        self.assertHas(self.lint(), "E01", "sources/s.md")


class E02(VaultCase):
    def check(self, content, text, path="notes/A.md"):
        self.put(path, content)
        res = self.lint()
        self.assertHas(res, "E02", path, text, level="ERROR")
        self.assertEqual(self.run_cli()[0], 1)
        return res

    def test_missing_type(self):
        self.check(doc(type=None), "missing type")

    def test_unsupported_type(self):
        self.check(doc(type="journal"), "unsupported type")

    def test_empty_type_value(self):
        self.check(doc(type=""), "missing type")

    def test_missing_created(self):
        self.check(doc(created=None), "missing created")

    def test_bad_created(self):
        self.check(doc(created="2026-13-40"), "bad created date")
        self.check(doc(created="yesterday"), "bad created date")

    def test_missing_updated(self):
        self.check(doc(updated=None), "missing updated")

    def test_bad_updated(self):
        self.check(doc(updated="2026-02-30"), "bad updated date")

    def test_standalone_must_be_boolean(self):
        self.check(doc(standalone="yes"), "standalone")
        self.put("notes/ok.md", doc(standalone="true"))
        self.put("notes/ok2.md", doc(standalone="false"))
        self.assertNone(self.lint(), "E02", "notes/ok.md")
        self.assertNone(self.lint(), "E02", "notes/ok2.md")

    def test_bad_confidence(self):
        self.check(doc(confidence="certain"), "confidence")
        for good in ["shaky", "ok", "solid"]:
            self.put("notes/g%s.md" % good, doc(confidence=good))
        self.assertEqual([f for f in self.m2(self.lint()) if f.path.startswith("notes/g")], [])

    def test_source_missing_sha256(self):
        self.check(src(sha256=None), "missing sha256", "sources/s.md")

    def test_source_bad_sha256_format(self):
        self.check(src(sha256="ABC"), "64 lowercase hex", "sources/s.md")
        self.check(src(sha256="A" * 64), "64 lowercase hex", "sources/s.md")

    def test_source_missing_original(self):
        self.check(src(original=None), "missing original", "sources/s.md")

    def test_each_condition_is_separate(self):
        self.put("notes/A.md", doc(type=None, created=None, updated=None))
        details = sorted(d for c, p, d in self.found(self.lint(), "E02"))
        self.assertEqual(details, ["missing created", "missing type", "missing updated"])

    def test_inbox_exempt(self):
        self.put("inbox/c.md", "---\ntype: bogus\n---\nbody")
        self.assertNone(self.lint(), "E02")

    def test_non_source_needs_no_sha_or_original(self):
        self.put("notes/A.md", doc())
        self.assertNone(self.lint(), "E02")

    def test_original_accepted(self):
        names = ["2026-11-25-notes.md", "v1..2.pdf", "a...b.md", "..foo", "\u65e5\u672c\u8a9e \u30ce\u30fc\u30c8.md",
                 "a" * 252 + ".md", "e\u0301.md", "caf\u00e9.md", 'has # hash and "quote".md']
        for i, name in enumerate(names):
            self.put("sources/s%d.md" % i, src(original=q(name)))
        res = self.lint()
        self.assertNone(res, "E02")

    def test_original_rejected(self):
        names = ["", ".", "..", "a/b", "a" + chr(92) + "b", "/abs", "C:x", "a:b", "x.", "x ", " x", "\u3000x",
                 "ctl" + chr(1) + "x", "x\u202e", "x\u2066", "a" * 253 + ".md", "\u65e5" * 90]
        for i, name in enumerate(names):
            p = "sources/s%d.md" % i
            self.put(p, src(original=q(name)))
            self.assertHas(self.lint(), "E02", p, "original violates basename rule")

    def test_quoted_original_with_hash_and_escape_parses(self):
        self.put("sources/s.md", src(original=q('a #b "c".md')))
        self.assertNone(self.lint(), "E02")


class E03(VaultCase):
    def test_updated_before_created(self):
        self.put("notes/A.md", doc(created="2026-05-02", updated="2026-05-01"))
        self.assertHas(self.lint(), "E03", "notes/A.md", level="ERROR")

    def test_equal_dates_ok_and_bad_dates_do_not_double_report(self):
        self.put("notes/A.md", doc(created="2026-05-02", updated="2026-05-02"))
        self.put("notes/B.md", doc(created="2026-05-02", updated="nonsense"))
        res = self.lint()
        self.assertNone(res, "E03")


class W10W11(VaultCase):
    def test_missing_frontmatter_is_warning_exit_0(self):
        self.put("notes/A.md", "# Just text\n[[B]]\n")
        self.put("notes/B.md", doc())
        res = self.lint()
        self.assertHas(res, "W10", "notes/A.md", level="WARNING")
        self.assertNone(res, "E02")
        self.assertEqual(self.run_cli()[0], 0)

    def test_links_still_checked_without_frontmatter(self):
        self.put("notes/A.md", "[[Missing]]")
        res = self.lint()
        self.assertHas(res, "W10", "notes/A.md")
        self.assertHas(res, "E04", "notes/A.md")

    def test_w10_not_in_inbox_and_not_for_binaries(self):
        self.put("inbox/c.md", "raw")
        self.put("sources/x.pdf", b"%PDF-1.4")
        self.put("sources/x.png", b"\x89PNG")
        self.assertEqual(self.m2(self.lint()), [])

    def test_index_without_frontmatter_warns(self):
        self.put("index.md", "# Index\n")
        self.assertHas(self.lint(), "W10", "index.md")

    def test_non_utf8_md_gives_w11_not_crash(self):
        self.put("notes/A.md", b"caf" + bytes([0xe9]) + b" [[Missing]]")
        self.put("inbox/c.md", b"caf" + bytes([0xe9]))
        res = self.lint()
        self.assertHas(res, "W11", "notes/A.md", level="WARNING")
        self.assertHas(res, "W11", "inbox/c.md", level="WARNING")
        self.assertNone(res, "E04")
        self.assertNone(res, "W10")
        self.assertEqual(self.run_cli()[0], 0)

    def test_non_utf8_txt_and_pdf_no_w11(self):
        self.put("inbox/c.txt", b"caf" + bytes([0xe9]))
        self.put("sources/x.pdf", bytes([0xff, 0xfe, 0x00]))
        self.assertEqual(self.m2(self.lint()), [])

    def test_bom_utf8_is_fine(self):
        self.put("notes/A.md", bytes([0xef, 0xbb, 0xbf]) + doc().encode())
        self.assertEqual(self.m2(self.lint()), [])


class E04(VaultCase):
    def test_missing_target(self):
        self.put("notes/A.md", doc("[[Nope]]\n"))
        f = self.assertHas(self.lint(), "E04", "notes/A.md", "Nope", level="ERROR")
        self.assertEqual(f.line, 6)
        self.assertEqual(self.run_cli()[0], 1)

    def test_embed_missing(self):
        self.put("notes/A.md", doc("![[img.png]]\n"))
        self.assertHas(self.lint(), "E04", "notes/A.md", "img.png")

    def test_resolves_by_basename_case_and_nfc_insensitive(self):
        self.put("notes/Caf\u00e9 Au Lait.md", doc())
        self.put("notes/A.md", doc("[[cafe\u0301 au lait]] [[CAF\u00c9 AU LAIT.md]]\n"))
        self.assertEqual(self.m2(self.lint()), [])

    def test_resolves_path_forms_and_non_markdown(self):
        self.put("sources/X.pdf", b"%PDF")
        self.put("projects/P/P.md", doc("# P\n"))
        self.put("notes/A.md", doc("[[sources/X.pdf]] ![[x.PDF#page=2]] [[X.pdf|text]] [[projects/P/P]] [[P/P]]\n"))
        self.assertEqual(self.m2(self.lint()), [])

    def test_ambiguous(self):
        self.put("notes/Dup.md", doc())
        self.put("projects/Q/Dup.md", doc())
        self.put("notes/A.md", doc("[[Dup]]\n"))
        res = self.lint()
        self.assertHas(res, "E04", "notes/A.md", "ambiguous")
        self.assertHas(res, "E06")

    def test_path_disambiguates(self):
        self.put("notes/Dup.md", doc())
        self.put("projects/Q/Dup.md", doc())
        self.put("notes/A.md", doc("[[notes/Dup]] [[Q/Dup]]\n"))
        res = self.lint()
        self.assertNone(res, "E04")

    def test_alias_only_match_is_error(self):
        self.put("notes/Real.md", doc(aliases="[Nick]"))
        self.put("notes/A.md", doc("[[Nick]]\n"))
        self.assertHas(self.lint(), "E04", "notes/A.md", "alias")

    def test_frontmatter_links_checked(self):
        self.put("notes/A.md", doc(sources='["[[Gone]]"]'))
        f = self.assertHas(self.lint(), "E04", "notes/A.md", "Gone")
        self.assertEqual(f.line, 5)

    def test_code_and_standard_links_ignored(self):
        body = TICK + "[[Nope]]" + TICK + " and [x](y.md)\n" + F3 + "\n[[Nope2]]\n" + F3 + "\n"
        self.put("notes/A.md", doc(body))
        self.assertNone(self.lint(), "E04")

    def test_self_link(self):
        self.put("notes/A.md", doc("# Top\n[[#Top]] [[A#top]]\n"))
        self.assertEqual(self.m2(self.lint()), [])

    def test_inbox_links_are_exempt_by_approval(self):
        self.put("inbox/c.md", "[[Nope]]")
        self.assertNone(self.lint(), "E04", "inbox/c.md")

    def test_inbox_files_are_not_link_targets(self):
        self.put("inbox/Target.md", "x")
        self.put("notes/A.md", doc("[[Target]]\n"))
        self.assertHas(self.lint(), "E04", "notes/A.md")


class SourceBodies(VaultCase):
    def test_verbatim_body_exempt_for_e04_e05(self):
        self.put("notes/N.md", doc("# H\n"))
        self.put("sources/s.md", src("[[missing]] and [[N#Nope]] and ![[x.png]]\n"))
        res = self.lint()
        self.assertNone(res, "E04")
        self.assertNone(res, "E05")

    def test_frontmatter_link_in_source_is_checked(self):
        self.put("sources/s.md", src("body\n", url='"x"', related='"[[Gone]]"'))
        self.assertHas(self.lint(), "E04", "sources/s.md", "Gone")

    def test_source_without_frontmatter_body_exempt(self):
        self.put("sources/s.md", "[[missing]]\n")
        res = self.lint()
        self.assertNone(res, "E04")
        self.assertHas(res, "W10", "sources/s.md")


class E05(VaultCase):
    def test_missing_heading(self):
        self.put("notes/B.md", doc("# One\n"))
        self.put("notes/A.md", doc("[[B#Two]]\n"))
        self.assertHas(self.lint(), "E05", "notes/A.md", "Two", level="ERROR")

    def test_heading_found_case_and_whitespace_insensitive(self):
        self.put("notes/B.md", doc("## Page   Object Model\n"))
        self.put("notes/A.md", doc("[[B#page object model]]\n"))
        self.assertNone(self.lint(), "E05")

    def test_heading_in_code_is_not_a_heading(self):
        self.put("notes/B.md", doc(F3 + "\n# Fake\n" + F3 + "\n"))
        self.put("notes/A.md", doc("[[B#Fake]]\n"))
        self.assertHas(self.lint(), "E05", "notes/A.md")

    def test_non_markdown_target_anchor_not_validated(self):
        self.put("sources/X.pdf", b"%PDF")
        self.put("notes/A.md", doc("[[X.pdf#page=3]]\n"))
        self.assertEqual(self.m2(self.lint()), [])

    def test_block_reference_not_error(self):
        self.put("notes/B.md", doc("text ^abc\n"))
        self.put("notes/A.md", doc("[[B#^abc]] [[B#^zzz]]\n"))
        self.assertNone(self.lint(), "E05")

    def test_target_not_found_gives_only_e04(self):
        self.put("notes/A.md", doc("[[Gone#H]]\n"))
        res = self.lint()
        self.assertHas(res, "E04")
        self.assertNone(res, "E05")


class E06(VaultCase):
    def test_duplicate_basenames(self):
        self.put("notes/Same.md", doc())
        self.put("projects/P/same.md", doc())
        res = self.lint()
        self.assertHas(res, "E06", "notes/Same.md")
        self.assertHas(res, "E06", "projects/P/same.md")

    def test_nfc_duplicates(self):
        self.put("notes/caf\u00e9.md", doc())
        self.put("projects/cafe\u0301.md", doc())
        self.assertEqual(len(self.found(self.lint(), "E06")), 2)

    def test_markdown_and_binary_with_same_stem_do_not_collide(self):
        self.put("sources/Foo.pdf", b"%PDF")
        self.put("notes/Foo.md", doc())
        self.assertNone(self.lint(), "E06")

    def test_binary_duplicates_by_full_filename(self):
        self.put("sources/Foo.pdf", b"%PDF")
        self.put("notes/foo.PDF", b"%PDF")
        self.assertEqual(len(self.found(self.lint(), "E06")), 2)

    def test_forbidden_characters(self):
        for i, ch in enumerate("#^[]|"):
            self.put("notes/bad%dx%sy.md" % (i, ch), doc())
        res = self.lint()
        self.assertEqual(len(self.found(res, "E06")), 5)

    def test_inbox_exempt(self):
        self.put("inbox/Same.md", "x")
        self.put("inbox/sub/Same.md", "x")
        self.put("notes/Same.md", doc())
        self.put("inbox/a#b.md", "x")
        self.assertNone(self.lint(), "E06")


class E08Companion(VaultCase):
    def binary(self, name="guide.pdf", data=b"%PDF-1.7 hello"):
        self.put("sources/" + name, data)
        return hashlib.sha256(data).hexdigest()

    def test_passes_with_matching_hash_and_without_processed_dir(self):
        sha = self.binary()
        self.put("sources/guide.md", src("![[guide.pdf]]\n", sha256=sha, original=q("guide.pdf")))
        self.assertEqual(self.m2(self.lint()), [])

    def test_missing_binary(self):
        self.put("sources/guide.md", src("body\n", original=q("guide.pdf")))
        self.assertHas(self.lint(), "E08", "sources/guide.md", "not found", level="ERROR")

    def test_hash_mismatch(self):
        self.binary()
        self.put("sources/guide.md", src("body\n", sha256="b" * 64, original=q("guide.pdf")))
        self.assertHas(self.lint(), "E08", "sources/guide.md", "sha256 mismatch")

    def test_extension_compared_case_insensitively(self):
        sha = self.binary("Guide.PDF")
        self.put("sources/g.md", src(sha256=sha, original=q("guide.pdf")))
        self.assertEqual(self.m2(self.lint()), [])
        self.put("sources/h.md", src(original=q("missing.PDF")))
        self.assertHas(self.lint(), "E08", "sources/h.md")

    def test_text_source_is_not_a_companion(self):
        self.put("sources/a.md", src(original=q("2026-11-25-a.md")))
        self.put("sources/b.md", src(original=q("2026-11-25-b.txt")))
        self.put("sources/c.md", src(original=q("x-1a2b3c4d.md")))
        self.assertEqual(self.m2(self.lint()), [])

    def test_txt_original_naming_an_existing_binary_is_a_companion(self):
        data = bytes([0xff, 0xfe, 0x41])
        sha = self.binary("notes.txt", data)
        self.put("sources/n.md", src(sha256=sha, original=q("notes.txt")))
        self.assertEqual(self.m2(self.lint()), [])
        self.put("sources/m.md", src(sha256="c" * 64, original=q("notes.txt")))
        self.assertHas(self.lint(), "E08", "sources/m.md", "sha256 mismatch")

    def test_extensionless_original_is_a_companion_shape(self):
        self.put("sources/n.md", src(original=q("README")))
        self.assertHas(self.lint(), "E08", "sources/n.md")

    def test_invalid_original_touches_nothing_outside_sources(self):
        (self.base / "x").write_bytes(b"decoy")
        self.put("sources/s.md", src(original=q("../x")))
        res = self.lint()
        self.assertHas(res, "E02", "sources/s.md", "basename")
        self.assertNone(res, "E08")

    def test_decoy_never_read(self):
        decoy = self.base / "decoy.pdf"
        decoy.write_bytes(b"%PDF")
        os.chmod(decoy, 0)
        self.addCleanup(lambda: os.chmod(decoy, 0o644))
        self.put("sources/s.md", src(original=q("../decoy.pdf")))
        self.lint()

    def test_matching_is_nfc_and_case_insensitive(self):
        sha = self.binary("Caf\u00e9.pdf")
        self.put("sources/c.md", src(sha256=sha, original=q("CAFE\u0301.pdf")))
        self.assertEqual(self.m2(self.lint()), [])

    def test_text_source_with_missing_original_file_raises_nothing(self):
        self.put("sources/a.md", src(original=q("2026-11-25-a.md")))
        self.assertEqual(self.m2(self.lint()), [])

    def test_companion_without_sha256_is_e02_only(self):
        self.binary()
        self.put("sources/guide.md", src(sha256=None, original=q("guide.pdf")))
        res = self.lint()
        self.assertHas(res, "E02", "sources/guide.md", "missing sha256")
        self.assertNone(res, "E08")

    def test_binary_source_without_frontmatter_exempt(self):
        self.binary()
        self.assertEqual(self.m2(self.lint()), [])


class Pending(VaultCase):
    def notes(self):
        self.put("notes/A.md", doc("[[X.pdf]] ![[X.pdf]] [[X.pdf#page=2]] [[X.pdf|text]] [[sources/X.pdf]] [[x.PDF]]\n"))
        self.put("notes/B.md", doc("See [[X.pdf]]\n"))

    def test_without_flag_all_forms_are_errors(self):
        self.notes()
        self.assertEqual(len(self.found(self.lint(), "E04", "ERROR")), 7)

    def test_every_link_form_becomes_pending(self):
        self.notes()
        res = self.lint(pending="X.pdf")
        self.assertEqual(self.found(res, level="ERROR"), [])
        self.assertEqual(len(self.found(res, "E04", "PENDING")), 7)
        self.assertEqual(res.pending_targets, ["X.pdf"])
        self.assertEqual(self.run_cli("--pending", "X.pdf")[0], 0)

    def test_pending_name_case_insensitive(self):
        self.notes()
        self.assertEqual(self.found(self.lint(pending="x.PDF"), level="ERROR"), [])

    def test_unrelated_targets_stay_errors(self):
        self.notes()
        self.put("notes/C.md", doc("[[Other.pdf]] [[Nope]]\n"))
        res = self.lint(pending="X.pdf")
        self.assertEqual(len(self.found(res, "E04", "ERROR")), 2)

    def test_companion_e08_becomes_pending(self):
        self.put("sources/x.md", src("![[X.pdf]]\n", original=q("X.pdf")))
        self.notes()
        res = self.lint(pending="X.pdf")
        self.assertEqual(self.found(res, level="ERROR"), [])
        self.assertTrue(self.found(res, "E08", "PENDING"))
        self.assertEqual(res.pending_targets, ["X.pdf"])

    def test_companion_for_other_file_stays_error(self):
        self.put("sources/y.md", src("body\n", original=q("Y.pdf")))
        res = self.lint(pending="X.pdf")
        self.assertHas(res, "E08", "sources/y.md", level="ERROR")

    def test_existing_file_means_nothing_pending(self):
        self.put("sources/X.pdf", b"%PDF")
        self.notes()
        res = self.lint(pending="X.pdf")
        self.assertEqual(self.m2(res), [])
        self.assertEqual(res.pending_targets, [])

    def test_txt_name_accepted(self):
        self.put("notes/A.md", doc("[[x.txt]]\n"))
        res = self.lint(pending="x.txt")
        self.assertEqual(self.found(res, level="ERROR"), [])

    def test_invalid_pending_names_exit_2(self):
        for bad in ["Foo", "Foo.md", "Foo.MD", ".hidden", "a/b.pdf", "x.pdf ", ""]:
            rc, out, err = self.run_cli("--pending", bad)
            self.assertEqual(rc, 2, bad)

    def test_second_pending_exits_2(self):
        self.assertEqual(self.run_cli("--pending", "a.pdf", "--pending", "b.pdf")[0], 2)

    def test_pending_does_not_hide_ambiguity(self):
        self.put("notes/X.pdf", b"%PDF")
        self.put("sources/X.pdf", b"%PDF")
        self.put("notes/A.md", doc("[[X.pdf]]\n"))
        res = self.lint(pending="X.pdf")
        self.assertHas(res, "E04", "notes/A.md", "ambiguous", level="ERROR")


class Levels(VaultCase):
    def test_json_shape_and_levels_separate(self):
        self.put("notes/A.md", doc("[[Nope]] [[Later.pdf]]\n", standalone="true"))
        self.put("notes/B.md", "plain")
        rc, out, err = self.run_cli("--json", "--pending", "Later.pdf")
        self.assertEqual(rc, 1)
        data = json.loads(out)
        self.assertEqual(sorted(data["counts"]), ["ERROR", "PENDING", "REVIEW", "WARNING"])
        self.assertEqual(data["counts"], {"ERROR": 1, "WARNING": 2, "REVIEW": 0, "PENDING": 1})
        for f in data["findings"]:
            self.assertEqual(sorted(f), ["code", "detail", "id", "level", "line", "path"])
            self.assertTrue(f["id"].startswith(f["code"] + "|" + f["path"] + "|"))
        self.assertEqual(data["pending_targets"], ["Later.pdf"])

    def test_text_output_groups_by_level(self):
        self.put("notes/A.md", doc("[[Nope]]\n"))
        self.put("notes/B.md", "plain")
        rc, out, err = self.run_cli()
        self.assertEqual(rc, 1)
        self.assertLess(out.index("ERROR"), out.index("WARNING"))
        self.assertIn("E04", out)
        self.assertIn("W10", out)

    def test_warnings_only_exit_0(self):
        self.put("notes/B.md", "plain")
        self.assertEqual(self.run_cli()[0], 0)

    def test_pending_level_only_with_flag(self):
        self.put("notes/A.md", doc("[[Later.pdf]]\n", standalone="true"))
        self.assertEqual(self.lint().findings[0].level, "ERROR")
        self.assertEqual(self.lint(pending="Later.pdf").findings[0].level, "PENDING")


class Ids(VaultCase):
    def test_second_identical_problem_gets_new_id_and_ids_survive_line_shifts(self):
        self.put("notes/A.md", doc("[[Nope]]\n\n[[Nope]]\n", standalone="true"))
        ids1 = [f.id for f in self.lint().findings]
        self.assertEqual(len(ids1), 2)
        self.assertEqual(len(set(ids1)), 2)
        self.put("notes/A.md", doc("intro\nmore\n[[Nope]]\n\n\n[[Nope]]\n", standalone="true"))
        self.assertEqual([f.id for f in self.lint().findings], ids1)


class ExitCodes(VaultCase):
    def test_non_vault_root_exit_2(self):
        empty = self.base / "empty"
        empty.mkdir()
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            rc = kb.main(["lint", "--root", str(empty)])
        self.assertEqual(rc, 2)

    def test_missing_root_exit_2(self):
        rc = self.run_cli("--root", str(self.base / "nope"), root=False)[0]
        self.assertEqual(rc, 2)

    def test_root_is_a_file_exit_2(self):
        f = self.base / "afile"
        f.write_text("x")
        self.assertEqual(self.run_cli("--root", str(f), root=False)[0], 2)

    def test_bad_flags_exit_2(self):
        self.assertEqual(self.run_cli("--nonsense")[0], 2)
        self.assertEqual(self.run_cli("--pending")[0], 2)

    def test_no_subcommand_exit_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                rc = kb.main([])
            except SystemExit as exc:
                rc = exc.code
        self.assertEqual(rc, 2)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read anything")
    def test_unreadable_file_is_exit_2_not_a_crash(self):
        p = self.put("notes/A.md", doc())
        os.chmod(p, 0)
        self.addCleanup(lambda: os.chmod(p, 0o644))
        self.assertEqual(self.run_cli()[0], 2)

    def test_internal_error_exit_2_without_traceback_content(self):
        self.put("notes/A.md", doc())
        original = kb.lint
        def boom(*a, **k):
            raise RuntimeError("SECRET-VALUE")
        kb.lint = boom
        try:
            rc, out, err = self.run_cli()
        finally:
            kb.lint = original
        self.assertEqual(rc, 2)
        self.assertNotIn("SECRET-VALUE", out + err)

    def test_default_root_is_parent_of_scripts(self):
        self.assertEqual(kb.default_root(), Path(kb.__file__).resolve().parent.parent)

    def test_runs_as_a_script(self):
        import subprocess
        self.put("notes/A.md", doc())
        script = Path(kb.__file__).resolve()
        r = subprocess.run([sys.executable, "-B", str(script), "lint", "--root", str(self.root)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


# ======================================================================== M3: warnings, review items, secrets

NOW = datetime.datetime(2026, 11, 25, 12, 0, 0)


def fake(kind):
    """Fake secrets are assembled at run time so this file itself contains none."""
    return {
        "aws": "AKIA" + "IOSFODNN7EXAMPLE",
        "github": "gh" + "p_" + "a1B2c3D4e5" * 4,
        "slack": "xo" + "xb-" + "1234567890-abcdefghij",
        "stripe": "sk_" + "live_" + "abcdefghijklmnop1234",
        "jwt": "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcdefghijklmnopqrst",
        "private-key": "-----BEGIN RSA " + "PRIVATE KEY-----",
        "assignment": "api_key = " + "Zq8xR2mN5vB7cK9d",
    }[kind]


SECRET_KINDS = ["aws", "github", "slack", "stripe", "jwt", "private-key", "assignment"]


class InboxLinkExemption(VaultCase):
    def test_inbox_captures_never_raise_e04_or_e05(self):
        self.put("notes/Real.md", doc("# Head\n", standalone="true"))
        self.put("notes/Dup.md", doc(standalone="true"))
        self.put("projects/Q/Dup.md", doc(standalone="true"))
        self.put("notes/Aliased.md", doc(aliases="[Nick]", standalone="true"))
        self.put("inbox/c.md", "[[Missing]] ![[img.png]] [[Dup]] [[Nick]] [[Real#NoSuchHeading]] [[Gone#H]]\n")
        self.put("inbox/d.md", doc("body\n", related='"[[AlsoMissing]]"'))
        res = self.lint()
        self.assertNone(res, "E04")
        self.assertNone(res, "E05")

    def test_inbox_exempt_with_pending_too(self):
        self.put("inbox/c.md", "[[Later.pdf]]")
        res = self.lint(pending="Later.pdf")
        self.assertEqual(self.found(res, "E04"), [])
        self.assertEqual(res.pending_targets, [])

    def test_notes_and_projects_still_enforced(self):
        self.put("notes/Real.md", doc("# Head\n", standalone="true"))
        self.put("notes/Dup.md", doc(standalone="true"))
        self.put("projects/Q/Dup.md", doc(standalone="true"))
        self.put("notes/Aliased.md", doc(aliases="[Nick]", standalone="true"))
        self.put("notes/A.md", doc("[[Missing]] [[Dup]] [[Nick]] [[Real#NoSuchHeading]]\n", standalone="true"))
        self.put("projects/P/P.md", doc("[[Missing2]]\n", type="project"))
        self.put("index.md", doc("[[Missing3]]\n", type="topic"))
        res = self.lint()
        self.assertHas(res, "E04", "notes/A.md", "Missing")
        self.assertHas(res, "E04", "notes/A.md", "ambiguous")
        self.assertHas(res, "E04", "notes/A.md", "alias")
        self.assertHas(res, "E05", "notes/A.md", "NoSuchHeading")
        self.assertHas(res, "E04", "projects/P/P.md", "Missing2")
        self.assertHas(res, "E04", "index.md", "Missing3")

    def test_source_body_exemption_unchanged(self):
        self.put("sources/s.md", src("[[missing]] [[N#Nope]]\n"))
        self.put("sources/t.md", src("body\n", related='"[[Gone]]"'))
        res = self.lint()
        self.assertNone(res, "E04", "sources/s.md")
        self.assertHas(res, "E04", "sources/t.md", "Gone")

    def test_inbox_still_reports_other_rules(self):
        self.put("inbox/a.md", b"caf" + bytes([0xe9]))
        self.assertHas(self.lint(), "W11", "inbox/a.md")


class SecretScan(VaultCase):
    def test_scan_text_reports_line_and_pattern_name_only(self):
        for kind in SECRET_KINDS:
            hits = kb.scan_text("harmless\nprefix " + fake(kind) + " suffix\n")
            self.assertEqual([line for line, name in hits], [2], kind)
            self.assertTrue(all(isinstance(name, str) and fake(kind) not in name for line, name in hits), kind)

    def test_each_pattern_in_a_knowledge_note_is_e07(self):
        for kind in SECRET_KINDS:
            with self.subTest(kind):
                self.put("notes/A.md", doc("line\n" + fake(kind) + "\n", standalone="true"))
                res = self.lint()
                f = self.assertHas(res, "E07", "notes/A.md", "possible secret", level="ERROR")
                self.assertEqual(f.line, 8)
                self.assertEqual(self.run_cli()[0], 1)

    def test_each_pattern_in_a_capture_is_w07_warning(self):
        for kind in SECRET_KINDS:
            with self.subTest(kind):
                self.put("inbox/c.md", "x\n" + fake(kind) + "\n")
                res = self.lint()
                f = self.assertHas(res, "W07", "inbox/c.md", "possible secret", level="WARNING")
                self.assertEqual(f.line, 2)
                self.assertNone(res, "E07")
                self.assertEqual(self.run_cli()[0], 0)

    def test_json_and_csv_captures_and_other_text_files(self):
        self.put("inbox/c.json", '{"k": "' + fake("aws") + '"}')
        self.put("inbox/d.csv", "a,b\n1," + fake("github") + "\n")
        self.put("inbox/e.txt", fake("slack"))
        self.put("inbox/sub/f.html", "<p>" + fake("stripe") + "</p>")
        res = self.lint()
        for p in ["inbox/c.json", "inbox/d.csv", "inbox/e.txt", "inbox/sub/f.html"]:
            self.assertHas(res, "W07", p)

    def test_non_markdown_file_in_sources_is_e07(self):
        self.put("sources/data.json", '{"k": "' + fake("aws") + '"}')
        self.assertHas(self.lint(), "E07", "sources/data.json", level="ERROR")

    def test_processed_originals_are_scanned_as_w07(self):
        self.put("inbox/processed/2026-11-25-a.md", "x " + fake("jwt"))
        res = self.lint()
        self.assertHas(res, "W07", "inbox/processed/2026-11-25-a.md", level="WARNING")
        self.assertNone(res, "E07")
        self.assertEqual(self.run_cli()[0], 0)

    def test_processed_is_not_otherwise_linted(self):
        self.put("inbox/processed/old.md", "---\nbroken\n---\n[[Nope]]\n")
        self.assertEqual(self.lint().findings, [])

    def test_undecodable_files_are_not_scanned(self):
        self.put("inbox/c.bin", fake("aws").encode() + bytes([0xff, 0xfe]))
        self.put("inbox/d.md", fake("aws").encode() + bytes([0xe9]))
        self.put("sources/x.pdf", b"%PDF " + fake("github").encode() + bytes([0xff]))
        res = self.lint()
        self.assertNone(res, "W07")
        self.assertNone(res, "E07")

    def test_benign_text_is_not_flagged(self):
        text = "password: hunter2\nthe token is short\napi_key = abc\nsha256: " + "a" * 64 + "\nAKIA is a prefix\n"
        self.put("notes/A.md", doc(text, standalone="true"))
        res = self.lint()
        self.assertNone(res, "E07")

    def test_secret_never_appears_in_any_output(self):
        secret = fake("aws")
        self.put("notes/A.md", doc("x " + secret + "\n", standalone="true"))
        self.put("inbox/c.md", "y " + secret + "\n")
        self.put("inbox/processed/p.md", secret)
        self.put("sources/d.json", secret)
        res = self.lint()
        self.assertNotIn(secret, repr(res.findings))
        for args in ([], ["--json"]):
            rc, out, err = self.run_cli(*args)
            self.assertNotIn(secret, out + err)
            self.assertNotIn(secret[4:], out + err)

    def test_secret_never_appears_in_a_forced_failure(self):
        secret = fake("github")
        self.put("inbox/c.md", secret)
        original = kb.scan_text

        def boom(text):
            raise ValueError(text)

        kb.scan_text = boom
        try:
            rc, out, err = self.run_cli()
        finally:
            kb.scan_text = original
        self.assertEqual(rc, 2)
        self.assertNotIn(secret, out + err)

    def test_ids_have_no_line_number(self):
        self.put("inbox/c.md", "a\n" + fake("aws") + "\n")
        first = self.lint().findings[0].id
        self.put("inbox/c.md", "a\nb\nc\n" + fake("aws") + "\n")
        self.assertEqual(self.lint().findings[0].id, first)

    def test_nothing_modified_or_deleted(self):
        p = self.put("inbox/c.md", fake("aws"))
        before = p.read_bytes()
        self.lint()
        self.assertEqual(p.read_bytes(), before)


class W01Orphans(VaultCase):
    def test_orphan_note_flagged_and_linked_note_not(self):
        self.put("notes/Orphan.md", doc("x\n"))
        self.put("notes/Linked.md", doc("x\n"))
        self.put("notes/Hub.md", doc("[[Linked]]\n", type="topic"))
        res = self.lint()
        self.assertHas(res, "W01", "notes/Orphan.md", level="WARNING")
        self.assertNone(res, "W01", "notes/Linked.md")
        self.assertEqual(self.run_cli()[0], 0)

    def test_exemptions(self):
        self.put("index.md", doc("# I\n", type="topic"))
        self.put("notes/T.md", doc(type="topic"))
        self.put("projects/P/P.md", doc(type="project"))
        self.put("notes/S.md", doc(standalone="true"))
        self.put("sources/s.md", src())
        self.assertNone(self.lint(), "W01")

    def test_unclassified_file_gets_no_type_exemption(self):
        self.put("notes/NoFm.md", "plain text\n")
        self.assertHas(self.lint(), "W01", "notes/NoFm.md")

    def test_decision_is_not_exempt(self):
        self.put("projects/P/P - choice.md", doc(type="decision"))
        self.assertHas(self.lint(), "W01", "projects/P/P - choice.md")

    def test_self_links_do_not_count(self):
        self.put("notes/A.md", doc("# H\n[[A]] [[#H]]\n"))
        self.assertHas(self.lint(), "W01", "notes/A.md")

    def test_frontmatter_links_and_embeds_and_aliases_forms_count(self):
        self.put("notes/A.md", doc())
        self.put("notes/B.md", doc(sources='["[[A]]"]'), )
        self.put("notes/C.md", doc("![[B]]\n"))
        self.put("notes/D.md", doc("[[C|alias text]] [[notes/D]]\n"))
        res = self.lint()
        self.assertNone(res, "W01", "notes/A.md")
        self.assertNone(res, "W01", "notes/B.md")
        self.assertNone(res, "W01", "notes/C.md")
        self.assertHas(res, "W01", "notes/D.md")

    def test_links_from_captures_do_not_count(self):
        self.put("notes/A.md", doc())
        self.put("inbox/c.md", "[[A]]")
        self.assertHas(self.lint(), "W01", "notes/A.md")

    def test_link_from_a_source_body_counts(self):
        self.put("notes/A.md", doc())
        self.put("sources/s.md", src("see [[A]]\n"))
        self.assertNone(self.lint(), "W01", "notes/A.md")


class W02Aliases(VaultCase):
    def test_duplicate_alias_across_files(self):
        self.put("notes/A.md", doc(aliases="[Same]", standalone="true"))
        self.put("notes/B.md", doc(aliases="[same]", standalone="true"))
        res = self.lint()
        self.assertHas(res, "W02", "notes/A.md", "duplicate alias")
        self.assertHas(res, "W02", "notes/B.md", "duplicate alias")

    def test_duplicate_alias_inside_one_file(self):
        self.put("notes/A.md", doc(aliases="[x, X]", standalone="true"))
        self.assertHas(self.lint(), "W02", "notes/A.md", "duplicate alias")

    def test_alias_equal_to_another_files_basename(self):
        self.put("notes/A.md", doc(aliases="[Other]", standalone="true"))
        self.put("notes/Other.md", doc(standalone="true"))
        res = self.lint()
        self.assertHas(res, "W02", "notes/A.md", "basename")
        self.assertNone(res, "W02", "notes/Other.md")

    def test_alias_equal_to_own_basename_is_fine_and_unique_aliases_are_fine(self):
        self.put("notes/A.md", doc(aliases="[A, Unique]", standalone="true"))
        self.assertNone(self.lint(), "W02")

    def test_alias_block_list(self):
        self.put("notes/A.md", doc(aliases="\n  - Dup", standalone="true"))
        self.put("notes/B.md", doc(aliases="\n  - Dup", standalone="true"))
        self.assertEqual(len(self.found(self.lint(), "W02")), 2)


class W03Duplicates(VaultCase):
    def test_same_body_different_frontmatter(self):
        self.put("notes/A.md", doc("Same words here.\n", standalone="true"))
        self.put("notes/B.md", doc("Same words here.\n", standalone="true", confidence="ok", tags="[x]"))
        res = self.lint()
        self.assertHas(res, "W03", "notes/A.md", level="WARNING")
        self.assertHas(res, "W03", "notes/B.md")

    def test_whitespace_is_normalized(self):
        self.put("notes/A.md", doc("Same   words\n\nhere.\n", standalone="true"))
        self.put("notes/B.md", doc("  Same words here.  \r\n", standalone="true"))
        self.assertEqual(len(self.found(self.lint(), "W03")), 2)

    def test_note_and_source_duplicate(self):
        self.put("notes/A.md", doc("Verbatim text.\n", standalone="true"))
        self.put("sources/s.md", src("Verbatim text.\n"))
        self.assertEqual(len(self.found(self.lint(), "W03")), 2)

    def test_different_bodies_and_empty_bodies_not_flagged(self):
        self.put("notes/A.md", doc("one\n", standalone="true"))
        self.put("notes/B.md", doc("two\n", standalone="true"))
        self.put("notes/C.md", doc("", standalone="true"))
        self.put("notes/D.md", doc("   \n", standalone="true"))
        self.assertNone(self.lint(), "W03")

    def test_binaries_and_inbox_ignored(self):
        self.put("sources/a.pdf", b"%PDF same")
        self.put("sources/b.pdf", b"%PDF same")
        self.put("inbox/c.md", "dup")
        self.put("notes/A.md", doc("dup\n", standalone="true"))
        self.assertNone(self.lint(), "W03")


class W04SourceOrphans(VaultCase):
    def test_unlinked_text_and_binary_sources(self):
        self.put("sources/s.md", src())
        self.put("sources/x.pdf", b"%PDF")
        res = self.lint()
        self.assertHas(res, "W04", "sources/s.md", level="WARNING")
        self.assertHas(res, "W04", "sources/x.pdf")

    def test_linked_from_knowledge_notes(self):
        self.put("sources/s.md", src())
        self.put("sources/x.pdf", b"%PDF")
        self.put("notes/A.md", doc("[[s]] [[x.pdf]]\n", standalone="true"))
        self.assertNone(self.lint(), "W04")

    def test_link_from_index_or_frontmatter_sources_counts(self):
        self.put("sources/s.md", src())
        self.put("sources/t.md", src())
        self.put("index.md", doc("[[s]]\n", type="topic"))
        self.put("notes/A.md", doc(sources='["[[t]]"]', standalone="true"))
        self.assertNone(self.lint(), "W04")

    def test_link_from_another_source_or_a_capture_does_not_count(self):
        self.put("sources/s.md", src())
        self.put("sources/guide.md", src("![[x.pdf]]\n", original='"x.pdf"', sha256="b" * 64))
        self.put("sources/x.pdf", b"%PDF")
        self.put("inbox/c.md", "[[s]]")
        res = self.lint()
        self.assertHas(res, "W04", "sources/s.md")
        self.assertHas(res, "W04", "sources/x.pdf")


class W05CaptureDuplicates(VaultCase):
    def test_text_capture_matching_a_source_hash(self):
        data = b"hello capture\n"
        sha = hashlib.sha256(data).hexdigest()
        self.put("sources/s.md", src("hello capture\n", sha256=sha))
        self.put("inbox/again.md", data)
        self.put("inbox/other.md", b"different")
        res = self.lint()
        self.assertHas(res, "W05", "inbox/again.md", "sources/s.md", level="WARNING")
        self.assertNone(res, "W05", "inbox/other.md")

    def test_binary_capture_matching_hashed_binary(self):
        data = b"%PDF-1.7 payload"
        self.put("sources/x.pdf", data)
        self.put("inbox/copy.pdf", data)
        self.assertHas(self.lint(), "W05", "inbox/copy.pdf", "sources/x.pdf")

    def test_companion_hash_also_matches(self):
        data = b"%PDF-1.7 payload"
        sha = hashlib.sha256(data).hexdigest()
        self.put("sources/g.md", src("![[g.pdf]]\n", sha256=sha, original='"g.pdf"'))
        self.put("inbox/g.pdf", data)
        self.assertEqual(len(self.found(self.lint(), "W05")), 1)

    def test_no_match_no_warning_and_processed_not_considered(self):
        self.put("inbox/processed/a.md", b"same")
        self.put("sources/s.md", src(sha256=hashlib.sha256(b"same").hexdigest()))
        self.assertNone(self.lint(), "W05")


class W06OldCaptures(VaultCase):
    def age(self, rel, days):
        p = self.put(rel, "x")
        ts = (NOW - datetime.timedelta(days=days)).timestamp()
        os.utime(p, (ts, ts))

    def test_default_14_days(self):
        self.age("inbox/old.md", 15)
        self.age("inbox/new.md", 13)
        self.age("inbox/edge.md", 14)
        res = self.lint(now=NOW)
        self.assertHas(res, "W06", "inbox/old.md", level="WARNING")
        self.assertNone(res, "W06", "inbox/new.md")
        self.assertNone(res, "W06", "inbox/edge.md")

    def test_custom_threshold(self):
        self.age("inbox/a.md", 5)
        self.assertNone(self.lint(now=NOW, inbox_days=10), "W06")
        self.assertHas(self.lint(now=NOW, inbox_days=3), "W06", "inbox/a.md")

    def test_binaries_and_nested_captures_and_exit_code(self):
        self.age("inbox/x.pdf", 40)
        self.age("inbox/sub/y.txt", 40)
        res = self.lint(now=NOW)
        self.assertHas(res, "W06", "inbox/x.pdf")
        self.assertHas(res, "W06", "inbox/sub/y.txt")
        self.assertEqual(self.run_cli("--inbox-days", "1")[0], 0)

    def test_notes_are_not_captures(self):
        p = self.put("notes/A.md", doc(standalone="true"))
        os.utime(p, (1, 1))
        self.assertNone(self.lint(now=NOW), "W06")


class W08Collisions(VaultCase):
    def test_capture_colliding_with_a_scanned_file(self):
        self.put("notes/Page Object Model.md", doc(standalone="true"))
        self.put("inbox/page object model.md", "new capture")
        res = self.lint()
        self.assertHas(res, "W08", "inbox/page object model.md", "notes/Page Object Model.md", level="WARNING")

    def test_binary_capture_collides_by_full_filename(self):
        self.put("sources/x.pdf", b"%PDF a")
        self.put("inbox/X.PDF", b"%PDF b")
        self.put("inbox/x.png", b"png")
        res = self.lint()
        self.assertHas(res, "W08", "inbox/X.PDF")
        self.assertNone(res, "W08", "inbox/x.png")

    def test_capture_stem_does_not_collide_with_a_binary(self):
        self.put("sources/Foo.pdf", b"%PDF")
        self.put("inbox/Foo.md", "x")
        self.assertNone(self.lint(), "W08")


class W09BlockRefs(VaultCase):
    def test_block_reference_warns(self):
        self.put("notes/B.md", doc("text ^abc\n", standalone="true"))
        self.put("notes/A.md", doc("[[B#^abc]]\n", standalone="true"))
        res = self.lint()
        self.assertHas(res, "W09", "notes/A.md", "^abc", level="WARNING")
        self.assertNone(res, "E05")
        self.assertEqual(self.run_cli()[0], 0)

    def test_source_bodies_and_broken_targets(self):
        self.put("sources/s.md", src("[[B#^abc]]\n"))
        self.put("notes/A.md", doc("[[Nope#^abc]]\n", standalone="true"))
        res = self.lint()
        self.assertNone(res, "W09", "sources/s.md")
        self.assertNone(res, "W09", "notes/A.md")
        self.assertHas(res, "E04", "notes/A.md")


class ReviewItems(VaultCase):
    def test_r01_for_note_topic_project_decision_never_for_source(self):
        old = "2024-01-01"
        self.put("notes/N.md", doc(created=old, updated=old, standalone="true"))
        self.put("notes/T.md", doc(type="topic", created=old, updated=old))
        self.put("projects/P/P.md", doc(type="project", created=old, updated=old))
        self.put("projects/P/P - d.md", doc(type="decision", created=old, updated=old, standalone="true"))
        self.put("sources/s.md", src(created=old, updated=old))
        res = self.lint(now=NOW)
        for p in ["notes/N.md", "notes/T.md", "projects/P/P.md", "projects/P/P - d.md"]:
            self.assertHas(res, "R01", p, level="REVIEW")
        self.assertNone(res, "R01", "sources/s.md")
        self.assertEqual(self.run_cli()[0], 0)

    def test_message_states_the_updated_rule_and_stale_means_review(self):
        self.put("notes/N.md", doc(created="2024-01-01", updated="2024-01-01", standalone="true"))
        f = self.assertHas(self.lint(now=NOW), "R01", "notes/N.md")
        self.assertIn("last knowledge-text or link change", f.detail)
        self.assertIn("needs human review", f.detail)
        self.assertIn("not obsolete", f.detail)

    def test_boundary_and_flag(self):
        d_ok = (NOW.date() - datetime.timedelta(days=365)).isoformat()
        d_old = (NOW.date() - datetime.timedelta(days=366)).isoformat()
        self.put("notes/Ok.md", doc(created=d_ok, updated=d_ok, standalone="true"))
        self.put("notes/Old.md", doc(created=d_old, updated=d_old, standalone="true"))
        res = self.lint(now=NOW)
        self.assertNone(res, "R01", "notes/Ok.md")
        self.assertHas(res, "R01", "notes/Old.md")
        self.assertHas(self.lint(now=NOW, stale_days=100), "R01", "notes/Ok.md")
        self.assertNone(self.lint(now=NOW, stale_days=400), "R01", "notes/Old.md")

    def test_no_frontmatter_or_invalid_dates_skipped(self):
        self.put("notes/A.md", "plain\n")
        self.put("notes/B.md", doc(updated="garbage", standalone="true"))
        self.assertNone(self.lint(now=NOW), "R01")

    def test_index_topic_can_be_stale(self):
        self.put("index.md", doc(type="topic", created="2020-01-01", updated="2020-01-01"))
        self.assertHas(self.lint(now=NOW), "R01", "index.md")

    def test_r02_standalone_with_inbound_links(self):
        self.put("notes/A.md", doc(standalone="true"))
        self.put("notes/B.md", doc("[[A]]\n", standalone="true"))
        self.put("notes/C.md", doc(standalone="false"))
        self.put("notes/D.md", doc("[[C]]\n", standalone="true"))
        res = self.lint()
        self.assertHas(res, "R02", "notes/A.md", level="REVIEW")
        self.assertNone(res, "R02", "notes/B.md")
        self.assertNone(res, "R02", "notes/C.md")

    def test_review_is_a_separate_level_and_never_changes_exit_code(self):
        self.put("notes/A.md", doc(created="2020-01-01", updated="2020-01-01", standalone="true"))
        rc, out, err = self.run_cli("--stale-days", "30")
        self.assertEqual(rc, 0)
        self.assertIn("REVIEW (1)", out)
        data = json.loads(self.run_cli("--json", "--stale-days", "30")[1])
        self.assertEqual(data["counts"]["REVIEW"], 1)


class FlagsAndHelp(VaultCase):
    def test_invalid_thresholds_exit_2(self):
        for args in (["--stale-days", "-1"], ["--stale-days", "abc"], ["--inbox-days", "x"], ["--inbox-days", "-5"],
                     ["--stale-days"], ["--inbox-days", "1.5"]):
            self.assertEqual(self.run_cli(*args)[0], 2, args)

    def test_valid_thresholds_accepted(self):
        self.assertEqual(self.run_cli("--stale-days", "0", "--inbox-days", "0")[0], 0)

    def test_help_documents_updated_and_stale(self):
        rc, out, err = self.run_cli("--help")
        self.assertEqual(rc, 0)
        flat = " ".join(out.split())
        self.assertIn("last knowledge-text or link change", flat)
        self.assertIn("needs human review", flat)
        self.assertIn("--stale-days", flat)
        self.assertIn("--inbox-days", flat)
        self.assertIn("never modifies", flat.lower())

    def test_thresholds_default_values(self):
        import inspect
        sig = inspect.signature(kb.lint).parameters
        self.assertEqual(sig["stale_days"].default, 365)
        self.assertEqual(sig["inbox_days"].default, 14)


class EveryRuleFires(VaultCase):
    def test_all_rules_in_one_vault(self):
        data = b"%PDF payload"
        sha = hashlib.sha256(data).hexdigest()
        self.put("notes/e01.md", "---\ntype: note\ntype: topic\n---\n")
        self.put("notes/e02.md", doc(type=None, standalone="true"))
        self.put("notes/e03.md", doc(created="2026-05-02", updated="2026-05-01", standalone="true"))
        self.put("notes/e04.md", doc("[[Nowhere]] [[e05#Nope]] [[e05#^blk]]\n", standalone="true"))
        self.put("notes/e05.md", doc("# Real\n", standalone="true"))
        self.put("notes/dup.md", doc(standalone="true"))
        self.put("projects/dup.md", doc(standalone="true"))
        self.put("notes/e07.md", doc(fake("aws") + "\n", standalone="true"))
        self.put("sources/missing.md", src(original='"gone.pdf"'))
        self.put("notes/w01.md", doc("w01 body\n"))
        self.put("notes/w02a.md", doc("alias a\n", aliases="[Twin]", standalone="true"))
        self.put("notes/w02b.md", doc("alias b\n", aliases="[Twin]", standalone="true"))
        self.put("notes/w03a.md", doc("same\n", standalone="true"))
        self.put("notes/w03b.md", doc("same\n", standalone="true"))
        self.put("sources/w04.md", src("verbatim\n", sha256=sha))
        self.put("inbox/w05.bin", data)
        self.put("sources/w05.pdf", data)
        old = self.put("inbox/w06.md", "old")
        os.utime(old, (1, 1))
        self.put("inbox/w07.md", fake("github"))
        self.put("inbox/w08.md", "collides")
        self.put("notes/w08.md", doc("w08 note\n", standalone="true"))
        self.put("notes/w10.md", "no frontmatter")
        self.put("notes/w11.md", b"caf" + bytes([0xe9]))
        self.put("notes/r01.md", doc(created="2020-01-01", updated="2020-01-01", standalone="true"))
        self.put("notes/r02.md", doc("r02\n", standalone="true"))
        self.put("notes/linker.md", doc("[[r02]]\n", standalone="true"))
        res = self.lint(now=NOW)
        fired = {f.code for f in res.findings if f.level != "PENDING"}
        expected = {"E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08", "W01", "W02", "W03", "W04", "W05",
                    "W06", "W07", "W08", "W09", "W10", "W11", "R01", "R02"}
        self.assertEqual(expected - fired, set())
        self.assertEqual(self.run_cli()[0], 1)



# ======================================================================== M4: search and backlinks

class CmdCase(VaultCase):
    def cmd(self, name, *args, root=True):
        argv = [name] + (["--root", str(self.root)] if root else []) + list(args)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = kb.main(argv)
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def search_json(self, *args):
        rc, out, err = self.cmd("search", "--json", *args)
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def paths(self, *args):
        return [h["path"] for h in self.search_json(*args)["hits"]]


class SearchBasics(CmdCase):
    def test_case_insensitive_and_nfc(self):
        self.put("notes/Caf\u00e9.md", doc("Body text\n", standalone="true"))
        self.assertEqual(self.paths("CAFE\u0301"), ["notes/Caf\u00e9.md"])
        self.assertEqual(self.paths("caf\u00c9"), ["notes/Caf\u00e9.md"])

    def test_ranking_title_alias_tag_heading_body_frontmatter(self):
        self.put("notes/zeta body.md", doc("mentions widget in the body\n", standalone="true"))
        self.put("notes/y heading.md", doc("## Widget details\ntext\n", standalone="true"))
        self.put("notes/x tag.md", doc("nothing\n", standalone="true", tags="[widget]"))
        self.put("notes/w alias.md", doc("nothing\n", standalone="true", aliases="[Widget]"))
        self.put("notes/Widget.md", doc("nothing\n", standalone="true"))
        self.put("notes/v fm.md", doc("nothing\n", standalone="true", project="widget"))
        hits = self.search_json("widget")["hits"]
        fields = {h["path"]: h["field"] for h in hits}
        self.assertEqual(fields["notes/Widget.md"], "title")
        self.assertEqual(fields["notes/w alias.md"], "alias")
        self.assertEqual(fields["notes/x tag.md"], "tag")
        self.assertEqual(fields["notes/y heading.md"], "heading")
        self.assertEqual(fields["notes/zeta body.md"], "body")
        self.assertEqual(fields["notes/v fm.md"], "frontmatter")
        order = [h["path"] for h in hits]
        for better, worse in [("notes/Widget.md", "notes/w alias.md"), ("notes/w alias.md", "notes/x tag.md"),
                              ("notes/x tag.md", "notes/y heading.md"), ("notes/y heading.md", "notes/zeta body.md")]:
            self.assertLess(order.index(better), order.index(worse), (better, worse))

    def test_title_ranks_above_body(self):
        self.put("notes/A.md", doc("playwright is mentioned here\n", standalone="true"))
        self.put("notes/Playwright.md", doc("unrelated\n", standalone="true"))
        self.assertEqual(self.paths("playwright"), ["notes/Playwright.md", "notes/A.md"])

    def test_all_terms_must_match(self):
        self.put("notes/A.md", doc("alpha and beta\n", standalone="true"))
        self.put("notes/B.md", doc("alpha only\n", standalone="true"))
        self.put("notes/C.md", doc("beta in body\n", standalone="true", tags="[alpha]"))
        self.assertEqual(sorted(self.paths("alpha beta")), ["notes/A.md", "notes/C.md"])

    def test_scope(self):
        self.put("notes/N.md", doc("needle\n", standalone="true"))
        self.put("sources/s.md", src("needle verbatim\n"))
        self.put("projects/P/P.md", doc("needle\n", type="project"))
        self.put("index.md", doc("needle\n", type="topic"))
        self.put("inbox/c.md", "needle in a capture")
        self.put("inbox/processed/old.md", "needle processed")
        self.put("docs/d.md", "needle docs")
        self.put("scripts/x.md", "needle scripts")
        self.put("notes/.hidden.md", "needle hidden")
        self.assertEqual(sorted(self.paths("needle")), ["index.md", "notes/N.md", "projects/P/P.md", "sources/s.md"])

    def test_binary_sources_match_by_filename_only(self):
        self.put("sources/playwright-guide.pdf", b"%PDF needle")
        hits = self.search_json("playwright")["hits"]
        self.assertEqual(hits[0]["path"], "sources/playwright-guide.pdf")
        self.assertEqual(hits[0]["type"], "(none)")
        self.assertEqual(hits[0]["field"], "title")
        self.assertEqual(self.paths("needle"), [])

    def test_hit_fields_type_heading_snippet(self):
        self.put("notes/A.md", doc("intro line\n## Setup\nfirst line\nthe unique-term lives here today\n# Later\n", standalone="true"))
        self.put("notes/B.md", "unique-term in a file without frontmatter\n")
        hits = {h["path"]: h for h in self.search_json("unique-term")["hits"]}
        self.assertEqual(hits["notes/A.md"]["type"], "note")
        self.assertEqual(hits["notes/A.md"]["heading"], "Setup")
        self.assertIn("unique-term lives here", hits["notes/A.md"]["snippet"])
        self.assertEqual(hits["notes/B.md"]["type"], "(none)")
        self.assertEqual(hits["notes/B.md"]["heading"], "")
        self.assertEqual(sorted(hits["notes/A.md"]), ["field", "heading", "path", "snippet", "type"])

    def test_snippet_is_bounded(self):
        self.put("notes/A.md", doc("x" * 300 + " needle " + "y" * 300 + "\n", standalone="true"))
        h = self.search_json("needle")["hits"][0]
        self.assertIn("needle", h["snippet"])
        self.assertLessEqual(len(h["snippet"]), 200)

    def test_malformed_and_non_utf8_files_do_not_crash(self):
        self.put("notes/Bad.md", "---\ntype: note\ntype: topic\n---\nfindme in body\n")
        self.put("notes/Findme latin.md", b"caf" + bytes([0xe9]))
        hits = {h["path"]: h for h in self.search_json("findme")["hits"]}
        self.assertEqual(hits["notes/Bad.md"]["type"], "(invalid)")
        self.assertEqual(hits["notes/Findme latin.md"]["field"], "title")

    def test_no_hits_exit_0(self):
        self.put("notes/A.md", doc(standalone="true"))
        rc, out, err = self.cmd("search", "zzzzqqq")
        self.assertEqual(rc, 0)
        self.assertIn("No matches", out)
        self.assertEqual(self.search_json("zzzzqqq")["total"], 0)

    def test_does_not_modify_files(self):
        self.put("notes/A.md", doc("needle\n", standalone="true"))
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.cmd("search", "needle")
        self.cmd("search", "--json", "needle")
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_vault_without_inbox_or_processed_runs(self):
        self.put("sources/s.md", src("needle\n"))
        self.assertEqual(self.cmd("search", "needle")[0], 0)


class SearchLimitAndFilters(CmdCase):
    def many(self, n=12):
        for i in range(n):
            self.put("notes/Item %02d.md" % i, doc("shared\n", standalone="true"))

    def test_default_limit_10_and_n_of_m_shown(self):
        self.many(12)
        data = self.search_json("shared")
        self.assertEqual((data["total"], data["shown"], len(data["hits"])), (12, 10, 10))
        rc, out, err = self.cmd("search", "shared")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip().splitlines()[-1], "10 of 12 shown")

    def test_explicit_limit(self):
        self.many(12)
        self.assertEqual(len(self.paths("shared", "--limit", "3")), 3)
        self.assertEqual(self.cmd("search", "shared", "--limit", "3")[1].strip().splitlines()[-1], "3 of 12 shown")
        self.assertEqual(len(self.paths("shared", "--limit", "50")), 12)

    def test_no_truncation_no_footer(self):
        self.many(3)
        rc, out, err = self.cmd("search", "shared")
        self.assertNotIn("shown", out)

    def test_invalid_limit_exit_2(self):
        for bad in ["0", "-1", "abc", "1.5"]:
            self.assertEqual(self.cmd("search", "x", "--limit", bad)[0], 2, bad)

    def test_type_filter(self):
        self.put("notes/N.md", doc("shared\n", standalone="true"))
        self.put("notes/T.md", doc("shared\n", type="topic"))
        self.put("sources/s.md", src("shared\n"))
        self.put("notes/NoFm.md", "shared\n")
        self.assertEqual(self.paths("shared", "--type", "note"), ["notes/N.md"])
        self.assertEqual(self.paths("shared", "--type", "TOPIC"), ["notes/T.md"])
        self.assertEqual(self.paths("shared", "--type", "source"), ["sources/s.md"])
        self.assertEqual(self.paths("shared", "--type", "(none)"), ["notes/NoFm.md"])

    def test_tag_filter(self):
        self.put("notes/A.md", doc("shared\n", standalone="true", tags="[go, Testing]"))
        self.put("notes/B.md", doc("shared\n", standalone="true", tags="\n  - java"))
        self.put("notes/C.md", doc("shared\n", standalone="true"))
        self.assertEqual(self.paths("shared", "--tag", "go"), ["notes/A.md"])
        self.assertEqual(self.paths("shared", "--tag", "#testing"), ["notes/A.md"])
        self.assertEqual(self.paths("shared", "--tag", "java"), ["notes/B.md"])
        self.assertEqual(self.paths("shared", "--tag", "rust"), [])

    def test_filters_combine_and_apply_before_limit(self):
        for i in range(5):
            self.put("notes/Keep %d.md" % i, doc("shared\n", standalone="true", tags="[keep]"))
        for i in range(5):
            self.put("notes/Drop %d.md" % i, doc("shared\n", standalone="true"))
        data = self.search_json("shared", "--tag", "keep", "--limit", "2")
        self.assertEqual((data["total"], data["shown"]), (5, 2))
        self.assertEqual(self.paths("shared", "--tag", "keep", "--type", "topic"), [])


class SearchSecrets(CmdCase):
    def test_snippet_with_secret_pattern_is_withheld(self):
        secret = fake("aws")
        self.put("notes/A.md", doc("deploy notes\nthe deploy key is " + secret + " ok\n", standalone="true"))
        data = self.search_json("key")
        hit = data["hits"][0]
        self.assertEqual(hit["path"], "notes/A.md")
        self.assertIn("withheld", hit["snippet"])
        rc, out, err = self.cmd("search", "key")
        self.assertNotIn(secret, out + err + json.dumps(data))
        self.assertNotIn(secret[4:], out + err + json.dumps(data))

    def test_other_lines_still_give_snippets(self):
        self.put("notes/A.md", doc("deploy steps are listed here\nkey " + fake("github") + "\n", standalone="true"))
        hit = self.search_json("steps")["hits"][0]
        self.assertIn("deploy steps", hit["snippet"])

    def test_frontmatter_and_heading_snippets_are_checked_too(self):
        secret = fake("slack")
        self.put("notes/A.md", doc("## Token " + secret + "\nplain\n", standalone="true", note='"look ' + secret + '"'))
        for q in ["look", "Token"]:
            data = self.search_json(q)
            self.assertNotIn(secret, json.dumps(data))
            self.assertIn("withheld", data["hits"][0]["snippet"])
        self.assertNotIn(secret, self.cmd("search", "look")[1] + self.cmd("search", "Token")[1])

    def test_forced_failure_does_not_echo_content(self):
        secret = fake("stripe")
        self.put("notes/A.md", doc("x " + secret + "\n", standalone="true"))
        original = kb.scan_text

        def boom(text):
            raise ValueError(text)

        kb.scan_text = boom
        try:
            rc, out, err = self.cmd("search", "x")
        finally:
            kb.scan_text = original
        self.assertEqual(rc, 2)
        self.assertNotIn(secret, out + err)

    def test_undecodable_file_is_not_searched_or_scanned(self):
        self.put("notes/Latin.md", b"needle " + fake("aws").encode() + bytes([0xe9]))
        data = self.search_json("needle")
        self.assertEqual(data["total"], 0)


class SearchUsage(CmdCase):
    def test_empty_query_and_missing_query_exit_2(self):
        self.assertEqual(self.cmd("search", "")[0], 2)
        self.assertEqual(self.cmd("search")[0], 2)
        self.assertEqual(self.cmd("search", "   ")[0], 2)

    def test_no_backlinks_flag_on_search(self):
        self.assertEqual(self.cmd("search", "x", "--backlinks")[0], 2)

    def test_non_vault_root_exit_2(self):
        empty = self.base / "empty"
        empty.mkdir()
        self.assertEqual(self.cmd("search", "x", "--root", str(empty), root=False)[0], 2)

    def test_bad_flag_exit_2(self):
        self.assertEqual(self.cmd("search", "x", "--nonsense")[0], 2)


class BacklinksBasics(CmdCase):
    def lines(self, *args):
        rc, out, err = self.cmd("backlinks", *args)
        return rc, [l for l in out.splitlines() if l.strip()], err

    def test_body_and_frontmatter_links_with_text_and_heading(self):
        self.put("notes/Target.md", doc("# H\n", standalone="true"))
        self.put("notes/B.md", doc("see [[Target|the target]] and [[Target#H]]\n", standalone="true"))
        self.put("notes/C.md", doc("x\n", standalone="true", sources='["[[Target]]"]'))
        rc, lines, err = self.lines("Target")
        self.assertEqual(rc, 0)
        text = "\n".join(lines)
        self.assertIn("notes/B.md:7", text)
        self.assertIn("notes/C.md:6", text)
        self.assertIn("text: the target", text)
        self.assertIn("heading: H", text)
        self.assertEqual(text.count("notes/B.md:7"), 2)

    def test_embeds_are_listed(self):
        self.put("sources/X.pdf", b"%PDF")
        self.put("sources/x.md", src("![[X.pdf]]\n", original='"X.pdf"', sha256=hashlib.sha256(b"%PDF").hexdigest()))
        rc, lines, err = self.lines("X.pdf")
        self.assertEqual(rc, 0)
        self.assertTrue(any("sources/x.md:" in l and "![[" in l for l in lines), lines)

    def test_name_forms(self):
        self.put("notes/Page Object Model.md", doc("x\n", standalone="true"))
        self.put("notes/B.md", doc("[[page object model]]\n", standalone="true"))
        for name in ["Page Object Model", "page object model", "Page Object Model.md", "notes/Page Object Model.md",
                     "notes/Page Object Model", "PAGE OBJECT MODEL"]:
            rc, lines, err = self.lines(name)
            self.assertEqual(rc, 0, name)
            self.assertTrue(any("notes/B.md:7" in l for l in lines), name)

    def test_nfc_name(self):
        self.put("notes/Caf\u00e9.md", doc("x\n", standalone="true"))
        self.put("notes/B.md", doc("[[Cafe\u0301]]\n", standalone="true"))
        rc, lines, err = self.lines("CAF\u00c9")
        self.assertTrue(any("notes/B.md:7" in l for l in lines))

    def test_file_with_no_backlinks_exit_0(self):
        self.put("notes/Lonely.md", doc("x\n", standalone="true"))
        rc, lines, err = self.lines("Lonely")
        self.assertEqual(rc, 0)
        self.assertTrue(any("No backlinks" in l for l in lines))

    def test_unknown_name_without_links_exit_1(self):
        self.put("notes/A.md", doc("x\n", standalone="true"))
        rc, lines, err = self.lines("Nonexistent")
        self.assertEqual(rc, 1)

    def test_dangling_target_lists_every_link_form(self):
        self.put("notes/A.md", doc("[[X.pdf]] ![[x.PDF#page=2]] [[sources/X.pdf|text]]\n", standalone="true"))
        self.put("notes/B.md", doc("x\n", standalone="true", related='"[[X.pdf]]"'))
        self.put("notes/C.md", doc("[[Other.pdf]]\n", standalone="true"))
        rc, lines, err = self.lines("X.pdf")
        self.assertEqual(rc, 0)
        text = "\n".join(lines)
        self.assertEqual(text.count("notes/A.md:7"), 3)
        self.assertIn("notes/B.md:6", text)
        self.assertNotIn("notes/C.md", text)
        self.assertIn("not found", text.lower())

    def test_ambiguous_name_lists_candidates_exit_1(self):
        self.put("notes/Dup.md", doc(standalone="true"))
        self.put("projects/Q/Dup.md", doc(standalone="true"))
        self.put("notes/A.md", doc("[[notes/Dup]]\n", standalone="true"))
        rc, lines, err = self.lines("Dup")
        self.assertEqual(rc, 1)
        text = "\n".join(lines)
        self.assertIn("notes/Dup.md", text)
        self.assertIn("projects/Q/Dup.md", text)
        self.assertIn("ambiguous", text.lower())
        self.assertEqual(self.lines("notes/Dup")[0], 0)

    def test_self_links_code_and_standard_links_are_ignored(self):
        self.put("notes/T.md", doc("[[T]] and [[#x]]\n", standalone="true"))
        self.put("notes/B.md", doc("`[[T]]` and [t](T.md)\n" + F3 + "\n[[T]]\n" + F3 + "\n", standalone="true"))
        rc, lines, err = self.lines("T")
        self.assertEqual(rc, 0)
        self.assertTrue(any("No backlinks" in l for l in lines), lines)

    def test_alias_does_not_make_a_backlink(self):
        self.put("notes/Real.md", doc(aliases="[Nick]", standalone="true"))
        self.put("notes/A.md", doc("[[Nick]]\n", standalone="true"))
        rc, lines, err = self.lines("Real")
        self.assertTrue(any("No backlinks" in l for l in lines))

    def test_source_bodies_and_captures_are_included(self):
        self.put("notes/T.md", doc(standalone="true"))
        self.put("sources/s.md", src("verbatim [[T]]\n"))
        self.put("inbox/c.md", "capture [[T]]\n")
        rc, lines, err = self.lines("T")
        text = "\n".join(lines)
        self.assertIn("sources/s.md:", text)
        self.assertIn("inbox/c.md:", text)

    def test_malformed_frontmatter_note_is_found_by_raw_scan_and_marked(self):
        self.put("sources/S.md", src("x\n"))
        self.put("notes/Broken.md", "---\ntype: note\ntype: topic\nsources: [[[S]]]\n---\ntext\n" + F3 + "\n[[S]]\n" + F3 + "\n")
        self.put("notes/Fine.md", doc("[[S]]\n", standalone="true"))
        rc, lines, err = self.lines("S")
        self.assertEqual(rc, 0)
        broken = [l for l in lines if "notes/Broken.md:" in l]
        self.assertTrue(broken, lines)
        self.assertTrue(all("raw" in l.split() or "(raw)" in l for l in broken), broken)
        self.assertTrue(any("notes/Broken.md:4" in l for l in broken))
        self.assertTrue(any("notes/Broken.md:8" in l for l in broken), broken)  # raw text: fences are not skipped
        fine = [l for l in lines if "notes/Fine.md:" in l]
        self.assertTrue(fine)
        self.assertFalse(any("raw" in l for l in fine))

    def test_unclosed_frontmatter_note_is_found_by_raw_scan(self):
        self.put("sources/S.md", src("x\n"))
        self.put("notes/Open.md", "---\ntype: note\nsources: [[[S]]]\nno closing delimiter [[S]]\n")
        rc, lines, err = self.lines("S")
        self.assertEqual(rc, 0)
        found = [l for l in lines if "notes/Open.md:" in l]
        self.assertEqual(len(found), 2, lines)
        self.assertTrue(all("raw" in l.split() for l in found), found)

    def test_does_not_modify_files(self):
        self.put("notes/A.md", doc("[[B]]\n", standalone="true"))
        self.put("notes/B.md", doc(standalone="true"))
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.cmd("backlinks", "B")
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_vault_without_inbox_or_processed_runs(self):
        self.put("sources/s.md", src())
        self.assertEqual(self.cmd("backlinks", "s")[0], 0)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.cmd("backlinks")[0], 2)
        self.assertEqual(self.cmd("backlinks", "")[0], 2)
        self.assertEqual(self.cmd("backlinks", "a", "--nonsense")[0], 2)
        empty = self.base / "empty"
        empty.mkdir()
        self.assertEqual(self.cmd("backlinks", "a", "--root", str(empty), root=False)[0], 2)

    def test_unreadable_file_is_exit_2_without_content(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root can read anything")
        p = self.put("notes/A.md", doc("[[B]] " + fake("aws") + "\n", standalone="true"))
        os.chmod(p, 0)
        self.addCleanup(lambda: os.chmod(p, 0o644))
        rc, out, err = self.cmd("backlinks", "B")
        self.assertEqual(rc, 2)
        self.assertNotIn(fake("aws"), out + err)


class CommandLineSurface(CmdCase):
    def test_top_level_help_lists_all_three_subcommands(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                kb.main(["--help"])
            except SystemExit:
                pass
        for name in ["lint", "search", "backlinks"]:
            self.assertIn(name, out.getvalue())

    def test_search_and_backlinks_run_as_a_script(self):
        import subprocess
        self.put("notes/A.md", doc("needle [[B]]\n", standalone="true"))
        self.put("notes/B.md", doc("x\n", standalone="true"))
        script = Path(kb.__file__).resolve()
        for argv, code in ([["search", "needle"], 0], [["backlinks", "B"], 0], [["backlinks", "nope"], 1]):
            r = subprocess.run([sys.executable, "-B", str(script)] + argv + ["--root", str(self.root)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, code, (argv, r.stderr))



# ======================================================================== M6 fix: unreadable captures are isolated

@unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read anything")
class UnreadableCapture(CmdCase):
    def lock(self, rel, content):
        p = self.put(rel, content)
        os.chmod(p, 0)
        self.addCleanup(lambda: os.chmod(p, 0o644))
        return p

    def test_unreadable_capture_is_w11_not_exit_2(self):
        self.lock("inbox/locked.md", "key " + fake("aws") + "\n")
        self.put("inbox/good.md", "key " + fake("github") + "\n")
        rc, out, err = self.run_cli()
        self.assertEqual(rc, 0, err)
        res = self.lint()
        w11 = [f for f in res.findings if f.code == "W11"]
        self.assertEqual([(f.path, f.level, f.detail) for f in w11],
                         [("inbox/locked.md", "WARNING", "unreadable; content checks skipped")])
        self.assertEqual([f.path for f in res.findings if f.code == "W07"], ["inbox/good.md"])
        self.assertNotIn(fake("aws"), out + err)

    def test_unreadable_non_markdown_capture_and_processed_original(self):
        self.lock("inbox/locked.pdf", b"%PDF")
        self.lock("inbox/processed/old.md", "text")
        res = self.lint()
        self.assertEqual(sorted(f.path for f in res.findings if f.code == "W11"),
                         ["inbox/locked.pdf", "inbox/processed/old.md"])
        self.assertEqual(self.run_cli()[0], 0)

    def test_unreadable_capture_never_matches_a_source_or_crashes_w05_w06_w08(self):
        self.put("sources/Locked.md", src("x\n"))
        self.lock("inbox/Locked.md", "x")
        codes = {f.code for f in self.lint(inbox_days=0).findings}
        self.assertIn("W11", codes)
        self.assertNotIn("W05", codes)

    def test_other_unreadable_files_still_exit_2(self):
        self.lock("sources/s.md", src())
        self.assertEqual(self.run_cli()[0], 2)

    def test_unreadable_note_still_exit_2_without_content(self):
        self.lock("notes/A.md", doc("secret " + fake("aws") + "\n"))
        rc, out, err = self.run_cli()
        self.assertEqual(rc, 2)
        self.assertNotIn(fake("aws"), out + err)

    def test_search_and_backlinks_tolerate_an_unreadable_capture(self):
        self.lock("inbox/locked.md", "[[A]]")
        self.put("notes/A.md", doc("needle\n", standalone="true"))
        self.assertEqual(self.cmd("search", "needle")[0], 0)
        rc, out, err = self.cmd("backlinks", "A")
        self.assertEqual(rc, 0, err)


if __name__ == "__main__":
    unittest.main()
