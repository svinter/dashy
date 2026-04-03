# Dashy — Design Specification & Operations Guide

**Version:** 2.0  
**Date:** 2026-04-03  
**Status:** Billing module complete and operational  
**Repo:** https://github.com/svinter/dashy (public)  
**Upstream:** https://github.com/richwhitjr/dashboard (Rich Whitcomb, v1.2.21)

---

## 1. What Dashy Is

Dashy is a personal dashboard app running locally on macOS, forked from Rich Whitcomb's Dashboard (v1.2.21). It centralizes Google Calendar, Gmail, Obsidian, Notion, Granola, and LunchMoney into a single interface, and extends the upstream app with a complete billing module for Vantage Insights.

**Provider:** Steve Vinter, Vantage Insights  
*(Contact info stored in `config.json` under `billing_settings` — not in the repo)*

**Tech stack:**

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.13, Uvicorn |
| Frontend | React 19, TypeScript, Vite, React Router |
| State | TanStack React Query |
| Database | SQLite (WAL mode) at `~/.personal-dashboard/dashboard.db` |
| Styling | Tufte CSS — no Tailwind/MUI |
| Native app | pywebview |
| PDF | reportlab |
| Payments | lunchable (LunchMoney API) |

**Data directory:** `~/.personal-dashboard/`  
**Obsidian vault:** `/Users/stevevinter/Obsidian/MyNotes/`  
**Version:** `1.2.21-dashy` (in `VERSION` file at repo root)

---

## 2. Daily Operations

### 2.1 Starting Dashy

```bash
cd ~/dashy
make dev
```

Opens backend on `:8000` and frontend on `:5173`. Browse to `http://localhost:5173`.

**If ports are busy from a previous session:**
```bash
pkill -f uvicorn
pkill -f vite
make dev
```

### 2.2 Daily Billing Tasks

Two items require attention each day — both are flagged with red badge counts in the sidebar:

1. **Queue badge** — unprocessed calendar sessions (grape events not yet confirmed)
   - Go to Billing → Queue
   - Confirm or dismiss each session

2. **Payments badge** — unmatched LunchMoney payments
   - Go to Billing → Payments
   - Click "Sync from LunchMoney" to pull new transactions
   - Assign unmatched payments to invoices

The home page briefing also shows: *"Billing: N to process, N to match"* when either count is > 0.

### 2.3 Monthly Billing Workflow

1. **Sync calendar** — press `s` in Dashy or trigger via Settings → Connectors
2. **Process queue** — confirm all grape sessions for the month
3. **Billing → Prepare** — select previous month, review sessions, add expenses, generate invoices
4. **Generate PDFs** — from Invoices list, bulk generate or per-invoice
5. **Send invoices** — click ✉ on each invoice, review email preview, send or save draft
6. **Track payments** — as payments arrive in LunchMoney, sync and match to invoices

### 2.4 Saving Changes to GitHub

```bash
make checkpoint
```

Runs `git add -A && git commit && git push origin main`. Run whenever you've made changes worth saving. No manual git commands needed beyond this.

### 2.5 Pulling Rich's Upstream Updates

```bash
git fetch upstream
git log upstream/main --oneline -10   # review what's new
git merge upstream/main               # bring changes in
make db-upgrade                       # apply any new migrations
make checkpoint                       # save the merge
```

### 2.6 Building the macOS App

```bash
make release
```

Builds `Dashy.app`. Run explicitly when needed — never automatic.

### 2.7 Seed File Management

The billing seed (`app/backend/billing_seed.json`) is **excluded from git** — it contains confidential client names, rates, and contact details.

**After any seed changes:**
1. Edit `~/dashy/app/backend/billing_seed.json`
2. In Dashy Settings → Billing, click "Re-import Seed Data"
3. Back up to iCloud:
```bash
cp ~/dashy/app/backend/billing_seed.json \
   ~/Library/Mobile\ Documents/com~apple~CloudDocs/Dashy/billing_seed.json
```

**Never commit the seed file to git.**

### 2.8 Database Backup

```bash
cp ~/.personal-dashboard/dashboard.db \
   ~/Library/Mobile\ Documents/com~apple~CloudDocs/Dashy/dashboard.db
```

---

## 3. Architecture

### 3.1 Key Files

