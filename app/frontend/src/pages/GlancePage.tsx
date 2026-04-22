import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  useGlanceData,
  useGlanceMembers,
  useGlanceLocations,
  useCreateGlanceTrip,
  useUpdateGlanceTrip,
  useDeleteGlanceTrip,
  useCreateGlanceEntries,
  useUpdateGlanceEntry,
  useDeleteGlanceEntry,
} from '../hooks/useGlanceData';
import type { GlanceTripDay, GlanceEntry } from '../hooks/useGlanceData';
import { GlanceGrid } from '../components/glance/GlanceGrid';
import { GlanceTooltip } from '../components/glance/GlanceTooltip';
import type { TooltipData } from '../components/glance/GlanceTooltip';
import type { LaneId } from '../components/glance/LaneRow';
import { HorizontalGlance } from '../components/glance/HorizontalGlance';
import { TripForm } from '../components/glance/TripForm';
import type { TripFormInitial } from '../components/glance/TripForm';
import { EntryForm } from '../components/glance/EntryForm';
import type { EntryFormInitial } from '../components/glance/EntryForm';
import { ViewEditPopover } from '../components/glance/ViewEditPopover';

// ---------------------------------------------------------------------------
// Exported types — imported by GlanceGrid, GlanceWeek, LaneRow
// ---------------------------------------------------------------------------

export type DragState =
  | { type: 'create'; startDate: string; currentDate: string; laneId: LaneId }
  | { type: 'edge'; tripId: number; edge: 'start' | 'end'; originalDate: string; currentDate: string };

export type CursorCell = { date: string; laneId: LaneId };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LANE_CONFIG: { id: LaneId; controlLabel: string; shortLabel: string; shortcutHint: string }[] = [
  { id: 'gcal',        controlLabel: 'calendar',      shortLabel: 'calendar',  shortcutHint: 'f1' },
  { id: 'york',        controlLabel: 'york house',    shortLabel: 'york',      shortcutHint: 'f2' },
  { id: 'fam_events',  controlLabel: 'family events', shortLabel: 'family',    shortcutHint: 'f3' },
  { id: 'fam_travel',  controlLabel: 'family travel', shortLabel: 'travel',    shortcutHint: 'f4' },
  { id: 'steve_events',controlLabel: 'my events',     shortLabel: 'my events', shortcutHint: 'f5' },
  { id: 'steve_travel',controlLabel: 'my travel',     shortLabel: 'my travel', shortcutHint: 'f6' },
];

const LANE_IDS: LaneId[] = LANE_CONFIG.map((l) => l.id);

const DEFAULT_VISIBLE_LANES: Set<LaneId> = new Set([
  'york', 'fam_events', 'fam_travel', 'steve_events', 'steve_travel',
]);

const DEFAULT_VISIBLE_MEMBERS: Set<string> = new Set(['pgv', 'kpv', 'ovinters']);

const MEMBER_SWATCHES: Record<string, { label: string; color: string; shortcutHint: string }> = {
  pgv:      { label: 'PGV',      color: '#F4C0D1', shortcutHint: 'fp' },
  kpv:      { label: 'KPV',      color: '#9FE1CB', shortcutHint: 'fk' },
  ovinters: { label: 'OVinters', color: '#FAC775', shortcutHint: 'fo' },
};

const TRAVEL_LANES = new Set<LaneId>(['steve_travel', 'fam_travel']);
const EVENT_LANES  = new Set<LaneId>(['steve_events', 'fam_events', 'york']);

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

type ModalState =
  | { type: 'trip-form';   initial: TripFormInitial;  editId?: number; existingTrip?: GlanceTripDay }
  | { type: 'entry-form';  initial: EntryFormInitial; editId?: number; existingEntry?: GlanceEntry; existingDate?: string }
  | { type: 'view-edit';   date: string; laneId: LaneId; laneLabel: string; trips: GlanceTripDay[]; entries: GlanceEntry[]; anchorPos?: { top: number; left: number } };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function localIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function getLaneShortLabel(id: LaneId): string {
  return LANE_CONFIG.find((l) => l.id === id)?.shortLabel ?? id;
}

// ---------------------------------------------------------------------------
// Page navigation constants and helpers
// ---------------------------------------------------------------------------

