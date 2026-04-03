# Dashy Billing Module — Reference Spec

*Generated 2026-04-03. Covers all code in `app/backend/routers/billing.py`, `billing_pdf.py`, `connectors/lunchmoney.py`, and `app/frontend/src/pages/BillingPage.tsx`.*

---

## 1. Overview

The billing module tracks advisory/coaching sessions against clients, generates invoices, and reconciles incoming payments from LunchMoney. It is a Dashy-exclusive feature (not in the upstream Desktop codebase).

**Mount point:** All backend routes live under `/api/billing/`. Frontend routes live under `/billing/`.

---

## 2. Database Schema

### 2.1 `billing_companies`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `name` | TEXT NOT NULL | Full company name |
| `abbrev` | TEXT | Short abbreviation used in invoice numbers |
| `default_rate` | REAL | Default hourly rate for sessions |
| `billing_method` | TEXT | e.g. `bill.com`, `direct` — NULL means not billable |
| `payment_method` | TEXT | e.g. `etrade`, `paypal`, `venmo`, `check`, `tipalti` |
| `ap_email` | TEXT | Accounts payable recipient for invoice emails |
| `cc_email` | TEXT | CC recipient for invoice emails |
| `tax_tool` | TEXT | e.g. `taxjar` |
| `invoice_prefix` | TEXT | Fallback prefix for invoice numbers if `abbrev` not set |
| `notes` | TEXT | Free-form internal notes |
| `active` | BOOLEAN DEFAULT 1 | Soft-delete flag |
| `payment_instructions` | TEXT | *(migration 20260402_0002)* Overrides auto-derived payment text in PDF |
| `email_subject` | TEXT | *(migration 20260403_0001)* Template for invoice email subject |
| `email_body` | TEXT | *(migration 20260403_0001)* Template for invoice email body |

### 2.2 `billing_clients`

Individual contacts within a company (each billed separately).

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `name` | TEXT NOT NULL | Full name |
| `company_id` | INTEGER → `billing_companies(id)` | Parent company |
| `rate_override` | REAL | Per-client rate; overrides `default_rate` if set |
| `prepaid` | BOOLEAN DEFAULT 0 | Prepaid block client (sessions have `amount=0`) |
| `obsidian_name` | TEXT | Filename stem for Obsidian meeting notes |
| `employee_id` | INTEGER → `people(id)` | Link to dashboard's people record |
| `active` | BOOLEAN DEFAULT 1 | Soft-delete flag |

### 2.3 `billing_sessions`

One row per coaching/advisory session.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `date` | DATE | Session date (YYYY-MM-DD) |
| `client_id` | INTEGER → `billing_clients(id)` | NULL for company-level (no-client) sessions |
| `company_id` | INTEGER → `billing_companies(id)` | Denormalized for fast grouping |
| `duration_hours` | REAL | Billable hours (may differ from calendar slot) |
| `rate` | REAL | Rate at time of confirmation |
| `amount` | REAL | `duration_hours × rate` (0 for prepaid sessions) |
| `is_confirmed` | BOOLEAN DEFAULT 0 | Grape (confirmed past); 0 = banana (projected future) |
| `prepaid_block_id` | INTEGER → `billing_prepaid_blocks(id)` | Set if session consumed a prepaid block |
| `calendar_event_id` | TEXT | Google Calendar event ID |
| `color_id` | TEXT | `'3'`=grape, `'5'`=banana |
| `obsidian_note_path` | TEXT | Relative vault path to session note |
| `notes` | TEXT | Free-form notes |
| `invoice_line_id` | INTEGER → `billing_invoice_lines(id)` | Set when session is invoiced |
| `dismissed` | BOOLEAN DEFAULT 0 | *(migration 20260401_0003)* True = skipped from queue permanently |
| `created_at` | DATETIME DEFAULT now | |