```
~/dashy/
├── VERSION                              # 1.2.21-dashy
├── CLAUDE.md                            # upstream Claude Code instructions
├── DASHY.md                             # Dashy-specific standing instructions
├── app/
│   ├── backend/
│   │   ├── main.py                      # FastAPI app, router registration
│   │   ├── database.py                  # SQLite schema + init
│   │   ├── alembic/                     # migrations (append-only)
│   │   ├── routers/
│   │   │   ├── billing.py               # all billing CRUD + logic endpoints
│   │   │   ├── billing_pdf.py           # PDF generation + email sending
│   │   │   └── ...                      # upstream routers (unchanged)
│   │   └── connectors/
│   │       ├── calendar_sync.py         # extended with color_id capture
│   │       ├── lunchmoney.py            # LunchMoney payment sync
│   │       └── ...                      # upstream connectors (unchanged)
│   └── frontend/src/
│       ├── pages/BillingPage.tsx        # all billing UI
│       ├── api/hooks.ts                 # all React Query hooks
│       └── api/types.ts                 # TypeScript interfaces
├── app/backend/billing_seed.json        # ⚠️ EXCLUDED FROM GIT
└── .gitignore                           # excludes seed, venv, node_modules, workflows
```

### 3.2 Conventions

- All billing tables prefixed `billing_`
- All schema changes via Alembic only — never manual SQL
- Styling: Tufte CSS only — no new CSS frameworks
- All API calls via React Query hooks in `api/hooks.ts`
- PDF generation: Python/reportlab backend only
- Calendar data: read from `calendar_events` table — no direct Google API calls from billing

### 3.3 Config Keys (`~/.personal-dashboard/config.json`)

Stored under `billing_settings`:

| Key | Purpose |
|---|---|
| `provider_name` | "Vantage Insights" — PDF header |
| `provider_address` | Multi-line address — PDF header |
| `provider_phone` | Phone — PDF header |
| `provider_email` | Email — PDF header |
| `invoice_output_dir` | PDF save location (default: `~/.personal-dashboard/invoices/`) |

---

## 4. Calendar Integration

### 4.1 Color-Based Session Detection

`connectors/calendar_sync.py` extended to store `color_id` from Google Calendar.

| colorId | Name | Meaning |
|---|---|---|
| `"3"` | Grape (purple) | Past coaching session — confirmed, billable |
| `"5"` | Banana (yellow) | Future coaching session — projected revenue |
| all others | — | Ignored by billing module |

Sessions = `calendar_events WHERE color_id IN ('3', '5')`.

### 4.2 Banana → Grape Transition

When a banana event passes and the next sync sees it as grape, Dashy automatically sets `is_confirmed = true`, `color_id = '3'`, and re-reads the Obsidian note for actual duration.

### 4.3 Duration Resolution

1. Obsidian note at `8 Meetings/YYYY-MM-DD - {client.obsidian_name}.md` → `duration` frontmatter (integer minutes)
2. Fallback: daily note at `9 Daily/YYYY-MM-DD.md`
3. Final fallback: calendar slot length **rounded up** to nearest half hour (25 min → 0.5 hr, 55 min → 1.0 hr)

### 4.4 Obsidian Deep Links

Format: `obsidian://open?vault=MyNotes&file=8%20Meetings%2FYYYY-MM-DD%20-%20{name}.md`

---

## 5. Database Schema

### 5.1 `billing_companies`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT | e.g. "Arboretum" |
| `abbrev` | TEXT | e.g. "ARB" |
| `default_rate` | REAL | hourly rate USD |
| `billing_method` | TEXT | `invoice` \| `bill.com` \| `payasgo` \| null (pro bono) |
| `payment_method` | TEXT | e.g. "etrade", "venmo", "paypal", "check", "tipalti" |
| `ap_email` | TEXT | accounts payable email |
| `cc_email` | TEXT | optional CC |
| `tax_tool` | TEXT | e.g. "Zenwork", "mail" |
| `invoice_prefix` | TEXT | fallback if abbrev not set |
| `payment_instructions` | TEXT | overrides auto-derived payment text in PDF |
| `email_subject` | TEXT | template with `{{invoice_number}}`, `{{month}}` etc. |
| `email_body` | TEXT | same variables |
| `notes` | TEXT | internal |
| `active` | BOOLEAN | soft-delete |

