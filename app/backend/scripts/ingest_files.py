"""Process all files in the Libby Staging folder, creating Libby entries + vault stubs.

Triggered by Keyboard Maestro when files land in the Staging folder.

Usage:
    cd /Users/stevevinter/dashy/app/backend
    source venv/bin/activate
    python scripts/ingest_files.py
"""

import re
import shutil
import sys
from datetime import date
from pathlib import Path

# ── Path bootstrap ──────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent.parent  # app/backend
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from app_config import load_config
from database import get_write_db, get_db
from connectors.obsidian import get_vault_path, get_vault_name


# ── Config ──────────────────────────────────────────────────────────────────

def _load_libby_config() -> dict:
    cfg = load_config().get("libby", {})
    return cfg


def _expand(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"[-_]+", " ", stem).strip()


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")[:80]


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text. Returns (fm_dict, body_text)."""
    import re as _re
    try:
        import yaml
    except ImportError:
        yaml = None  # type: ignore

    m = _re.match(r"^---\s*\n(.*?)\n---\s*\n", text, _re.DOTALL)
    if m:
        fm_text = m.group(1)
        body = text[m.end():]
        if yaml:
            try:
                fm = yaml.safe_load(fm_text) or {}
            except Exception:
                fm = {}
        else:
            # Minimal key:value parser fallback
            fm = {}
            for line in fm_text.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
    else:
        fm = {}
        body = text
    return fm, body


def _first_paragraph(text: str) -> str:
    for para in text.strip().split("\n\n"):
        stripped = para.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:300]
    return ""


def _create_vault_stub(
    vault: Path,
    vault_name: str,
    inbox_folder: str,
    filename_stem: str,
    frontmatter: dict,
    body: str = "",
) -> str:
    """Write a vault stub in the inbox folder. Returns obsidian:// link."""
    from urllib.parse import quote

    folder_path = vault / inbox_folder
    folder_path.mkdir(parents=True, exist_ok=True)

    safe_stem = _safe_filename(filename_stem)
    note_path = folder_path / f"{safe_stem}.md"

    # Build YAML frontmatter string
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, bool):
            fm_lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, list):
            fm_lines.append(f"{k}: {v!r}")
        else:
            fm_lines.append(f"{k}: \"{v}\"")
    fm_lines.append("---")
    fm_lines.append("")

    content = "\n".join(fm_lines)
    if body:
        content += "\n" + body
    else:
        content += "\n## Notes\n\n"

    if not note_path.exists():
        note_path.write_text(content, encoding="utf-8")

    rel = str(note_path.relative_to(vault))
    return f"obsidian://open?vault={quote(vault_name or '')}&file={quote(rel)}"


def _create_entry(
    name: str,
    url: str | None,
    gdoc_id: str | None,
    comments: str | None,
    ingest_source: str,
    ingest_original: str,
    obsidian_link: str | None,
) -> int:
    """Insert library_items + library_entries rows. Returns entry_id."""
    now = "datetime('now')"
    with get_write_db() as dbw:
        # Insert empty library_items row
        cur = dbw.execute(
            "INSERT INTO library_items DEFAULT VALUES"
        )
        entity_id = cur.lastrowid

        # Insert library_entries row
        cur2 = dbw.execute(
            """INSERT INTO library_entries
               (name, type_code, priority, url, gdoc_id, comments, entity_id,
                needs_review, ingest_source, ingest_original, obsidian_link,
                needs_enrichment, created_at, updated_at)
               VALUES (?, 'u', 'medium', ?, ?, ?, ?,
                       1, ?, ?, ?,
                       0, datetime('now'), datetime('now'))""",
            (name, url, gdoc_id, comments, entity_id,
             ingest_source, ingest_original, obsidian_link),
        )
        entry_id = cur2.lastrowid
        dbw.commit()
    return entry_id


def _update_obsidian_link(entry_id: int, link: str) -> None:
    with get_write_db() as dbw:
        dbw.execute(
            "UPDATE library_entries SET obsidian_link = ? WHERE id = ?",
            (link, entry_id),
        )
        dbw.commit()


# ── PDF ingestion ────────────────────────────────────────────────────────────