const CALENDAR_START = new Date(2026, 3, 1); // Apr 1, 2026 — immutable
const CALENDAR_END   = new Date(2030, 3, 1); // Apr 1, 2030 — immutable
const PAGE_MONTHS    = 6;

/** Returns the Monday on or before `d`. */
function getMondayOnOrBefore(d: Date): Date {
  const result = new Date(d);
  const day = result.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat
  const diff = day === 0 ? -6 : 1 - day;
  result.setDate(result.getDate() + diff);
  return result;
}

/** Returns the Sunday on or after `d`. */
function getSundayOnOrAfter(d: Date): Date {
  const result = new Date(d);
  const day = result.getDay();
  const diff = day === 0 ? 0 : 7 - day;
  result.setDate(result.getDate() + diff);
  return result;
}

const MONTH_ABBR_LONG = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function getPage1Start(): Date {
  const today = new Date();
  return new Date(today.getFullYear(), today.getMonth() - 1, 1);
}

function pageStartForIndex(n: number): Date {
  if (n === 0) return new Date(CALENDAR_START);
  const base = getPage1Start();
  base.setMonth(base.getMonth() + (n - 1) * PAGE_MONTHS);
  return base;
}

function formatPageLabel(start: Date, end: Date): string {
  // end is exclusive (pageStart + 6 months), so last visible month is end - 1 month
  const lastMonth = new Date(end);
  lastMonth.setMonth(lastMonth.getMonth() - 1);
  const sm = MONTH_ABBR_LONG[start.getMonth()];
  const em = MONTH_ABBR_LONG[lastMonth.getMonth()];
  if (start.getFullYear() === lastMonth.getFullYear()) {
    return `${sm} – ${em} ${start.getFullYear()}`;
  }
  return `${sm} ${start.getFullYear()} – ${em} ${lastMonth.getFullYear()}`;
}

// ---------------------------------------------------------------------------
// GlancePage
// ---------------------------------------------------------------------------