### 5.2 `billing_clients`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT | |
| `company_id` | INTEGER FK → billing_companies | |
| `rate_override` | REAL | overrides company default_rate |
| `prepaid` | BOOLEAN | sessions have amount=0 |
| `obsidian_name` | TEXT | exact string in note filenames |
| `employee_id` | INTEGER FK → people | optional cross-reference |
| `active` | BOOLEAN | |

### 5.3 `billing_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `date` | DATE | |
| `client_id` | INTEGER FK → billing_clients | NULL for company-level sessions |
| `company_id` | INTEGER FK → billing_companies | denormalized |
| `duration_hours` | REAL | billable hours |
| `rate` | REAL | snapshot at confirmation |
| `amount` | REAL | duration × rate; 0 if prepaid |
| `is_confirmed` | BOOLEAN | true=grape; false=banana/projected |
| `prepaid_block_id` | INTEGER FK → billing_prepaid_blocks | |
| `calendar_event_id` | TEXT | Google Calendar event id |
| `color_id` | TEXT | `'3'` or `'5'` |
| `obsidian_note_path` | TEXT | relative vault path |
| `notes` | TEXT | |
| `invoice_line_id` | INTEGER FK → billing_invoice_lines | set when invoiced |
| `dismissed` | BOOLEAN | permanently skipped from queue |
| `created_at` | DATETIME | |

### 5.4 `billing_invoices`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `invoice_number` | TEXT UNIQUE | format: `YYYY-{ABBREV}-{MM}` |
| `company_id` | INTEGER FK → billing_companies | |
| `period_month` | TEXT | YYYY-MM |
| `invoice_date` | DATE | today when generated |
| `services_date` | DATE | "services rendered through" date |
| `due_date` | DATE | invoice_date + 30 days |
| `status` | TEXT | `draft` → `sent` → `paid` / `partial` / `cancelled` |
| `total_amount` | REAL | |
| `pdf_path` | TEXT | absolute path to PDF |
| `receipt_pdf_path` | TEXT | optional receipt bundle |
| `notes` | TEXT | internal |
| `sent_at` | TEXT | ISO timestamp when emailed |
| `created_at` | DATETIME | |

### 5.5 `billing_invoice_lines`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `invoice_id` | INTEGER FK → billing_invoices | |
| `type` | TEXT | `sessions` or `manual` |
| `description` | TEXT | |
| `date_range` | TEXT | Oxford-style: "March 3, 10 & 17, 2026" |
| `unit_cost` | REAL | |
| `quantity` | REAL | hours or unit count |
| `amount` | REAL | negative for corrections |
| `sort_order` | INTEGER | |

### 5.6 `billing_prepaid_blocks`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `client_id` | INTEGER FK → billing_clients | |
| `sessions_purchased` | INTEGER | |
| `starting_after_date` | DATE | |
| `invoice_id` | INTEGER FK → billing_invoices | invoice that billed this block |
| `created_at` | DATETIME | |

`sessions_used` computed: `COUNT(*) FROM billing_sessions WHERE prepaid_block_id = ?`

### 5.7 `billing_payments`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `lunchmoney_transaction_id` | INTEGER UNIQUE | deduplication key |
| `date` | DATE | |
| `amount` | REAL | negative = incoming (LunchMoney convention) |
| `payee` | TEXT | |
| `notes` | TEXT | often contains company name |
| `company_id` | INTEGER FK → billing_companies | inferred by name matching |
| `created_at` | DATETIME | |

### 5.8 `billing_invoice_payments`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `invoice_id` | INTEGER FK → billing_invoices | |
| `payment_id` | INTEGER FK → billing_payments | |
| `amount_applied` | REAL | supports partial and split payments |

---

## 6. API Endpoints

All routes prefixed `/api/billing/`.

### Companies & Clients
| Method | Path | Description |
|---|---|---|
| GET | `/companies` | List; `?active_only=true` |
| POST | `/companies` | Create |
| PATCH | `/companies/{id}` | Update |
| DELETE | `/companies/{id}` | Delete |
| GET | `/clients` | List; `?company_id=N&active_only=true` |
| POST | `/clients` | Create |
| PATCH | `/clients/{id}` | Update |
| DELETE | `/clients/{id}` | Delete |

### Seed
| Method | Path | Description |
|---|---|---|
| GET | `/seed/status` | Seed file path + counts |
| POST | `/seed/import` | Import; `?force=true` clears companies+clients only (never sessions/invoices) |

