# Keyboard Maestro Setup — Libby Ingestion

Two KM macros trigger the ingestion pipeline: one for files dropped into the Staging folder, one for URLs copied to the clipboard.

---

## Prerequisites

```bash
cd /Users/stevevinter/dashy/app/backend
source venv/bin/activate
pip install httpx  # already installed; verify with: pip show httpx
```

Config must have a `libby` section in `~/.personal-dashboard/config.json`:

```json
{
  "libby": {
    "staging_folder": "~/Dropbox/2tech/Libby/Staging",
    "processed_folder": "~/Dropbox/2tech/Libby/Processed",
    "inbox_vault_folder": "4 Library/Inbox",
    "gdrive_pdf_folder_id": "1TSuEEmQK64UFwAHXYod4aqOuhnUaSDVr"
  }
}
```

---

## Macro 1 — Ingest Files from Staging

**Trigger:** Folder action on `~/Dropbox/2tech/Libby/Staging` (new item added), or manual hotkey.

**Action: Execute Shell Script**

```bash
#!/bin/bash
cd /Users/stevevinter/dashy/app/backend
source venv/bin/activate
python scripts/ingest_files.py >> /tmp/libby-ingest.log 2>&1
```

**Supported file types:**
- `.pdf` — uploaded to Google Drive (PDF folder), vault stub created in `4 Library/Inbox/`, entry added to Libby inbox
- `.md` — content preserved in vault stub, entry added to Libby inbox
- Other types — skipped with a warning

**Output:** Written to `/tmp/libby-ingest.log`

---

## Macro 2 — Ingest URL from Clipboard

**Trigger:** Hotkey (e.g. `⌘⌥U`) — run when a URL is on the clipboard.

**Action: Execute Shell Script**

```bash
#!/bin/bash
URL=$(pbpaste)
cd /Users/stevevinter/dashy/app/backend
source venv/bin/activate
python scripts/ingest_url.py "$URL" >> /tmp/libby-ingest.log 2>&1
```

**What it does:**
1. Fetches page metadata (Open Graph title, author, description, published date)
2. Special-cases YouTube URLs via oEmbed
3. Creates a vault stub in `4 Library/Inbox/`
4. Adds a `needs_review` entry to the Libby inbox (type = unknown)

**Output:** Written to `/tmp/libby-ingest.log`

---

## Viewing the inbox

Open Dashy → Library → New → scroll to **Inbox** section at the top.

Each inbox item shows:
- Title, source (file/url), age
- Obsidian deep link (if vault stub was created)
- **Classify** — click to pre-fill a creation form; saving dismisses the inbox entry
- **×** — dismiss without classifying

---

## Logs

```bash
tail -f /tmp/libby-ingest.log
```