def _ingest_pdf(
    file_path: Path,
    processed_dir: Path,
    libby_cfg: dict,
    vault: Path,
    vault_name: str,
) -> str:
    """Upload PDF to Drive, create Libby entry, create vault stub. Returns status string."""
    from connectors.drive import upload_file

    folder_id = libby_cfg.get("gdrive_pdf_folder_id", "")
    if not folder_id:
        raise ValueError("libby.gdrive_pdf_folder_id not set in config")

    title = _title_from_filename(file_path.name)

    # Upload to Drive
    result = upload_file(file_path, folder_id, mime_type="application/pdf")
    drive_id = result["id"]
    drive_url = result["web_url"]

    # Create vault stub
    today = date.today().isoformat()
    fm = {
        "type": ["unknown"],
        "title": title,
        "source": file_path.name,
        "gdoc_id": drive_id,
        "created": today,
        "needs_review": True,
    }
    inbox_folder = libby_cfg.get("inbox_vault_folder", "4 Library/Inbox")
    obsidian_link = _create_vault_stub(vault, vault_name, inbox_folder, title, fm)

    # Create Libby entry
    entry_id = _create_entry(
        name=title,
        url=drive_url,
        gdoc_id=drive_id,
        comments=None,
        ingest_source="file",
        ingest_original=file_path.name,
        obsidian_link=obsidian_link,
    )

    # Move to processed
    processed_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(file_path), str(processed_dir / file_path.name))

    return f"Drive uploaded, Libby entry #{entry_id} created"


# ── MD ingestion ─────────────────────────────────────────────────────────────

def _ingest_md(
    file_path: Path,
    processed_dir: Path,
    libby_cfg: dict,
    vault: Path,
    vault_name: str,
) -> str:
    """Parse MD file, create Libby entry, copy content to vault stub. Returns status string."""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    fm, body = _parse_frontmatter(text)

    title = fm.get("title") or _title_from_filename(file_path.name)
    author = fm.get("author")
    url = fm.get("url")
    created = fm.get("date") or fm.get("created") or date.today().isoformat()

    comments = _first_paragraph(body)

    # Create vault stub with body content
    today = date.today().isoformat()
    stub_fm: dict = {
        "type": ["unknown"],
        "title": title,
        "source": file_path.name,
        "created": today,
        "needs_review": True,
    }
    if author:
        stub_fm["author"] = author
    if url:
        stub_fm["url"] = url

    inbox_folder = libby_cfg.get("inbox_vault_folder", "4 Library/Inbox")
    obsidian_link = _create_vault_stub(
        vault, vault_name, inbox_folder, title, stub_fm, body=body
    )

    # Create Libby entry (no Drive upload for MD)
    entry_id = _create_entry(
        name=title,
        url=url,
        gdoc_id=None,
        comments=comments or None,
        ingest_source="file",
        ingest_original=file_path.name,
        obsidian_link=obsidian_link,
    )

    # Move to processed
    processed_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(file_path), str(processed_dir / file_path.name))

    return f"Libby entry #{entry_id} created, content preserved"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    libby_cfg = _load_libby_config()

    staging_dir = _expand(libby_cfg.get("staging_folder", "~/Dropbox/2tech/Libby/Staging"))
    processed_dir = _expand(libby_cfg.get("processed_folder", "~/Dropbox/2tech/Libby/Processed"))

    vault = get_vault_path()
    vault_name = get_vault_name() or ""

    if not staging_dir.is_dir():
        print(f"Staging folder not found: {staging_dir}")
        sys.exit(1)

    if not vault:
        print("Obsidian vault not configured — vault stubs will be skipped")

    files = [f for f in staging_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
    if not files:
        print("No files in staging folder")
        return

    ok_count = 0
    err_count = 0
    results = []

    for f in sorted(files):
        try:
            ext = f.suffix.lower()
            if ext == ".pdf":
                msg = _ingest_pdf(f, processed_dir, libby_cfg, vault, vault_name)
            elif ext == ".md":
                msg = _ingest_md(f, processed_dir, libby_cfg, vault, vault_name)
            else:
                results.append(f"  ⚠ {f.name} → skipped (unsupported type {ext})")
                continue
            results.append(f"  ✓ {f.name} → {msg}")
            ok_count += 1
        except Exception as exc:
            results.append(f"  ✗ {f.name} → ERROR: {exc}")
            err_count += 1

    total = ok_count + err_count
    print(f"Processed {total} files:")
    for r in results:
        print(r)
    print(f"{ok_count} items added to Libby inbox")


if __name__ == "__main__":
    main()