### Sessions
| Method | Path | Description |
|---|---|---|
| GET | `/sessions/unprocessed` | Grape/banana events not yet confirmed or dismissed |
| POST | `/sessions/confirm` | Confirm a calendar event as a session |
| POST | `/sessions/dismiss` | Dismiss an event from the queue |
| POST | `/sessions/unprocess/{id}` | Move confirmed session back to queue |
| GET | `/sessions` | All sessions; filterable |
| PATCH | `/sessions/{id}` | Update any session field |
| DELETE | `/sessions/{id}` | Delete |

### Invoices
| Method | Path | Description |
|---|---|---|
| GET | `/invoices` | List; `?period_month=YYYY-MM&status=X&company_id=N` |
| POST | `/invoices` | Create manual/historical invoice |
| GET | `/invoices/{id}` | Detail with line items + sessions |
| PATCH | `/invoices/{id}` | Update status, dates, notes |
| DELETE | `/invoices/{id}` | Delete |
| POST | `/invoices/import-csv` | Bulk import from CSV |

### Invoice Prep
| Method | Path | Description |
|---|---|---|
| GET | `/prepare/{year}/{month}` | Session + subtotal data for prep wizard |
| POST | `/prepare/{year}/{month}/generate` | Generate draft invoices |

### PDF & Email
| Method | Path | Description |
|---|---|---|
| POST | `/invoices/{id}/pdf` | Generate PDF |
| GET | `/invoices/{id}/pdf` | Download PDF |
| GET | `/invoices/{id}/compose` | Compose email (substitutes template variables) |
| POST | `/invoices/{id}/send-draft` | Save as Gmail draft with PDF attached |
| POST | `/invoices/{id}/send-email` | Send via Gmail; marks invoice sent |

### Payments
| Method | Path | Description |
|---|---|---|
| POST | `/lunchmoney/sync` | Pull from LunchMoney; `?days_back=180` |
| POST | `/lunchmoney/relink-companies` | Re-infer company_id for unlinked payments |
| GET | `/payments` | List; `?unmatched_only=true` |
| POST | `/payments/{id}/assign` | Assign payment to invoice |
| DELETE | `/invoice-payments/{id}` | Remove assignment |

### Misc
| Method | Path | Description |
|---|---|---|
| GET | `/badge-counts` | `{queue_count, unmatched_payments_count}` |
| GET | `/settings` | Billing provider settings |
| POST | `/settings` | Update billing settings |

---

## 7. Frontend Views

Sub-nav: **Queue · Sessions · Invoices · Payments · Summary · Prepare**

| Route | View | Description |
|---|---|---|
| `/billing` | UnprocessedQueue | Grape/banana events to confirm/dismiss; company+client inference with confidence badges; banana toggle |
| `/billing/sessions` | SessionsView | Three tabs: By Company & Date / By Date / Summary; date filter bar; inline editing; Obsidian links; Unprocess button |
| `/billing/invoices` | InvoicesListView | Filterable list; per-row PDF + email buttons; bulk generate+download; Delete All; grand total |
| `/billing/invoices/:id` | InvoiceDetailView | Line items, sessions, payment assignments, Mark as Sent/Paid, Generate PDF, Send Invoice modal |
| `/billing/payments` | PaymentsView | LunchMoney transactions; company selector; invoice assignment checkbox panel |
| `/billing/summary` | SummaryView | Billing tab + Cash Received/Tax tab; current year |
| `/billing/annual/:year` | AnnualSummaryView | Same grid for any year |
| `/billing/prepare/:year/:month` | InvoicePrepPage | 4-stage wizard: select period → review sessions → configure invoice (with number override) → done |

### Date Filter Bar (shared component)
```
[Year ▾]  All  Jan  Feb  Mar  Apr  May  Jun  Jul  Aug  Sep  Oct  Nov  Dec
Week: All  1  2  3  4  5
```
Default: current year, previous month, all weeks. Week boundaries are Monday-anchored.

### Sidebar Badges
Red badge counts on Queue (unprocessed sessions) and Payments (unmatched payments). Combined badge on top-level Billing nav when not on billing pages. Briefing home page shows "Billing: N to process, N to match" when either count > 0.

---

## 8. Business Logic

