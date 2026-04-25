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

export interface LibbySearchResult {
  id: number;
  name: string;
  type_code: string;
  type_label: string | null;
  author: string | null;
  cover_url: string | null;
  synopsis: string | null;
  url: string | null;
  amazon_url: string | null;
  amazon_short_url: string | null;
  comments: string | null;
}

export interface LibbySearchResponse {
  items: LibbySearchResult[];
  total: number;
}

export function fetchLibbySearch(q: string = ''): Promise<LibbySearchResponse> {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  return apiFetch<LibbySearchResponse>(`/libby/search?${params}`);
}

export interface LibbyLookupResult {
  matched: boolean;
  is_url: boolean;
  name: string;
  author: string | null;
  cover_url: string | null;
  isbn: string | null;
  info_link: string | null;
}

export async function checkLibbyExists(
  name: string,
): Promise<{ exists: false } | { exists: true; existing_id: number; existing_name: string }> {
  const params = new URLSearchParams({ name });
  return apiFetch(`/libby/exists?${params}`);
}

export async function lookupLibbyBook(name: string): Promise<LibbyLookupResult> {
  return apiFetch('/libby/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export interface LibbyAddResult {
  id: number;
  name: string;
  type_code: string;
  type_label: string;
  author: string | null;
  cover_url: string | null;
  duplicate?: false;
}

export interface LibbyAddDuplicate {
  duplicate: true;
  existing_id: number;
  existing_name: string;
}

export async function patchLibbyNotes(
  id: number,
  comments: string | null,
): Promise<{ ok: boolean; comments: string | null }> {
  return apiFetch(`/libby/${id}/notes`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ comments }),
  });
}

export async function addLibbyItem(data: {
  name: string;
  author?: string | null;
  cover_url?: string | null;
  isbn?: string | null;
  notes?: string | null;
  type_code?: string | null;
  url?: string | null;
  amazon_url?: string | null;
  force?: boolean;
}): Promise<LibbyAddResult | LibbyAddDuplicate> {
  return apiFetch('/libby/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
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
  display: string;
  color_bg: string;
  color_text: string;
  color_accent: string;
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
