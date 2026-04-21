/**
 * useGlanceData — all Glance data fetching lives here.
 * Never fetch Glance data inside page or component files.
 */

import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GlanceTripDay {
  id: number;
  lane: string;
  member_id: string;
  member_display: string | null;
  member_color_bg: string | null;
  member_color_text: string | null;
  location_id: string;
  location_display: string | null;
  location_color_bg: string | null;
  location_color_text: string | null;
  trip_id: number;
  trip_start: string;
  trip_end: string;
  trip_notes: string | null;
  depart: boolean;
  sleep: boolean;
  return: boolean;
  day_notes: string | null;
}

export interface GlanceEntry {
  id: number;
  lane: string;
  member_id: string | null;
  member_display: string | null;
  member_color_bg: string | null;
  member_color_text: string | null;
  label: string;
  notes: string | null;
}

export interface GlanceDayData {
  trips: GlanceTripDay[];
  entries: GlanceEntry[];
  gcal: unknown[];
}

export type GlanceWeeksData = Record<string, GlanceDayData>;

export interface GlanceMember {
  id: string;
  display: string;
  color_bg: string;
  color_text: string;
  color_accent: string;
  sort_order: number;
  gcal_calendar_id: string | null;
}

export interface GlanceLocation {
  id: string;
  display: string;
  color_bg: string;
  color_text: string;
  is_home: boolean;
  is_york: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Return the Monday that starts the ISO week containing d. */
function isoWeekStart(d: Date): Date {
  const day = d.getDay(); // 0=Sun, 1=Mon, ...
  const diff = day === 0 ? -6 : 1 - day;
  return addDays(d, diff);
}

function defaultRange(weeksCount = 12): { start: string; end: string } {
  const today = new Date();
  const monday = isoWeekStart(today);
  // Go back to start of first week in range
  const startMonday = addDays(monday, -Math.floor(weeksCount / 2) * 7);
  const end = addDays(startMonday, weeksCount * 7 - 1);
  return { start: toIso(startMonday), end: toIso(end) };
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

async function fetchWeeks(start: string, end: string): Promise<GlanceWeeksData> {
  const res = await fetch(`/api/glance/weeks?start=${start}&end=${end}`);
  if (!res.ok) throw new Error(`Glance weeks fetch failed: ${res.status}`);
  return res.json();
}

async function fetchMembers(): Promise<GlanceMember[]> {
  const res = await fetch('/api/glance/members');
  if (!res.ok) throw new Error(`Glance members fetch failed: ${res.status}`);
  return res.json();
}

async function fetchLocations(): Promise<GlanceLocation[]> {
  const res = await fetch('/api/glance/locations');
  if (!res.ok) throw new Error(`Glance locations fetch failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useGlanceData(initialWeeks = 12) {
  const [range, setRangeState] = useState(() => defaultRange(initialWeeks));

  const weeksQuery = useQuery<GlanceWeeksData>({
    queryKey: ['glance-weeks', range.start, range.end],
    queryFn: () => fetchWeeks(range.start, range.end),
    staleTime: 60_000,
  });

  function setRange(start: string, end: string) {
    setRangeState({ start, end });
  }

  return {
    weeksData: weeksQuery.data ?? {},
    isLoading: weeksQuery.isLoading,
    error: weeksQuery.error,
    range,
    setRange,
  };
}

export function useGlanceMembers() {
  return useQuery<GlanceMember[]>({
    queryKey: ['glance-members'],
    queryFn: fetchMembers,
    staleTime: 5 * 60_000,
  });
}

export function useGlanceLocations() {
  return useQuery<GlanceLocation[]>({
    queryKey: ['glance-locations'],
    queryFn: fetchLocations,
    staleTime: 5 * 60_000,
  });
}

/** Compute the list of ISO week-starting Mondays from the weeksData keys. */
export function useGlanceWeeks(weeksData: GlanceWeeksData): Date[][] {
  return useMemo(() => {
    const dates = Object.keys(weeksData).sort();
    if (dates.length === 0) return [];

    const weeks: Date[][] = [];
    let current: Date[] = [];

    for (const ds of dates) {
      const d = new Date(ds + 'T00:00:00');
      const dow = d.getDay(); // 0=Sun
      if (dow === 1 && current.length > 0) {
        // new Monday — flush
        while (current.length < 7) current.push(addDays(current[current.length - 1], 1));
        weeks.push(current);
        current = [];
      }
      current.push(d);
    }
    if (current.length > 0) {
      while (current.length < 7) current.push(addDays(current[current.length - 1], 1));
      weeks.push(current);
    }

    return weeks;
  }, [weeksData]);
}
