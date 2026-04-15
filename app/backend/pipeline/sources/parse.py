"""
libby_pipeline/parse.py — Source parsers for all input files
Version 1.0

Returns a unified staging dict:
{
  "books": [BookRecord, ...],
  "unresolved": [UnresolvedRecord, ...],
  "favorites_titles": set(),       # normalized titles from Favorites.md
  "gbooks_status": {title: status},
  "gbooks_favorites": set(),
  "summaries": {title: gdoc_url},
  "curated_annotations": {title: annotation},
  "curated_topics": {title: [topic_name, ...]},
}
"""

import re
import pdfplumber
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BookRecord:
    title: str
    author: str
    url: str                          # original URL (tinyurl preserved)
    tags: list[str] = field(default_factory=list)
    source: str = ""
    priority: str = "medium"          # high / medium / low
    status: str = "unread"            # read / unread / reading
    amazon_url: str = ""              # populated by resolve_urls phase
    comments: str = ""               # brief annotation
    topics: list[str] = field(default_factory=list)
    gdoc_summary_id: str = ""
    summary_path: str = ""
    highlights_path: str = ""


@dataclass
class UnresolvedRecord:
    name: str
    author: str
    url: str
    raw_tags: str
    source: str
    raw_line: str
    notes: str = ""


# ── Normalisation helpers ─────────────────────────────────────────────────────

def normalize_title(title: str) -> str:
    """Lowercase, strip subtitle after ':', strip punctuation for matching."""
    title = title.split(":")[0]
    title = re.sub(r"[^\w\s]", "", title)
    return title.strip().lower()


def normalize_author(author: str) -> str:
    return author.strip().lower()


def extract_gdoc_id(url: str) -> str:
    """Extract Google Drive doc ID from a Drive URL."""
    m = re.search(r"/d/([a-zA-Z0-9_-]{20,})", url)
    return m.group(1) if m else ""


# ── ground_truth.txt ──────────────────────────────────────────────────────────

GROUND_TRUTH_SEP = "⎯"

def parse_ground_truth(path: Path) -> tuple[list[BookRecord], list[UnresolvedRecord]]:
    """
    Format: title ⎯ author ⎯ url ⎯ #tag1 #tag2 ...
    Some entries use comma-separated tags instead of #hash format.
    """
    books = []
    unresolved = []
    malformed = 0

    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            parts = [p.strip() for p in line.split(GROUND_TRUTH_SEP)]
            if len(parts) < 3:
                malformed += 1
                continue

            title  = parts[0]
            author = parts[1]
            url    = parts[2]
            tags_raw = parts[3] if len(parts) > 3 else ""

            # Normalise tags — handle both #tag and comma formats
            tags = re.findall(r"#([a-zA-Z0-9_-]+)", tags_raw)
            if not tags:
                tags = [t.strip().lstrip("#") for t in tags_raw.split(",") if t.strip()]

            is_book = (
                "#book" in tags_raw or
                "book" in [t.lower() for t in tags] or
                "#books" in tags_raw
            )

            if is_book:
                priority = "high" if "STVFavorite" in tags else "medium"
                record = BookRecord(
                    title=title,
                    author=author,
                    url=url,
                    tags=tags,
                    source="ground_truth",
                    priority=priority,
                )
                books.append(record)
            elif any(t in tags_raw for t in ["#article", "#website", "#podcast", "#tool"]):
                unresolved.append(UnresolvedRecord(
                    name=title,
                    author=author,
                    url=url,
                    raw_tags=tags_raw,
                    source="ground_truth",
                    raw_line=line,
                ))
            else:
                # Unknown type — goes to unresolved for review
                unresolved.append(UnresolvedRecord(
                    name=title,
                    author=author,
                    url=url,
                    raw_tags=tags_raw,
                    source="ground_truth",
                    raw_line=line,
                ))

    print(f"  ground_truth: {len(books)} books, {len(unresolved)} unresolved, {malformed} malformed")
    return books, unresolved


# ── Favorites.md ──────────────────────────────────────────────────────────────

def parse_favorites(path: Path) -> set[str]:
    """Return set of normalized titles. All are read + high priority."""
    titles = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            # Match markdown list items with links: * [Title](url) by Author
            m = re.match(r"\*\s+\[([^\]]+)\]", line)
            if m:
                titles.add(normalize_title(m.group(1)))
    print(f"  Favorites.md: {len(titles)} titles")
    return titles


# ── Google Books PDF ──────────────────────────────────────────────────────────

GBOOKS_STATUS_TOKENS = {"Have read", "To read", "Reading now", "Favorites"}

