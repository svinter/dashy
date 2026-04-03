# DASHY.md — Dashy-specific standing instructions

This file contains standing instructions for Claude Code sessions working on Dashy.
Always read both **CLAUDE.md** and **DASHY.md** at the start of every session before writing any code.

---

## Session startup

1. Read `CLAUDE.md` — tech stack, project structure, conventions, API reference.
2. Read `DASHY.md` (this file) — Dashy-specific overrides and invariants.

---

## Obsidian sync

Whenever `CLAUDE.md` or `DASHY.md` is modified, immediately copy both files to the Obsidian vault so they stay in sync:

```bash
cp /Users/stevevinter/dashy/CLAUDE.md /Users/stevevinter/Obsidian/MyNotes/Projects/Dashy/
cp /Users/stevevinter/dashy/DASHY.md  /Users/stevevinter/Obsidian/MyNotes/Projects/Dashy/
```

Do this as the last step after writing any changes to either file — no need to ask first.

---

## Spec location

The Dashy feature spec lives at:
- **Obsidian**: the path the user specifies (typically their personal vault, e.g. `~/Obsidian/MyNotes/Projects/Dashy.md`)
- **Repo fallback**: `DASHY_SPEC.md` at the repo root (if the user has placed it there)

When the user says "read the spec" or "from the spec, do step N", locate it via whichever path applies. Ask the user to confirm the path if unclear.

---

## Seed data import

The billing seed file lives at `app/backend/dashy_billing_seed.json`.

When the user says **"re-import seed data"** (or equivalent), this means:

1. Clear the two master-data tables:
   ```sql
   DELETE FROM billing_clients;
   DELETE FROM billing_companies;
   ```
2. Re-run the import endpoint:
   ```bash
   curl -s -X POST http://localhost:8000/api/billing/seed/import | python3 -m json.tool
   ```

The import endpoint (`POST /api/billing/seed/import`) will return a 409 if rows exist, which is why the tables must be cleared first. Do **not** drop and recreate the tables — only `DELETE` the rows so that schema and FK constraints are preserved.

---

## Invariants — never change without explicit user instruction

Dashy is a fork of the Desktop dashboard. The following must never be altered incidentally:

| Invariant | Why |
|-----------|-----|
| All `billing_*` table names | Alembic migrations are append-only; renaming breaks the migration chain and existing data |
| `color_id` column on `calendar_events` | Required by the billing session-discovery pipeline to identify grape/banana calendar events |
| `VERSION` file format | Must remain `Desktop vX.Y.Z Dashy vA.B.C` — the Desktop version comes from `git tag \| sort -V \| tail -1` at the time of release; do not reformat or collapse it |
| `SEED_PATH` in `routers/billing.py` | Points to `app/backend/dashy_billing_seed.json` — do not change this path |

---

## Billing module notes

- **Grape** (`color_id = '3'`): confirmed past sessions — show in unprocessed queue
- **Banana** (`color_id = '5'`): projected future sessions — hidden by default, toggled with "Show banana" checkbox
- `_slot_hours` rounds calendar duration **up** to the nearest 0.5 h (`math.ceil(raw * 2) / 2`)
- Obsidian meeting notes live at `{vault}/8 Meetings/YYYY-MM-DD - {obsidian_name}.md`; `duration` frontmatter is integer minutes as a string (e.g. `"45"`)
- Client inference filters out `@resource.calendar.google.com` attendees (Zoom Rooms) and the user's own email/name from the profile config before scoring
