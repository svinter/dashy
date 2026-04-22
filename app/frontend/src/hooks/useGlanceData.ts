/**
 * useGlanceData — all Glance data fetching and mutations live here.
 * Never fetch/mutate Glance data inside page or component files.
 */

import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

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
  member_travel_color_bg: string | null;
  member_travel_color_text: string | null;
  location_id: string;
  location_display: string | null;
  location_color_bg: string | null;
  location_color_text: string | null;
  trip_id: number;
  trip_start: string;
  trip_end: string;
  trip_notes: string | null;
  color_data: string | null;
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
  color_data: string | null;
}

export interface GlanceDayData {
  trips: GlanceTripDay[];
  entries: GlanceEntry[];
  gcal: unknown[];
  week_comment?: Record<string, string>;  // present only on Mondays
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
  travel_color_bg: string | null;
  travel_color_text: string | null;
}

export interface GlanceLocation {
  id: string;
  display: string;
  color_bg: string;
  color_text: string;
  is_home: boolean;
  is_york: boolean;
}

export interface GlanceTripFull {
  id: number;
  member_id: string;
  location_id: string;
  start_date: string;
  end_date: string;
  notes: string | null;
  days: Array<{
    id: number;
    trip_id: number;
    date: string;
    depart: boolean;
    sleep: boolean;
    return: boolean;
    notes: string | null;
  }>;
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
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function isoWeekStart(d: Date): Date {
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  return addDays(d, diff);
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
// Read hooks
// ---------------------------------------------------------------------------

export function useGlanceData(start: string, end: string) {
  const weeksQuery = useQuery<GlanceWeeksData>({
    queryKey: ['glance-weeks', start, end],
    queryFn: () => fetchWeeks(start, end),
    staleTime: 60_000,
  });

  return {
    weeksData: weeksQuery.data ?? {},
    isLoading: weeksQuery.isLoading,
    error: weeksQuery.error,
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

export function useGlanceWeeks(weeksData: GlanceWeeksData): Date[][] {
  return useMemo(() => {
    const dates = Object.keys(weeksData).sort();
    if (dates.length === 0) return [];
    const weeks: Date[][] = [];
    let current: Date[] = [];
    for (const ds of dates) {
      const d = new Date(ds + 'T00:00:00');
      const dow = d.getDay();
      if (dow === 1 && current.length > 0) {
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

// ---------------------------------------------------------------------------
// Mutation hooks
// ---------------------------------------------------------------------------

export function useCreateGlanceTrip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      member_id: string;
      location_id?: string; location_name?: string;
      start_date: string; end_date: string;
      notes?: string; color_data?: string | null; day_overrides?: object[];
    }) => {
      const res = await fetch('/api/glance/trips', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Failed to create trip');
      return res.json() as Promise<GlanceTripFull>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['glance-weeks'] }),
  });
}

export function useUpdateGlanceTrip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: {
      id: number; member_id?: string; location_id?: string; location_name?: string;
      start_date?: string; end_date?: string; color_data?: string | null;
      notes?: string; day_overrides?: object[];
    }) => {
      const res = await fetch(`/api/glance/trips/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Failed to update trip');
      return res.json() as Promise<GlanceTripFull>;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['glance-weeks'] }),
  });
}

export function useDeleteGlanceTrip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/glance/trips/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete trip');
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['glance-weeks'] }),
  });
}

export function useCreateGlanceEntries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (entries: Array<{
      lane: string; member_id?: string | null;
      date: string; label: string; notes?: string | null; color_data?: string | null;
    }>) => {
      const res = await fetch('/api/glance/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entries }),
      });
      if (!res.ok) throw new Error('Failed to create entries');
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['glance-weeks'] }),
  });
}

export function useUpdateGlanceEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: {
      id: number; lane?: string; member_id?: string | null;
      date?: string; label?: string; notes?: string | null; color_data?: string | null;
    }) => {
      const res = await fetch(`/api/glance/entries/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Failed to update entry');
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['glance-weeks'] }),
  });
}

export function useDeleteGlanceEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/glance/entries/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete entry');
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['glance-weeks'] }),
  });
}
