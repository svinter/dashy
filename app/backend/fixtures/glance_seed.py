"""Glance seed data — sample trips and entries for visual testing.

Run with:
    python -m backend.fixtures.glance_seed

Idempotent: rows with source_ref='seed_v1' are skipped on re-run.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure backend is on the path when run as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db_connection


SOURCE_REF = "seed_v1"


def _date_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def seed():
    with get_db_connection() as db:
        # ------------------------------------------------------------------
        # Trips
        # ------------------------------------------------------------------
        existing_trip_refs = {
            r["source_ref"]
            for r in db.execute(
                "SELECT source_ref FROM glance_trips WHERE source_ref IS NOT NULL"
            ).fetchall()
        }

        # Trip 1: Steve → Portugal, 2026-04-04 → 2026-04-22
        trip1_ref = "seed_v1_trip_steve_portugal"
        if trip1_ref not in existing_trip_refs:
            cur = db.execute(
                """
                INSERT INTO glance_trips
                    (member_id, location_id, start_date, end_date, source, source_ref)
                VALUES ('steve', 'portugal', '2026-04-04', '2026-04-22', 'manual', ?)
                """,
                (trip1_ref,),
            )
            t1_id = cur.lastrowid

            trip1_start = date(2026, 4, 4)
            trip1_end = date(2026, 4, 22)
            day_notes = {
                date(2026, 4, 4): "TAP BOS→LIS, 9:45pm",
                date(2026, 4, 22): "LIS→BOS, late afternoon",
            }
            for d in _date_range(trip1_start, trip1_end):
                depart = (d == trip1_start)
                is_return = (d == trip1_end)
                sleep = (d != trip1_end)   # sleep every night except return day
                notes = day_notes.get(d)
                db.execute(
                    """
                    INSERT INTO glance_trip_days
                        (trip_id, date, depart, sleep, "return", notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (t1_id, d.isoformat(), int(depart), int(sleep), int(is_return), notes),
                )
            print(f"Inserted trip: Steve → Portugal ({t1_id})")
        else:
            print("Skipped trip: Steve → Portugal (already exists)")

        # Trip 2: PGV → Azores, 2026-05-09 → 2026-05-15
        trip2_ref = "seed_v1_trip_pgv_azores"
        if trip2_ref not in existing_trip_refs:
            cur = db.execute(
                """
                INSERT INTO glance_trips
                    (member_id, location_id, start_date, end_date, source, source_ref)
                VALUES ('pgv', 'azores', '2026-05-09', '2026-05-15', 'manual', ?)
                """,
                (trip2_ref,),
            )
            t2_id = cur.lastrowid

            trip2_start = date(2026, 5, 9)
            trip2_end = date(2026, 5, 15)
            for d in _date_range(trip2_start, trip2_end):
                depart = (d == trip2_start)
                is_return = (d == trip2_end)
                sleep = True  # sleep every night including return day per spec
                db.execute(
                    """
                    INSERT INTO glance_trip_days
                        (trip_id, date, depart, sleep, "return", notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (t2_id, d.isoformat(), int(depart), int(sleep), int(is_return), None),
                )
            print(f"Inserted trip: PGV → Azores ({t2_id})")
        else:
            print("Skipped trip: PGV → Azores (already exists)")

        # Trip 3: PGV → Sark, 2026-05-16 → 2026-05-21
        trip3_ref = "seed_v1_trip_pgv_sark"
        if trip3_ref not in existing_trip_refs:
            cur = db.execute(
                """
                INSERT INTO glance_trips
                    (member_id, location_id, start_date, end_date, source, source_ref)
                VALUES ('pgv', 'sark', '2026-05-16', '2026-05-21', 'manual', ?)
                """,
                (trip3_ref,),
            )
            t3_id = cur.lastrowid

            trip3_start = date(2026, 5, 16)
            trip3_end = date(2026, 5, 21)
            for d in _date_range(trip3_start, trip3_end):
                depart = (d == trip3_start)
                is_return = (d == trip3_end)
                sleep = (d != trip3_end)
                db.execute(
                    """
                    INSERT INTO glance_trip_days
                        (trip_id, date, depart, sleep, "return", notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (t3_id, d.isoformat(), int(depart), int(sleep), int(is_return), None),
                )
            print(f"Inserted trip: PGV → Sark ({t3_id})")
        else:
            print("Skipped trip: PGV → Sark (already exists)")

        # ------------------------------------------------------------------
        # Entries
        # ------------------------------------------------------------------
        existing_entry_refs = {
            r["source_ref"]
            for r in db.execute(
                "SELECT source_ref FROM glance_entries WHERE source_ref IS NOT NULL"
            ).fetchall()
        }

        entries = [
            # (source_ref, lane, member_id, date, label, notes)
            ("seed_v1_e01", "steve_events", None, "2026-04-07", "dental cleaning", "Dr. Lin, 8am. Cleaning + x-rays."),
            ("seed_v1_e02", "steve_events", None, "2026-04-27", "offsite", "Acme LT offsite, Cambridge. Day 1."),
            ("seed_v1_e03", "steve_events", None, "2026-04-28", "offsite", "Acme LT offsite day 2."),
            ("seed_v1_e04", "steve_events", None, "2026-04-30", "Swept Away", "Dinner at Swept Away, 7:30."),
            ("seed_v1_e05", "steve_events", None, "2026-05-01", "first Friday", "Monthly leadership circle. 4–6pm."),
            ("seed_v1_e06", "york", None, "2026-04-01", "us", "Whole family up. Back Sunday."),
            ("seed_v1_e07", "york", None, "2026-04-02", "us", None),
            ("seed_v1_e08", "york", None, "2026-04-03", "us", None),
            ("seed_v1_e09", "york", None, "2026-04-26", "PGV", "PGV solo overnight."),
            ("seed_v1_e10", "fam_events", "kpv", "2026-04-30", "recital", "School spring recital, 6pm."),
            ("seed_v1_e11", "fam_events", "ovinters", "2026-05-12", "soccer final", "Championship game, 4pm."),
        ]

        for ref, lane, member_id, entry_date, label, notes in entries:
            if ref in existing_entry_refs:
                print(f"Skipped entry: {ref} (already exists)")
                continue
            db.execute(
                """
                INSERT INTO glance_entries
                    (lane, member_id, date, label, notes, source, source_ref)
                VALUES (?, ?, ?, ?, ?, 'manual', ?)
                """,
                (lane, member_id, entry_date, label, notes, ref),
            )
            print(f"Inserted entry: {ref} — {lane} {entry_date} '{label}'")

        db.commit()
        print("Done.")


if __name__ == "__main__":
    seed()
