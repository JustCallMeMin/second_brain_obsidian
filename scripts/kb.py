"""kb.py: deterministic helpers for the engineering second-brain vault.

Python standard library only (3.10+). This file holds the M1 parsing core:
name rules, the restricted YAML frontmatter parser, wikilink and heading
extraction, the vault walker and finding ids. The lint, search and backlinks
subcommands are added in later milestones (M2 adds lint errors, W10 and W11; M3 the secret scan, W01-W09, R01 and R02).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BOM = chr(0xFEFF)
BIDI_CONTROLS = {chr(c) for c in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))}


# ---------------------------------------------------------------- names

def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def norm_name(s: str) -> str:
    """NFC-normalized, case-insensitive form used to compare basenames."""
    return nfc(nfc(s).casefold())


def basename_error(name: Any) -> Optional[str]:
    """Return None if `name` satisfies the basename rule, else the reason."""
    if not isinstance(name, str) or name == "":
        return "empty"
    if len(name.encode("utf-8")) > 255:
        return "longer than 255 UTF-8 bytes"
    if name in (".", ".."):
        return "is . or .."
    if "/" in name or "\\" in name:
        return "contains a path separator"
    if ":" in name:
        return "contains ':'"
    if name[0].isspace() or name[-1].isspace():
        return "leading or trailing whitespace"
    if name.endswith("."):
        return "ends with '.'"
    for ch in name:
        if unicodedata.category(ch) == "Cc":
            return "contains a control character"
        if ch in BIDI_CONTROLS:
            return "contains a bidirectional control character"
    return None


def is_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------- reading

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FileData:
    raw: Optional[bytes]
    text: Optional[str]  # None if unreadable or not valid UTF-8; BOM removed
    error: Optional[str]  # set only when the file could not be read at all
    sha256: Optional[str]


def read_file(path) -> FileData:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return FileData(None, None, f"{type(exc).__name__}: {exc.strerror or exc}", None)
    try:
        text: Optional[str] = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None and text.startswith(BOM):
        text = text[1:]
    return FileData(raw, text, None, sha256_hex(raw))


# ---------------------------------------------------------------- frontmatter

@dataclass
class Frontmatter:
    status: str  # "missing" | "ok" | "malformed"
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    end_line: int = 0  # 1-based line of the closing delimiter, 0 if none
    body: str = ""


class _YamlError(Exception):
    pass


_KEY_RE = re.compile(r"^[^\s\-#\[\]{}\"'|>&*!%@`,?:][^\[\]{}\"'#:|]*$")
_ITEM_RE = re.compile(r"^\s*-(\s+(.*))?$")


def _lines(text: str) -> List[str]:
    return text.split("\n")


def _frontmatter_end(lines: List[str]) -> Optional[int]:
    """Index of the closing delimiter if the text starts a frontmatter block."""
    if not lines or lines[0] not in ("---", "---\r"):
        return None
    for i in range(1, len(lines)):
        if lines[i] in ("---", "---\r"):
            return i
    return -1  # opened but never closed


def _parse_dq(v: str) -> str:
    out: List[str] = []
    i = 1
    while i < len(v):
        c = v[i]
        if c == "\\":
            if i + 1 < len(v) and v[i + 1] in ('"', "\\"):
                out.append(v[i + 1])
                i += 2
                continue
            raise _YamlError("unsupported escape in double-quoted value (only \\\" and \\\\ are allowed)")
        if c == '"':
            if v[i + 1:].strip():
                raise _YamlError("text after closing quote")
            return "".join(out)
        out.append(c)
        i += 1
    raise _YamlError("unterminated double-quoted value")


def _parse_sq(v: str) -> str:
    out: List[str] = []
    i = 1
    while i < len(v):
        c = v[i]
        if c == "'":
            if i + 1 < len(v) and v[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            if v[i + 1:].strip():
                raise _YamlError("text after closing quote")
            return "".join(out)
        out.append(c)
        i += 1
    raise _YamlError("unterminated single-quoted value")


def _parse_scalar(v: str, inline: bool = False) -> Any:
    v = v.strip()
    if v.startswith('"'):
        return _parse_dq(v)
    if v.startswith("'"):
        return _parse_sq(v)
    if v.startswith("["):
        if inline:
            raise _YamlError("nested lists are not supported")
        return _parse_inline_list(v)
    if v[:1] in "{|>&*!%@`":
        raise _YamlError("unsupported YAML construct starting with " + repr(v[:1]))
    if "[[" in v:
        raise _YamlError("a value containing a wikilink must be quoted")
    if inline and ("[" in v or "]" in v):
        raise _YamlError("unquoted brackets in a list item")
    if v.startswith("#") or " #" in v:
        raise _YamlError("comments are not supported")
    if ": " in v or v.endswith(":"):
        raise _YamlError("unquoted ': ' in a plain value")
    if v == "true":
        return True
    if v == "false":
        return False
    return v


def _split_inline(inner: str) -> List[str]:
    items: List[str] = []
    cur: List[str] = []
    quote = ""
    i = 0
    while i < len(inner):
        c = inner[i]
        if quote:
            cur.append(c)
            if quote == '"' and c == "\\" and i + 1 < len(inner):
                cur.append(inner[i + 1])
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'" and not "".join(cur).strip():
            quote = c
            cur.append(c)
        elif c == ",":
            items.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if quote:
        raise _YamlError("unterminated quote in list")
    items.append("".join(cur))
    return items


def _parse_inline_list(v: str) -> List[Any]:
    if not v.endswith("]"):
        raise _YamlError("unclosed inline list")
    inner = v[1:-1]
    if not inner.strip():
        return []
    result = []
    for item in _split_inline(inner):
        if not item.strip():
            raise _YamlError("empty item in inline list")
        result.append(_parse_scalar(item, inline=True))
    return result


def _parse_block(lines: List[str], first_lineno: int) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    key: Optional[str] = None
    block_open = False
    for offset, raw in enumerate(lines):
        n = first_lineno + offset
        line = raw.rstrip("\r")
        try:
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                raise _YamlError("comments are not supported")
            m = _ITEM_RE.match(line)
            if m:
                if key is None or not block_open:
                    raise _YamlError("list item without a key, or nesting, is not supported")
                item = (m.group(2) or "").strip()
                if not item:
                    raise _YamlError("empty list item")
                if data[key] is None:
                    data[key] = []
                data[key].append(_parse_scalar(item, inline=True))
                continue
            if line[0] in " \t":
                raise _YamlError("indentation and nesting are not supported")
            idx = line.find(":")
            if idx < 0:
                raise _YamlError("expected 'key: value'")
            k = line[:idx].rstrip()
            rest = line[idx + 1:]
            if not _KEY_RE.match(k):
                raise _YamlError("invalid key " + repr(k))
            if rest and rest[0] not in " \t":
                raise _YamlError("expected a space after ':'")
            if k in data:
                raise _YamlError("duplicate key " + repr(k))
            value = rest.strip()
            key = k
            if not value:
                data[k] = None
                block_open = True
            else:
                data[k] = _parse_scalar(value)
                block_open = False
        except _YamlError as exc:
            raise _YamlError(f"line {n}: {exc}") from None
    return data


def parse_frontmatter(text: str) -> Frontmatter:
    if text.startswith(BOM):
        text = text[1:]
    lines = _lines(text)
    end = _frontmatter_end(lines)
    if end is None:
        return Frontmatter("missing", body=text)
    if end == -1:
        return Frontmatter("malformed", error="unterminated frontmatter (no closing '---')", body=text)
    body = "\n".join(lines[end + 1:])
    try:
        data = _parse_block(lines[1:end], 2)
    except _YamlError as exc:
        return Frontmatter("malformed", error=str(exc), end_line=end + 1, body=body)
    return Frontmatter("ok", data=data, end_line=end + 1, body=body)


# ---------------------------------------------------------------- code, links, headings

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


class _FenceTracker:
    def __init__(self) -> None:
        self.char = ""
        self.size = 0

    def in_fence_after(self, line: str) -> Tuple[bool, bool]:
        """Feed one body line. Returns (is_code, unused)."""
        if self.char:
            stripped = line.lstrip(" ")
            if len(line) - len(stripped) <= 3:
                body = stripped.rstrip()
                if len(body) >= self.size and set(body) == {self.char}:
                    self.char = ""
                    self.size = 0
            return True, False
        m = _FENCE_OPEN.match(line)
        if m:
            fence, info = m.group(1), m.group(2)
            if fence[0] == "`" and "`" in info:
                return False, False
            self.char = fence[0]
            self.size = len(fence)
            return True, False
        return False, False


def _mask_inline_code(line: str) -> str:
    out = list(line)
    i = 0
    n = len(line)
    while i < n:
        if line[i] != "`":
            i += 1
            continue
        j = i
        while j < n and line[j] == "`":
            j += 1
        size = j - i
        k = j
        close = -1
        while k < n:
            if line[k] == "`":
                e = k
                while e < n and line[e] == "`":
                    e += 1
                if e - k == size:
                    close = e
                    break
                k = e
            else:
                k += 1
        if close < 0:
            i = j
            continue
        for p in range(i, close):
            out[p] = " "
        i = close
    return "".join(out)


@dataclass
class Link:
    name: str
    anchor: Optional[str]
    label: Optional[str]
    embed: bool
    line: int
    raw: str

    @property
    def is_block_ref(self) -> bool:
        return bool(self.anchor) and self.anchor.startswith("^")


_LINK_RE = re.compile(r"(!?)\[\[([^\[\]\n]*)\]\]")


def _links_in(line: str, lineno: int) -> List[Link]:
    found = []
    for m in _LINK_RE.finditer(line):
        inner = m.group(2).replace("\\|", "|")
        target, sep, label = inner.partition("|")
        name, hsep, anchor = target.partition("#")
        name, anchor = name.strip(), anchor.strip()
        if not name and not anchor:
            continue
        found.append(Link(name, anchor if hsep and anchor else None,
                          label.strip() or None if sep else None, m.group(1) == "!", lineno, inner))
    return found


def _body_start(lines: List[str]) -> int:
    """Index of the first body line (0 if there is no closed frontmatter)."""
    end = _frontmatter_end(lines)
    return end + 1 if end is not None and end > 0 else 0


def extract_links(text: str) -> List[Link]:
    """Wikilinks and embeds, frontmatter included, code (fenced and inline) skipped."""
    if text.startswith(BOM):
        text = text[1:]
    lines = _lines(text)
    start = _body_start(lines)
    links: List[Link] = []
    for i in range(start):
        links.extend(_links_in(lines[i].rstrip("\r"), i + 1))
    fence = _FenceTracker()
    for i in range(start, len(lines)):
        line = lines[i].rstrip("\r")
        is_code, _ = fence.in_fence_after(line)
        if is_code:
            continue
        links.extend(_links_in(_mask_inline_code(line), i + 1))
    return links


@dataclass
class Heading:
    level: int
    text: str
    line: int


_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"[ \t]+#+[ \t]*$")


def extract_headings(text: str) -> List[Heading]:
    if text.startswith(BOM):
        text = text[1:]
    lines = _lines(text)
    fence = _FenceTracker()
    out: List[Heading] = []
    for i in range(_body_start(lines), len(lines)):
        line = lines[i].rstrip("\r")
        is_code, _ = fence.in_fence_after(line)
        if is_code:
            continue
        m = _HEADING_RE.match(line)
        if not m:
            continue
        title = _CLOSING_HASHES.sub("", m.group(2) or "").strip()
        out.append(Heading(len(m.group(1)), title, i + 1))
    return out


def norm_heading(s: str) -> str:
    return " ".join(nfc(s).split()).casefold()


def heading_exists(anchor: str, headings: List[Heading]) -> bool:
    wanted = norm_heading(anchor.split("#")[-1])
    return any(norm_heading(h.text) == wanted for h in headings)


# ---------------------------------------------------------------- findings

@dataclass
class Finding:
    code: str
    level: str
    path: str
    line: int
    detail: str
    id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "level": self.level, "path": self.path,
                "line": self.line, "detail": self.detail, "id": self.id}


def assign_ids(findings: List[Finding]) -> None:
    """id = code|path|detail|n, n counting repeats of the same code, path and detail."""
    seen: Dict[Tuple[str, str, str], int] = {}
    for f in findings:
        key = (f.code, f.path, f.detail)
        seen[key] = seen.get(key, 0) + 1
        f.id = f"{f.code}|{f.path}|{f.detail}|{seen[key]}"


# ---------------------------------------------------------------- vault walker

@dataclass
class ScanFile:
    rel: str
    path: Path
    area: str  # "index" | "inbox" | "sources" | "notes" | "projects"


_AREAS = ("inbox", "sources", "notes", "projects")


def _regular(path: str) -> bool:
    return os.path.isfile(path) and not os.path.islink(path)


def scan_vault(root) -> List[ScanFile]:
    """Files kb.py reads: index.md, inbox/ (not inbox/processed/), sources/, notes/, projects/.

    Hidden files and folders are ignored everywhere; symlinks are neither
    followed nor scanned; missing folders are tolerated.
    """
    root = Path(root)
    found: List[ScanFile] = []
    index = root / "index.md"
    if _regular(str(index)):
        found.append(ScanFile("index.md", index, "index"))
    for area in _AREAS:
        top = root / area
        if not top.is_dir() or top.is_symlink():
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            at_inbox_top = area == "inbox" and Path(dirpath) == top
            dirnames[:] = sorted(
                d for d in dirnames
                if not d.startswith(".")
                and not os.path.islink(os.path.join(dirpath, d))
                and not (at_inbox_top and d == "processed")
            )
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                if name.startswith(".") or not _regular(full):
                    continue
                rel = Path(full).relative_to(root).as_posix()
                found.append(ScanFile(rel, Path(full), area))
    found.sort(key=lambda f: f.rel)
    return found


# ---------------------------------------------------------------- lint (M2: errors, W10, W11)

class LintError(Exception):
    """Usage or environment problem: reported without file content, exit code 2."""


LEVELS = ("ERROR", "WARNING", "REVIEW", "PENDING")
VALID_TYPES = ("note", "topic", "project", "decision", "source")
CONFIDENCE = ("shaky", "ok", "solid")
FORBIDDEN_NAME_CHARS = "#^[]|"
_SHA_RE = re.compile(r"[0-9a-f]{64}")


@dataclass
class LintResult:
    findings: List[Finding]
    pending_targets: List[str]


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check_vault(root: Path) -> None:
    if not root.is_dir():
        raise LintError("root is not a readable directory")
    if not os.access(root, os.R_OK | os.X_OK):
        raise LintError("root is not readable")
    markers = [".obsidian", "inbox", "sources", "notes", "projects", "index.md"]
    if not any((root / m).exists() for m in markers):
        raise LintError("root does not look like a vault (no inbox, sources, notes, projects, index.md or .obsidian)")


def validate_pending(name: str) -> None:
    reason = basename_error(name)
    if reason:
        raise LintError("--pending: not a valid filename (" + reason + ")")
    ext = os.path.splitext(name)[1]
    if not ext:
        raise LintError("--pending: the filename needs an extension other than .md")
    if ext.lower() == ".md":
        raise LintError("--pending: Markdown names are not allowed, only non-Markdown files")


def _is_md(sf: ScanFile) -> bool:
    return sf.path.suffix.lower() == ".md"


def _file_keys(sf: ScanFile) -> List[str]:
    name = sf.path.name
    keys = [norm_name(name)]
    if _is_md(sf):
        keys.append(norm_name(sf.path.stem))
    return keys


class _Index:
    """Link-resolution index over the scanned files outside inbox/."""

    def __init__(self, files: List[ScanFile], aliases: Dict[str, List[str]]) -> None:
        self.files = files
        self.by_key: Dict[str, List[str]] = {}
        self.full: Dict[str, str] = {}
        self.rel_keys: List[Tuple[str, str, str]] = []
        for sf in files:
            for key in dict.fromkeys(_file_keys(sf)):
                self.by_key.setdefault(key, []).append(sf.rel)
            r = norm_name(sf.rel)
            rs = r[:-3] if _is_md(sf) else r
            self.rel_keys.append((sf.rel, r, rs))
        self.aliases = aliases

    def resolve(self, name: str) -> Tuple[str, Optional[str]]:
        n = name.strip().strip("/")
        if "/" in n:
            p = norm_name(n)
            hits = [rel for rel, r, rs in self.rel_keys
                    if r == p or rs == p or r.endswith("/" + p) or rs.endswith("/" + p)]
        else:
            hits = list(self.by_key.get(norm_name(n), []))
        if len(hits) == 1:
            return "ok", hits[0]
        if len(hits) > 1:
            return "ambiguous", None
        if "/" not in n and norm_name(n) in self.aliases:
            return "alias", None
        return "missing", None


def _frontmatter_line(fm: Frontmatter) -> Tuple[int, str]:
    m = re.match(r"^line (\d+): (.*)$", fm.error or "")
    if m:
        return int(m.group(1)), m.group(2)
    return 1, fm.error or "malformed frontmatter"


def _check_fields(fm: Frontmatter, rel: str, add, inbox: bool) -> None:
    data = fm.data
    created, updated = data.get("created"), data.get("updated")
    if not inbox:
        t = data.get("type")
        if t is None or t == "":
            add("E02", "ERROR", rel, 1, "missing type")
        elif not isinstance(t, str) or t not in VALID_TYPES:
            add("E02", "ERROR", rel, 1, "unsupported type: " + str(t))
        for key, val in (("created", created), ("updated", updated)):
            if val is None or val == "":
                add("E02", "ERROR", rel, 1, "missing " + key)
            elif not is_iso_date(val):
                add("E02", "ERROR", rel, 1, "bad " + key + " date")
        if "standalone" in data and not isinstance(data["standalone"], bool):
            add("E02", "ERROR", rel, 1, "standalone must be true or false")
        if "confidence" in data and data["confidence"] not in CONFIDENCE:
            add("E02", "ERROR", rel, 1, "bad confidence (shaky, ok or solid)")
        if t == "source":
            sha = data.get("sha256")
            if sha is None or sha == "":
                add("E02", "ERROR", rel, 1, "source missing sha256")
            elif not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
                add("E02", "ERROR", rel, 1, "sha256 must be 64 lowercase hex")
            orig = data.get("original")
            if orig is None:
                add("E02", "ERROR", rel, 1, "source missing original")
            else:
                reason = basename_error(orig)
                if reason:
                    add("E02", "ERROR", rel, 1, "original violates basename rule: " + reason)
    if is_iso_date(created) and is_iso_date(updated) and updated < created:
        add("E03", "ERROR", rel, 1, "updated is earlier than created")


SECRET_PATTERNS = [
    ("private key header", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Stripe key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("credential assignment",
     re.compile(r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_/+=-]{16,}")),
]


def scan_text(text: str) -> List[Tuple[int, str]]:
    """Return (line, pattern name) for each suspected secret. Matched text is never returned.

    A safety net, not comprehensive secret detection.
    """
    hits: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                hits.append((lineno, name))
    return hits


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _processed_files(root: Path) -> List[Tuple[str, Path]]:
    base = root / "inbox" / "processed"
    out: List[Tuple[str, Path]] = []
    if not base.is_dir() or base.is_symlink():
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if not name.startswith(".") and _regular(full):
                out.append((Path(full).relative_to(root).as_posix(), Path(full)))
    return out


def _norm_body(body: str) -> str:
    return " ".join(body.split())


def lint(root, pending: Optional[str] = None, stale_days: int = 365, inbox_days: int = 14,
         now: Optional[datetime.datetime] = None) -> LintResult:
    root = Path(root)
    check_vault(root)
    if pending is not None:
        validate_pending(pending)
    now = now or _now()
    pending_key = norm_name(pending) if pending is not None else None
    findings: List[Finding] = []
    pending_used = False

    def add(code: str, level: str, path: str, line: int, detail: str) -> None:
        findings.append(Finding(code, level, path, line, detail))

    scan = scan_vault(root)
    docs: Dict[str, Tuple[ScanFile, Optional[str], Optional[Frontmatter]]] = {}
    texts: Dict[str, Optional[str]] = {}
    shas: Dict[str, str] = {}
    for sf in scan:
        fd = read_file(sf.path)
        if fd.error:
            if sf.area != "inbox":
                raise LintError("cannot read " + sf.rel + " (" + fd.error + ")")
            # an unreadable capture is isolated: warn and carry on (its content is never looked at)
            add("W11", "WARNING", sf.rel, 1, "unreadable; content checks skipped")
            texts[sf.rel] = None
            shas[sf.rel] = ""
            if _is_md(sf):
                docs[sf.rel] = (sf, None, None)
            continue
        texts[sf.rel] = fd.text
        shas[sf.rel] = fd.sha256 or ""
        if not _is_md(sf):
            continue
        if fd.text is None:
            add("W11", "WARNING", sf.rel, 1, "not valid UTF-8; content checks skipped")
            docs[sf.rel] = (sf, None, None)
            continue
        docs[sf.rel] = (sf, fd.text, parse_frontmatter(fd.text))

    outside = [sf for sf in scan if sf.area != "inbox"]
    captures = [sf for sf in scan if sf.area == "inbox"]

    # names: E06
    groups: Dict[str, List[str]] = {}
    for sf in outside:
        key = norm_name(sf.path.stem) if _is_md(sf) else norm_name(sf.path.name)
        groups.setdefault(key, []).append(sf.rel)
        bad = [c for c in FORBIDDEN_NAME_CHARS if c in sf.path.name]
        if bad:
            add("E06", "ERROR", sf.rel, 1, "forbidden character in filename: " + "".join(bad))
    for key, rels in groups.items():
        if len(rels) > 1:
            for rel in rels:
                add("E06", "ERROR", rel, 1, "duplicate basename: " + key)

    # frontmatter: E01, E02, E03, W10
    for rel, (sf, text, fm) in docs.items():
        if fm is None:
            continue
        inbox = sf.area == "inbox"
        if fm.status == "missing":
            if not inbox:
                add("W10", "WARNING", rel, 1, "no frontmatter")
        elif fm.status == "malformed":
            if not inbox:
                line, detail = _frontmatter_line(fm)
                add("E01", "ERROR", rel, line, detail)
        else:
            _check_fields(fm, rel, add, inbox)

    # aliases (used by link resolution and W02)
    aliases: Dict[str, List[str]] = {}
    alias_names: Dict[str, Dict[str, str]] = {}  # rel -> {normalized alias: alias as written}
    alias_counts: Dict[str, List[str]] = {}
    for sf in outside:
        entry = docs.get(sf.rel)
        if entry and entry[2] is not None and entry[2].status == "ok":
            al = entry[2].data.get("aliases")
            for a in (al if isinstance(al, list) else [al] if isinstance(al, str) else []):
                if isinstance(a, str) and a.strip():
                    na = norm_name(a.strip())
                    aliases.setdefault(na, []).append(sf.rel)
                    alias_counts.setdefault(na, []).append(sf.rel)
                    alias_names.setdefault(sf.rel, {}).setdefault(na, a.strip())
    index = _Index(outside, aliases)

    headings: Dict[str, List[Heading]] = {}

    def headings_of(rel: str) -> Optional[List[Heading]]:
        entry = docs.get(rel)
        if not entry or entry[1] is None:
            return None
        if rel not in headings:
            headings[rel] = extract_headings(entry[1])
        return headings[rel]

    # links: E04, E05, W09; inbound-link maps for W01, W04, R02
    inbound: Dict[str, set] = {}
    knowledge_inbound: Dict[str, set] = {}
    for rel, (sf, text, fm) in docs.items():
        if text is None or fm is None:
            continue
        cutoff = -1
        if sf.area == "sources" and (fm.status != "ok" or fm.data.get("type") in (None, "source")):
            cutoff = fm.end_line if fm.status != "missing" else 0
        for link in extract_links(text):
            if not link.name:
                status, target = "ok", rel
            else:
                status, target = index.resolve(link.name)
            if status == "ok" and target != rel and sf.area != "inbox":
                inbound.setdefault(target, set()).add(rel)
                if sf.area in ("notes", "projects", "index"):
                    knowledge_inbound.setdefault(target, set()).add(rel)
            if cutoff >= 0 and link.line > cutoff:
                continue  # verbatim source body: exempt (frontmatter links are still checked)
            if status != "ok":
                if sf.area == "inbox":
                    continue  # approved: captures are exempt from E04 and E05
                detail = {"missing": "target not found: ", "ambiguous": "ambiguous target: ",
                          "alias": "target matches only an alias: "}[status] + link.name
                level = "ERROR"
                if status == "missing" and pending_key is not None and \
                        norm_name(link.name.strip().strip("/").rsplit("/", 1)[-1]) == pending_key:
                    level = "PENDING"
                    pending_used = True
                add("E04", level, rel, link.line, detail)
                continue
            if link.is_block_ref:
                add("W09", "WARNING", rel, link.line, "unverified block reference: " + link.name + "#" + link.anchor)
            elif link.anchor and sf.area != "inbox" and target and target in docs:
                hs = headings_of(target)
                if hs is not None and not heading_exists(link.anchor, hs):
                    add("E05", "ERROR", rel, link.line, "heading not found: " + link.name + "#" + link.anchor)

    # companions: E08
    flat_binaries = {norm_name(sf.path.name): sf for sf in outside
                     if sf.area == "sources" and not _is_md(sf) and sf.path.parent == root / "sources"}
    for rel, (sf, text, fm) in docs.items():
        if sf.area != "sources" or fm is None or fm.status != "ok" or fm.data.get("type") != "source":
            continue
        orig = fm.data.get("original")
        if not isinstance(orig, str) or basename_error(orig):
            continue
        ext = os.path.splitext(orig)[1].lower()
        target = flat_binaries.get(norm_name(orig))
        if ext in (".md", ".txt") and target is None:
            continue
        if ext == ".md":
            continue
        if target is None:
            level = "ERROR"
            if pending_key is not None and norm_name(orig) == pending_key:
                level, pending_used = "PENDING", True
            add("E08", level, rel, 1, "companion binary not found: " + orig)
            continue
        sha = fm.data.get("sha256")
        if isinstance(sha, str) and _SHA_RE.fullmatch(sha) and shas.get(target.rel) != sha:
            add("E08", "ERROR", rel, 1, "sha256 mismatch with " + orig)

    # secrets: E07 outside inbox/, W07 in captures and in inbox/processed/
    for sf in scan:
        text = texts.get(sf.rel)
        if text is None:
            continue
        for line, name in scan_text(text):
            if sf.area == "inbox":
                add("W07", "WARNING", sf.rel, line, "possible secret: " + name)
            else:
                add("E07", "ERROR", sf.rel, line, "possible secret: " + name)
    for rel, path in _processed_files(root):
        fd = read_file(path)
        if fd.error:
            add("W11", "WARNING", rel, 1, "unreadable; content checks skipped")
            continue
        if fd.text is None:
            continue
        for line, name in scan_text(fd.text):
            add("W07", "WARNING", rel, line, "possible secret: " + name)

    # warnings and review items on knowledge notes and sources
    today = now.date()
    body_groups: Dict[str, List[str]] = {}
    for sf in outside:
        rel = sf.rel
        entry = docs.get(rel)
        fm = entry[2] if entry else None
        is_note_area = sf.area in ("notes", "projects")
        if sf.area == "sources" and not knowledge_inbound.get(rel):
            add("W04", "WARNING", rel, 1, "source not linked from any knowledge note")
        if fm is None:
            continue
        ok = fm.status == "ok"
        typ = fm.data.get("type") if ok else None
        standalone = ok and fm.data.get("standalone") is True
        if is_note_area and not (typ in ("topic", "project", "source") or standalone) and not inbound.get(rel):
            add("W01", "WARNING", rel, 1, "no inbound links from other files")
        if standalone and inbound.get(rel):
            add("R02", "REVIEW", rel, 1, "standalone note already has inbound links")
        if ok and typ in ("note", "topic", "project", "decision") and is_iso_date(fm.data.get("updated")):
            updated = fm.data["updated"]
            if (today - datetime.date.fromisoformat(updated)).days > stale_days:
                add("R01", "REVIEW", rel, 1,
                    f"updated {updated} is more than {stale_days} days old: updated is the last "
                    "knowledge-text or link change; stale means needs human review, not obsolete or incorrect")
        if sf.area in ("notes", "projects", "index", "sources") and entry and entry[1] is not None:
            norm = _norm_body(fm.body)
            if norm:
                body_groups.setdefault(sha256_hex(norm.encode("utf-8")), []).append(rel)
    for rels in body_groups.values():
        if len(rels) > 1:
            for rel in rels:
                others = ", ".join(sorted(r for r in rels if r != rel))
                add("W03", "WARNING", rel, 1, "duplicate content of: " + others)

    # W02: aliases
    for na, rels in alias_counts.items():
        if len(rels) > 1:
            for rel in sorted(set(rels)):
                add("W02", "WARNING", rel, 1, "duplicate alias: " + alias_names[rel][na])
    for rel, names in alias_names.items():
        for na, written in names.items():
            others = [r for r in index.by_key.get(na, []) if r != rel]
            if others:
                add("W02", "WARNING", rel, 1, "alias matches the basename of another file: " + written)

    # captures: W05, W06, W08
    source_hashes: Dict[str, List[str]] = {}
    for sf in outside:
        if sf.area != "sources":
            continue
        entry = docs.get(sf.rel)
        if _is_md(sf):
            fm = entry[2] if entry else None
            sha = fm.data.get("sha256") if fm is not None and fm.status == "ok" else None
            if isinstance(sha, str) and _SHA_RE.fullmatch(sha):
                source_hashes.setdefault(sha, []).append(sf.rel)
        else:
            source_hashes.setdefault(shas[sf.rel], []).append(sf.rel)
    for sf in captures:
        match = source_hashes.get(shas[sf.rel])
        if match:
            add("W05", "WARNING", sf.rel, 1, "same content as source: " + sorted(match)[0])
        try:
            mtime = sf.path.stat().st_mtime
        except OSError as exc:
            raise LintError("cannot read " + sf.rel + " (" + type(exc).__name__ + ")") from None
        if now.timestamp() - mtime > inbox_days * 86400:
            add("W06", "WARNING", sf.rel, 1, f"capture is older than {inbox_days} days")
        key = norm_name(sf.path.stem) if _is_md(sf) else norm_name(sf.path.name)
        if groups.get(key):
            add("W08", "WARNING", sf.rel, 1, "capture basename collides with " + sorted(groups[key])[0])

    order = {name: i for i, name in enumerate(LEVELS)}
    findings.sort(key=lambda f: (order[f.level], f.path, f.line, f.code, f.detail))
    assign_ids(findings)
    return LintResult(findings, [pending] if pending_used and pending is not None else [])


def format_text(res: LintResult, show_pending: bool) -> str:
    out: List[str] = []
    counts = {lv: 0 for lv in LEVELS}
    for f in res.findings:
        counts[f.level] += 1
    for lv in LEVELS:
        if lv == "PENDING" and not show_pending:
            continue
        out.append(f"{lv} ({counts[lv]})")
        for f in res.findings:
            if f.level == lv:
                out.append(f"  {f.path}:{f.line}  {f.code}  {f.detail}")
    if show_pending:
        out.append("PENDING targets: " + (", ".join(res.pending_targets) if res.pending_targets else "none"))
    return "\n".join(out)


def format_json(res: LintResult) -> str:
    counts = {lv: 0 for lv in LEVELS}
    for f in res.findings:
        counts[f.level] += 1
    return json.dumps({"findings": [f.as_dict() for f in res.findings], "counts": counts,
                       "pending_targets": res.pending_targets}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- command line

# ---------------------------------------------------------------- search and backlinks (M4)

WITHHELD = "[line withheld: possible secret]"
SNIPPET_MAX = 160
_FIELD_RANK = {"title": 0, "alias": 1, "tag": 2, "heading": 3, "frontmatter": 4, "body": 5}


@dataclass
class _Doc:
    sf: ScanFile
    text: Optional[str]
    fm: Optional[Frontmatter]
    sha: str


def _load_docs(root: Path) -> List[_Doc]:
    docs: List[_Doc] = []
    for sf in scan_vault(root):
        fd = read_file(sf.path)
        if fd.error:
            if sf.area != "inbox":
                raise LintError("cannot read " + sf.rel + " (" + fd.error + ")")
            docs.append(_Doc(sf, None, None, ""))  # an unreadable capture is skipped
            continue
        fm = parse_frontmatter(fd.text) if _is_md(sf) and fd.text is not None else None
        docs.append(_Doc(sf, fd.text if _is_md(sf) else None, fm, fd.sha256 or ""))
    return docs


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _norm_tag(tag: str) -> str:
    return norm_name(tag.strip().lstrip("#"))


def _type_of(d: _Doc) -> str:
    if d.fm is None or d.fm.status == "missing":
        return "(none)"
    if d.fm.status == "malformed":
        return "(invalid)"
    t = d.fm.data.get("type")
    return t if isinstance(t, str) and t else "(none)"


def _safe_line(line: str, first: int) -> str:
    """A bounded snippet of the line around the first match; a line that looks like a secret is withheld."""
    line = line.strip()
    if scan_text(line):
        return WITHHELD
    if len(line) > SNIPPET_MAX:
        start = max(0, min(first - SNIPPET_MAX // 2, len(line) - SNIPPET_MAX))
        line = ("..." if start else "") + line[start:start + SNIPPET_MAX] + ("..." if start + SNIPPET_MAX < len(line) else "")
    if scan_text(line):
        return WITHHELD
    return line


def _search_doc(d: _Doc, terms: List[str]) -> Optional[Dict[str, Any]]:
    sf = d.sf
    title = sf.path.stem if _is_md(sf) else sf.path.name
    typ = _type_of(d)
    ok = d.fm is not None and d.fm.status == "ok"
    aliases = _as_list(d.fm.data.get("aliases")) if ok else []
    tags = _as_list(d.fm.data.get("tags")) if ok else []
    # (rank, text, line number or None) for each searchable piece, best field first
    pieces: List[Tuple[str, str, Optional[int]]] = [("title", title, None)]
    pieces += [("alias", a, None) for a in aliases]
    pieces += [("tag", t, None) for t in tags]
    lines: List[str] = []
    body_from = 0
    if d.text is not None:
        lines = _lines(d.text)
        if d.fm is not None and d.fm.status != "malformed" and d.fm.end_line > 0:
            body_from = d.fm.end_line
        for i in range(0, body_from):
            pieces.append(("frontmatter", lines[i], i + 1))
        headings = extract_headings(d.text)
        heading_lines = {h.line for h in headings}
        for h in headings:
            pieces.append(("heading", h.text, h.line))
        for i in range(body_from, len(lines)):
            if i + 1 not in heading_lines:
                pieces.append(("body", lines[i], i + 1))
    else:
        headings = []
    best: Optional[Tuple[int, str, Optional[int], str, int]] = None  # rank, field, line, text, match index
    ranks: List[int] = []
    for term in terms:
        found = None
        for fld, text, line in pieces:
            idx = norm_name(text).find(term)
            if idx >= 0 and (found is None or _FIELD_RANK[fld] < found[0]):
                found = (_FIELD_RANK[fld], fld, line, text, idx)
                if found[0] == 0:
                    break
        if found is None:
            return None
        ranks.append(found[0])
        if best is None or found[0] < best[0]:
            best = found
    assert best is not None
    rank, fld, line, text, idx = best
    heading = ""
    if line is not None and d.text is not None:
        before = [h for h in headings if h.line <= line]
        if before:
            heading = before[-1].text
            if scan_text(heading):
                heading = WITHHELD
    if fld in ("title", "alias", "tag"):
        snippet = ""
        for i in range(body_from, len(lines)):
            if lines[i].strip():
                snippet = _safe_line(lines[i], 0)
                break
    else:
        snippet = _safe_line(text, idx)
    return {"path": sf.rel, "type": typ, "field": fld, "heading": heading, "snippet": snippet,
            "_key": (min(ranks), sum(ranks), sf.rel)}


def search(root, query: str, limit: int = 10, type_filter: Optional[str] = None,
           tag_filter: Optional[str] = None) -> Dict[str, Any]:
    root = Path(root)
    check_vault(root)
    terms = [norm_name(t) for t in query.split()]
    if not terms:
        raise LintError("empty query")
    want_type = norm_name(type_filter) if type_filter else None
    want_tag = _norm_tag(tag_filter) if tag_filter else None
    hits = []
    for d in _load_docs(root):
        if d.sf.area == "inbox":
            continue
        if want_type is not None and norm_name(_type_of(d)) != want_type:
            continue
        if want_tag is not None:
            ok = d.fm is not None and d.fm.status == "ok"
            if not ok or want_tag not in [_norm_tag(t) for t in _as_list(d.fm.data.get("tags"))]:
                continue
        hit = _search_doc(d, terms)
        if hit is not None:
            hits.append(hit)
    hits.sort(key=lambda h: h["_key"])
    for h in hits:
        del h["_key"]
    return {"query": query, "total": len(hits), "shown": min(limit, len(hits)), "hits": hits[:limit]}


def format_search(data: Dict[str, Any]) -> str:
    if not data["hits"]:
        return "No matches."
    out = []
    for h in data["hits"]:
        out.append(f"{h['path']}  [{h['type']}]  {h['field']}")
        where = (h["heading"] + ": " if h["heading"] else "") + h["snippet"]
        if where.strip():
            out.append("    " + where)
    if data["shown"] < data["total"]:
        out.append(f"{data['shown']} of {data['total']} shown")
    return "\n".join(out)


def _link_text(link: Link) -> str:
    inner = link.name + ("#" + link.anchor if link.anchor else "") + ("|" + link.label if link.label else "")
    text = ("!" if link.embed else "") + "[[" + inner + "]]"
    return WITHHELD if scan_text(text) else text


def _raw_links(text: str) -> List[Link]:
    links: List[Link] = []
    for i, line in enumerate(_lines(text)):
        links.extend(_links_in(line.rstrip("\r"), i + 1))
    return links


def _dangling_key(name: str) -> str:
    key = norm_name(name.strip().strip("/").rsplit("/", 1)[-1])
    return key[:-3] if key.endswith(".md") else key


def backlinks(root, name: str) -> Tuple[int, List[str]]:
    """Return (exit code, output lines)."""
    root = Path(root)
    check_vault(root)
    if not name.strip():
        raise LintError("empty name")
    docs = _load_docs(root)
    outside = [d.sf for d in docs if d.sf.area != "inbox"]
    index = _Index(outside, {})
    status, target = index.resolve(name)
    if status == "ambiguous":
        n = name.strip().strip("/")
        if "/" in n:
            p = norm_name(n)
            cands = [rel for rel, r, rs in index.rel_keys
                     if r == p or rs == p or r.endswith("/" + p) or rs.endswith("/" + p)]
        else:
            cands = list(index.by_key.get(norm_name(n), []))
        return 1, ["Ambiguous name: " + name, "Candidates:"] + ["  " + c for c in sorted(cands)]
    want = _dangling_key(name)
    rows: List[str] = []
    for d in docs:
        if d.text is None:
            continue
        raw = d.fm is not None and d.fm.status == "malformed"
        for link in (_raw_links(d.text) if raw else extract_links(d.text)):
            if not link.name:
                continue
            if status == "ok":
                st, tgt = index.resolve(link.name)
                if st != "ok" or tgt != target or d.sf.rel == target:
                    continue
            elif _dangling_key(link.name) != want:
                continue
            parts = [f"{d.sf.rel}:{link.line}", _link_text(link)]
            if link.label:
                parts.append("text: " + (WITHHELD if scan_text(link.label) else link.label))
            if link.anchor:
                parts.append("heading: " + (WITHHELD if scan_text(link.anchor) else link.anchor))
            if raw:
                parts.append("raw")
            rows.append("  ".join(parts))
    if status == "ok":
        if rows:
            return 0, ["Backlinks to " + str(target) + " (" + str(len(rows)) + "):"] + rows
        return 0, ["No backlinks to " + str(target) + "."]
    if rows:
        return 0, ["Target not found: " + name + "; links to it (" + str(len(rows)) + "):"] + rows
    return 1, ["Target not found: " + name + ", and nothing links to it."]


def _non_negative_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number of days") from None
    if n < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return n


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb.py", description="Deterministic helpers for the second-brain vault.")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="vault root (default: the parent of scripts/)")
    lp = sub.add_parser(
        "lint", parents=[common], help="check the vault; never modifies files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Check the vault. Never modifies files.\n"
            "Levels are shown separately: ERROR, WARNING, REVIEW and (with --pending) PENDING.\n"
            "Exit 1 only if there is an ERROR; warnings and review items never change the exit code.\n"
            "\n"
            "'updated' means the last knowledge-text or link change; it is not the last review\n"
            "or access. Claude sets it. Whitespace, formatting and tags/aliases/confidence/standalone\n"
            "edits do not move it. A REVIEW item for an old 'updated' says the note\n"
            "needs human review. Stale does not mean obsolete or incorrect.\n"
            "\n"
            "The secret scan is a safety net, not comprehensive; matched text is never printed."))
    lp.add_argument("--stale-days", type=_non_negative_int, default=365, metavar="N",
                    help="R01: 'updated' older than N days needs human review (default 365)")
    lp.add_argument("--inbox-days", type=_non_negative_int, default=14, metavar="N",
                    help="W06: a capture older than N days is flagged (default 14)")
    lp.add_argument("--pending", action="append", metavar="FILENAME",
                    help="treat an unresolved link or companion reference to this one non-Markdown file as PENDING")
    lp.add_argument("--json", action="store_true", help="machine-readable output")
    sp = sub.add_parser("search", parents=[common], help="search notes, projects, sources and index.md; never modifies files",
                        description="Case-insensitive search; every word must match. Ranks title, alias, tag, heading, "
                                    "frontmatter, then body. A snippet that looks like a secret is withheld. "
                                    "Captures in inbox/ are not searched.")
    sp.add_argument("query", help="words to find (all must match)")
    sp.add_argument("--limit", type=_positive_int, default=10, metavar="N", help="show at most N hits (default 10)")
    sp.add_argument("--type", dest="type_filter", metavar="TYPE", help="only this frontmatter type, or (none) or (invalid)")
    sp.add_argument("--tag", dest="tag_filter", metavar="TAG", help="only notes with this tag")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    bp = sub.add_parser("backlinks", parents=[common], help="list the files that link to a name; never modifies files",
                        description="List file:line of every wikilink or embed to NAME (basename or path), including "
                                    "frontmatter links, captures and a dangling target. A note with malformed "
                                    "frontmatter is scanned as raw text and marked raw. "
                                    "Exit 1 if NAME is not found and nothing links to it.")
    bp.add_argument("name", help="file name or path, with or without .md")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "lint":
        pending = None
        if args.pending:
            if len(args.pending) > 1:
                parser.error("--pending may be given only once")
            pending = args.pending[0]
        try:
            root = Path(args.root) if args.root else default_root()
            res = lint(root, pending=pending, stale_days=args.stale_days, inbox_days=args.inbox_days)
        except LintError as exc:
            print("kb.py: error: " + str(exc), file=sys.stderr)
            return 2
        except Exception as exc:  # never echo exception text: it could contain file content
            print("kb.py: internal error (" + type(exc).__name__ + ")", file=sys.stderr)
            return 2
        print(format_json(res) if args.json else format_text(res, pending is not None))
        return 1 if any(f.level == "ERROR" for f in res.findings) else 0
    if args.command in ("search", "backlinks"):
        try:
            root = Path(args.root) if args.root else default_root()
            if args.command == "search":
                data = search(root, args.query, args.limit, args.type_filter, args.tag_filter)
                print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_search(data))
                return 0
            code, lines = backlinks(root, args.name)
            print("\n".join(lines))
            return code
        except LintError as exc:
            print("kb.py: error: " + str(exc), file=sys.stderr)
            return 2
        except Exception as exc:  # never echo exception text: it could contain file content
            print("kb.py: internal error (" + type(exc).__name__ + ")", file=sys.stderr)
            return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
