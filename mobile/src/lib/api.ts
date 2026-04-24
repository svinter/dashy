const BASE = '/api/mobile';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    ...options,
  });
  if (res.status === 401) {
    // Redirect to login — let the layout handle it
    throw new Error('UNAUTHENTICATED');
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface LibbyItem {
  id: number;
  name: string;
  type_code: string;
  type_label: string | null;
  author: string | null;
  cover_url: string | null;
  loan_due_date: string | null;
  days_left: number | null;
}

export interface LibbyResponse {
  items: LibbyItem[];
  total: number;
}

export function fetchLibby(): Promise<LibbyResponse> {
  return apiFetch<LibbyResponse>('/libby');
}

export interface GlanceEntry {
  id: number;
  lane: string;
  member_id: string | null;
  label: string;
  notes: string | null;
  color_data: string | null;
  text_color: string | null;
}

export interface GlanceTrip {
  id: number;
  member_id: string;
  location: string;
  start_date: string;
  end_date: string;
  notes: string | null;
  color_data: string | null;
  text_color: string | null;
}

export interface GlanceMember {
  id: string;
  name: string;
  display_name: string;
  color: string;
  text_color: string;
  sort_order: number;
}

export interface GlanceDay {
  entries: GlanceEntry[];
  trips: GlanceTrip[];
}

export interface GlanceResponse {
  week_start: string;
  week_end: string;
  members: GlanceMember[];
  days: Record<string, GlanceDay>;
  week_comments: Record<string, string>;
}

export function fetchGlance(): Promise<GlanceResponse> {
  return apiFetch<GlanceResponse>('/glance');
}

export async function login(password: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail || 'Login failed');
  }
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: 'POST', credentials: 'include' });
}

export async function checkAuth(): Promise<boolean> {
  const res = await fetch(`${BASE}/auth/me`, { credentials: 'include' });
  return res.ok;
}