def parse_google_books_pdf(path: Path) -> tuple[dict[str, str], set[str]]:
    """
    Returns:
      status_map: {normalized_title: status}  ('read'/'unread'/'reading')
      favorites:  set of normalized titles marked Favorites
    """
    status_map = {}
    favorites  = set()

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Each entry block: title line, author line, tags line, year line
            # Tags line contains comma-separated: "biography, history, Have read, Favorites"
            # We look for lines containing status tokens
            lines = text.split("\n")
            current_title = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Heuristic: title lines start with a digit (row number)
                if re.match(r"^\d+$", line):
                    current_title = None
                    continue
                # Lines that contain status tokens are tag lines
                has_status = any(tok in line for tok in GBOOKS_STATUS_TOKENS)
                if has_status and current_title:
                    norm = normalize_title(current_title)
                    if "Have read" in line:
                        status_map[norm] = "read"
                    elif "Reading now" in line:
                        status_map[norm] = "reading"
                    else:
                        status_map.setdefault(norm, "unread")
                    if "Favorites" in line:
                        favorites.add(norm)
                    current_title = None
                elif not has_status and current_title is None:
                    # Candidate title line — store tentatively
                    # Skip known non-title patterns
                    if not re.match(r"^(Books|Search|YOUR LIBRARY|All books|biography|mystery|history|Create|More|CLASSIC|Back to|Classic Google)", line):
                        current_title = line

    print(f"  Google Books PDF: {len(status_map)} status entries, {len(favorites)} favorites")
    return status_map, favorites


# ── Summaries.md ──────────────────────────────────────────────────────────────

def parse_summaries(path: Path) -> dict[str, str]:
    """
    Returns {normalized_title: gdoc_url} for entries with Google Drive links.
    """
    summaries = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            # Match: * [Title](drive.google.com/...) or [Title](docs.google.com/...)
            m = re.match(r"\*\s+\[([^\]]+)\]\((https://(?:drive|docs)\.google\.com[^\)]+)\)", line)
            if m:
                title = normalize_title(m.group(1))
                url   = m.group(2)
                summaries[title] = url
    print(f"  Summaries.md: {len(summaries)} Drive-linked summaries")
    return summaries


# ── Curated.md ────────────────────────────────────────────────────────────────

def parse_curated(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """
    Returns:
      annotations: {normalized_title: annotation_text}
      topic_map:   {normalized_title: [topic_heading, ...]}
    """
    annotations = {}
    topic_map   = {}
    current_topic = None

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Heading detection — topic sections
        if line.startswith("#"):
            current_topic = re.sub(r"^#+\s*", "", line)
            current_topic = re.sub(r"\s*\{.*\}", "", current_topic).strip()
            i += 1
            continue

        # List item with link
        m = re.match(r"\*\s+\[([^\]]+)\]", line)
        if m and current_topic:
            title = normalize_title(m.group(1))
            # Collect annotation: remainder of this line + next non-list lines
            annotation_parts = []
            after_link = re.sub(r"\*\s+\[[^\]]+\]\([^\)]*\)\s*", "", line).strip()
            # Strip "by Author" prefix
            after_link = re.sub(r"^by [^.]+\.\s*", "", after_link).strip()
            if after_link:
                annotation_parts.append(after_link)

            # Look ahead for continuation lines (indented or plain text, not another list item)
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line or next_line.startswith("*") or next_line.startswith("#"):
                    break
                annotation_parts.append(next_line)
                j += 1

            annotation = " ".join(annotation_parts).strip()
            if annotation:
                annotations[title] = annotation[:500]  # cap at 500 chars

            topic_map.setdefault(title, [])
            if current_topic not in topic_map[title]:
                topic_map[title].append(current_topic)

        i += 1

    print(f"  Curated.md: {len(annotations)} annotations, {len(topic_map)} topic assignments")
    return annotations, topic_map


# ── Master entry point ────────────────────────────────────────────────────────

def parse_all_sources(config: dict) -> dict:
    print("Parsing sources...")

    books_gt, unresolved_gt = parse_ground_truth(config["ground_truth"])
    favorites_titles = parse_favorites(config["favorites_md"])
    gbooks_status, gbooks_favorites = parse_google_books_pdf(config["gbooks_pdf"])
    summaries = parse_summaries(config["summaries_md"])
    curated_annotations, curated_topics = parse_curated(config["curated_md"])

    # Apply favorites + Google Books status back onto ground_truth books
    for book in books_gt:
        norm = normalize_title(book.title)
        # Status: Google Books wins, then Favorites (all read)
        if norm in gbooks_status:
            book.status = gbooks_status[norm]
        elif norm in favorites_titles:
            book.status = "read"
        # Priority: STVFavorite already set; Google Favorites or Favorites.md → high
        if norm in gbooks_favorites or norm in favorites_titles:
            book.priority = "high"
        # Annotations from Curated
        if norm in curated_annotations:
            book.comments = curated_annotations[norm]
        # Topics from Curated
        if norm in curated_topics:
            book.topics = curated_topics[norm]
        # Summary Drive link
        if norm in summaries:
            book.gdoc_summary_id = extract_gdoc_id(summaries[norm])

    return {
        "books": books_gt,
        "unresolved": unresolved_gt,
        "favorites_titles": favorites_titles,
        "gbooks_status": gbooks_status,
        "gbooks_favorites": gbooks_favorites,
        "summaries": summaries,
        "curated_annotations": curated_annotations,
        "curated_topics": curated_topics,
    }
