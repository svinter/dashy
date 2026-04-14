"""Parse Quotes.md and seed library_entries with type_code='q'.

Usage (run from app/backend/):
    venv/bin/python scripts/parse_quotes.py [--dry-run] [--file PATH]

Default input: vault's 5 Philosophy/Quotes.md (falls back to 7 Miscellaneous/Quotes.md)
Output (unmatched): /tmp/quotes_unmatched.md

Formats recognised (single-line only):
  A)  - "text" — Author            (em/en dash attribution)
  B)  - "text" – Author            (en dash)
  C)  - "text" - Author            (hyphen, space-separated)
  D)  - "text" by **Author**       (bold by)
  E)  - "text" by [[Author]]       (wikilink by)
  F)  - __text__ — Author          (underscored, dash)
  G)  - __text__ by [[Author]]     (underscored, wikilink)
  H)  - __text__ ** – Author**     (underscored, bold+dash)
  I)  - __text__ – **Author**      (underscored, dash+bold)
  J)  - __text__ by **Author**     (underscored, bold by)
  K)  ##### N. "text"              (numbered heading under book section)
  L)  - "text"                     (under named-person section → section attribution)
  M)  "text" — Author              (no leading dash)

Section attribution: quotes with no inline attribution inherit
the person/source from the most recent "# From X" or "# Quotes from X" heading.
"""

import re
import sys
import os
import sqlite3
import argparse
import logging
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "dashboard.db"
UNMATCHED_PATH = Path("/tmp/quotes_unmatched.md")