### 2.4 `billing_invoices`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `invoice_number` | TEXT UNIQUE NOT NULL | Format: `YYYY-{ABBREV}-{MM}` |
| `company_id` | INTEGER → `billing_companies(id)` | |
| `period_month` | TEXT | `YYYY-MM` billing period |
| `invoice_date` | DATE | Date on the invoice |
| `services_date` | DATE | "Services rendered through" date |
| `due_date` | DATE | `invoice_date + 30 days` |
| `status` | TEXT DEFAULT `'draft'` | `draft` → `sent` → `paid` / `partial` / `cancelled` |
| `total_amount` | REAL | Sum of all line items |
| `pdf_path` | TEXT | Absolute path to generated PDF on disk |
| `receipt_pdf_path` | TEXT | Reserved for receipt PDFs |
| `notes` | TEXT | |
| `created_at` | DATETIME DEFAULT now | |
| `sent_at` | TEXT | *(migration 20260403_0001)* ISO timestamp when email was sent |

### 2.5 `billing_invoice_lines`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `invoice_id` | INTEGER NOT NULL → `billing_invoices(id)` | |
| `type` | TEXT NOT NULL | `sessions` or `manual` |
| `description` | TEXT | Line item description |
| `date_range` | TEXT | e.g. "Jan 2026 – Mar 2026" |
| `unit_cost` | REAL | Hourly rate or unit price |
| `quantity` | REAL | Hours or unit count |
| `amount` | REAL | Total for this line |
| `sort_order` | INTEGER | Display order |

### 2.6 `billing_prepaid_blocks`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `client_id` | INTEGER NOT NULL → `billing_clients(id)` | |
| `sessions_purchased` | INTEGER NOT NULL | Number of sessions in the block |
| `starting_after_date` | DATE | Block starts counting after this date |
| `invoice_id` | INTEGER → `billing_invoices(id)` | Invoice that billed this block |
| `created_at` | DATETIME DEFAULT now | |

### 2.7 `billing_provider_settings`

Single-row table (enforced by `CHECK (id = 1)`). Stores provider identity for PDF and email generation.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK (always 1) | Singleton row |
| `provider_name` | TEXT DEFAULT '' | Appears as PDF header and in email templates as `{{provider_name}}` |
| `provider_address1` | TEXT DEFAULT '' | Street address line 1 |
| `provider_address2` | TEXT DEFAULT '' | Suite / floor (optional) |
| `provider_city_state_zip` | TEXT DEFAULT '' | City, State ZIP |
| `provider_phone` | TEXT DEFAULT '' | Phone (PDF contact line) |
| `provider_email` | TEXT DEFAULT '' | Email (PDF contact line) |

Populated via seed import (`provider` key in `dashy_billing_seed.json`) or via Settings → Billing → Invoice Settings UI. Managed by `GET /api/billing/settings` and `POST /api/billing/settings`.

### 2.8 `billing_payments`

Incoming payments from LunchMoney.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `lunchmoney_transaction_id` | INTEGER UNIQUE | Deduplication key from LunchMoney |
| `date` | DATE | Transaction date |
| `amount` | REAL | Raw amount (negative = incoming per LunchMoney convention) |
| `payee` | TEXT | Payee/description from LunchMoney |
| `notes` | TEXT | Memo/notes from LunchMoney |
| `created_at` | DATETIME DEFAULT now | |
| `company_id` | INTEGER → `billing_companies(id)` | *(migration 20260402_0001)* Set by name-match inference |

### 2.8 `billing_invoice_payments`

Many-to-many link between payments and invoices.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `invoice_id` | INTEGER NOT NULL → `billing_invoices(id)` | |
| `payment_id` | INTEGER NOT NULL → `billing_payments(id)` | |
| `amount_applied` | REAL NOT NULL | Portion of payment applied to this invoice |

---

## 3. API Endpoints

All routes are prefixed `/api/billing/`.

### 3.1 Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | Return billing provider settings from `config.json` |
| POST | `/settings` | Update billing settings (provider name, address, invoice output dir, etc.) |

### 3.2 Companies

| Method | Path | Description |
|--------|------|-------------|
| GET | `/companies` | List all companies; `?active_only=true` filters inactive |
| POST | `/companies` | Create a company |
| PATCH | `/companies/{id}` | Update mutable fields |
| DELETE | `/companies/{id}` | Delete a company |

