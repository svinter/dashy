"""SQLAlchemy-style dataclass models for the Glance module.

These mirror the glance_* table schemas exactly.
Used for type documentation, __repr__ convenience, and router serialization.
The underlying database uses raw SQLite (not the ORM engine), so these are
plain dataclasses rather than declarative_base subclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GlanceMember:
    id: str
    display: str
    color_bg: str
    color_text: str
    color_accent: str
    sort_order: int = 0
    gcal_calendar_id: Optional[str] = None

    def __repr__(self) -> str:
        return f"<GlanceMember id={self.id!r} display={self.display!r} sort_order={self.sort_order}>"


@dataclass
class GlanceLocation:
    id: str
    display: str
    color_bg: str
    color_text: str
    is_home: bool = False
    is_york: bool = False

    def __repr__(self) -> str:
        flags = []
        if self.is_home:
            flags.append("home")
        if self.is_york:
            flags.append("york")
        return f"<GlanceLocation id={self.id!r} display={self.display!r} flags={flags}>"


@dataclass
class GlanceTrip:
    id: int
    member_id: str
    location_id: str
    start_date: str          # ISO date YYYY-MM-DD
    end_date: str            # ISO date YYYY-MM-DD
    notes: Optional[str] = None
    source: str = "manual"
    source_ref: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"<GlanceTrip id={self.id} member={self.member_id!r} "
            f"location={self.location_id!r} {self.start_date}→{self.end_date}>"
        )


@dataclass
class GlanceTripDay:
    id: int
    trip_id: int
    date: str                # ISO date YYYY-MM-DD
    depart: bool = False
    sleep: bool = False
    # 'return' is a Python reserved word — stored as 'return' in DB, accessed via dict key
    is_return: bool = False
    notes: Optional[str] = None

    def __repr__(self) -> str:
        marks = "".join([
            "→" if self.depart else "",
            "·" if self.sleep else "",
            "←" if self.is_return else "",
        ])
        return f"<GlanceTripDay id={self.id} trip_id={self.trip_id} date={self.date!r} marks={marks!r}>"


@dataclass
class GlanceEntry:
    id: int
    lane: str                # steve_events | fam_events | york
    date: str                # ISO date YYYY-MM-DD
    label: str
    member_id: Optional[str] = None
    notes: Optional[str] = None
    source: str = "manual"
    source_ref: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"<GlanceEntry id={self.id} lane={self.lane!r} "
            f"date={self.date!r} label={self.label!r}>"
        )


@dataclass
class GlanceGcalCache:
    id: int
    gcal_event_id: Optional[str] = None
    gcal_calendar_id: Optional[str] = None
    lane_overlay: Optional[str] = None
    member_id: Optional[str] = None
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_recurring_instance: bool = False
    recurring_series_id: Optional[str] = None
    is_promoted: bool = False
    fetched_at: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"<GlanceGcalCache id={self.id} event_id={self.gcal_event_id!r} "
            f"title={self.title!r} {self.start_date}→{self.end_date}>"
        )


@dataclass
class GlancePromotedGcalEvent:
    id: int
    gcal_event_id: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    promoted_at: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"<GlancePromotedGcalEvent id={self.id} "
            f"event_id={self.gcal_event_id!r} target={self.target_type}:{self.target_id}>"
        )