export function GlancePage() {
  const [pageStart, setPageStart] = useState<Date>(() => pageStartForIndex(1));
  const [isTodayWindow, setIsTodayWindow] = useState(true);

  const pageEnd   = new Date(pageStart);
  pageEnd.setMonth(pageEnd.getMonth() + PAGE_MONTHS);
  const clampedEnd = pageEnd > CALENDAR_END ? new Date(CALENDAR_END) : pageEnd;

  // Extend query to full Mon–Sun week boundaries so the grid always starts on
  // Monday and ends on Sunday. This prevents a partial first week (Bug: grid
  // starts on a Wednesday instead of the Monday before) and ensures trips that
  // straddle the last week are stored and displayed with their full date range
  // (Bug: trip end_date in synthetic padding days appeared truncated).
  const queryStart = getMondayOnOrBefore(pageStart);
  const queryEnd   = getSundayOnOrAfter(clampedEnd);

  const { weeksData, isLoading, error } = useGlanceData(localIso(queryStart), localIso(queryEnd));
  const { data: members = [] } = useGlanceMembers();
  const { data: locations = [] } = useGlanceLocations();

  const createTrip   = useCreateGlanceTrip();
  const updateTrip   = useUpdateGlanceTrip();
  const deleteTrip   = useDeleteGlanceTrip();
  const createEntries = useCreateGlanceEntries();
  const updateEntry  = useUpdateGlanceEntry();
  const deleteEntry  = useDeleteGlanceEntry();

  const [visibleLanes,   setVisibleLanes]   = useState<Set<LaneId>>(new Set(DEFAULT_VISIBLE_LANES));
  const [visibleMembers, setVisibleMembers] = useState<Set<string>>(new Set(DEFAULT_VISIBLE_MEMBERS));
  const [mode,           setMode]           = useState<'vertical' | 'horizontal'>('vertical');
  const [tooltip,        setTooltip]        = useState<TooltipData | null>(null);
  const [cursor,         setCursor]         = useState<CursorCell | null>(null);
  const [dragState,      setDragState]      = useState<DragState | null>(null);
  const [modal,          setModal]          = useState<ModalState | null>(null);
  const [gMode,          setGMode]          = useState(false);
  const [gInput,         setGInput]         = useState('');
  const [monthOpacity,   setMonthOpacity]   = useState<number>(() => {
    const stored = localStorage.getItem('glance_month_opacity');
    return stored !== null ? Number(stored) : 7;
  });

  const containerRef   = useRef<HTMLDivElement>(null);
  const gridScrollRef  = useRef<HTMLDivElement>(null);
  const gInputRef      = useRef<HTMLInputElement>(null);
  const didDragRef    = useRef(false);
  // Ref mirror of dragState so callbacks can read latest without stale closures
  const dragStateRef  = useRef<DragState | null>(null);
  dragStateRef.current = dragState;
  // Ref mirrors for keyboard handler
  const weeksDataRef  = useRef(weeksData);
  weeksDataRef.current = weeksData;
  const cursorRef     = useRef(cursor);
  cursorRef.current   = cursor;
  const modalRef      = useRef(modal);
  modalRef.current    = modal;
  // (currentPageRef removed — page navigation now uses functional state updaters)
  const [filterMode, setFilterMode] = useState(false);
  const filterModeRef = useRef(false);
  filterModeRef.current = filterMode;

  // --- Lane / member toggles ---

  const toggleLane = useCallback((id: LaneId) => {
    setVisibleLanes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleMember = useCallback((id: string) => {
    setVisibleMembers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // --- Tooltip ---

  const handleNoteHover = useCallback(
    (e: React.MouseEvent, laneLabel: string, date: string, notes: string[]) => {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      setTooltip({ laneLabel, date, notes, anchorRect: rect });
    },
    [],
  );

  const handleNoteLeave = useCallback(() => setTooltip(null), []);

  // --- Cell event handlers ---

  const handleCellMouseDown = useCallback((date: string, laneId: LaneId, _e: React.MouseEvent) => {
    if (laneId === 'gcal') return;
    didDragRef.current = false;
    setDragState({ type: 'create', startDate: date, currentDate: date, laneId });
    setCursor({ date, laneId });
  }, []);

  const handleCellMouseEnter = useCallback((date: string) => {
    setDragState((prev) => {
      if (!prev) return prev;
      if (prev.type === 'create') {
        if (prev.currentDate !== date) didDragRef.current = true;
        return { ...prev, currentDate: date };
      }
      if (prev.type === 'edge' && prev.currentDate !== date) {
        return { ...prev, currentDate: date };
      }
      return prev;
    });
  }, []);

  const handleCellMouseUp = useCallback((date: string, _laneId: LaneId) => {
    const ds = dragStateRef.current;
    if (ds?.type === 'edge') {
      const key = ds.edge === 'start' ? 'start_date' : 'end_date';
      updateTrip.mutate({ id: ds.tripId, [key]: ds.currentDate });
      setDragState(null);
      return;
    }
    if (ds?.type === 'create' && didDragRef.current) {
      const startDate = ds.startDate < date ? ds.startDate : date;
      const endDate   = ds.startDate > date ? ds.startDate : date;
      const lane = ds.laneId;
      if (TRAVEL_LANES.has(lane)) {
        setModal({ type: 'trip-form', initial: { laneId: lane, startDate, endDate } });
      } else if (EVENT_LANES.has(lane)) {
        setModal({ type: 'entry-form', initial: { laneId: lane, startDate, endDate } });
      }
    }
    setDragState(null);
  }, [updateTrip]);

  const handleCellClick = useCallback((date: string, laneId: LaneId, e: React.MouseEvent) => {
    if (didDragRef.current) return;
    if (laneId === 'gcal') return;

    const data = weeksDataRef.current[date];
    const trips   = (data?.trips   ?? []).filter((t)  => t.lane  === laneId);
    const entries = (data?.entries ?? []).filter((en) => en.lane === laneId);

    if (trips.length > 0 || entries.length > 0) {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      const popoverH = 200;
      const top = rect.bottom + 4 + popoverH > window.innerHeight ? rect.top - popoverH - 4 : rect.bottom + 4;
      const left = Math.min(rect.left, window.innerWidth - 300);
      setModal({ type: 'view-edit', date, laneId, laneLabel: getLaneShortLabel(laneId), trips, entries, anchorPos: { top, left } });
    } else if (TRAVEL_LANES.has(laneId)) {
      setModal({ type: 'trip-form', initial: { laneId, startDate: date, endDate: date } });
    } else if (EVENT_LANES.has(laneId)) {
      setModal({ type: 'entry-form', initial: { laneId, startDate: date, endDate: date } });
    }
  }, []);

  const handleEdgeDragStart = useCallback((tripId: number, edge: 'start' | 'end', _e: React.MouseEvent) => {
    let originalDate = '';
    for (const dayData of Object.values(weeksDataRef.current)) {
      const trip = dayData.trips.find((t) => t.trip_id === tripId);
      if (trip) {
        originalDate = edge === 'start' ? trip.trip_start : trip.trip_end;
        break;
      }
    }
    setDragState({ type: 'edge', tripId, edge, originalDate, currentDate: originalDate });
  }, []);

  // Global mouseup: clean up drag if released outside a grid cell
  useEffect(() => {
    function onGlobalMouseUp() {
      if (dragStateRef.current) setDragState(null);
    }
    document.addEventListener('mouseup', onGlobalMouseUp);
    return () => document.removeEventListener('mouseup', onGlobalMouseUp);
  }, []);

  useEffect(() => {
    localStorage.setItem('glance_month_opacity', String(monthOpacity));
  }, [monthOpacity]);

  // --- Page navigation ---

  function scrollToToday() {
    const el = gridScrollRef.current;
    if (!el) return;
    const today = new Date();
    const pageStartDate = pageStartForIndex(1);
    const msPerWeek = 7 * 24 * 60 * 60 * 1000;
    const weeksFromStart = Math.floor(
      (today.getTime() - pageStartDate.getTime()) / msPerWeek
    );
    const pageEndDate = new Date(pageStartDate);
    pageEndDate.setMonth(pageEndDate.getMonth() + PAGE_MONTHS);
    const totalWeeks = Math.ceil((pageEndDate.getTime() - pageStartDate.getTime()) / msPerWeek);
    const weekHeight = el.scrollHeight / totalWeeks;
    el.scrollTop = Math.max(0, weeksFromStart * weekHeight);
  }

  // goToPage: index-based jump (used by digit keyboard shortcuts)
  function goToPage(n: number) {
    const maxPage = Math.ceil(
      (CALENDAR_END.getTime() - getPage1Start().getTime())
      / (1000 * 60 * 60 * 24 * 30 * PAGE_MONTHS)
    ) + 1;
    const clamped = Math.max(0, Math.min(n, maxPage));
    setPageStart(pageStartForIndex(clamped));
    setIsTodayWindow(clamped === 1);
  }

  // Full-page navigation ([ and ]): step by PAGE_MONTHS
  function pageForward() {
    setPageStart((prev) => {
      const next = new Date(prev.getFullYear(), prev.getMonth() + PAGE_MONTHS, 1);
      return next >= CALENDAR_END ? prev : next;
    });
    setIsTodayWindow(false);
  }

  function pageBackward() {
    setPageStart((prev) => {
      if (prev.getTime() <= CALENDAR_START.getTime()) return prev;
      const candidate = new Date(prev.getFullYear(), prev.getMonth() - PAGE_MONTHS, 1);
      return candidate.getTime() <= CALENDAR_START.getTime() ? new Date(CALENDAR_START) : candidate;
    });
    setIsTodayWindow(false);
  }

  // Month-step navigation ({ and }): step by 1 month
  function pageForwardMonth() {
    setPageStart((prev) => {
      const next = new Date(prev.getFullYear(), prev.getMonth() + 1, 1);
      return next >= CALENDAR_END ? prev : next;
    });
    setIsTodayWindow(false);
  }

  function pageBackwardMonth() {
    setPageStart((prev) => {
      const candidate = new Date(prev.getFullYear(), prev.getMonth() - 1, 1);
      return candidate.getTime() < CALENDAR_START.getTime() ? new Date(CALENDAR_START) : candidate;
    });
    setIsTodayWindow(false);
  }

  // When navigating to the today window, scroll to current week
  useEffect(() => {
    if (!isTodayWindow) return;
    setTimeout(scrollToToday, 150);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTodayWindow]);

  // Initial load: scroll today into view once data arrives
  const didInitialScrollRef = useRef(false);
  useEffect(() => {
    if (isLoading || didInitialScrollRef.current) return;
    if (Object.keys(weeksData).length === 0) return;
    didInitialScrollRef.current = true;
    setTimeout(scrollToToday, 150);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading]);

  // --- Edit handlers invoked from ViewEditPopover ---

  const handleEditTrip = useCallback((tripId: number) => {
    for (const dayData of Object.values(weeksDataRef.current)) {
      const trip = dayData.trips.find((t) => t.trip_id === tripId);
      if (trip) {
        setModal({
          type: 'trip-form',
          initial: { laneId: trip.lane as LaneId, startDate: trip.trip_start, endDate: trip.trip_end },
          editId: tripId,
          existingTrip: trip,
        });
        return;
      }
    }
  }, []);

  const handleEditEntry = useCallback((entryId: number) => {
    for (const [dateStr, dayData] of Object.entries(weeksDataRef.current)) {
      const entry = dayData.entries.find((e) => e.id === entryId);
      if (entry) {
        const laneId = entry.lane as LaneId;
        setModal({
          type: 'entry-form',
          initial: { laneId, startDate: dateStr, endDate: dateStr },
          editId: entryId,
          existingEntry: entry,
          existingDate: dateStr,
        });
        return;
      }
    }
  }, []);

  // --- g-mode focus + commit ---

  useEffect(() => {
    if (gMode && gInputRef.current) gInputRef.current.focus();
  }, [gMode]);

  function handleGCommit() {
    const parts = gInput.trim().split(/\s+/);
    const month = parseInt(parts[0]);
    if (!isNaN(month) && month >= 1 && month <= 12) {
      const year   = parts[1] ? 2000 + parseInt(parts[1]) : new Date().getFullYear();
      const target = localIso(new Date(year, month - 1, 1));
      const el = (document.querySelector(`[data-date="${target}"]`) as HTMLElement) ??
                 (document.querySelector(`[data-date^="${target.slice(0, 7)}"]`) as HTMLElement);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setGMode(false);
  }

  // --- Global keyboard handler ---

  useEffect(() => {
    function isInputActive() {
      const el = document.activeElement;
      return el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT');
    }

    function handler(e: KeyboardEvent) {
      const { key } = e;

      // Escape — always handled regardless of focus
      if (key === 'Escape') {
        if (modalRef.current)      { setModal(null);       return; }
        if (filterModeRef.current) { setFilterMode(false); return; }
        if (gMode)                 { setGMode(false);      return; }
        if (dragStateRef.current)  { setDragState(null);   return; }
        setCursor(null);
        return;
      }

      if (modalRef.current || gMode) return;
      if (isInputActive()) return;

      // ── Single-key shortcuts (only when not in filter mode) ────────────────
      if (!filterModeRef.current) {
        // Page navigation: digits 0–9 map directly to page index
        if (key >= '0' && key <= '9') {
          e.preventDefault();
          goToPage(parseInt(key));
          return;
        }
        if (key === '[') { e.preventDefault(); pageBackward(); return; }
        if (key === ']') { e.preventDefault(); pageForward(); return; }
        if (key === '{') { e.preventDefault(); pageBackwardMonth(); return; }
        if (key === '}') { e.preventDefault(); pageForwardMonth(); return; }

        // Enter filter mode
        if (key === 'f') { e.preventDefault(); setFilterMode(true); return; }

        // Scroll
        if (key === 'j') { e.preventDefault(); gridScrollRef.current?.scrollBy({ top:  260, behavior: 'smooth' }); return; }
        if (key === 'k') { e.preventDefault(); gridScrollRef.current?.scrollBy({ top: -260, behavior: 'smooth' }); return; }
        if (key === 'J') { e.preventDefault(); gridScrollRef.current?.scrollBy({ top:  520, behavior: 'smooth' }); return; }
        if (key === 'K') { e.preventDefault(); gridScrollRef.current?.scrollBy({ top: -520, behavior: 'smooth' }); return; }
        if (key === 't') {
          e.preventDefault();
          const el = document.querySelector(`[data-date="${localIso(new Date())}"]`) as HTMLElement | null;
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }

        // Go-to-month input mode
        if (key === 'g') { e.preventDefault(); setGMode(true); setGInput(''); return; }

        // View toggle
        if (key === 'v') { e.preventDefault(); setMode((m) => m === 'vertical' ? 'horizontal' : 'vertical'); return; }

        // Cursor movement
        if (key === 'ArrowRight') {
          e.preventDefault();
          setCursor((prev) => {
            if (!prev) return null;
            const d = new Date(prev.date + 'T00:00:00');
            d.setDate(d.getDate() + 1);
            return { date: localIso(d), laneId: prev.laneId };
          });
          return;
        }
        if (key === 'ArrowLeft') {
          e.preventDefault();
          setCursor((prev) => {
            if (!prev) return null;
            const d = new Date(prev.date + 'T00:00:00');
            d.setDate(d.getDate() - 1);
            return { date: localIso(d), laneId: prev.laneId };
          });
          return;
        }
        if (key === 'ArrowDown') {
          e.preventDefault();
          setCursor((prev) => {
            if (!prev) return null;
            const idx = LANE_IDS.indexOf(prev.laneId);
            return { date: prev.date, laneId: LANE_IDS[(idx + 1) % LANE_IDS.length] };
          });
          return;
        }
        if (key === 'ArrowUp') {
          e.preventDefault();
          setCursor((prev) => {
            if (!prev) return null;
            const idx = LANE_IDS.indexOf(prev.laneId);
            return { date: prev.date, laneId: LANE_IDS[(idx - 1 + LANE_IDS.length) % LANE_IDS.length] };
          });
          return;
        }

        // Entry actions at cursor
        const cur = cursorRef.current;
        if (cur) {
          const { date, laneId } = cur;
          if (key === 'n') {
            e.preventDefault();
            if (TRAVEL_LANES.has(laneId)) {
              setModal({ type: 'trip-form', initial: { laneId, startDate: date, endDate: date } });
            } else if (EVENT_LANES.has(laneId)) {
              setModal({ type: 'entry-form', initial: { laneId, startDate: date, endDate: date } });
            }
            return;
          }
          if (key === 'e' || key === 'x') {
            e.preventDefault();
            const data    = weeksDataRef.current[date];
            const trips   = (data?.trips   ?? []).filter((t)  => t.lane  === laneId);
            const entries = (data?.entries ?? []).filter((en) => en.lane === laneId);
            if (trips.length > 0 || entries.length > 0) {
              setModal({ type: 'view-edit', date, laneId, laneLabel: getLaneShortLabel(laneId), trips, entries });
            }
            return;
          }
        }

        return;
      }

      // ── Filter mode: waiting for second key after 'f' ──────────────────────
      if (filterModeRef.current) {
        setFilterMode(false);
        e.preventDefault();
        if (key === '1') { toggleLane('gcal');         return; }
        if (key === '2') { toggleLane('york');         return; }
        if (key === '3') { toggleLane('fam_events');   return; }
        if (key === '4') { toggleLane('fam_travel');   return; }
        if (key === '5') { toggleLane('steve_events'); return; }
        if (key === '6') { toggleLane('steve_travel'); return; }
        if (key === 'p') { toggleMember('pgv');        return; }
        if (key === 'k') { toggleMember('kpv');        return; }
        if (key === 'o') { toggleMember('ovinters');   return; }
        // Unrecognized key — filter mode already cancelled, consume silently
        return;
      }
    }

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  // filterModeRef is a ref mirror — no need in deps
  }, [gMode, toggleLane, toggleMember]);

  // ---------------------------------------------------------------------------

  if (error) {
    return (
      <div style={{ padding: '24px', color: 'var(--color-text-secondary)' }}>
        Error loading Glance data.
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ position: 'relative', padding: '0 16px 40px' }}>
      {/* Page header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '12px', paddingTop: '16px' }}>
        <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Glance</h1>
        {isLoading && (
          <span style={{ fontSize: '12px', color: 'var(--color-text-light)' }}>loading…</span>
        )}
        {gMode && (
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--color-text-muted)' }}>
            go to month:
            <input
              ref={gInputRef}
              value={gInput}
              onChange={(e) => setGInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter')  { e.preventDefault(); handleGCommit(); }
                if (e.key === 'Escape') { setGMode(false); }
              }}
              onBlur={() => setGMode(false)}
              style={{
                width: '60px', fontSize: '12px', padding: '1px 4px',
                border: '1px solid var(--color-border)', borderRadius: '3px',
              }}
              placeholder="5 27"
            />
          </span>
        )}
      </div>

      {/* Control bar — two rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '10px', fontSize: '11px', color: 'var(--color-text-secondary)' }}>

        {/* Row 1: lanes + show */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px', alignItems: 'center' }}>
          <span style={{ opacity: 0.5, marginRight: '2px' }}>lanes:</span>
          {LANE_CONFIG.map(({ id, controlLabel, shortcutHint }) => (
            <div key={id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={visibleLanes.has(id)} onChange={() => toggleLane(id)} style={{ margin: 0 }} />
                {controlLabel}
              </label>
              <span style={{ fontSize: '10px', color: 'var(--color-text-tertiary, #bbb)', lineHeight: 1 }}>{shortcutHint}</span>
            </div>
          ))}

          <span style={{ opacity: 0.3 }}>|</span>

          <span style={{ opacity: 0.5, marginRight: '2px' }}>show:</span>
          {Object.entries(MEMBER_SWATCHES).map(([id, { label, color, shortcutHint }]) => (
            <div key={id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                <input type="checkbox" checked={visibleMembers.has(id)} onChange={() => toggleMember(id)} style={{ margin: 0 }} />
                <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '2px', background: color, flexShrink: 0 }} />
                {label}
              </label>
              <span style={{ fontSize: '10px', color: 'var(--color-text-tertiary, #bbb)', lineHeight: 1 }}>{shortcutHint}</span>
            </div>
          ))}
        </div>

        {/* Row 2: page nav + f… indicator + (toggle + month tint right-justified) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <button
                onClick={pageBackward}
                disabled={pageStart.getTime() <= CALENDAR_START.getTime()}
                style={{ background: 'none', border: 'none', padding: '0 3px', cursor: pageStart.getTime() <= CALENDAR_START.getTime() ? 'default' : 'pointer', opacity: pageStart.getTime() <= CALENDAR_START.getTime() ? 0.25 : 0.6, fontSize: '11px', lineHeight: 1 }}
              >←</button>
              <span style={{ fontSize: '11px', color: 'var(--color-text-secondary)', whiteSpace: 'nowrap' }}>
                {formatPageLabel(pageStart, clampedEnd)}
                {pageStart.getTime() <= CALENDAR_START.getTime() && <span style={{ opacity: 0.55, marginLeft: '4px' }}>· start</span>}
                {isTodayWindow && <span style={{ opacity: 0.55, marginLeft: '4px' }}>· today</span>}
              </span>
              <button
                onClick={pageForward}
                style={{ background: 'none', border: 'none', padding: '0 3px', cursor: 'pointer', opacity: 0.6, fontSize: '11px', lineHeight: 1 }}
              >→</button>
            </div>
            <span style={{ fontSize: '10px', color: 'var(--color-text-tertiary, #bbb)', textAlign: 'center', marginTop: '2px', lineHeight: 1 }}>
              {isTodayWindow ? '· today' : ''}
            </span>
          </div>

          {filterMode && (
            <span style={{
              fontSize: '11px', fontWeight: 600,
              background: 'rgba(55, 138, 221, 0.13)',
              color: '#1a6eb5',
              padding: '1px 7px', borderRadius: '3px',
              letterSpacing: '0.02em',
            }}>f…</span>
          )}

          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button
              onClick={() => setMode((m) => m === 'vertical' ? 'horizontal' : 'vertical')}
              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'var(--color-background-secondary, #f0efeb)'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent'; }}
              style={{
                fontSize: '11px', padding: '2px 8px',
                border: '0.5px solid var(--color-border-secondary, #d8d6ce)',
                borderRadius: '3px', cursor: 'pointer',
                background: 'transparent', fontFamily: 'inherit',
                color: 'var(--color-text-secondary)',
              }}
            >
              {mode === 'vertical' ? 'horizontal' : 'vertical'}
            </button>

            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ opacity: 0.5 }}>month tint</span>
              <input
                type="range"
                min={0}
                max={20}
                value={monthOpacity}
                onChange={(e) => setMonthOpacity(Number(e.target.value))}
                style={{ width: '80px', margin: 0 }}
              />
              <span style={{ opacity: 0.7, minWidth: '22px' }}>{monthOpacity}%</span>
            </div>
          </div>
        </div>

      </div>

      {/* Grid */}
      {mode === 'horizontal' ? (
        <HorizontalGlance
          weeksData={weeksData}
          visibleLanes={visibleLanes}
          visibleMembers={visibleMembers}
        />
      ) : (
        <GlanceGrid
          scrollRef={gridScrollRef}
          weeksData={weeksData}
          visibleLanes={visibleLanes}
          visibleMembers={visibleMembers}
          monthOpacity={monthOpacity}
          onNoteHover={handleNoteHover}
          onNoteLeave={handleNoteLeave}
          cursor={cursor}
          dragState={dragState}
          onCellMouseDown={handleCellMouseDown}
          onCellMouseEnter={handleCellMouseEnter}
          onCellMouseUp={handleCellMouseUp}
          onCellClick={handleCellClick}
          onEdgeDragStart={handleEdgeDragStart}
        />
      )}

      <GlanceTooltip tooltip={tooltip} />

      {/* Modals */}
      {modal?.type === 'trip-form' && (
        <TripForm
          initial={modal.initial}
          editId={modal.editId}
          existingData={modal.existingTrip ? {
            member_id:   modal.existingTrip.member_id,
            location_id: modal.existingTrip.location_id,
            start_date:  modal.existingTrip.trip_start,
            end_date:    modal.existingTrip.trip_end,
            notes:       modal.existingTrip.trip_notes ?? undefined,
            color_data:  modal.existingTrip.color_data ?? undefined,
            text_color:  modal.existingTrip.text_color ?? undefined,
          } : undefined}
          members={members}
          locations={locations}
          onSave={(data) => {
            if (modal.editId) {
              updateTrip.mutate({ id: modal.editId, ...data });
            } else {
              createTrip.mutate(data);
            }
            setModal(null);
          }}
          onCancel={() => setModal(null)}
        />
      )}

      {modal?.type === 'entry-form' && (
        <EntryForm
          initial={modal.initial}
          editId={modal.editId}
          existingData={modal.existingEntry ? {
            label:      modal.existingEntry.label,
            notes:      modal.existingEntry.notes,
            member_id:  modal.existingEntry.member_id,
            date:       modal.existingDate ?? modal.initial.startDate,
            color_data: modal.existingEntry.color_data ?? undefined,
            text_color: modal.existingEntry.text_color ?? undefined,
          } : undefined}
          members={members}
          onSave={(entries) => {
            if (modal.editId) {
              updateEntry.mutate({ id: modal.editId!, ...entries[0] });
            } else {
              createEntries.mutate(entries);
            }
            setModal(null);
          }}
          onCancel={() => setModal(null)}
        />
      )}

      {modal?.type === 'view-edit' && modal.anchorPos ? (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 498 }} onClick={() => setModal(null)} />
          <div style={{ position: 'fixed', top: modal.anchorPos.top, left: modal.anchorPos.left, zIndex: 499 }}>
            <ViewEditPopover
              date={modal.date}
              laneId={modal.laneId}
              laneLabel={modal.laneLabel}
              trips={modal.trips}
              entries={modal.entries}
              onEditTrip={handleEditTrip}
              onEditEntry={handleEditEntry}
              onDeleteTrip={(id) => { deleteTrip.mutate(id); setModal(null); }}
              onDeleteEntry={(id) => { deleteEntry.mutate(id); setModal(null); }}
              onClose={() => setModal(null)}
              noBackdrop
            />
          </div>
        </>
      ) : modal?.type === 'view-edit' ? (
        <ViewEditPopover
          date={modal.date}
          laneId={modal.laneId}
          laneLabel={modal.laneLabel}
          trips={modal.trips}
          entries={modal.entries}
          onEditTrip={handleEditTrip}
          onEditEntry={handleEditEntry}
          onDeleteTrip={(id) => { deleteTrip.mutate(id); setModal(null); }}
          onDeleteEntry={(id) => { deleteEntry.mutate(id); setModal(null); }}
          onClose={() => setModal(null)}
        />
      ) : null}
    </div>
  );
}