### 3.3 Clients

| Method | Path | Description |
|--------|------|-------------|
| GET | `/clients` | List clients; `?company_id=N` and `?active_only=true` supported |
| POST | `/clients` | Create a client |
| PATCH | `/clients/{id}` | Update mutable fields |
| DELETE | `/clients/{id}` | Delete a client |

### 3.4 Seed Import

| Method | Path | Description |
|--------|------|-------------|
| GET | `/seed/status` | Return seed file path and company/client counts |
| POST | `/seed/import` | Import companies and clients from `dashy_billing_seed.json`; returns 409 if rows already exist (use `?force=true` to overwrite) |

### 3.5 Badge Counts

| Method | Path | Description |
|--------|------|-------------|
| GET | `/badge-counts` | Return `queue_count` and `unmatched_payments_count` for sidebar badges |

**Queue count:** Calendar events with `color_id IN ('3','5')` AND `date(start_time) < date('now')` that have no `billing_sessions` row with `dismissed=1` OR `is_confirmed=1`.

**Unmatched count:** `billing_payments` where `company_id IS NOT NULL` AND `date >= date('now', '-90 days')` AND no `billing_invoice_payments` entry.

### 3.6 Sessions — Unprocessed Queue

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sessions/unprocessed` | Return calendar events with `color_id IN ('3','5')` not yet confirmed or dismissed; includes client inference and Obsidian note lookup for each event |
| POST | `/sessions/confirm` | Confirm an unprocessed event as a billing session; creates or updates a `billing_sessions` row |
| POST | `/sessions/dismiss` | Mark a calendar event as dismissed; inserts a `billing_sessions` row with `dismissed=1` so it never reappears |
| POST | `/sessions/refresh-from-calendar` | Promote banana→grape sessions whose calendar event `color_id` has changed to `'3'` |
| POST | `/sessions/relink` | Re-link `billing_sessions.client_id` after a seed re-import and re-apply rates |

### 3.7 Sessions — CRUD

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sessions` | List all confirmed, non-dismissed sessions with client/company info; supports `?company_id=N` and `?month=YYYY-MM` |
| POST | `/sessions` | Manually create a session without a calendar event |
| GET | `/sessions/{id}` | Return a single session |
| PATCH | `/sessions/{id}` | Update date, duration, rate, amount, notes, client_id, company_id |
| DELETE | `/sessions/{id}` | Delete a session (unlinks from invoice line) |
| POST | `/sessions/{id}/unprocess` | Move a confirmed session back to the unprocessed queue (clears `is_confirmed`, `invoice_line_id`, recalculates `amount`) |

### 3.8 Invoice Prep

| Method | Path | Description |
|--------|------|-------------|
| GET | `/prepare/{year}/{month}` | Return sessions + company totals for the billing period, grouped by company; skips companies with no activity |
| POST | `/prepare/{year}/{month}/generate` | Create draft `billing_invoices` + `billing_invoice_lines` for the period; skips companies that already have an invoice; back-links sessions via `invoice_line_id` |

### 3.9 Invoices

| Method | Path | Description |
|--------|------|-------------|
| GET | `/invoices` | List invoices; supports `?company_id`, `?status`, `?period_month`, `?period_year` |
| POST | `/invoices` | Manually create a historical invoice with optional line items |
| GET | `/invoices/csv-template` | Download CSV template for bulk import |
| POST | `/invoices/bulk-import` | Bulk-create historical invoices from CSV rows; rejects duplicates and unknown companies per row |
| GET | `/invoices/{id}` | Invoice detail with lines and linked sessions |
| DELETE | `/invoices/{id}` | Delete invoice, unlink sessions, remove PDF from disk |
| PATCH | `/invoices/{id}` | Update status, notes, dates, sent_at |

### 3.10 Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/summary` | Return billing grid (invoiced/confirmed/projected per company × month) and cash-received totals for a year; defaults to current year |

**Cash received** merges two sources: invoice-linked `billing_invoice_payments` and unlinked `billing_payments` with a `company_id`.

