#!/usr/bin/env python3
"""One-shot cleanup: remove April 7 duplicate payments that have no invoice links.

Safe to re-run — exits cleanly if nothing to delete.
"""

import sqlite3
from pathlib import Path

DB = Path.home() / ".personal-dashboard/dashboard.db"
conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

print("=== Before cleanup: all 2026-04-07 payments ===")
rows = conn.execute("""
    SELECT p.id, p.payee, p.amount, p.date, p.lunchmoney_transaction_id,
           COUNT(bip.invoice_id) AS invoice_links
    FROM billing_payments p
    LEFT JOIN billing_invoice_payments bip ON bip.payment_id = p.id
    WHERE p.date = '2026-04-07'
    GROUP BY p.id
    ORDER BY p.id
""").fetchall()
for r in rows:
    print(f"  id={r['id']:5}  lm_id={r['lunchmoney_transaction_id']}  "
          f"amount={r['amount']:10.2f}  links={r['invoice_links']}  payee={r['payee']!r:.60}")

orphans = [r for r in rows if r["invoice_links"] == 0]

if not orphans:
    print("\nNo orphan rows found — nothing to delete.")
    conn.close()
    exit(0)

ids = [r["id"] for r in orphans]
print(f"\nOrphan rows to delete (no invoice links): {ids}")

# FK-safe: delete invoice_payments first (should be empty, but be safe)
conn.execute(
    f"DELETE FROM billing_invoice_payments WHERE payment_id IN ({','.join('?'*len(ids))})", ids
)
conn.execute(
    f"DELETE FROM billing_payments WHERE id IN ({','.join('?'*len(ids))})", ids
)
conn.commit()
print("Deleted.")

print("\n=== After cleanup: 2026-04-07 payments ===")
remaining = conn.execute("""
    SELECT p.id, p.payee, p.amount, p.date, p.lunchmoney_transaction_id,
           COUNT(bip.invoice_id) AS invoice_links
    FROM billing_payments p
    LEFT JOIN billing_invoice_payments bip ON bip.payment_id = p.id
    WHERE p.date = '2026-04-07'
    GROUP BY p.id
    ORDER BY p.id
""").fetchall()
for r in remaining:
    print(f"  id={r['id']:5}  lm_id={r['lunchmoney_transaction_id']}  "
          f"amount={r['amount']:10.2f}  links={r['invoice_links']}  payee={r['payee']!r:.60}")

conn.close()
