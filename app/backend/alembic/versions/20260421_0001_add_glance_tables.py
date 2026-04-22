"""Add Glance family activity tracking tables

Revision ID: 20260421_0001
Revises: 20260420_0001
Create Date: 2026-04-21 00:01:00

Tables created:
  glance_members              — family members (steve, pgv, kpv, ovinters)
  glance_locations            — named locations (boston, york, portugal, azores, sark)
  glance_trips                — travel spans with member + location
  glance_trip_days            — per-day marks (depart/sleep/return) within a trip
  glance_entries              — one-off events in lanes (steve_events, fam_events, york)
  glance_gcal_cache           — GCal event cache (populated in Phase 3)
  glance_promoted_gcal_events — promoted GCal events linked to trips/entries
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260421_0001"
down_revision: Union[str, None] = "20260420_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_members (
            id               TEXT PRIMARY KEY,
            display          TEXT NOT NULL,
            color_bg         TEXT NOT NULL,
            color_text       TEXT NOT NULL,
            color_accent     TEXT NOT NULL,
            sort_order       INTEGER NOT NULL DEFAULT 0,
            gcal_calendar_id TEXT
        )
    """)

    op.execute("""
        INSERT OR IGNORE INTO glance_members
            (id, display, color_bg, color_text, color_accent, sort_order, gcal_calendar_id)
        VALUES
            ('steve',    'Steve',    '#B5D4F4', '#0C447C', '#B5D4F4', 0, 'Steve Vinter (personal)'),
            ('pgv',      'PGV',      '#F4C0D1', '#72243E', '#F4C0D1', 1, 'Pat Vinter'),
            ('kpv',      'KPV',      '#9FE1CB', '#085041', '#9FE1CB', 2, NULL),
            ('ovinters', 'OVinters', '#FAC775', '#633806', '#FAC775', 3, NULL)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_locations (
            id         TEXT PRIMARY KEY,
            display    TEXT NOT NULL,
            color_bg   TEXT NOT NULL,
            color_text TEXT NOT NULL,
            is_home    BOOLEAN NOT NULL DEFAULT 0,
            is_york    BOOLEAN NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        INSERT OR IGNORE INTO glance_locations
            (id, display, color_bg, color_text, is_home, is_york)
        VALUES
            ('boston',   'boston',   '#8CB8E5', '#042C53', 1, 0),
            ('york',     'york',     '#97C35B', '#173404', 0, 1),
            ('portugal', 'Portugal', '#EF997A', '#4A1B0C', 0, 0),
            ('azores',   'Azores',   '#EF997A', '#4A1B0C', 0, 0),
            ('sark',     'Sark',     '#EF997A', '#4A1B0C', 0, 0)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_trips (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id   TEXT NOT NULL REFERENCES glance_members(id),
            location_id TEXT NOT NULL REFERENCES glance_locations(id),
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            notes       TEXT,
            source      TEXT NOT NULL DEFAULT 'manual',
            source_ref  TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_glance_trips_member
            ON glance_trips (member_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_glance_trips_dates
            ON glance_trips (start_date, end_date)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_trip_days (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id  INTEGER NOT NULL REFERENCES glance_trips(id) ON DELETE CASCADE,
            date     TEXT NOT NULL,
            depart   BOOLEAN NOT NULL DEFAULT 0,
            sleep    BOOLEAN NOT NULL DEFAULT 0,
            "return" BOOLEAN NOT NULL DEFAULT 0,
            notes    TEXT
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_glance_trip_days_trip
            ON glance_trip_days (trip_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_glance_trip_days_date
            ON glance_trip_days (date)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_entries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            lane       TEXT NOT NULL,
            member_id  TEXT REFERENCES glance_members(id),
            date       TEXT NOT NULL,
            label      TEXT NOT NULL,
            notes      TEXT,
            source     TEXT NOT NULL DEFAULT 'manual',
            source_ref TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_glance_entries_date
            ON glance_entries (date)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_glance_entries_lane
            ON glance_entries (lane)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_gcal_cache (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            gcal_event_id         TEXT UNIQUE,
            gcal_calendar_id      TEXT,
            lane_overlay          TEXT,
            member_id             TEXT,
            title                 TEXT,
            start_date            TEXT,
            end_date              TEXT,
            is_recurring_instance BOOLEAN NOT NULL DEFAULT 0,
            recurring_series_id   TEXT,
            is_promoted           BOOLEAN NOT NULL DEFAULT 0,
            fetched_at            TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS glance_promoted_gcal_events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            gcal_event_id TEXT UNIQUE,
            target_type   TEXT,
            target_id     INTEGER,
            promoted_at   TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS glance_promoted_gcal_events")
    op.execute("DROP TABLE IF EXISTS glance_gcal_cache")
    op.execute("DROP TABLE IF EXISTS glance_entries")
    op.execute("DROP TABLE IF EXISTS glance_trip_days")
    op.execute("DROP TABLE IF EXISTS glance_trips")
    op.execute("DROP TABLE IF EXISTS glance_locations")
    op.execute("DROP TABLE IF EXISTS glance_members")