### 3.11 LunchMoney

| Method | Path | Description |
|--------|------|-------------|
| GET | `/lunchmoney/check` | Check LunchMoney API connectivity |
| POST | `/lunchmoney/sync` | Sync transactions into `billing_payments`; `?days_back=180`; `?clear=true` wipes payments and reassignments first |
| POST | `/lunchmoney/relink-companies` | Back-fill `company_id` on payments with no company set using name/abbrev matching |

### 3.12 Payments

| Method | Path | Description |
|--------|------|-------------|
| GET | `/payments` | List all payments with invoice assignments and exact-amount match suggestions; `?unmatched_only=true` |
| PATCH | `/payments/{id}` | Update `company_id` on a payment |
| POST | `/payments/{id}/assign` | Assign (or update) a payment → invoice link; auto-recalculates invoice status |
| DELETE | `/invoice-payments/{assignment_id}` | Remove a payment → invoice assignment; auto-recalculates invoice status |

### 3.13 PDF (billing_pdf.py)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/invoices/dir` | Return the configured invoice output directory path |
| POST | `/invoices/{id}/pdf` | Generate (or regenerate) the PDF; stores path in `billing_invoices.pdf_path` |
| GET | `/invoices/{id}/pdf` | Stream the PDF file for download |
| GET | `/invoices/{id}/compose` | Return composed email preview (to, cc, subject, body) using per-company templates |
| POST | `/invoices/{id}/send-draft` | Save invoice email as a Gmail draft (with PDF attachment if generated) |
| POST | `/invoices/{id}/send-email` | Send invoice email via Gmail with PDF attached; requires PDF to exist; marks invoice `sent_at` |

---

## 4. Business Logic

### 4.1 Duration Rounding — `_slot_hours`

Calendar event duration is rounded **up** to the nearest 0.5 hour.

```
raw_hours = (end_time - start_time).total_seconds() / 3600
slot_hours = math.ceil(raw_hours * 2) / 2
```

Examples: 25 min → 0.5 h, 30 min → 0.5 h, 55 min → 1.0 h, 75 min → 1.5 h.

If duration cannot be parsed, defaults to 1.0 h.

### 4.2 Client Inference — `_infer_client`

Scores each active client against a calendar event's `summary` and `attendees_json`. Returns `(client_id, client_name, confidence)`.

**Exclusions before scoring:**
- Attendees whose email ends with `@resource.calendar.google.com` (Zoom Rooms) are excluded.
- The user's own email (from `profile.user_email`) is excluded.
- The user's own name parts are excluded from title matching to avoid false positives.

**Scoring rules (highest wins):**

| Match | Score |
|-------|-------|
| Full client name in event title | 1.00 |
| Exact attendee display name match | 0.95 |
| Last name (word boundary) in title | 0.75 |
| `firstname.lastname` in email local part | 0.85 |
| Last name in email parts | 0.65 |
| First name in email local part | 0.60 |
| First name in attendee name | 0.70 |
| First name (word boundary) in title | 0.55 |

If best score < 0.30, returns `(None, None, 0.0)`.

### 4.3 Banana → Grape Promotion — `_promote_banana_sessions`

Sessions created from banana events (`color_id = '5'`) that have not yet been confirmed are re-checked against the live calendar. If the event's `color_id` has changed to `'3'` (grape), the session is promoted: `is_confirmed = 1`, `color_id = '3'`, and Obsidian note data is re-read.

Called explicitly via `POST /sessions/refresh-from-calendar`.

### 4.4 Invoice Numbering — `_invoice_number_for_period`

```
format: YYYY-{ABBREV}-{MM}
example: 2026-ARB-03
```

`ABBREV` resolution order:
1. `billing_companies.abbrev`
2. `billing_companies.invoice_prefix`
3. First 3 characters of company name, uppercased

Invoice number can also be overridden manually during the Prepare flow.

### 4.5 Invoice Generation — `generate_invoices`

Called by `POST /prepare/{year}/{month}/generate`. For each company in the request:

1. Skip if `billing_method` is NULL (non-billable).
2. Skip if total line amount is 0.
3. Skip if an invoice already exists for this company × period.
4. Create `billing_invoices` row with status `'draft'`; due date = invoice date + 30 days.
5. Create `billing_invoice_lines` rows in sort order.
6. Back-link sessions via `UPDATE billing_sessions SET invoice_line_id = ?` for lines of type `'sessions'`.

### 4.6 Payment Status Sync — `_sync_invoice_payment_status`

Called automatically after every `assign` or `remove` assignment operation.

```
paid_sum = SUM(amount_applied) for this invoice
if paid_sum >= total_amount - 0.01 → status = 'paid'
elif paid_sum > 0.01              → status = 'partial'
else                               → status = 'sent'
```

Does not run if the invoice is in `'draft'` status.

### 4.7 Rate Resolution

Session rate at confirmation time:

1. `billing_clients.rate_override` (if set and client is not prepaid)
2. `billing_companies.default_rate`
3. `0` (no rate configured)

For prepaid sessions: `amount = 0` regardless of rate.

### 4.8 Obsidian Note Lookup — `_lookup_obsidian_note`

Checks two locations in order:

1. `{vault}/8 Meetings/YYYY-MM-DD - {obsidian_name}.md` — session note (preferred)
2. `{vault}/9 Daily/YYYY-MM-DD.md` — daily note fallback

Reads `duration` frontmatter (integer minutes as a string, e.g. `"45"`); converts to hours. Returns `duration_source` to indicate where duration came from (`obsidian`, `daily_note`, or `note_found_no_duration`).

### 4.9 Invoice PDF — `_generate_pdf`

Uses **ReportLab**. PDF filename format:
```
Vantage Insights Invoice {invoice_number} {Month YYYY}.pdf
```

Provider info (name, address, phone, email) comes from billing settings in `config.json`. Payment instructions come from `billing_companies.payment_instructions`; if empty, derived via `_payment_text_fallback`:

- `billing_method = 'bill.com'` → "Arranged previously through Bill.com"
- `payment_method = 'etrade'` → "Payment via E*TRADE (ACH or wire transfer)"
- Other known methods: PayPal, Venmo, check, Tipalti

**Brand colors:** Green `#016630`, table header `#05DF72`.

### 4.10 Invoice Email Templates

Subject and body templates are stored per-company in `billing_companies.email_subject` and `billing_companies.email_body`. Template variables use `{{double_braces}}`:

| Variable | Value |
|----------|-------|
| `{{invoice_number}}` | Invoice number |
| `{{month}}` | "March 2026" |
| `{{client_names}}` | Comma-separated client names from linked sessions |
| `{{company_name}}` | Company name |
| `{{total_amount}}` | Formatted dollar amount |
| `{{due_date}}` | Due date string |

---

## 5. Frontend Views & Routes

All views are nested under `/billing` in the app router. The `BillingPage` component provides the sub-navigation bar and `<Routes>`.

| Route | Component | Description |
|-------|-----------|-------------|
| `/billing` (exact) | `UnprocessedQueue` | Unprocessed queue — grape/banana calendar events awaiting confirmation or dismissal |
| `/billing/sessions` | `SessionsView` | All confirmed sessions; tabs: By Company & Date / By Date / Summary |
| `/billing/invoices` | `InvoicesListView` | Invoice list with PDF generation and download |
| `/billing/invoices/:id` | `InvoiceDetailView` | Invoice detail with line items, sessions, payment assignments, and email compose/send |
| `/billing/payments` | `PaymentsView` | LunchMoney payment list with assignment UI |
| `/billing/summary` | `SummaryView` | Annual billing grid (Billing tab + Cash Received/Tax tab) for current year |
| `/billing/annual/:year` | `AnnualSummaryView` | Same grid for a specific year with year navigation |
| `/billing/prepare/:year/:month` | `InvoicePrepPage` | Multi-stage invoice prep wizard |

### Sub-navigation bar

```
Queue | Sessions | Invoices | Payments | Summary | Prepare
```

