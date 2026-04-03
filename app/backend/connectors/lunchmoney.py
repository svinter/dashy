"""LunchMoney connector — syncs transactions into billing_payments with auto-matching."""

import logging
from datetime import datetime, timedelta

from app_config import get_secret
from database import get_write_db, get_db_connection

logger = logging.getLogger(__name__)


def _get_client():
    token = get_secret("LUNCHMONEY_API_KEY")
    if not token:
        raise RuntimeError("LUNCHMONEY_API_KEY not configured")
    try:
        from lunchable import LunchMoney  # type: ignore
    except ImportError:
        raise RuntimeError("lunchable not installed — run: pip install lunchable")
    return LunchMoney(access_token=token)


def check_lunchmoney() -> dict:
    try:
        _get_client()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _infer_company_id(haystack: str, companies: list) -> int | None:
    """Return a company_id if exactly one company's name or abbrev appears in haystack.

    Matching rules (in priority order):
    1. Exact case-insensitive match of company name or abbrev as a standalone token
    2. Company name is a substring of the haystack
    Falls back to None if zero or multiple companies match (ambiguous).
    """
    haystack_lower = haystack.lower()
    matched: set[int] = set()

    for co in companies:
        name = (co["name"] or "").lower().strip()
        abbrev = (co["abbrev"] or "").lower().strip()

        # Abbrev match: treat as a word-boundary token to avoid false positives
        # (e.g. "CFS" shouldn't match "ACHCREDIT CFS INC")
        if abbrev and _token_in(abbrev, haystack_lower):
            matched.add(co["id"])
            continue

        # Full name substring match
        if name and name in haystack_lower:
            matched.add(co["id"])

    return next(iter(matched)) if len(matched) == 1 else None


def _token_in(token: str, haystack: str) -> bool:
    """Return True if `token` appears as a word/token inside `haystack`."""
    import re
    # Escape for regex, then require word-like boundaries
    pattern = r'(?<![a-z0-9])' + re.escape(token) + r'(?![a-z0-9])'
    return bool(re.search(pattern, haystack))


def infer_company_ids_for_existing(db) -> int:
    """Back-fill company_id on billing_payments rows that have no company_id,
    or where company_id references a company that no longer exists (stale FK).

    Uses the same matching logic as the sync. Returns the count of rows updated.
    """
    companies = db.execute("SELECT id, name, abbrev FROM billing_companies").fetchall()
    valid_company_ids = {co["id"] for co in companies}
    rows = db.execute(
        "SELECT id, payee, notes, company_id FROM billing_payments"
    ).fetchall()
    rows = [r for r in rows if r["company_id"] is None or r["company_id"] not in valid_company_ids]

    updated = 0
    for row in rows:
        haystack = ((row["payee"] or "") + " " + (row["notes"] or "")).strip()
        company_id = _infer_company_id(haystack, companies)
        if company_id is not None:
            db.execute(
                "UPDATE billing_payments SET company_id = ? WHERE id = ?",
                (company_id, row["id"]),
            )
            updated += 1

    if updated:
        db.commit()
    return updated


def sync_lunchmoney_transactions(days_back: int = 180) -> dict:
    """Fetch recent LunchMoney transactions and upsert into billing_payments.

    Only imports transactions where:
    - category_name == "Coaching income" (case-insensitive)
    - is_income is True (i.e. the transaction is a credit)

    For each newly inserted payment:
    - Attempts to infer company_id from payee/notes (name or abbrev match).
    - Tier-1 auto-match: company name/abbrev found in payee or notes + exact amount → auto-link.
    - Tier-2 auto-match: exact amount + ±30 days of due_date → auto-link.
    - Uses absolute value of amount (LunchMoney credits are negative).
    """
    client = _get_client()

    start = (datetime.now() - timedelta(days=days_back)).date()
    end = datetime.now().date()

    transactions = client.get_transactions(start_date=start, end_date=end)

    inserted = 0
    skipped = 0
    auto_matched = 0

    with get_write_db() as db:
        companies = db.execute("SELECT id, name, abbrev FROM billing_companies").fetchall()

        open_invoices = db.execute(
            "SELECT bi.id, bi.total_amount, bi.due_date, bi.company_id "
            "FROM billing_invoices bi "
            "JOIN billing_companies bco ON bco.id = bi.company_id "
            "WHERE bi.status NOT IN ('paid', 'cancelled') AND bi.due_date IS NOT NULL "
            "AND bco.active = 1"
        ).fetchall()

        for txn in transactions:
            # Only import coaching income credits
            cat = (txn.category_name or "").lower().strip()
            if cat != "coaching income" or not txn.is_income:
                skipped += 1
                continue

            txn_id = str(txn.id)
            amount = float(txn.amount)
            txn_date = str(txn.date)
            payee = txn.payee or ""
            notes = getattr(txn, "notes", None) or ""

            existing = db.execute(
                "SELECT id FROM billing_payments WHERE lunchmoney_transaction_id = ?",
                (txn_id,),
            ).fetchone()

            if existing:
                skipped += 1
                continue

            haystack = (payee + " " + notes).strip()
            company_id = _infer_company_id(haystack, companies)

            cur = db.execute(
                "INSERT INTO billing_payments (lunchmoney_transaction_id, date, amount, payee, notes, company_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (txn_id, txn_date, amount, payee, notes, company_id),
            )
            payment_id = cur.lastrowid
            inserted += 1

            # Auto-match: exact absolute amount, prioritising company-name matches.
            # Tier 1: company match + exact amount (any date) → auto-link.
            # Tier 2: exact amount + ±30 days of due_date → auto-link.
            abs_amount = abs(amount)
            linked = False
            linked_company_id: int | None = None
            for tier in (1, 2):
                for inv in open_invoices:
                    if linked:
                        break
                    inv_total = float(inv["total_amount"])
                    if abs(inv_total - abs_amount) >= 0.01:
                        continue
                    if tier == 1 and inv["company_id"] != company_id:
                        continue
                    if tier == 2:
                        try:
                            due = datetime.strptime(inv["due_date"][:10], "%Y-%m-%d").date()
                            paid = datetime.strptime(txn_date[:10], "%Y-%m-%d").date()
                            if abs((paid - due).days) > 30:
                                continue
                        except (ValueError, TypeError):
                            continue
                    db.execute(
                        "INSERT INTO billing_invoice_payments "
                        "(invoice_id, payment_id, amount_applied) VALUES (?, ?, ?)",
                        (inv["id"], payment_id, abs_amount),
                    )
                    auto_matched += 1
                    linked = True
                    linked_company_id = inv["company_id"]

            # Refine company_id from invoice link (wins over name-only match)
            if linked_company_id and linked_company_id != company_id:
                db.execute(
                    "UPDATE billing_payments SET company_id=? WHERE id=?",
                    (linked_company_id, payment_id),
                )

        db.commit()

    return {
        "inserted": inserted,
        "skipped": skipped,
        "auto_matched": auto_matched,
        "total": len(transactions),
    }