VAULT = Path.home() / "Obsidian" / "MyNotes"
DEFAULT_FILES = [
    VAULT / "5 Philosophy" / "Quotes.md",
    VAULT / "7 Miscellaneous" / "Quotes.md",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Quote:
    text: str
    attribution: str
    context: str          # section heading
    tags: list[str] = field(default_factory=list)
    source_file: str = ""
    source_line: int = 0


@dataclass
class Unmatched:
    reason: str           # "unattributed" | "multi-line" | "malformed"
    raw: str
    context: str
    source_line: int = 0
    detail: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Obsidian wikilink: [[Path/To/Name]] → "Name"
_WIKILINK_RE = re.compile(r"\[\[(?:[^\]|#^]*/)?([^\]|#^]+?)(?:\|[^\]]+)?\]\]")
# Bold: **text** or __text__
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_UNDER_RE = re.compile(r"__(.+?)__")

def clean_author(raw: str) -> str:
    """Strip wikilink brackets, bold markers, leading dashes and whitespace."""
    s = raw.strip()
    # Replace [[Path/Name]] → Name
    s = _WIKILINK_RE.sub(lambda m: m.group(1).strip(), s)
    # Replace **Name** → Name
    s = _BOLD_RE.sub(lambda m: m.group(1).strip(), s)
    # Strip remaining * and _ markers
    s = s.replace("*", "").replace("_", "")
    # Strip path prefixes like "1 People/Person/"
    if "/" in s:
        s = s.split("/")[-1].strip()
    # Strip leading dashes and spaces
    s = s.lstrip("–—-").strip()
    return s.strip()


def clean_text(raw: str) -> str:
    """Strip surrounding quotes, __ markers, leading/trailing whitespace."""
    s = raw.strip()
    # Remove __...__ wrapper
    m = re.fullmatch(r"__(.+?)__", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    # Remove surrounding "..." or "..."
    for open_q, close_q in [('"', '"'), ('"', '"'), ('"', '"')]:
        if s.startswith(open_q) and s.endswith(close_q) and len(s) > 2:
            s = s[len(open_q):-len(close_q)].strip()
            break
    if s.startswith('"') and s.endswith('"') and len(s) > 2:
        s = s[1:-1].strip()
    return s


def extract_tags(line: str) -> list[str]:
    return re.findall(r"#(\w+)", line)


def extract_section_attribution(heading: str) -> str | None:
    """
    '# From coaching with [[Sharna Fey]]' → 'Sharna Fey'
    '# Quotes from Same as Ever'          → 'Morgan Housel'  (handled separately)
    Returns None if section has no clear person attribution.
    """
    # Named person in wikilink or plain text after "with"
    m = re.search(r"[Ff]rom\s+(?:coaching\s+with\s+)?\[\[(.+?)\]\]", heading)
    if m:
        return clean_author(m.group(1))
    m = re.search(r"[Ff]rom\s+(?:coaching\s+with\s+)(.+)$", heading)
    if m:
        return clean_author(m.group(1).strip())
    # "Quotes from <book>" — return None (no person), leave for section_context
    return None


# ---------------------------------------------------------------------------
# Attribution patterns (ordered: most specific first)
# ---------------------------------------------------------------------------

# Dash variants for em/en/hyphen: —–-
_DASHES = r"(?:—|–|⎯|\s[-–—]\s?)"

# Pattern A/B/C: "text" — Author  or  "text" – Author  or  "text" - Author
_PAT_QUOTED_DASH = re.compile(
    r'^[\s\-\*]*'                          # optional list marker
    r'(?:__)?'                             # optional __
    r'["\u201c\u201d](.+?)["\u201c\u201d]'  # quoted text
    r'(?:__)?'                             # optional __
    r'\s*(?:—|–|⎯|\s[–—-])\s*'           # dash
    r'(.+)$'                               # attribution
)

# Pattern D/E: "text" by **Author** or "text" by [[Author]]
_PAT_QUOTED_BY = re.compile(
    r'^[\s\-\*]*'
    r'["\u201c\u201d](.+?)["\u201c\u201d]'
    r'\s+by\s+'
    r'(.+)$'
)

# Pattern F/G/H/I/J: __text__ — Author  |  __text__ by [[Author]]  |  __text__ ** – Author**
_PAT_UNDER_DASH = re.compile(
    r'^[\s\-\*]*'
    r'__(.+?)__'
    r'\s*(?:—|–|⎯|\s[–—-])\s*'
    r'(.+)$'
)

_PAT_UNDER_BY = re.compile(
    r'^[\s\-\*]*'
    r'__(.+?)__'
    r'\s+by\s+'
    r'(.+)$'
)

_PAT_UNDER_BOLDASH = re.compile(
    r'^[\s\-\*]*'
    r'__(.+?)__'
    r'\s*\*\*\s*[–—-]\s*(.+?)\*\*\s*$'
)

# Pattern K: ##### N. "text"  (numbered headings — book sections)
_PAT_NUMBERED_HEADING = re.compile(
    r'^#{1,6}\s+\d+\.\s+["\u201c\u201d](.+?)["\u201c\u201d]\s*$'
)

# Pattern M: "text" — Author  (no list marker)
_PAT_BARE_QUOTED_DASH = re.compile(
    r'^["\u201c\u201d](.+?)["\u201c\u201d]'
    r'\s*(?:—|–|⎯)\s*'
    r'(.+)$'
)

# Unattributed quoted line (for section-attribution)
_PAT_UNATTR_QUOTED = re.compile(
    r'^[\s\-\*]*["\u201c\u201d](.+?)["\u201c\u201d]\s*(?:#\w+\s*)*$'
)

# Unattributed underscored line
_PAT_UNATTR_UNDER = re.compile(
    r'^[\s\-\*]*__(.+?)__\s*(?:#\w+\s*)*$'
)


def try_parse_line(line: str) -> tuple[str, str] | None:
    """
    Returns (text, raw_attribution) if line matches any attributed pattern, else None.
    raw_attribution still needs clean_author() applied.
    """
    for pat in [
        _PAT_QUOTED_DASH,
        _PAT_QUOTED_BY,
        _PAT_UNDER_DASH,
        _PAT_UNDER_BY,
        _PAT_UNDER_BOLDASH,
        _PAT_BARE_QUOTED_DASH,
    ]:
        m = pat.match(line)
        if m:
            return m.group(1).strip(), m.group(2).strip()

    # Numbered heading (K) — no inline attribution, handled by section context
    # Returns text only, attribution handled externally
    return None


def is_quote_line(line: str) -> bool:
    """True if line looks like it contains a quote."""
    stripped = line.strip()
    return bool(
        re.search(r'["\u201c\u201d]', stripped)
        or re.match(r'[\s\-\*]*__', stripped)
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_file(path: Path, seen_texts: set[str]) -> tuple[list[Quote], list[Unmatched]]:
    quotes: list[Quote] = []
    unmatched: list[Unmatched] = []

    lines = path.read_text(encoding="utf-8").splitlines()
    section = ""                    # current heading text
    section_person: str | None = None  # person name if section is "From X with Y"
    section_is_book = False         # True for "Quotes from <Book>" sections

    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        lineno = i + 1

        # --- Heading: update section context ---
        if re.match(r"^#{1,6}\s", stripped):
            heading_text = re.sub(r"^#{1,6}\s+", "", stripped)
            # Strip wikilinks for display
            section = _WIKILINK_RE.sub(lambda m: m.group(1), heading_text).strip()
            section_person = extract_section_attribution(stripped)
            section_is_book = bool(
                re.search(r"[Qq]uotes?\s+from\b", stripped)
                and not re.search(r"coaching\s+with", stripped)
            )

            # Numbered heading = a quote from the book section
            m = _PAT_NUMBERED_HEADING.match(stripped)
            if m and section_is_book:
                text = clean_text(m.group(1))
                if text and text not in seen_texts:
                    # Attribution comes from section context (e.g. Morgan Housel for Same as Ever)
                    book_author = "Morgan Housel" if "Same as Ever" in section else section.strip()
                    tags = extract_tags(stripped)
                    quotes.append(Quote(
                        text=text,
                        attribution=book_author,
                        context=section,
                        tags=tags,
                        source_file=str(path),
                        source_line=lineno,
                    ))
                    seen_texts.add(text)
            i += 1
            continue

        # Skip frontmatter, blank lines, non-quote lines
        if not stripped or stripped.startswith("---") or stripped.startswith("{{"):
            i += 1
            continue

        # Skip reference links, image embeds, HTML, plain prose
        if (
            re.match(r"^[-*]\s+\[", stripped)       # reference link
            or re.match(r"^!\[", stripped)           # image
            or re.match(r"^\s*[*-]\s+History", stripped)  # prose commentary
        ):
            i += 1
            continue

        # --- Numbered heading in current line (some files use ##### at body level) ---
        m = _PAT_NUMBERED_HEADING.match(stripped)
        if m:
            text = clean_text(m.group(1))
            if text and text not in seen_texts:
                attribution = section_person or section or ""
                tags = extract_tags(stripped)
                if attribution:
                    quotes.append(Quote(
                        text=text,
                        attribution=attribution,
                        context=section,
                        tags=tags,
                        source_file=str(path),
                        source_line=lineno,
                    ))
                    seen_texts.add(text)
                else:
                    unmatched.append(Unmatched(
                        reason="unattributed",
                        raw=stripped,
                        context=section,
                        source_line=lineno,
                        detail="numbered heading, no section person",
                    ))
            i += 1
            continue

        # --- Multi-line check: if line ends without closing quote but has opening ---
        # Simple heuristic: if the line has an odd number of quotes, it might be multi-line.
        # We handle this by requiring quotes to close on the same line.
        if not is_quote_line(stripped):
            i += 1
            continue

        # --- Try inline-attributed patterns first ---
        result = try_parse_line(stripped)
        if result:
            raw_text, raw_attr = result
            text = clean_text(raw_text)
            attribution = clean_author(raw_attr)
            # Ignore "unknown" attribution
            if attribution.lower() in ("unknown", ""):
                unmatched.append(Unmatched(
                    reason="unattributed",
                    raw=stripped,
                    context=section,
                    source_line=lineno,
                    detail="attribution is 'unknown'",
                ))
                i += 1
                continue
            if text and attribution and text not in seen_texts:
                tags = extract_tags(stripped)
                quotes.append(Quote(
                    text=text,
                    attribution=attribution,
                    context=section,
                    tags=tags,
                    source_file=str(path),
                    source_line=lineno,
                ))
                seen_texts.add(text)
            i += 1
            continue

        # --- Unattributed quoted line: try section attribution ---
        m_uq = _PAT_UNATTR_QUOTED.match(stripped)
        m_uu = _PAT_UNATTR_UNDER.match(stripped)

        if m_uq or m_uu:
            raw_text = (m_uq or m_uu).group(1)
            text = clean_text(raw_text)

            if not text:
                i += 1
                continue

            if text in seen_texts:
                i += 1
                continue

            attribution = section_person or ""

            if attribution:
                tags = extract_tags(stripped)
                quotes.append(Quote(
                    text=text,
                    attribution=attribution,
                    context=section,
                    tags=tags,
                    source_file=str(path),
                    source_line=lineno,
                ))
                seen_texts.add(text)
            else:
                # Could be unattributed OR from a named section we don't recognise
                unmatched.append(Unmatched(
                    reason="unattributed",
                    raw=stripped,
                    context=section,
                    source_line=lineno,
                ))

        i += 1

    return quotes, unmatched


# ---------------------------------------------------------------------------
# DB insert
# ---------------------------------------------------------------------------

def name_from_text(text: str) -> str:
    if len(text) <= 60:
        return text
    return text[:59].rstrip() + "…"


def insert_quotes(quotes: list[Quote], db: sqlite3.Connection) -> int:
    # Ensure library_quotes type is registered
    q_row = db.execute("SELECT table_name FROM library_types WHERE code = 'q'").fetchone()
    if not q_row:
        logger.error("Type 'q' not registered in library_types")
        return 0

    table_name = q_row[0]
    inserted = 0

    for q in quotes:
        comments = f'"{q.text}" — {q.attribution}'
        name = name_from_text(q.text)

        # Deduplicate by name (first 60 chars of text)
        existing = db.execute(
            "SELECT id FROM library_entries WHERE name = ? AND type_code = 'q'",
            (name,),
        ).fetchone()
        if existing:
            logger.debug("Skip duplicate quote: %r", name[:40])
            continue

        # Insert entity row
        cur = db.execute(f"INSERT INTO {table_name} (id) VALUES (NULL)")
        entity_id = cur.lastrowid

        # Insert entry (needs_enrichment=0 for quotes)
        db.execute(
            """INSERT INTO library_entries
               (name, type_code, comments, priority, entity_id,
                needs_enrichment, created_at, updated_at)
               VALUES (?, 'q', ?, 'medium', ?, 0, datetime('now'), datetime('now'))""",
            (name, comments, entity_id),
        )
        inserted += 1

    db.commit()
    return inserted


# ---------------------------------------------------------------------------
# Unmatched output
# ---------------------------------------------------------------------------

def write_unmatched(unmatched: list[Unmatched], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Unmatched Quotes — Review Required",
        "*Generated by parse_quotes.py — quotes not loaded into Libby*",
        "",
    ]

    by_reason: dict[str, list[Unmatched]] = {}
    for u in unmatched:
        by_reason.setdefault(u.reason, []).append(u)

    section_titles = {
        "unattributed": "Unattributed",
        "multi-line": "Multi-line",
        "malformed": "Malformed",
    }

    for reason, title in section_titles.items():
        items = by_reason.get(reason, [])
        if not items:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for u in items:
            detail_part = f" *({u.detail})*" if u.detail else ""
            lines.append(
                f'- "{u.raw[:120]}" '
                f'*(section: {u.context}, line {u.source_line})*'
                f'{detail_part}'
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Unmatched quotes written to %s", path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Quotes.md and seed Libby")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", help="Path to Quotes.md (overrides default)")
    args = parser.parse_args()

    # Resolve input files
    if args.file:
        input_files = [Path(args.file)]
    else:
        input_files = [f for f in DEFAULT_FILES if f.exists()]

    if not input_files:
        logger.error("No Quotes.md found. Use --file to specify path.")
        sys.exit(1)

    logger.info("Parsing %d file(s): %s", len(input_files), [str(f) for f in input_files])

    seen_texts: set[str] = set()
    all_quotes: list[Quote] = []
    all_unmatched: list[Unmatched] = []

    for f in input_files:
        quotes, unmatched = parse_file(f, seen_texts)
        all_quotes.extend(quotes)
        all_unmatched.extend(unmatched)
        logger.info("%s: %d quotes, %d unmatched", f.name, len(quotes), len(unmatched))

    # Write unmatched
    write_unmatched(all_unmatched, UNMATCHED_PATH)

    if args.dry_run:
        print(f"\n── Dry run ──────────────────────────────")
        print(f"  Quotes parsed:    {len(all_quotes)}")
        print(f"  Unmatched:        {len(all_unmatched)}")
        print(f"  Unmatched file:   {UNMATCHED_PATH}")
        for q in all_quotes[:10]:
            print(f"    [{q.attribution}] {q.text[:60]!r}")
        return

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    inserted = insert_quotes(all_quotes, db)
    db.close()

    print(f"\n── Quote seed results ────────────────────")
    print(f"  Quotes parsed:    {len(all_quotes)}")
    print(f"  Inserted:         {inserted}")
    print(f"  Duplicates/skip:  {len(all_quotes) - inserted}")
    print(f"  Unmatched:        {len(all_unmatched)}")
    print(f"  Unmatched file:   {UNMATCHED_PATH}")


if __name__ == "__main__":
    main()