"Prepare" links to the previous month if before the 1st, otherwise current month.

### Sidebar Badges

When navigating any `/billing/*` route, the sidebar fetches `GET /api/billing/badge-counts` (stale after 60 s) and shows red `nav-count-badge` spans:

- **Billing** (top-level, when not on billing pages): combined total badge
- **Queue** sub-link: `queue_count` badge
- **Payments** sub-link: `unmatched_payments_count` badge

### InvoicePrepPage — Stage Flow

| Stage | Description |
|-------|-------------|
| 1. Select period | Month/year picker |
| 2. Review sessions | Per-company session tables, editable rates, prepaid override |
| 3. Configure invoice | Invoice date, services date, invoice number override, line item preview |
| 4. Done | Success screen with "View Invoices" and "View Sessions" buttons |

---

## 6. LunchMoney Connector

**File:** `app/backend/connectors/lunchmoney.py`

**Auth:** LunchMoney API token from `config.json` secret `LUNCHMONEY_TOKEN`.

**Sync behavior (`sync_lunchmoney_transactions`):**

1. Fetch transactions for the past `days_back` days (default 180) from the LunchMoney API.
2. Load all active `billing_companies` for name matching.
3. For each transaction with a new `lunchmoney_transaction_id`:
   - Insert into `billing_payments`.
   - Infer `company_id` from payee + notes using `_infer_company_id`.
   - **Tier-1 auto-match:** If company inferred AND an open invoice exists for that company with an exact amount match (`|invoice.total_amount - abs(payment.amount)| < 0.01`), auto-assign via `billing_invoice_payments`.
   - If auto-assigned, refine `company_id` from the matched invoice (wins over name-only inference).

**Company inference (`_infer_company_id`):**
- Matches company `name` or `abbrev` as whole tokens in `payee + notes`.
- Returns a match only if exactly one company matches (no ambiguous multi-match).
- Token matching uses word boundaries (`\b`).

**Re-link (`infer_company_ids_for_existing`):**
- Re-runs inference on all payments with `company_id IS NULL` or a stale FK.
- Called by `POST /lunchmoney/relink-companies`.

---

## 7. Color ID Convention

| `color_id` | Calendar color | Meaning |
|------------|---------------|---------|
| `'3'` | Grape (purple) | Confirmed past session — appears in unprocessed queue |
| `'5'` | Banana (yellow) | Projected future session — hidden by default; shown with "Show banana" toggle in queue |

Events with any other `color_id` never appear in the billing queue.

---

## 8. Briefing Integration

`GET /api/briefing` includes billing counts in the `pulse` block:

```json
{
  "pulse": {
    "billing_queue": 3,
    "billing_unmatched_payments": 0
  }
}
```

The briefing home page renders: **"Billing: 3 to process"** (or "N to match") as a clickable link to `/billing`. Only shown if either count is > 0.

---

## 9. Invariants — Never Change Without Explicit Instruction

| Rule | Why |
|------|-----|
| All `billing_*` table names | Alembic migrations are append-only; renaming breaks the chain |
| `color_id IN ('3','5')` filter | Matches grape/banana Google Calendar colors used in session discovery |
| Invoice number format `YYYY-{ABBREV}-{MM}` | Historical consistency; changing breaks import/dedup |
| `SEED_PATH` in `routers/billing.py` | Points to `app/backend/dashy_billing_seed.json` |
| `_slot_hours` rounding direction | Must round **up** — never round down or to nearest |
| `app/backend/dashy_billing_seed.json` | Never commit to git — contains private client and rate data |

---

## 10. Config Keys (billing settings in `config.json`)

Stored under `billing_settings`:

| Key | Purpose |
|-----|---------|
| `provider_name` | Defaults to "Vantage Insights" — appears in PDF header |
| `provider_address` | Multi-line address for PDF header |
| `provider_phone` | Phone for PDF header |
| `provider_email` | Email for PDF header |
| `invoice_output_dir` | Directory where PDFs are saved; defaults to `~/.personal-dashboard/invoices/` |