### Rate Resolution
```
effective_rate = COALESCE(client.rate_override, company.default_rate)
amount = duration_hours × effective_rate  (0 for prepaid clients)
```

### Invoice Numbering
Format: `YYYY-{ABBREV}-{MM}` where MM = zero-padded billing period month.  
Example: March 2026 for Arboretum → `2026-ARB-03`  
Override available in Prepare Stage 3 for historical invoices.

### Invoice Generation Rules
- Skip if `billing_method` is NULL (pro bono — e.g. CCSC)
- Skip if total amount = $0
- Skip if invoice already exists for this company × period
- Due date = invoice_date + 30 days

### Payment Status Auto-Update
After every payment assignment change:
```
paid_sum = SUM(amount_applied) for invoice
if paid_sum >= total_amount - 0.01  → status = 'paid'
elif paid_sum > 0.01                → status = 'partial'
else                                 → status = 'sent'
```
Does not apply to draft invoices.

### LunchMoney Sync Filters
Only imports transactions where:
- `category_name == "Coaching income"` (case-insensitive)
- `is_income == True`

### LunchMoney Auto-Matching
Company name or abbrev found as whole token in `payee + notes` AND exact amount match (`|invoice_total - |payment_amount|| < 0.01`) → auto-assign.

### Prepaid Sessions
- `amount = 0` on session record
- No invoice when session occurs
- Invoice generated when new block purchased

### Corrections
Negative amounts on `billing_invoice_lines` (type=`manual`). Entered via expense form in Prepare wizard.

---

## 9. PDF Generation

**Library:** reportlab  
**Filename:** `Vantage Insights Invoice {invoice_number} {Month YYYY}.pdf`  
**Save location:** configurable via `billing_settings.invoice_output_dir`  
**Brand colors:** `#016630` (name + invoice number), `#05DF72` (table header)  
**Provider info:** read from `config.json billing_settings` — not hardcoded in repo

**Payment instructions:** from `billing_companies.payment_instructions`; fallback derives from billing/payment method.

**Session line consolidation:** All sessions for same client → one line with Oxford-style dates.

---

## 10. Email Sending

**Via:** Gmail API (Google OAuth with `gmail.send` and `gmail.compose` scopes)

**Template variables:**

| Variable | Value |
|---|---|
| `{{invoice_number}}` | e.g. "2026-ARB-03" |
| `{{month}}` | e.g. "March 2026" |
| `{{client_names}}` | Comma-separated names from linked sessions |
| `{{company_name}}` | Company name |
| `{{total_amount}}` | Formatted dollar amount |
| `{{due_date}}` | Due date string |

**Flow:** Compose preview modal (editable To/CC/Subject/Body) → Save Draft or Send. PDF attached automatically if generated. Sending marks invoice `sent` and records `sent_at`.

---

## 11. Upstream Recommendations for Rich

Changes worth proposing as PRs to the upstream Dashboard repo:

1. **`color_id` on `calendar_events`** — one column in `calendar_sync.py` and schema; useful for any user who uses calendar colors to categorize events
2. **Version number in UI** — `VERSION` file at repo root, `GET /api/version` endpoint, displayed in sidebar and Settings; makes it easy for users to report which version they're running
3. **Obsidian connector** — already added by Rich; no changes needed

---

## 12. Invariants — Never Change Without Explicit Instruction

| Rule | Why |
|---|---|
| All `billing_*` table names | Alembic migrations are append-only |
| `color_id IN ('3','5')` filter | Matches grape/banana Google Calendar colors |
| Invoice number format `YYYY-{ABBREV}-{MM}` | Historical consistency |
| `_slot_hours` rounds **up** | Never round down or to nearest |
| `billing_seed.json` never committed | Contains private client data |
| `billing_method = null` → never invoice | Pro bono clients (e.g. CCSC) |

---

## 13. Claude Code Session Protocol

At the start of every Claude Code session in `~/dashy`:

1. Read `CLAUDE.md` and `DASHY.md` before writing any code
2. The spec lives in Obsidian or as `DASHY_SPEC.md` in the repo root
3. "Re-import seed data" = disable FK, DELETE billing_companies + billing_clients, re-enable FK, POST `/api/billing/seed/import` — never touch sessions/invoices/payments
4. Run `make checkpoint` at the end of every session
5. Never commit `billing_seed.json`
