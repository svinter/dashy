import {
  useState,
  useRef,
  useEffect,
  useCallback,
  createContext,
  useContext,
  useMemo,
} from 'react';
import { NavLink, Routes, Route, Navigate, useLocation, useNavigate, Link } from 'react-router-dom';
import {
  CoachingClientSynopsisPage,
  type SynopsisResponse,
  SynopsisPanelContent,
} from './CoachingClientSynopsisPage';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import cloud from 'd3-cloud';
import { api, openExternal } from '../api/client';
import { ClientFilterBar, HelpPopover as SharedHelpPopover } from '../components/shared/ClientFilterBar';
import type { HelpShortcut as SharedHelpShortcut } from '../components/shared/ClientFilterBar';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CoachingClient {
  id: number;
  name: string;
  client_type: 'company' | 'individual';
  status: 'active' | 'infrequent';
  prepaid: boolean;
  obsidian_name: string | null;
  gdrive_coaching_docs_url: string | null;
  last_session_date: string | null;
  display_session_number: number | null;
  days_ago: number | null;
  next_session_date: string | null;
}

interface CoachingProject {
  id: number;
  name: string;
  company_id: number | null;
  billing_type: 'hourly' | 'fixed';
  obsidian_name: string | null;
  gdrive_coaching_docs_url: string | null;
  last_session_date: string | null;
  session_count: number;
  days_ago: number | null;
  next_session_date: string | null;
}

interface CoachingGroup {
  company_id: number | null;
  company_name: string;
  default_rate: number | null;
  active_client_count: number;
  clients: CoachingClient[];
  projects: CoachingProject[];
}

interface CoachingClientsResponse {
  groups: CoachingGroup[];
}

// By-date view types
type DateMode = 'past' | 'today' | 'next' | 'week';

interface ByDateSession {
  id: number;
  date: string;
  time: string | null;
  client_id: number;
  client_name: string;
  company_name: string;
  obsidian_name: string | null;
  gdrive_coaching_docs_url: string | null;
  is_confirmed: boolean;
  color_id: string | null;
  display_session_number: number | null;
  relative: string | null;
  has_note: boolean;
  obsidian_note_path: string | null;
}

interface ByDateGroup {
  date: string;
  header: string;
  session_count: number;
  sessions: ByDateSession[];
}

interface ByDateResponse {
  mode: string;
  day_groups: ByDateGroup[];
  future_submode?: 'today' | 'tomorrow';
}

interface WordSession {
  date: string;
  client_name: string;
  obsidian_name: string;
  path: string;
}

// Active client detection
type CoachingActiveResult =
  | { active: false }
  | { active: true; type: 'client' | 'project'; client_id: number | null; project_id: number | null; client_name: string; obsidian_name: string | null; company_name: string | null };

interface WordData {
  text: string;
  value: number;
  sessions: WordSession[];
}

interface WordCloudResponse {
  words: WordData[];
  sessions_analyzed: number;
  clients: string[];
}

// ---------------------------------------------------------------------------
// Data hooks
// ---------------------------------------------------------------------------

function useCoachingClients() {
  return useQuery({
    queryKey: ['coaching-clients'],
    queryFn: () => api.get<CoachingClientsResponse>('/coaching/clients'),
    staleTime: 60_000,
  });
}

function useCoachingActive() {
  return useQuery({
    queryKey: ['coaching-active'],
    queryFn: () => api.get<CoachingActiveResult>('/coaching/active'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

function useVinnyStatus() {
  return useQuery({
    queryKey: ['coaching-vinny-status'],
    queryFn: () => api.get<{ running: boolean }>('/coaching/vinny-status'),
    staleTime: 10_000,
    retry: false,
  });
}

function useWordCloud(clientIds: number[], projectIds: number[], sessionCount: number, recencyWeight: number) {
  return useQuery({
    queryKey: ['coaching-wordcloud', clientIds.slice().sort(), projectIds.slice().sort(), sessionCount, recencyWeight],
    queryFn: () =>
      api.post<WordCloudResponse>('/coaching/wordcloud', {
        client_ids: clientIds,
        project_ids: projectIds,
        session_count: sessionCount,
        recency_weight: recencyWeight,
      }),
    enabled: clientIds.length > 0 || projectIds.length > 0,
    staleTime: 120_000,
  });
}

function useByDate(mode: DateMode | null, days?: number) {
  return useQuery({
    queryKey: ['coaching-by-date', mode, days],
    queryFn: () => {
      // When days is set (;1-;9, ;A-;Z), send mode=days to hit the rolling-window backend branch.
      // Today mode uses the backend's smart today/tomorrow logic (backend mode=future).
      const backendMode = (days != null) ? 'days' : (mode === 'today') ? 'future' : mode!;
      const params = new URLSearchParams({ mode: backendMode });
      if (days != null) params.set('days', String(days));
      return api.get<ByDateResponse>(`/coaching/clients/by-date?${params}`);
    },
    enabled: mode !== null,
    staleTime: 30_000,
  });
}

// ---------------------------------------------------------------------------
// HelpShortcut + HelpPopover — re-exported from shared for backward compat
// ---------------------------------------------------------------------------

export type HelpShortcut = SharedHelpShortcut;
export { SharedHelpPopover as HelpPopover };

const COACHING_SHORTCUTS: HelpShortcut[] = [
  { keys: '/', description: 'Focus client search box' },
  { keys: '⌘A', description: 'Show all clients (clear filter)' },
  { keys: '⌘.', description: 'Finish editing (collapse autocomplete)' },
  { keys: 'Escape', description: 'Clear search text' },
  { keys: '← →', description: 'Cycle through multiple matches' },
  { keys: 'Return', description: 'Add current match to selection' },
  { keys: '. prefix', description: 'Match company name only  (e.g. .cfs)' },
  { keys: ', prefix', description: 'Match person first or last name  (e.g. ,berg)' },
  { keys: "' prefix", description: "Match project name  (e.g. 'offsite)" },
  { keys: '- prefix', description: 'Remove from selection  (e.g. -cfs)' },
  { keys: '.c', description: 'Select active client/project (if session in progress)' },
  { keys: '⌘/ or ⌘?', description: 'Show this help' },
  { keys: ';', description: 'Enter date mode → Today (today or tomorrow). Press ; again to exit.' },
  { keys: ';p / ;t / ;n', description: 'Date mode: Past / Today / Next' },
  { keys: ';w', description: 'Date mode: Week' },
  { keys: ';1 – ;9', description: 'Date mode: Today N days ahead (1–9)' },
  { keys: ';A – ;Z', description: 'Date mode: Today N days ahead (A=10, B=11 … Z=35)' },
];

// ---------------------------------------------------------------------------
// Filter selection model
//
//   selection = []  + allChip = false  → initial (no chips, show all)
//   selection = []  + allChip = true   → <All> chip, show all
//   selection = […] + allChip = false  → filtered, show item chips
// ---------------------------------------------------------------------------

interface FilterSelection {
  type: 'company' | 'client' | 'project';
  id: number | null;   // INDIVIDUAL_ID (-1) for the Individual symbolic company
  label: string;
  company_name?: string;
}

const INDIVIDUAL_ID = -1;

// ---------------------------------------------------------------------------
// Filter context — shared across all Coaching sub-pages
// ---------------------------------------------------------------------------

interface CoachingFilterCtx {
  groups: CoachingGroup[];
  selection: FilterSelection[];
  allChip: boolean;
  onSelectionChange: (sel: FilterSelection[], allChip: boolean) => void;
  /** null = all clients; Set = specific client IDs */
  effectiveIds: Set<number> | null;
  /** null = all projects; Set = specific project IDs */
  effectiveProjectIds: Set<number> | null;
  /** All active client IDs (flat list) */
  allClientIds: number[];
  /** All active project IDs (flat list) */
  allProjectIds: number[];
  demo: boolean;
  toggleDemo: () => void;
  activeResult: CoachingActiveResult | null;
  // Date mode
  dateModeActive: boolean;
  dateMode: DateMode;
  dateDays: number | undefined;
  /** 'today' | 'tomorrow' — the submode of Future, updated when future data loads */
  futureLabel: string;
  setDateModeActive: (v: boolean | ((p: boolean) => boolean)) => void;
  setDateMode: (m: DateMode) => void;
  setDateDays: (n: number | undefined) => void;
  setFutureLabel: (s: string) => void;
  // Sort mode
  sortMode: 'default' | 'last';
  setSortMode: (m: 'default' | 'last') => void;
}

const CoachingFilterContext = createContext<CoachingFilterCtx>({
  groups: [],
  selection: [],
  allChip: false,
  onSelectionChange: () => {},
  effectiveIds: null,
  effectiveProjectIds: null,
  allClientIds: [],
  allProjectIds: [],
  demo: false,
  toggleDemo: () => {},
  activeResult: null,
  dateModeActive: false,
  dateMode: 'today',
  dateDays: undefined,
  futureLabel: '',
  setDateModeActive: () => {},
  setDateMode: () => {},
  setDateDays: () => {},
  setFutureLabel: () => {},
  sortMode: 'default',
  setSortMode: () => {},
});

function useCoachingFilter() {
  return useContext(CoachingFilterContext);
}

// ---------------------------------------------------------------------------
// Search index + matching
// ---------------------------------------------------------------------------

function buildSearchIndex(groups: CoachingGroup[]) {
  const companies: { label: string; id: number | null }[] = [];
  const clients: { label: string; client: CoachingClient; company_name: string }[] = [];
  const projectItems: { label: string; project: CoachingProject; company_name: string }[] = [];

  for (const g of groups) {
    if (g.company_id !== null) {
      companies.push({ label: g.company_name, id: g.company_id });
    } else {
      companies.push({ label: 'Individual', id: INDIVIDUAL_ID });
    }
    for (const c of g.clients) {
      clients.push({ label: c.name, client: c, company_name: g.company_name });
    }
    for (const p of (g.projects ?? [])) {
      projectItems.push({ label: p.name, project: p, company_name: g.company_name });
    }
  }
  companies.sort((a, b) => a.label.localeCompare(b.label));
  clients.sort((a, b) => a.label.localeCompare(b.label));
  projectItems.sort((a, b) => a.label.localeCompare(b.label));
  return { companies, clients, projectItems };
}

function matchItems(
  text: string,
  companies: { label: string; id: number | null }[],
  clients: { label: string; client: CoachingClient; company_name: string }[],
  projectItems: { label: string; project: CoachingProject; company_name: string }[]
): FilterSelection[] {
  if (!text) return [];

  if (text.startsWith("'")) {
    const q = text.slice(1).toLowerCase();
    return projectItems
      .filter(p => p.label.toLowerCase().includes(q))
      .map(p => ({ type: 'project' as const, id: p.project.id, label: `◆ ${p.label}`, company_name: p.company_name }));
  }

  if (text.startsWith('.')) {
    const q = text.slice(1).toLowerCase();
    return companies
      .filter(c => c.label.toLowerCase().startsWith(q))
      .map(c => ({ type: 'company' as const, id: c.id, label: c.label }));
  }

  if (text.startsWith(',')) {
    const q = text.slice(1).toLowerCase();
    return clients
      .filter(c => c.label.toLowerCase().split(' ').some(p => p.startsWith(q)))
      .map(c => ({ type: 'client' as const, id: c.client.id, label: c.label, company_name: c.company_name }));
  }

  // Default: company OR any word in person name starts with text
  const q = text.toLowerCase();
  const matchedCompanies: FilterSelection[] = companies
    .filter(c => c.label.toLowerCase().startsWith(q))
    .map(c => ({ type: 'company' as const, id: c.id, label: c.label }));
  const matchedClients: FilterSelection[] = clients
    .filter(c => c.label.toLowerCase().split(' ').some(p => p.startsWith(q)))
    .map(c => ({ type: 'client' as const, id: c.client.id, label: c.label, company_name: c.company_name }));
  return [...matchedCompanies, ...matchedClients];
}

function getEffectiveIds(selection: FilterSelection[], groups: CoachingGroup[]): Set<number> | null {
  if (selection.length === 0) return null;
  const ids = new Set<number>();
  for (const sel of selection) {
    if (sel.type === 'company') {
      if (sel.id === INDIVIDUAL_ID) {
        const indGroup = groups.find(g => g.company_id === null);
        if (indGroup) for (const c of indGroup.clients) ids.add(c.id);
      } else {
        const group = groups.find(g => g.company_id === sel.id);
        if (group) for (const c of group.clients) ids.add(c.id);
      }
    } else if (sel.type === 'client' && sel.id !== null) {
      ids.add(sel.id);
    }
    // project selections don't add client IDs
  }
  return ids;
}

function getEffectiveProjectIds(selection: FilterSelection[], groups: CoachingGroup[]): Set<number> | null {
  if (selection.length === 0) return null;
  const ids = new Set<number>();
  for (const sel of selection) {
    if (sel.type === 'company') {
      const group = sel.id === INDIVIDUAL_ID
        ? groups.find(g => g.company_id === null)
        : groups.find(g => g.company_id === sel.id);
      if (group) for (const p of (group.projects ?? [])) ids.add(p.id);
    } else if (sel.type === 'project' && sel.id !== null) {
      ids.add(sel.id);
    }
    // client selections don't add project IDs
  }
  return ids;
}

// ---------------------------------------------------------------------------
// Client Filter component — thin wrapper around shared ClientFilterBar
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Active client status bar
// ---------------------------------------------------------------------------

function activeObsidianUrl(result: Extract<CoachingActiveResult, { active: true }>): string {
  const name = result.obsidian_name ?? result.client_name;
  const vaultFile = result.type === 'project' && result.company_name
    ? `1 Company/${result.company_name}/${name}.md`
    : `1 People/${name}.md`;
  return `obsidian://open?vault=MyNotes&file=${encodeURIComponent(vaultFile)}`;
}

function ActiveClientBar({ result }: { result: CoachingActiveResult }) {
  if (!result.active) return null;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '3px 0 4px',
      fontSize: 'var(--text-xs)',
      color: 'var(--color-text-light)',
      borderBottom: '1px solid var(--color-border)',
      marginBottom: 4,
    }}>
      <span style={{ color: '#7B52AB', fontSize: '0.65em' }}>●</span>
      <span>Active:</span>
      <span style={{ color: '#444', fontWeight: 500 }}>{result.client_name}</span>
      <button
        className="coaching-link-btn"
        style={{ color: '#7B52AB' }}
        onClick={() => openExternal(activeObsidianUrl(result))}
        title="Open in Obsidian"
      >→</button>
    </div>
  );
}

interface ClientFilterProps {
  groups: CoachingGroup[];
  selection: FilterSelection[];
  allChip: boolean;
  onSelectionChange: (sel: FilterSelection[], allChip: boolean) => void;
  hideChips?: boolean;
  autoFocus?: boolean;
  activeResult?: CoachingActiveResult | null;
  onPhaseChange?: (phase: 'visible' | 'fading' | 'hidden') => void;
}

function ClientFilter({ groups, selection, allChip, onSelectionChange, hideChips, autoFocus, activeResult, onPhaseChange }: ClientFilterProps) {
  const { companies, clients, projectItems } = useMemo(() => buildSearchIndex(groups), [groups]);

  const activeFilterSel: FilterSelection | null = useMemo(() => {
    if (!activeResult?.active) return null;
    if (activeResult.type === 'client' && activeResult.client_id != null) {
      return { type: 'client', id: activeResult.client_id, label: activeResult.client_name };
    }
    if (activeResult.type === 'project' && activeResult.project_id != null) {
      return { type: 'project', id: activeResult.project_id, label: `◆ ${activeResult.client_name}`, company_name: activeResult.company_name ?? undefined };
    }
    return null;
  }, [activeResult]);

  const matchFn = useCallback(
    (text: string) => {
      if (text === '.c') return activeFilterSel ? [activeFilterSel] : [];
      return matchItems(text, companies, clients, projectItems);
    },
    [companies, clients, projectItems, activeFilterSel]
  );

  return (
    <ClientFilterBar
      selection={selection}
      allChip={allChip}
      onSelectionChange={onSelectionChange}
      matchFn={matchFn}
      placeholder="filter clients… (/)"
      helpTitle="Coaching keyboard shortcuts"
      shortcuts={COACHING_SHORTCUTS}
      hideChips={hideChips}
      autoFocus={autoFocus}
      onPhaseChange={onPhaseChange}
    />
  );
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const months = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'];
  return `${days[d.getDay()]} ${months[d.getMonth()]}/${d.getDate()}`;
}

function obsidianSessionUrl(obsidianName: string, dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `obsidian://open?vault=MyNotes&file=${encodeURIComponent(`8 Meetings/${yyyy}-${mm}-${dd} - ${obsidianName}.md`)}`;
}

function obsidianClientUrl(obsidianName: string): string {
  return `obsidian://open?vault=MyNotes&file=${encodeURIComponent(`1 People/${obsidianName}.md`)}`;
}

// ---------------------------------------------------------------------------
// Date mode bar + date view
// ---------------------------------------------------------------------------

const DATE_BUTTONS: { mode: DateMode; label: string; key: string }[] = [
  { mode: 'past',  label: 'Past',  key: ';p' },
  { mode: 'today', label: 'Today', key: ';t' },
  { mode: 'next',  label: 'Next',  key: ';n' },
  { mode: 'week',  label: 'Week',  key: ';w' },
];

function DateModeBar({
  active,
  dateMode,
  dateDays,
  todayLabelSuffix,
  onToggle,
  onModeSelect,
  onClientsClick,
}: {
  active: boolean;
  dateMode: DateMode;
  dateDays?: number;
  todayLabelSuffix?: string;
  onToggle: () => void;
  onModeSelect: (m: DateMode) => void;
  onClientsClick: () => void;
}) {
  return (
    <div className="coaching-date-bar">
      {/* Clients button — active when date mode is off */}
      <button
        className={`coaching-date-btn${!active ? ' coaching-date-btn--active' : ' coaching-date-btn--dim'}`}
        onClick={onClientsClick}
        title="clients view"
      >
        Clients
      </button>

      {/* Spacer before date buttons */}
      <span className="coaching-date-bar-sep" />

      {DATE_BUTTONS.map(btn => {
        const isActive = active && dateMode === btn.mode;
        // Dynamic label for Today button (shows today/tomorrow submode or N-days)
        let label = btn.label;
        if (btn.mode === 'today' && active) {
          if (dateDays != null) {
            label = `Today: ${dateDays}d`;
          } else if (todayLabelSuffix) {
            label = `Today: ${todayLabelSuffix}`;
          }
        }
        return (
          <button
            key={btn.mode}
            className={`coaching-date-btn${isActive ? ' coaching-date-btn--active' : ''}${!active ? ' coaching-date-btn--dim' : ''}`}
            onClick={() => {
              if (!active) onToggle();
              onModeSelect(btn.mode);
            }}
            title={`${btn.key}`}
          >
            {label}
            <span className="coaching-date-btn-key">{btn.key}</span>
          </button>
        );
      })}
    </div>
  );
}

function ByDateSessionRow({ session }: { session: ByDateSession }) {
  const meetingUrl = session.has_note
    ? (session.obsidian_note_path
        ? `obsidian://open?vault=MyNotes&file=${encodeURIComponent(session.obsidian_note_path)}`
        : session.obsidian_name && session.date
          ? obsidianSessionUrl(session.obsidian_name, session.date)
          : null)
    : null;

  const clientUrl = session.obsidian_name
    ? obsidianClientUrl(session.obsidian_name)
    : null;

  return (
    <div className="coaching-date-session-row">
      <span className="coaching-date-session-time">{session.time ?? '—'}</span>
      <span className="coaching-date-session-client">{session.client_name}</span>
      <span className="coaching-date-session-company">{session.company_name}</span>
      <span className="coaching-date-session-num">
        {session.display_session_number != null ? `#${session.display_session_number}` : ''}
      </span>
      <span className="coaching-date-session-rel">{session.relative ?? ''}</span>
      <span className="coaching-date-session-links">
        {meetingUrl && (
          <button className="coaching-link-btn" onClick={() => openExternal(meetingUrl)} title="Open session note">meeting</button>
        )}
        {clientUrl && (
          <button className="coaching-link-btn" onClick={() => openExternal(clientUrl)} title="Open client page">client</button>
        )}
        {session.gdrive_coaching_docs_url && (
          <button className="coaching-link-btn" onClick={() => openExternal(session.gdrive_coaching_docs_url!)} title="Open coaching docs">ƒolder</button>
        )}
      </span>
    </div>
  );
}

function DateView({ mode, days, onFutureSubmode }: { mode: DateMode; days?: number; onFutureSubmode?: (s: string) => void }) {
  const { data, isLoading, error } = useByDate(mode, days);

  useEffect(() => {
    if (data?.future_submode && onFutureSubmode) onFutureSubmode(data.future_submode);
  }, [data?.future_submode]); // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <div className="coaching-loading">Loading…</div>;
  if (error) return <div className="coaching-error">Failed to load sessions.</div>;
  if (!data || data.day_groups.length === 0) {
    return <div className="coaching-empty">No sessions for this view.</div>;
  }

  return (
    <div className="coaching-date-view">
      {data.day_groups.map(group => (
        <div key={group.date} className="coaching-date-group">
          <div className="coaching-date-group-header">
            {group.header} · {group.session_count} session{group.session_count !== 1 ? 's' : ''}
          </div>
          {group.sessions.map(s => (
            <ByDateSessionRow key={s.id} session={s} />
          ))}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Clients Page
// ---------------------------------------------------------------------------

const NOW_BADGE = (
  <span style={{ fontSize: '0.7em', color: '#7B52AB', marginLeft: 6, verticalAlign: 'middle', letterSpacing: '0.02em' }}>
    ● now
  </span>
);

const INFREQUENT_BADGE = (
  <span className="coaching-infrequent-badge">infrequent</span>
);

// ---------------------------------------------------------------------------
// Inline Synopsis Panel (shown when exactly one client is visible)
// ---------------------------------------------------------------------------

type SynopsisPhase = 'idle' | 'checking' | 'generating' | 'ready';

function InlineSynopsisPanel({
  phase,
  data,
  onGenerate,
}: {
  phase: SynopsisPhase;
  data: SynopsisResponse | null;
  onGenerate: () => void;
}) {
  if (phase === 'checking') {
    return (
      <div className="coaching-synopsis-inline">
        <span className="coaching-synopsis-inline-spinner">Checking cache…</span>
      </div>
    );
  }
  if (phase === 'generating') {
    return (
      <div className="coaching-synopsis-inline">
        <span className="coaching-synopsis-inline-spinner">Generating summaries…</span>
      </div>
    );
  }
  if (phase === 'idle') {
    return (
      <div className="coaching-synopsis-inline">
        <button className="coaching-synopsis-generate-btn" onClick={onGenerate}>
          Generate summary
        </button>
      </div>
    );
  }
  if (phase === 'ready' && data) {
    return (
      <div className="coaching-synopsis-inline">
        <SynopsisPanelContent
          client={data.client}
          past_sessions={data.past_sessions}
          future_sessions={data.future_sessions}
        />
      </div>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// ClientRow
// ---------------------------------------------------------------------------

function ClientRow({ client, showDaysFirst, isOnlyVisible }: {
  client: CoachingClient;
  showDaysFirst?: boolean;
  isOnlyVisible?: boolean;
}) {
  const { activeResult } = useCoachingFilter();
  const isNow = activeResult?.active && activeResult.type === 'client' && activeResult.client_id === client.id;

  const [inlineOpen, setInlineOpen] = useState(false);
  const [synopsisPhase, setSynopsisPhase] = useState<SynopsisPhase>('idle');
  const [synopsisData, setSynopsisData] = useState<SynopsisResponse | null>(null);

  // Proactively check cache when this becomes the only visible client
  useEffect(() => {
    if (!isOnlyVisible) return;
    if (synopsisData) {
      // Already loaded — re-show panel without hitting the backend
      setSynopsisPhase('ready');
      setInlineOpen(true);
      return;
    }
    let cancelled = false;
    setSynopsisPhase('checking');
    api.get<{ ready: boolean } & Partial<SynopsisResponse>>(
      `/coaching/clients/${client.id}/synopsis?generate=false`
    ).then(result => {
      if (cancelled) return;
      if (result.ready && result.client) {
        setSynopsisData(result as SynopsisResponse);
        setSynopsisPhase('ready');
        setInlineOpen(true);
      } else {
        setSynopsisPhase('idle');
      }
    }).catch(() => {
      if (!cancelled) setSynopsisPhase('idle');
    });
    return () => { cancelled = true; };
  }, [isOnlyVisible, client.id]);

  const handleGenerate = useCallback(async () => {
    setSynopsisPhase('generating');
    setInlineOpen(true);
    try {
      const result = await api.get<SynopsisResponse>(`/coaching/clients/${client.id}/synopsis`);
      setSynopsisData(result);
      setSynopsisPhase('ready');
    } catch {
      setSynopsisPhase('idle');
    }
  }, [client.id]);

  return (
    <>
    <div className={`coaching-client-row${showDaysFirst ? ' coaching-client-row--last-sort' : ''}`}>
      {showDaysFirst && (
        <span className="coaching-client-days-prominent">
          {client.days_ago != null ? `${client.days_ago}d` : '—'}
        </span>
      )}
      <span className="coaching-client-name">
        {client.name}
        {isNow && NOW_BADGE}
        {client.status === 'infrequent' && INFREQUENT_BADGE}
      </span>
      <span className="coaching-client-sessions">
        {(client.display_session_number ?? 0)} sessions
      </span>
      <span className="coaching-client-last">
        {client.days_ago != null && client.last_session_date ? (
          <>
            {client.days_ago === 0 ? 'today' : `${client.days_ago}d ago`}
            {' on '}
            {formatDate(client.last_session_date)}
            {client.obsidian_name && (
              <button
                className="coaching-link-btn"
                onClick={() => openExternal(obsidianSessionUrl(client.obsidian_name!, client.last_session_date!))}
                title="Open session note in Obsidian"
              >→</button>
            )}
          </>
        ) : (
          <span className="coaching-client-meta-dim">no sessions</span>
        )}
      </span>
      <span className="coaching-client-next">
        {client.next_session_date
          ? `next: ${formatDate(client.next_session_date)}`
          : <span className="coaching-client-meta-dim">next: none</span>}
      </span>
      {client.prepaid && <span className="coaching-prepaid-badge">Prepaid</span>}
      <span className="coaching-client-links">
        {client.obsidian_name && (
          <button className="coaching-link-btn" onClick={() => openExternal(obsidianClientUrl(client.obsidian_name!))} title="Open client page in Obsidian">notes</button>
        )}
        {client.gdrive_coaching_docs_url && (
          <button className="coaching-link-btn" onClick={() => openExternal(client.gdrive_coaching_docs_url!)} title="Open coaching docs in Drive">ƒolder</button>
        )}
        {isOnlyVisible ? (
          <>
            {synopsisPhase === 'idle' && (
              <button className="coaching-synopsis-generate-btn" onClick={handleGenerate}>
                Generate summary
              </button>
            )}
            {synopsisPhase === 'checking' && (
              <span className="coaching-synopsis-inline-spinner">checking…</span>
            )}
            {synopsisPhase === 'ready' && (
              <button
                className={`coaching-link-btn${inlineOpen ? ' coaching-link-btn--active' : ''}`}
                onClick={() => setInlineOpen(o => !o)}
                title="Pre-meeting summary"
              >📋</button>
            )}
          </>
        ) : (
          <Link className="coaching-link-btn" to={`/coaching/clients/${client.id}/synopsis`} title="Pre-meeting summary">📋</Link>
        )}
      </span>
    </div>
    {inlineOpen && isOnlyVisible && (
      <InlineSynopsisPanel
        phase={synopsisPhase}
        data={synopsisData}
        onGenerate={handleGenerate}
      />
    )}
    </>
  );
}

function ProjectRow({ project }: { project: CoachingProject }) {
  const { activeResult } = useCoachingFilter();
  const isNow = activeResult?.active && activeResult.type === 'project' && activeResult.project_id === project.id;
  return (
    <div className="coaching-client-row" style={{ borderLeft: '2px solid #7B52AB', paddingLeft: 8 }}>
      <span className="coaching-client-name" style={{ color: '#7B52AB' }}>◆ {project.name}{isNow && NOW_BADGE}</span>
      <span className="coaching-client-sessions">
        {project.session_count} session{project.session_count !== 1 ? 's' : ''}
      </span>
      <span className="coaching-client-last">
        {project.days_ago != null && project.last_session_date ? (
          <>
            {project.days_ago === 0 ? 'today' : `${project.days_ago}d ago`}
            {' on '}
            {formatDate(project.last_session_date)}
            {project.obsidian_name && (
              <button
                className="coaching-link-btn"
                onClick={() => openExternal(obsidianSessionUrl(project.obsidian_name!, project.last_session_date!))}
                title="Open session note in Obsidian"
              >→</button>
            )}
          </>
        ) : (
          <span className="coaching-client-meta-dim">no sessions</span>
        )}
      </span>
      <span className="coaching-client-next">
        {project.next_session_date
          ? `next: ${formatDate(project.next_session_date)}`
          : <span className="coaching-client-meta-dim">next: none</span>}
      </span>
      <span style={{ fontSize: 'var(--text-xs)', color: '#7B52AB', opacity: 0.7, marginLeft: 'auto' }}>
        {project.billing_type === 'fixed' ? 'fixed' : 'hourly'} project
      </span>
      <span className="coaching-client-links">
        {project.obsidian_name && (
          <button className="coaching-link-btn" onClick={() => openExternal(obsidianClientUrl(project.obsidian_name!))} title="Open project page in Obsidian">notes</button>
        )}
        {project.gdrive_coaching_docs_url && (
          <button className="coaching-link-btn" onClick={() => openExternal(project.gdrive_coaching_docs_url!)} title="Open coaching docs in Drive">ƒolder</button>
        )}
      </span>
    </div>
  );
}

function ClientsPage() {
  const { groups, selection, effectiveIds, effectiveProjectIds, demo, dateModeActive, dateMode, dateDays, setFutureLabel, sortMode } = useCoachingFilter();

  if (groups.length === 0) return <div className="coaching-loading">Loading…</div>;

  // Exactly one client visible → 📋 expands inline instead of navigating
  const totalVisibleClients = useMemo(() => {
    const allClients = groups.flatMap(g => g.clients);
    return effectiveIds === null ? allClients.length : allClients.filter(c => effectiveIds.has(c.id)).length;
  }, [effectiveIds, groups]);
  const isOnlyClient = !dateModeActive && totalVisibleClients === 1;

  // Last sort: clients grouped by status (active first, then infrequent), each sorted by days_ago DESC
  if (sortMode === 'last' && !dateModeActive) {
    const allClients = groups.flatMap(g => g.clients);
    const filteredClients = effectiveIds === null ? allClients : allClients.filter(c => effectiveIds.has(c.id));
    const sortByDays = (a: CoachingClient, b: CoachingClient) => {
      if (a.days_ago === null && b.days_ago === null) return 0;
      if (a.days_ago === null) return 1;
      if (b.days_ago === null) return -1;
      return b.days_ago - a.days_ago;
    };
    const activeClients = filteredClients.filter(c => c.status === 'active').sort(sortByDays);
    const infrequentClients = filteredClients.filter(c => c.status === 'infrequent').sort(sortByDays);

    const renderStatusGroup = (label: string, clients: CoachingClient[]) => {
      if (clients.length === 0) return null;
      return (
        <div className="coaching-group">
          <div className="coaching-group-header">
            <span className="coaching-group-name">{label}</span>
          </div>
          {clients.map(client => (
            <ClientRow key={client.id} client={client} showDaysFirst isOnlyVisible={isOnlyClient} />
          ))}
        </div>
      );
    };

    return (
      <div className="coaching-clients-page">
        <div className="coaching-client-list">
          {renderStatusGroup('Active', activeClients)}
          {renderStatusGroup('Infrequent', infrequentClients)}
          {filteredClients.length === 0 && selection.length > 0 && (
            <div className="coaching-empty">No clients match the current filter.</div>
          )}
        </div>
      </div>
    );
  }

  const visibleGroups = (effectiveIds === null && effectiveProjectIds === null)
    ? groups
    : groups
        .map(g => ({
          ...g,
          clients: effectiveIds === null ? g.clients : g.clients.filter(c => effectiveIds.has(c.id)),
          projects: effectiveProjectIds === null ? (g.projects ?? []) : (g.projects ?? []).filter(p => effectiveProjectIds.has(p.id)),
        }))
        .filter(g => g.clients.length > 0 || g.projects.length > 0);

  return (
    <div className="coaching-clients-page">
      {dateModeActive ? (
        <DateView mode={dateMode} days={dateDays} onFutureSubmode={setFutureLabel} />
      ) : (
        <div className="coaching-client-list">
          {visibleGroups.map(group => (
            <div key={group.company_id ?? 'individual'} className="coaching-group">
              <div className="coaching-group-header">
                <span className="coaching-group-name">{group.company_name.toUpperCase()}</span>
                {group.default_rate != null && (
                  <span className="coaching-group-meta">
                    {demo ? '••/hr' : `$${group.default_rate.toFixed(0)}/hr`} · {group.active_client_count} active client{group.active_client_count !== 1 ? 's' : ''}
                  </span>
                )}
              </div>
              {group.clients.map(client => (
                <ClientRow key={client.id} client={client} isOnlyVisible={isOnlyClient} />
              ))}
              {group.projects.length > 0 && (
                <>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', padding: '4px 0 2px 8px', opacity: 0.6 }}>── Projects ──</div>
                  {group.projects.map(project => (
                    <ProjectRow key={project.id} project={project} />
                  ))}
                </>
              )}
            </div>
          ))}
          {visibleGroups.length === 0 && selection.length > 0 && (
            <div className="coaching-empty">No clients match the current filter.</div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Word Cloud Page
// ---------------------------------------------------------------------------

const WORD_COLORS = [
  '#2563eb',
  '#16a34a',
  '#9333ea',
  '#ea580c',
  '#0891b2',
  '#be185d',
];

function wordColor(text: string): string {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = ((hash * 31) + text.charCodeAt(i)) >>> 0;
  }
  return WORD_COLORS[hash % WORD_COLORS.length];
}

interface LayoutWord {
  text?: string;
  size?: number;
  x?: number;
  y?: number;
  rotate?: number;
  wordData?: WordData;
  [key: string]: unknown;
}

interface WordPopover {
  word: WordData;
  x: number;
  y: number;
}

function WordCloudCanvas({
  words,
  onWordClick,
}: {
  words: WordData[];
  onWordClick: (word: WordData, x: number, y: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [layoutWords, setLayoutWords] = useState<LayoutWord[]>([]);
  const [dims, setDims] = useState<[number, number]>([800, 400]);

  // Watch container width for responsive layout
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(entries => {
      const w = entries[0].contentRect.width;
      if (w > 0) setDims([w, 400]);
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Re-run d3-cloud layout when words or dims change
  useEffect(() => {
    if (!words.length) { setLayoutWords([]); return; }

    const values = words.map(w => w.value);
    const maxVal = Math.max(...values);
    const minVal = Math.min(...values);
    const range = maxVal - minVal || 1;

    const fontSize = (val: number) => Math.round(14 + ((val - minVal) / range) * 52);

    const layout = cloud()
      .size(dims)
      .words(words.map(w => ({ text: w.text, size: fontSize(w.value), wordData: w } as LayoutWord)))
      .padding(4)
      .rotate(0)
      .font('system-ui, -apple-system, sans-serif')
      .fontSize(d => (d as LayoutWord).size ?? 14)
      .random(() => 0.5)
      .on('end', (laid) => setLayoutWords(laid as LayoutWord[]));

    layout.start();
  }, [words, dims]);

  return (
    <div ref={containerRef} className="wordcloud-container">
      <svg width={dims[0]} height={dims[1]}>
        <g transform={`translate(${dims[0] / 2},${dims[1] / 2})`}>
          {layoutWords.map((w, i) => (
            <text
              key={`${w.text}-${i}`}
              style={{
                fontSize: w.size,
                fontFamily: 'inherit',
                cursor: 'pointer',
                userSelect: 'none',
              }}
              fill={wordColor(w.text ?? '')}
              textAnchor="middle"
              transform={`translate(${w.x ?? 0},${w.y ?? 0}) rotate(${w.rotate ?? 0})`}
              onClick={e => {
                const rect = (e.currentTarget as SVGTextElement).getBoundingClientRect();
                onWordClick(w.wordData!, rect.left + rect.width / 2, rect.top);
              }}
            >
              {w.text}
            </text>
          ))}
        </g>
      </svg>
    </div>
  );
}

function WordCloudPage() {
  const { effectiveIds, effectiveProjectIds, allClientIds, allProjectIds } = useCoachingFilter();
  const [sessionCount, setSessionCount] = useState(10);
  const [recencyWeight, setRecencyWeight] = useState(0);
  const [popover, setPopover] = useState<WordPopover | null>(null);

  const clientIds = useMemo(
    () => effectiveIds === null ? allClientIds : Array.from(effectiveIds),
    [effectiveIds, allClientIds]
  );

  const projectIds = useMemo(
    () => effectiveProjectIds === null ? allProjectIds : Array.from(effectiveProjectIds),
    [effectiveProjectIds, allProjectIds]
  );

  const { data, isLoading, error } = useWordCloud(clientIds, projectIds, sessionCount, recencyWeight);

  const handleWordClick = useCallback((word: WordData, x: number, y: number) => {
    setPopover(prev => (prev?.word.text === word.text ? null : { word, x, y }));
  }, []);

  const closePopover = useCallback(() => setPopover(null), []);

  // Close popover on outside click
  useEffect(() => {
    if (!popover) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Element;
      if (!target.closest('.wordcloud-popover')) setPopover(null);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [popover]);

  return (
    <div className="wordcloud-page">
      {/* Controls */}
      <div className="wordcloud-controls">
        <label className="wordcloud-control-label">
          Last
          <input
            type="number"
            className="wordcloud-session-input"
            value={sessionCount}
            min={3}
            max={50}
            onChange={e => setSessionCount(Math.max(3, Math.min(50, Number(e.target.value))))}
          />
          sessions per client
        </label>
        <label className="wordcloud-control-label">
          Recency weight
          <input
            type="range"
            className="wordcloud-recency-slider"
            min={0}
            max={5}
            step={1}
            value={recencyWeight}
            onChange={e => setRecencyWeight(Number(e.target.value))}
          />
          <span className="wordcloud-recency-value">{recencyWeight === 0 ? 'off' : recencyWeight}</span>
        </label>
      </div>

      {/* Status */}
      {data && (
        <div className="wordcloud-status">
          {data.sessions_analyzed} sessions · {data.words.length} words
          {data.clients.length > 0 && ` · ${data.clients.slice(0, 3).join(', ')}${data.clients.length > 3 ? ` +${data.clients.length - 3}` : ''}`}
        </div>
      )}

      {/* Cloud */}
      {isLoading && <div className="coaching-loading">Generating word cloud…</div>}
      {error && <div className="coaching-error">Failed to generate word cloud.</div>}
      {!isLoading && clientIds.length === 0 && projectIds.length === 0 && (
        <div className="coaching-empty">No clients or projects to analyze. Select clients using the filter above.</div>
      )}
      {!isLoading && data && data.words.length === 0 && clientIds.length > 0 && (
        <div className="coaching-empty">No words found in the selected sessions. Notes may be empty or all words were filtered as stop words.</div>
      )}
      {!isLoading && data && data.words.length > 0 && (
        <WordCloudCanvas words={data.words} onWordClick={handleWordClick} />
      )}

      {/* Click popover */}
      {popover && (
        <div
          className="wordcloud-popover"
          style={{
            position: 'fixed',
            left: Math.min(popover.x, window.innerWidth - 260),
            top: popover.y - 8,
            transform: 'translate(-50%, -100%)',
            zIndex: 500,
          }}
        >
          <div className="wordcloud-popover-header">
            <span className="wordcloud-popover-word">"{popover.word.text}"</span>
            <button className="wordcloud-popover-close" onClick={closePopover}>×</button>
          </div>
          <div className="wordcloud-popover-subhead">Sessions containing this word:</div>
          <div className="wordcloud-popover-sessions">
            {popover.word.sessions.map((s, i) => (
              <div key={i} className="wordcloud-popover-session">
                <button
                  className="coaching-link-btn wordcloud-popover-session-link"
                  onClick={() => openExternal(obsidianSessionUrl(s.obsidian_name, s.date))}
                >
                  {formatDate(s.date)} — {s.client_name} →
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Setup Page
// ---------------------------------------------------------------------------

interface SetupCompany {
  id: number;
  name: string;
  abbrev: string | null;
  default_rate: number | null;
  gdrive_folder_url: string | null;
}

function useSetupCompanies() {
  return useQuery({
    queryKey: ['setup-companies'],
    queryFn: () => api.get<{ companies: SetupCompany[] }>('/coaching/setup/companies'),
    staleTime: 30_000,
  });
}

interface SetupClient {
  id: number;
  name: string;
  company_name: string;
  status: string;
  email: string | null;
  gdrive_coaching_docs_url: string | null;
  session_count: number;
}

function useSetupClients() {
  return useQuery({
    queryKey: ['setup-clients'],
    queryFn: () => api.get<{ clients: SetupClient[] }>('/coaching/setup/clients'),
    staleTime: 30_000,
  });
}

interface SetupProject {
  id: number;
  name: string;
  company_name: string;
  billing_type: string;
  gdrive_folder_url: string | null;
  session_count: number;
}

function useSetupProjects() {
  return useQuery({
    queryKey: ['setup-projects'],
    queryFn: () => api.get<{ projects: SetupProject[] }>('/coaching/setup/projects'),
    staleTime: 30_000,
  });
}

interface EmailTemplate {
  name: string;
  subject_raw: string;
  body_raw: string;
}

function useEmailTemplates() {
  return useQuery({
    queryKey: ['coaching-email-templates'],
    queryFn: () => api.get<{ templates: EmailTemplate[]; configured: boolean }>('/coaching/email-templates'),
    staleTime: 300_000,
  });
}

type SetupType = 'company' | 'client' | 'project' | 'delete-company' | 'delete-client' | 'delete-project';

interface SetupConfirmation {
  type: SetupType;
  name: string;
  details: Record<string, string>;
  mode?: 'create' | 'delete';
}

interface ClientTaskStep {
  name: string;
  status: 'running' | 'ok' | 'warning' | 'error';
  detail: string;
}

interface ClientCreateResult {
  status: string;
  client_id: number;
  name: string;
  company_name: string;
  client_type: string;
  gdrive_coaching_docs_url: string;
  copied_files: string[];
  manifest_gdoc_url: string | null;
  agreement_edited: boolean;
  obsidian: { action: string; path?: string };
  obsidian_name: string;
  draft_id: string | null;
  draft_url: string | null;
}

interface ClientTaskStatus {
  steps: ClientTaskStep[];
  done: boolean;
  result: ClientCreateResult | null;
  error: string | null;
}

// Shared field row
function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="setup-field-row">
      <label className="setup-field-label">{label}</label>
      <div className="setup-field-input">{children}</div>
    </div>
  );
}

function CompanyForm({ onSuccess }: { onSuccess: (c: SetupConfirmation) => void }) {
  const [name, setName] = useState('');
  const [abbrev, setAbbrev] = useState('');
  const [defaultRate, setDefaultRate] = useState('');
  const [billingMethod, setBillingMethod] = useState('');
  const [paymentMethod, setPaymentMethod] = useState('');
  const [apEmail, setApEmail] = useState('');
  const [ccEmail, setCcEmail] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) { setError('Name is required'); return; }
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.post<{ status: string; company_id: number; name: string; gdrive_folder_url: string; obsidian: { action: string } }>(
        '/coaching/setup/company',
        {
          name: name.trim(),
          abbrev: abbrev.trim() || null,
          default_rate: defaultRate ? parseFloat(defaultRate) : null,
          billing_method: billingMethod || null,
          payment_method: paymentMethod || null,
          ap_email: apEmail.trim() || null,
          cc_email: ccEmail.trim() || null,
          notes: notes.trim() || null,
        },
      );
      const obsidianActionOk = result.obsidian.action !== 'skipped' && result.obsidian.action !== 'error';
      const obsidianUrl = obsidianActionOk
        ? `obsidian://open?vault=MyNotes&file=1%20Company%2F${encodeURIComponent(result.name)}%2F${encodeURIComponent(result.name)}.md`
        : null;
      onSuccess({
        type: 'company',
        name: result.name,
        details: {
          'Drive folder': result.gdrive_folder_url,
          'Obsidian': obsidianUrl ?? result.obsidian.action,
        },
      });
      // Invalidate so the new company immediately appears in the Client form dropdown
      queryClient.invalidateQueries({ queryKey: ['setup-companies'] });
      setName(''); setAbbrev(''); setDefaultRate(''); setBillingMethod('');
      setPaymentMethod(''); setApEmail(''); setCcEmail(''); setNotes('');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Creation failed';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="setup-form" onSubmit={handleSubmit}>
      <FieldRow label="Name *">
        <input className="setup-input" value={name} onChange={e => setName(e.target.value)} placeholder="Full company name" autoFocus />
      </FieldRow>
      <FieldRow label="Abbreviation">
        <input className="setup-input setup-input--short" value={abbrev} onChange={e => setAbbrev(e.target.value)} placeholder="e.g. ARB" />
      </FieldRow>
      <FieldRow label="Default rate">
        <input className="setup-input setup-input--short" type="number" value={defaultRate} onChange={e => setDefaultRate(e.target.value)} placeholder="USD/hr" min="0" />
      </FieldRow>
      <FieldRow label="Billing method">
        <select className="setup-select" value={billingMethod} onChange={e => setBillingMethod(e.target.value)}>
          <option value="">— none / pro bono —</option>
          <option value="invoice">Invoice</option>
          <option value="bill.com">Bill.com</option>
          <option value="payasgo">Pay as you go</option>
        </select>
      </FieldRow>
      <FieldRow label="Payment method">
        <select className="setup-select" value={paymentMethod} onChange={e => setPaymentMethod(e.target.value)}>
          <option value="">— select —</option>
          <option value="etrade">eTrade</option>
          <option value="venmo">Venmo</option>
          <option value="paypal">PayPal</option>
          <option value="check">Check</option>
          <option value="tipalti">Tipalti</option>
        </select>
      </FieldRow>
      <FieldRow label="AP email">
        <input className="setup-input" type="email" value={apEmail} onChange={e => setApEmail(e.target.value)} placeholder="ap@company.com" />
      </FieldRow>
      <FieldRow label="CC email">
        <input className="setup-input" type="email" value={ccEmail} onChange={e => setCcEmail(e.target.value)} placeholder="optional" />
      </FieldRow>
      <FieldRow label="Notes">
        <textarea className="setup-textarea" value={notes} onChange={e => setNotes(e.target.value)} rows={3} />
      </FieldRow>
      {error && <div className="setup-error">{error}</div>}
      <div className="setup-actions">
        <button className="setup-submit-btn" type="submit" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create Company'}
        </button>
      </div>
    </form>
  );
}

function ClientForm({ companies, onSuccess, initialCompanyId }: { companies: SetupCompany[]; onSuccess: (c: SetupConfirmation) => void; initialCompanyId?: string }) {
  const readyCompanies = companies.filter(c => c.gdrive_folder_url);
  const [companyId, setCompanyId] = useState<string>(() => {
    if (initialCompanyId && readyCompanies.some(c => c.id.toString() === initialCompanyId)) return initialCompanyId;
    return readyCompanies[0]?.id.toString() ?? '';
  });
  const [name, setName] = useState('');
  const [obsidianName, setObsidianName] = useState('');
  const [email, setEmail] = useState('');
  const [rateOverride, setRateOverride] = useState('');
  const [prepaid, setPrepaid] = useState(false);
  const [emailTemplate, setEmailTemplate] = useState<string>('Welcome');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [steps, setSteps] = useState<ClientTaskStep[]>([]);
  const [taskDone, setTaskDone] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { data: templatesData } = useEmailTemplates();
  const templates = templatesData?.templates ?? [];
  const templatesConfigured = templatesData?.configured ?? false;

  const handleNameChange = (val: string) => {
    setName(val);
    if (!obsidianName || obsidianName === name) setObsidianName(val);
  };

  // Poll task status when taskId is set
  useEffect(() => {
    if (!taskId) return;
    const poll = async () => {
      try {
        const status = await api.get<ClientTaskStatus>(`/coaching/setup/client/status/${taskId}`);
        setSteps(status.steps);
        if (status.done) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          setTaskDone(true);
          setSubmitting(false);
          if (status.error) {
            setError(status.error);
          } else if (status.result) {
            const result = status.result;
            const obsidianOk = result.obsidian.action !== 'skipped' && result.obsidian.action !== 'error';
            const obsidianUrl = obsidianOk
              ? `obsidian://open?vault=MyNotes&file=1%20People%2F${encodeURIComponent(result.obsidian_name || result.name)}.md`
              : null;
            const details: Record<string, string> = {
              'Company': result.company_name,
              'Client type': result.client_type,
              'Coaching docs': result.gdrive_coaching_docs_url,
              'Files copied': result.copied_files.length.toString(),
              'Share with client': result.gdrive_coaching_docs_url,
              'Coaching Agreement': result.agreement_edited ? 'edited' : 'skipped',
              'Obsidian': obsidianUrl ?? result.obsidian.action,
              ...(result.draft_url ? { 'Email draft': result.draft_url } : {}),
            };
            if (result.manifest_gdoc_url) details['Manifest'] = result.manifest_gdoc_url;
            onSuccess({ type: 'client', name: result.name, details });
            setName(''); setObsidianName(''); setEmail(''); setRateOverride(''); setPrepaid(false);
            setTaskId(null); setSteps([]); setTaskDone(false);
          }
        }
      } catch {
        // ignore transient polling errors
      }
    };
    pollingRef.current = setInterval(poll, 1000);
    poll();
    return () => { if (pollingRef.current) clearInterval(pollingRef.current); };
  }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!companyId) { setError('Select a company'); return; }
    if (!name.trim()) { setError('Name is required'); return; }
    setSubmitting(true);
    setError(null);
    setSteps([]);
    setTaskDone(false);
    try {
      const { task_id } = await api.post<{ task_id: string }>(
        '/coaching/setup/client',
        {
          company_id: parseInt(companyId, 10),
          name: name.trim(),
          obsidian_name: obsidianName.trim() || name.trim(),
          email: email.trim() || null,
          rate_override: rateOverride ? parseFloat(rateOverride) : null,
          prepaid,
          email_template: email.trim() && emailTemplate ? emailTemplate : null,
        },
      );
      setTaskId(task_id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Creation failed';
      setError(msg);
      setSubmitting(false);
    }
  };

  if (readyCompanies.length === 0) {
    return (
      <div className="setup-empty-notice">
        No companies with Drive folders yet. Create a company first.
      </div>
    );
  }

  return (
    <form className="setup-form" onSubmit={handleSubmit}>
      <FieldRow label="Company *">
        <select className="setup-select" value={companyId} onChange={e => setCompanyId(e.target.value)}>
          <option value="">— select —</option>
          {readyCompanies.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label="Name *">
        <input className="setup-input" value={name} onChange={e => handleNameChange(e.target.value)} placeholder="Full client name" autoFocus />
      </FieldRow>
      <FieldRow label="Obsidian name">
        <input className="setup-input" value={obsidianName} onChange={e => setObsidianName(e.target.value)} placeholder="Auto-filled from name" />
      </FieldRow>
      <FieldRow label="Email">
        <input className="setup-input" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="client@company.com" />
      </FieldRow>
      <FieldRow label="Rate override">
        <input className="setup-input setup-input--short" type="number" value={rateOverride} onChange={e => setRateOverride(e.target.value)} placeholder="blank = company rate" min="0" />
      </FieldRow>
      <FieldRow label="Prepaid">
        <input type="checkbox" checked={prepaid} onChange={e => setPrepaid(e.target.checked)} style={{ margin: 0 }} />
        <span style={{ fontSize: 'var(--text-sm)', cursor: 'pointer', position: 'relative', top: '1px' }} onClick={() => setPrepaid(v => !v)}>{prepaid ? 'Yes' : 'No'}</span>
      </FieldRow>
      {templatesConfigured && (
        <FieldRow label="Email template">
          <select
            className="setup-select"
            value={emailTemplate}
            onChange={e => setEmailTemplate(e.target.value)}
          >
            <option value="">— none —</option>
            {templates.map(t => (
              <option key={t.name} value={t.name}>{t.name}</option>
            ))}
          </select>
          {emailTemplate && !email.trim() && (
            <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-tertiary)', marginLeft: 6 }}>needs email address</span>
          )}
        </FieldRow>
      )}
      {steps.length > 0 && (
        <div className="setup-progress">
          {steps.map((s, i) => (
            <div key={i} className={`setup-progress-step setup-progress-step--${s.status}`}>
              <span className="setup-progress-icon">
                {s.status === 'running' ? '⏳' : s.status === 'ok' ? '✓' : s.status === 'warning' ? '⚠' : '✗'}
              </span>
              <span className="setup-progress-name">{s.name}</span>
              {s.detail && <span className="setup-progress-detail">{s.detail}</span>}
            </div>
          ))}
          {submitting && !taskDone && (
            <div className="setup-progress-step setup-progress-step--running">
              <span className="setup-progress-icon">⏳</span>
              <span className="setup-progress-name">Working…</span>
            </div>
          )}
        </div>
      )}
      {error && <div className="setup-error">{error}</div>}
      <div className="setup-actions">
        <button className="setup-submit-btn" type="submit" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create Client'}
        </button>
      </div>
    </form>
  );
}

function ProjectForm({ companies, onSuccess }: { companies: SetupCompany[]; onSuccess: (c: SetupConfirmation) => void }) {
  const readyCompanies = companies.filter(c => c.gdrive_folder_url);
  const [companyId, setCompanyId] = useState<string>(readyCompanies[0]?.id.toString() ?? '');
  const [name, setName] = useState('');
  const [obsidianName, setObsidianName] = useState('');
  const [billingType, setBillingType] = useState<'hourly' | 'fixed'>('hourly');
  const [fixedAmount, setFixedAmount] = useState('');
  const [rateOverride, setRateOverride] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleNameChange = (val: string) => {
    setName(val);
    if (!obsidianName || obsidianName === name) setObsidianName(val);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!companyId) { setError('Select a company'); return; }
    if (!name.trim()) { setError('Name is required'); return; }
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.post<{ status: string; project_id: number; name: string; company_name: string; billing_type: string; gdrive_folder_url: string; obsidian: { action: string } }>(
        '/coaching/setup/project',
        {
          company_id: parseInt(companyId, 10),
          name: name.trim(),
          obsidian_name: obsidianName.trim() || name.trim(),
          billing_type: billingType,
          fixed_amount: billingType === 'fixed' && fixedAmount ? parseFloat(fixedAmount) : null,
          rate_override: billingType === 'hourly' && rateOverride ? parseFloat(rateOverride) : null,
        },
      );
      onSuccess({
        type: 'project',
        name: result.name,
        details: {
          'Company': result.company_name,
          'Billing': result.billing_type,
          'Drive folder': result.gdrive_folder_url,
          'Obsidian': result.obsidian.action,
        },
      });
      setName(''); setObsidianName(''); setBillingType('hourly'); setFixedAmount(''); setRateOverride('');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Creation failed';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (readyCompanies.length === 0) {
    return (
      <div className="setup-empty-notice">
        No companies with Drive folders yet. Create a company first.
      </div>
    );
  }

  return (
    <form className="setup-form" onSubmit={handleSubmit}>
      <FieldRow label="Company *">
        <select className="setup-select" value={companyId} onChange={e => setCompanyId(e.target.value)}>
          <option value="">— select —</option>
          {readyCompanies.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </FieldRow>
      <FieldRow label="Name *">
        <input className="setup-input" value={name} onChange={e => handleNameChange(e.target.value)} placeholder="Project name" autoFocus />
      </FieldRow>
      <FieldRow label="Obsidian name">
        <input className="setup-input" value={obsidianName} onChange={e => setObsidianName(e.target.value)} placeholder="Auto-filled from name" />
      </FieldRow>
      <FieldRow label="Billing type">
        <div className="setup-toggle-group">
          <button
            type="button"
            className={`setup-toggle-btn${billingType === 'hourly' ? ' setup-toggle-btn--active' : ''}`}
            onClick={() => setBillingType('hourly')}
          >Hourly</button>
          <button
            type="button"
            className={`setup-toggle-btn${billingType === 'fixed' ? ' setup-toggle-btn--active' : ''}`}
            onClick={() => setBillingType('fixed')}
          >Fixed</button>
        </div>
      </FieldRow>
      {billingType === 'fixed' && (
        <FieldRow label="Fixed amount">
          <input className="setup-input setup-input--short" type="number" value={fixedAmount} onChange={e => setFixedAmount(e.target.value)} placeholder="USD total" min="0" />
        </FieldRow>
      )}
      {billingType === 'hourly' && (
        <FieldRow label="Rate override">
          <input className="setup-input setup-input--short" type="number" value={rateOverride} onChange={e => setRateOverride(e.target.value)} placeholder="blank = company rate" min="0" />
        </FieldRow>
      )}
      {error && <div className="setup-error">{error}</div>}
      <div className="setup-actions">
        <button className="setup-submit-btn" type="submit" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create Project'}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Delete forms
// ---------------------------------------------------------------------------

function DeleteCompanyForm({ companies, onSuccess }: { companies: SetupCompany[]; onSuccess: (c: SetupConfirmation) => void }) {
  const [selectedId, setSelectedId] = useState<string>('');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const selected = companies.find(c => c.id.toString() === selectedId) ?? null;

  const handleDelete = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId || !confirmed) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.delete<{ deleted: boolean; name: string; gdrive_url: string; obsidian_url: string }>(`/coaching/setup/company/${selectedId}`);
      queryClient.invalidateQueries({ queryKey: ['setup-companies'] });
      onSuccess({ type: 'delete-company', name: selected!.name, details: {
        ...(result.gdrive_url ? { 'Drive folder': result.gdrive_url } : {}),
        'Obsidian': result.obsidian_url,
      }, mode: 'delete' });
      setSelectedId(''); setConfirmed(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="setup-form" onSubmit={handleDelete}>
      <FieldRow label="Company *">
        <select className="setup-select" value={selectedId} onChange={e => { setSelectedId(e.target.value); setConfirmed(false); setError(null); }}>
          <option value="">— select company to delete —</option>
          {companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </FieldRow>
      {selected && (
        <div className="setup-delete-preview">
          <span className="setup-delete-preview-name">{selected.name}</span>
          {selected.gdrive_folder_url && (
            <a href={selected.gdrive_folder_url} target="_blank" rel="noreferrer" className="setup-delete-preview-link">Drive folder →</a>
          )}
        </div>
      )}
      {selected && (
        <label className="setup-confirm-check">
          <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
          I understand this will permanently delete <strong>{selected.name}</strong> and all related data
        </label>
      )}
      {error && <div className="setup-error">{error}</div>}
      <div className="setup-actions">
        <button className="setup-delete-btn" type="submit" disabled={!selectedId || !confirmed || submitting}>
          {submitting ? 'Deleting…' : 'Delete Company'}
        </button>
      </div>
    </form>
  );
}

function DeleteClientForm({ onSuccess }: { onSuccess: (c: SetupConfirmation) => void }) {
  const { data } = useSetupClients();
  const clients = data?.clients ?? [];
  const [companyFilter, setCompanyFilter] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string>('');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const companyNames = Array.from(new Set(clients.map(c => c.company_name))).sort();
  const filtered = [...clients]
    .filter(c => !companyFilter || c.company_name === companyFilter)
    .sort((a, b) => a.name.localeCompare(b.name));

  const selected = clients.find(c => c.id.toString() === selectedId) ?? null;

  const handleDelete = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId || !confirmed) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.delete<{ deleted: boolean; name: string; gdrive_url: string; obsidian_url: string }>(`/coaching/setup/client/${selectedId}`);
      queryClient.invalidateQueries({ queryKey: ['setup-clients'] });
      queryClient.invalidateQueries({ queryKey: ['coaching-clients'] });
      onSuccess({ type: 'delete-client', name: selected!.name, details: {
        'Sessions deleted': selected!.session_count.toString(),
        ...(result.gdrive_url ? { 'Drive folder': result.gdrive_url } : {}),
        'Obsidian': result.obsidian_url,
      }, mode: 'delete' });
      setSelectedId(''); setConfirmed(false); setCompanyFilter('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="setup-form" onSubmit={handleDelete}>
      <FieldRow label="Company filter">
        <select className="setup-select" value={companyFilter} onChange={e => { setCompanyFilter(e.target.value); setSelectedId(''); setConfirmed(false); setError(null); }}>
          <option value="">All companies</option>
          {companyNames.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      </FieldRow>
      <FieldRow label="Client *">
        <select className="setup-select" value={selectedId} onChange={e => { setSelectedId(e.target.value); setConfirmed(false); setError(null); }}>
          <option value="">— select client to delete —</option>
          {filtered.map(c => <option key={c.id} value={c.id}>{c.name}{!companyFilter ? ` (${c.company_name})` : ''}</option>)}
        </select>
      </FieldRow>
      {selected && (
        <div className="setup-delete-preview">
          <span className="setup-delete-preview-name">{selected.name}</span>
          <span className="setup-delete-preview-meta">{selected.company_name} · {selected.session_count} session{selected.session_count !== 1 ? 's' : ''}</span>
          {selected.gdrive_coaching_docs_url && (
            <a href={selected.gdrive_coaching_docs_url} target="_blank" rel="noreferrer" className="setup-delete-preview-link">Coaching docs →</a>
          )}
        </div>
      )}
      {selected && (
        <label className="setup-confirm-check">
          <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
          I understand this will permanently delete <strong>{selected.name}</strong> and all sessions — Drive and Obsidian pages must be cleaned up manually
        </label>
      )}
      {error && <div className="setup-error">{error}</div>}
      <div className="setup-actions">
        <button className="setup-delete-btn" type="submit" disabled={!selectedId || !confirmed || submitting}>
          {submitting ? 'Deleting…' : 'Delete Client'}
        </button>
      </div>
    </form>
  );
}

function DeleteProjectForm({ onSuccess }: { onSuccess: (c: SetupConfirmation) => void }) {
  const { data } = useSetupProjects();
  const projects = data?.projects ?? [];
  const [companyFilter, setCompanyFilter] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string>('');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const companyNames = Array.from(new Set(projects.map(p => p.company_name))).sort();
  const filtered = [...projects]
    .filter(p => !companyFilter || p.company_name === companyFilter)
    .sort((a, b) => a.name.localeCompare(b.name));

  const selected = projects.find(p => p.id.toString() === selectedId) ?? null;

  const handleDelete = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId || !confirmed) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.delete<{ deleted: boolean; name: string; gdrive_url: string; obsidian_url: string }>(`/coaching/setup/project/${selectedId}`);
      queryClient.invalidateQueries({ queryKey: ['setup-projects'] });
      queryClient.invalidateQueries({ queryKey: ['coaching-clients'] });
      onSuccess({ type: 'delete-project', name: selected!.name, details: {
        'Sessions deleted': selected!.session_count.toString(),
        ...(result.gdrive_url ? { 'Drive folder': result.gdrive_url } : {}),
        'Obsidian': result.obsidian_url,
      }, mode: 'delete' });
      setSelectedId(''); setConfirmed(false); setCompanyFilter('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="setup-form" onSubmit={handleDelete}>
      <FieldRow label="Company filter">
        <select className="setup-select" value={companyFilter} onChange={e => { setCompanyFilter(e.target.value); setSelectedId(''); setConfirmed(false); setError(null); }}>
          <option value="">All companies</option>
          {companyNames.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      </FieldRow>
      <FieldRow label="Project *">
        <select className="setup-select" value={selectedId} onChange={e => { setSelectedId(e.target.value); setConfirmed(false); setError(null); }}>
          <option value="">— select project to delete —</option>
          {filtered.map(p => <option key={p.id} value={p.id}>{p.name}{!companyFilter ? ` (${p.company_name})` : ''}</option>)}
        </select>
      </FieldRow>
      {selected && (
        <div className="setup-delete-preview">
          <span className="setup-delete-preview-name">{selected.name}</span>
          <span className="setup-delete-preview-meta">{selected.company_name} · {selected.billing_type} · {selected.session_count} session{selected.session_count !== 1 ? 's' : ''}</span>
          {selected.gdrive_folder_url && (
            <a href={selected.gdrive_folder_url} target="_blank" rel="noreferrer" className="setup-delete-preview-link">Drive folder →</a>
          )}
        </div>
      )}
      {selected && (
        <label className="setup-confirm-check">
          <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
          I understand this will permanently delete <strong>{selected.name}</strong> and all sessions — Drive and Obsidian pages must be cleaned up manually
        </label>
      )}
      {error && <div className="setup-error">{error}</div>}
      <div className="setup-actions">
        <button className="setup-delete-btn" type="submit" disabled={!selectedId || !confirmed || submitting}>
          {submitting ? 'Deleting…' : 'Delete Project'}
        </button>
      </div>
    </form>
  );
}

function SetupPage() {
  const [activeType, setActiveType] = useState<SetupType | null>(null);
  const [confirmation, setConfirmation] = useState<SetupConfirmation | null>(null);
  const { data: companiesData } = useSetupCompanies();
  const companies = companiesData?.companies ?? [];

  const handleSuccess = (c: SetupConfirmation) => {
    setConfirmation(c);
  };

  const handleTypeSelect = (t: SetupType) => {
    setActiveType(t);
    setConfirmation(null);
  };

  const ENTITY_LABEL: Record<SetupType, string> = {
    company: 'Company', client: 'Client', project: 'Project',
    'delete-company': 'Company', 'delete-client': 'Client', 'delete-project': 'Project',
  };

  return (
    <div className="setup-page">
      {/* Type selector — two groups: Create and Delete */}
      <div className="setup-type-groups">
        <div className="setup-type-group">
          <span className="setup-type-group-label">Create</span>
          {(['company', 'client', 'project'] as SetupType[]).map(t => (
            <button
              key={t}
              className={`setup-type-btn${activeType === t ? ' setup-type-btn--active' : ''}`}
              onClick={() => handleTypeSelect(t)}
            >
              {ENTITY_LABEL[t]}
            </button>
          ))}
        </div>
        <div className="setup-type-group">
          <span className="setup-type-group-label setup-type-group-label--delete">Delete</span>
          {(['delete-company', 'delete-client', 'delete-project'] as SetupType[]).map(t => (
            <button
              key={t}
              className={`setup-type-btn setup-type-btn--delete${activeType === t ? ' setup-type-btn--delete-active' : ''}`}
              onClick={() => handleTypeSelect(t)}
            >
              {ENTITY_LABEL[t]}
            </button>
          ))}
        </div>
      </div>

      {/* Empty state */}
      {!activeType && (
        <p className="setup-prompt">Select what you'd like to create or delete.</p>
      )}

      {/* Confirmation banner */}
      {confirmation && (
        <div className={`setup-confirmation${confirmation.mode === 'delete' ? ' setup-confirmation--deleted' : ''}`}>
          <div className="setup-confirmation-title">
            {confirmation.mode === 'delete' ? `${ENTITY_LABEL[confirmation.type]} deleted: ` : `${ENTITY_LABEL[confirmation.type]} created: `}
            <strong>{confirmation.name}</strong>
          </div>
          {Object.keys(confirmation.details).length > 0 && (
            <dl className="setup-confirmation-details">
              {Object.entries(confirmation.details).map(([k, v]) => (
                <div key={k} className="setup-confirmation-row">
                  <dt>{k}</dt>
                  <dd>
                    {v.startsWith('https://') || v.startsWith('http://') || v.startsWith('obsidian://')
                      ? <a href={v} target="_blank" rel="noreferrer">
                          {k === 'Email draft' ? 'Open in Gmail →'
                          : k === 'Share with client' || k === 'Drive folder' || k === 'Coaching docs' ? 'Open Drive folder →'
                          : k === 'Obsidian' ? 'Open in Obsidian →'
                          : 'link'}
                        </a>
                      : v}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {confirmation.mode === 'delete'
            ? <p className="setup-confirmation-hint setup-confirmation-hint--warning">Drive folder and Obsidian page are NOT deleted — clean those up manually.</p>
            : <p className="setup-confirmation-hint">Form reset — create another {ENTITY_LABEL[confirmation.type].toLowerCase()}.</p>
          }
        </div>
      )}

      {/* Create forms */}
      {activeType === 'company' && <CompanyForm onSuccess={handleSuccess} />}
      {activeType === 'client' && <ClientForm companies={companies} onSuccess={handleSuccess} />}
      {activeType === 'project' && <ProjectForm companies={companies} onSuccess={handleSuccess} />}

      {/* Delete forms */}
      {activeType === 'delete-company' && <DeleteCompanyForm companies={companies} onSuccess={handleSuccess} />}
      {activeType === 'delete-client' && <DeleteClientForm onSuccess={handleSuccess} />}
      {activeType === 'delete-project' && <DeleteProjectForm onSuccess={handleSuccess} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Vinny Page
// ---------------------------------------------------------------------------

function VinnyPage() {
  const { data, isLoading } = useVinnyStatus();

  if (isLoading) return <div className="coaching-loading">Checking Vinny…</div>;

  if (!data?.running) {
    return (
      <div className="coaching-vinny-offline">
        <p className="coaching-vinny-offline-title">Vinny Chat is not running</p>
        <p>Start it with:</p>
        <pre className="coaching-vinny-offline-cmd">cd ~/vinny/vinny-chat && npm run dev</pre>
        <p>Then reload this page.</p>
      </div>
    );
  }

  return (
    <div className="coaching-vinny">
      <iframe src="http://localhost:5174/" title="Vinny" className="coaching-vinny-frame" allow="clipboard-read; clipboard-write" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Claude API Usage Panel (inside OperationsPage)
// ---------------------------------------------------------------------------

interface ClaudeUsagePeriod {
  period: string;
  call_count: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

interface ClaudeUsageFeature {
  feature: string;
  call_count: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

interface ClaudeUsageData {
  all_time: { call_count: number; input_tokens: number; output_tokens: number; cost_usd: number };
  daily: ClaudeUsagePeriod[];
  weekly: ClaudeUsagePeriod[];
  monthly: ClaudeUsagePeriod[];
  by_feature: ClaudeUsageFeature[];
}

function fmtCost(usd: number): string {
  if (usd < 0.001) return '<$0.001';
  return `$${usd.toFixed(4)}`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

type UsageTab = 'day' | 'week' | 'month';

function ClaudeUsagePanel() {
  const [tab, setTab] = useState<UsageTab>('day');
  const { data, isLoading } = useQuery<ClaudeUsageData>({
    queryKey: ['claude-usage'],
    queryFn: () => api.get<ClaudeUsageData>('/operations/claude-usage'),
    staleTime: 60_000,
  });

  const periods: ClaudeUsagePeriod[] = tab === 'day' ? (data?.daily ?? [])
    : tab === 'week' ? (data?.weekly ?? [])
    : (data?.monthly ?? []);

  const totalRow: ClaudeUsagePeriod | null = periods.length > 0 ? {
    period: 'Total',
    call_count: periods.reduce((s, r) => s + r.call_count, 0),
    input_tokens: periods.reduce((s, r) => s + r.input_tokens, 0),
    output_tokens: periods.reduce((s, r) => s + r.output_tokens, 0),
    cost_usd: periods.reduce((s, r) => s + r.cost_usd, 0),
  } : null;

  return (
    <div className="ops-card">
      <div className="ops-card-header">
        <div>
          <div className="ops-card-title">Claude API Usage</div>
          <div className="ops-card-desc">Token consumption and cost across all Dashy features.</div>
        </div>
      </div>

      <div style={{ marginTop: 8 }}>
        {isLoading && <div className="ops-card-status">Loading…</div>}
        {data && (
          <>
            {/* All-time summary */}
            <div className="ops-card-status" style={{ marginBottom: 10 }}>
                <strong>All time:</strong>{' '}
                {fmtCost(data.all_time.cost_usd)} · {data.all_time.call_count.toLocaleString()} calls ·{' '}
                {fmtTokens(data.all_time.input_tokens)} in / {fmtTokens(data.all_time.output_tokens)} out
              </div>

              {/* Tab bar */}
              <div className="ops-tab-bar">
                {(['day', 'week', 'month'] as UsageTab[]).map(t => (
                  <button
                    key={t}
                    className={`ops-tab-btn${tab === t ? ' ops-tab-btn--active' : ''}`}
                    onClick={() => setTab(t)}
                  >
                    {t === 'day' ? 'Day' : t === 'week' ? 'Week' : 'Month'}
                  </button>
                ))}
              </div>

              {/* Period table */}
              {periods.length === 0 ? (
                <div className="ops-card-status">No data yet.</div>
              ) : (
                <table className="ops-usage-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th className="ops-usage-num">Calls</th>
                      <th className="ops-usage-num">Input</th>
                      <th className="ops-usage-num">Output</th>
                      <th className="ops-usage-num">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {periods.map((r, i) => (
                      <tr key={i}>
                        <td>{r.period}</td>
                        <td className="ops-usage-num">{r.call_count}</td>
                        <td className="ops-usage-num">{fmtTokens(r.input_tokens)}</td>
                        <td className="ops-usage-num">{fmtTokens(r.output_tokens)}</td>
                        <td className="ops-usage-num">{fmtCost(r.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                  {totalRow && (
                    <tfoot>
                      <tr className="ops-usage-total">
                        <td>Total</td>
                        <td className="ops-usage-num">{totalRow.call_count}</td>
                        <td className="ops-usage-num">{fmtTokens(totalRow.input_tokens)}</td>
                        <td className="ops-usage-num">{fmtTokens(totalRow.output_tokens)}</td>
                        <td className="ops-usage-num">{fmtCost(totalRow.cost_usd)}</td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              )}

              {/* Feature breakdown */}
              {data.by_feature.length > 0 && (
                <>
                  <div className="ops-card-title" style={{ marginTop: 16, marginBottom: 6 }}>By feature</div>
                  <table className="ops-usage-table">
                    <thead>
                      <tr>
                        <th>Feature</th>
                        <th className="ops-usage-num">Calls</th>
                        <th className="ops-usage-num">Input</th>
                        <th className="ops-usage-num">Output</th>
                        <th className="ops-usage-num">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.by_feature.map((r, i) => (
                        <tr key={i}>
                          <td>{r.feature}</td>
                          <td className="ops-usage-num">{r.call_count}</td>
                          <td className="ops-usage-num">{fmtTokens(r.input_tokens)}</td>
                          <td className="ops-usage-num">{fmtTokens(r.output_tokens)}</td>
                          <td className="ops-usage-num">{fmtCost(r.cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </>
          )}
        </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OperationsPage
// ---------------------------------------------------------------------------

interface GranolaLogEntry {
  status: 'synced' | 'skipped' | 'unmatched' | 'error' | 'dry_run';
  title: string;
  filename: string | null;
  error?: string;
  // dry run fields
  has_existing_granola_content?: boolean;
  has_duplicate_granola_section?: boolean;
  would_action?: 'write' | 'skip' | 'append';
}

interface GranolaSyncResult {
  fetched: number;
  matched: number;
  written: number;
  skipped_existing: number;
  unmatched: string[];
  errors: string[];
  log?: GranolaLogEntry[];
  dry_run?: boolean;
}

interface GranolaStatus {
  running: boolean;
  last_run: string | null;
  last_result: GranolaSyncResult | null;
  last_error: string | null;
}

interface NoteLogEntry {
  status: 'created' | 'updated' | 'skipped';
  type: 'daily' | 'meeting';
  filename: string;
  reason?: string;
}

interface NotesSyncResult {
  daily_created: number;
  meeting_created: number;
  meeting_updated: number;
  skipped: number;
  log?: NoteLogEntry[];
  dry_run?: boolean;
}

interface NotesStatus {
  running: boolean;
  last_run: string | null;
  last_result: NotesSyncResult | null;
  last_error: string | null;
  config: { days_ahead: number };
}

function formatRunTime(iso: string | null): string {
  if (!iso) return 'Never';
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

interface ManifestClientResult {
  client_id: number;
  name: string;
  status: 'created' | 'skipped' | 'error';
  manifest_url?: string | null;
  reason?: string;
  error?: string;
}

interface CreateManifsetsResult {
  total: number;
  created: number;
  skipped: number;
  errors: number;
  results: ManifestClientResult[];
}

function OperationsPage() {
  const [granolaDaysBack, setGranolaDaysBack] = useState(7);
  const [granolaForce, setGranolaForce] = useState(false);
  const [granolaRunning, setGranolaRunning] = useState(false);
  const [granolaStatus, setGranolaStatus] = useState<GranolaStatus | null>(null);
  const [granolaError, setGranolaError] = useState<string | null>(null);
  const [granolaLogOpen, setGranolaLogOpen] = useState(false);
  const [granolaDryRunning, setGranolaDryRunning] = useState(false);
  const [granolaDryResult, setGranolaDryResult] = useState<GranolaSyncResult | null>(null);
  const [granolaDryError, setGranolaDryError] = useState<string | null>(null);

  const [notesRunning, setNotesRunning] = useState(false);
  const [notesStatus, setNotesStatus] = useState<NotesStatus | null>(null);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [daysAhead, setDaysAhead] = useState<number | null>(null);
  const [savingDays, setSavingDays] = useState(false);
  const [notesLogOpen, setNotesLogOpen] = useState(false);
  const [notesDryRunning, setNotesDryRunning] = useState(false);
  const [notesDryResult, setNotesDryResult] = useState<NotesSyncResult | null>(null);
  const [notesDryError, setNotesDryError] = useState<string | null>(null);

  const [manifestsRunning, setManifestsRunning] = useState(false);
  const [manifestsResult, setManifestsResult] = useState<CreateManifsetsResult | null>(null);
  const [manifestsError, setManifestsError] = useState<string | null>(null);

  // Load initial status
  useEffect(() => {
    api.get<GranolaStatus>('/coaching/granola/status').then(setGranolaStatus).catch(() => null);
    api.get<NotesStatus>('/coaching/notes/status').then(s => {
      setNotesStatus(s);
      setDaysAhead(s.config?.days_ahead ?? 5);
    }).catch(() => null);
  }, []);

  const handleGranolaSync = async () => {
    setGranolaRunning(true);
    setGranolaError(null);
    try {
      const resp = await api.post<{ status: string; error?: string; result: GranolaSyncResult | null }>(
        `/coaching/granola/sync?days_back=${granolaDaysBack}&force=${granolaForce}`
      );
      if (resp.status === 'error' && resp.error) {
        setGranolaError(resp.error);
      }
      const updated = await api.get<GranolaStatus>('/coaching/granola/status');
      setGranolaStatus(updated);
    } catch (e: unknown) {
      setGranolaError(e instanceof Error ? e.message : String(e));
    } finally {
      setGranolaRunning(false);
    }
  };

  const handleGranolaDryRun = async () => {
    setGranolaDryRunning(true);
    setGranolaDryError(null);
    setGranolaDryResult(null);
    try {
      const resp = await api.post<{ status: string; error?: string; result: GranolaSyncResult | null }>(
        `/coaching/granola/sync?days_back=${granolaDaysBack}&force=${granolaForce}&dry_run=true`
      );
      if (resp.status === 'error' && resp.error) {
        setGranolaDryError(resp.error);
      } else {
        setGranolaDryResult(resp.result);
      }
    } catch (e: unknown) {
      setGranolaDryError(e instanceof Error ? e.message : String(e));
    } finally {
      setGranolaDryRunning(false);
    }
  };

  const handleNotesCreate = async () => {
    setNotesRunning(true);
    setNotesError(null);
    try {
      await api.post('/coaching/notes/create');
      const updated = await api.get<NotesStatus>('/coaching/notes/status');
      setNotesStatus(updated);
    } catch (e: unknown) {
      setNotesError(e instanceof Error ? e.message : String(e));
    } finally {
      setNotesRunning(false);
    }
  };

  const handleNotesDryRun = async () => {
    setNotesDryRunning(true);
    setNotesDryError(null);
    setNotesDryResult(null);
    try {
      const resp = await api.post<{ status: string; error?: string; result: NotesSyncResult | null }>(
        '/coaching/notes/create?dry_run=true'
      );
      if (resp.status === 'error' && resp.error) {
        setNotesDryError(resp.error);
      } else {
        setNotesDryResult(resp.result);
      }
    } catch (e: unknown) {
      setNotesDryError(e instanceof Error ? e.message : String(e));
    } finally {
      setNotesDryRunning(false);
    }
  };

  const handleDaysAheadSave = async (val: number) => {
    setSavingDays(true);
    try {
      const result = await api.patch<{ config: { days_ahead: number } }>('/coaching/notes/config', { days_ahead: val });
      setDaysAhead(result.config.days_ahead);
    } catch (e) {
      // ignore
    } finally {
      setSavingDays(false);
    }
  };

  const handleCreateManifests = async () => {
    setManifestsRunning(true);
    setManifestsError(null);
    setManifestsResult(null);
    try {
      const result = await api.post<CreateManifsetsResult>('/coaching/setup/create-manifests');
      setManifestsResult(result);
    } catch (e: unknown) {
      setManifestsError(e instanceof Error ? e.message : String(e));
    } finally {
      setManifestsRunning(false);
    }
  };

  const gr = granolaStatus;
  const ns = notesStatus;

  return (
    <div className="coaching-operations">
      <h2 className="coaching-operations-title">Operations</h2>

      {/* Granola Sync Card */}
      <div className="ops-card">
        <div className="ops-card-header">
          <div>
            <div className="ops-card-title">Granola Notes Sync</div>
            <div className="ops-card-desc">
              Copies Granola AI summaries into Obsidian session notes automatically after each meeting.
            </div>
          </div>
        </div>

        <div className="ops-card-status">
          {gr?.last_run ? (
            <span>
              Last run: {formatRunTime(gr.last_run)}
              {gr.last_result && (
                <span className="ops-card-counts">
                  {' · '}{gr.last_result.fetched} fetched
                  {' · '}{gr.last_result.written} written
                  {(gr.last_result.skipped_existing ?? 0) > 0 && (
                    <span> · {gr.last_result.skipped_existing} already synced</span>
                  )}
                  {gr.last_result.unmatched.length > 0 && (
                    <span> · {gr.last_result.unmatched.length} unmatched</span>
                  )}
                  {gr.last_result.errors.length > 0 && (
                    <span style={{ color: 'var(--color-error, #c0392b)' }}> · {gr.last_result.errors.length} errors</span>
                  )}
                </span>
              )}
              {gr.last_error && <span style={{ color: 'var(--color-error, #c0392b)' }}> · Error: {gr.last_error}</span>}
            </span>
          ) : (
            <span style={{ color: 'var(--color-text-light)' }}>Never run</span>
          )}
        </div>

        {granolaError && (
          <div className="ops-card-error">{granolaError}</div>
        )}

        {gr?.last_result?.log && gr.last_result.log.length > 0 && (
          <div className="ops-card-log-wrap">
            <button className="ops-log-toggle" onClick={() => setGranolaLogOpen(o => !o)}>
              {granolaLogOpen ? 'Hide log' : 'Show log'} ({gr.last_result.log.length})
            </button>
            {granolaLogOpen && (
              <ul className="ops-log-list">
                {gr.last_result.log.map((entry, i) => {
                  const icon = entry.status === 'synced' ? '✓'
                    : entry.status === 'skipped' ? '—'
                    : entry.status === 'error' ? '✕'
                    : '?';
                  const statusCls = entry.status === 'synced' ? 'ops-log-created'
                    : entry.status === 'skipped' ? 'ops-log-skipped'
                    : 'ops-log-error';
                  const obsidianHref = entry.filename
                    ? `obsidian://open?vault=MyNotes&file=8%20Meetings%2F${encodeURIComponent(entry.filename)}`
                    : null;
                  return (
                    <li key={i} className={`ops-log-item ${statusCls}`}>
                      <span className="ops-log-icon">{icon}</span>
                      {obsidianHref
                        ? <a href={obsidianHref} className="ops-log-link">{entry.filename!.replace(/\.md$/, '')}</a>
                        : <span className="ops-log-link">{entry.title}</span>
                      }
                      {entry.error && <span className="ops-log-error-msg"> — {entry.error}</span>}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}

        <div className="ops-card-controls">
          <label className="ops-label">
            Date range:
            <select
              className="ops-select"
              value={granolaDaysBack}
              onChange={e => setGranolaDaysBack(Number(e.target.value))}
              disabled={granolaRunning}
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={60}>Last 60 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </label>
          <label className="ops-label ops-force-label">
            <input
              type="checkbox"
              checked={granolaForce}
              onChange={e => setGranolaForce(e.target.checked)}
              disabled={granolaRunning}
            />
            Force re-sync
          </label>
          <button
            className="ops-run-btn"
            onClick={handleGranolaSync}
            disabled={granolaRunning || granolaDryRunning}
          >
            {granolaRunning ? 'Syncing…' : 'Sync Now'}
          </button>
          <button
            className="ops-run-btn"
            style={{ background: 'transparent', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            onClick={handleGranolaDryRun}
            disabled={granolaRunning || granolaDryRunning}
          >
            {granolaDryRunning ? 'Running…' : 'Dry Run'}
          </button>
        </div>

        {granolaDryError && (
          <div className="ops-card-error">{granolaDryError}</div>
        )}

        {granolaDryResult && (
          <div className="ops-dry-run-wrap">
            <div className="ops-dry-run-header">
              <span className="ops-dry-run-badge">Dry Run</span>
              <span>{granolaDryResult.fetched} fetched · {granolaDryResult.matched} matched · {(granolaDryResult.log ?? []).filter(e => e.would_action === 'write').length} would write · {(granolaDryResult.log ?? []).filter(e => e.would_action === 'skip').length} would skip</span>
            </div>
            {((granolaDryResult.log ?? []).length > 0 || (granolaDryResult.unmatched ?? []).length > 0) && (
              <table className="ops-dry-run-table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Has content</th>
                    <th>Duplicate heading</th>
                    <th>Would action</th>
                  </tr>
                </thead>
                <tbody>
                  {(granolaDryResult.log ?? []).map((entry, i) => (
                    <tr key={i}>
                      <td>
                        {entry.filename
                          ? <a href={`obsidian://open?vault=MyNotes&file=8%20Meetings%2F${encodeURIComponent(entry.filename)}`} className="ops-log-link">{entry.filename.replace(/\.md$/, '')}</a>
                          : <span style={{ color: 'var(--color-text-light)' }}>{entry.title}</span>
                        }
                      </td>
                      <td className={entry.has_existing_granola_content ? 'ops-dry-run-bool--yes' : 'ops-dry-run-bool--no'}>
                        {entry.has_existing_granola_content ? 'yes' : 'no'}
                      </td>
                      <td className={entry.has_duplicate_granola_section ? 'ops-dry-run-bool--yes' : 'ops-dry-run-bool--no'}>
                        {entry.has_duplicate_granola_section ? 'yes' : 'no'}
                      </td>
                      <td className={`ops-dry-run-action--${entry.would_action ?? 'skip'}`}>
                        {entry.would_action ?? '—'}
                      </td>
                    </tr>
                  ))}
                  {(granolaDryResult.unmatched ?? []).map((title, i) => (
                    <tr key={`unmatched-${i}`} style={{ color: '#a05050' }}>
                      <td>{title}</td>
                      <td style={{ color: '#c0b0b0' }}>n/a</td>
                      <td style={{ color: '#c0b0b0' }}>n/a</td>
                      <td style={{ color: '#a05050', fontStyle: 'italic' }}>unmatched</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* Note Creation Card */}
      <div className="ops-card">
        <div className="ops-card-header">
          <div>
            <div className="ops-card-title">Daily &amp; Meeting Note Creation</div>
            <div className="ops-card-desc">
              Creates Obsidian notes for upcoming coaching sessions up to N days in advance.
            </div>
          </div>
        </div>

        <div className="ops-card-status">
          {ns?.last_run ? (
            <span>
              Last run: {formatRunTime(ns.last_run)}
              {ns.last_result && (
                <span className="ops-card-counts">
                  {ns.last_result.daily_created > 0 && <span> · {ns.last_result.daily_created} daily created</span>}
                  {ns.last_result.meeting_created > 0 && <span> · {ns.last_result.meeting_created} meeting created</span>}
                  {ns.last_result.meeting_updated > 0 && <span> · {ns.last_result.meeting_updated} updated</span>}
                  {(ns.last_result.daily_created === 0 && ns.last_result.meeting_created === 0 && ns.last_result.meeting_updated === 0) && (
                    <span> · all up to date</span>
                  )}
                </span>
              )}
              {ns.last_error && <span style={{ color: 'var(--color-error, #c0392b)' }}> · Error: {ns.last_error}</span>}
            </span>
          ) : (
            <span style={{ color: 'var(--color-text-light)' }}>Never run</span>
          )}
        </div>

        {notesError && (
          <div className="ops-card-error">{notesError}</div>
        )}

        {ns?.last_result?.log && ns.last_result.log.length > 0 && (
          <div className="ops-card-log-wrap">
            <button className="ops-log-toggle" onClick={() => setNotesLogOpen(o => !o)}>
              {notesLogOpen ? 'Hide log' : 'Show log'} ({ns.last_result.log.length})
            </button>
            {notesLogOpen && (
              <ul className="ops-log-list">
                {ns.last_result.log.map((entry, i) => {
                  const icon = entry.status === 'created' ? '✓' : entry.status === 'updated' ? '↻' : '—';
                  const obsidianPath = entry.type === 'daily'
                    ? `9%20Daily%2F${encodeURIComponent(entry.filename)}`
                    : `8%20Meetings%2F${encodeURIComponent(entry.filename)}`;
                  const href = `obsidian://open?vault=MyNotes&file=${obsidianPath}`;
                  return (
                    <li key={i} className={`ops-log-item ops-log-${entry.status}`}>
                      <span className="ops-log-icon">{icon}</span>
                      <a href={href} className="ops-log-link">{entry.filename.replace(/\.md$/, '')}</a>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}

        <div className="ops-card-controls">
          <label className="ops-label">
            Days ahead:
            <input
              type="number"
              className="ops-number-input"
              value={daysAhead ?? 5}
              min={1}
              max={30}
              disabled={notesRunning || savingDays}
              onChange={e => setDaysAhead(Number(e.target.value))}
              onBlur={e => {
                const v = Math.max(1, Math.min(30, Number(e.target.value)));
                setDaysAhead(v);
                handleDaysAheadSave(v);
              }}
            />
          </label>
          <button
            className="ops-run-btn"
            onClick={handleNotesCreate}
            disabled={notesRunning || notesDryRunning}
          >
            {notesRunning ? 'Running…' : 'Run Now'}
          </button>
          <button
            className="ops-run-btn"
            style={{ background: 'transparent', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            onClick={handleNotesDryRun}
            disabled={notesRunning || notesDryRunning}
          >
            {notesDryRunning ? 'Running…' : 'Dry Run'}
          </button>
        </div>

        {notesDryError && (
          <div className="ops-card-error">{notesDryError}</div>
        )}

        {notesDryResult && (
          <div className="ops-dry-run-wrap">
            <div className="ops-dry-run-header">
              <span className="ops-dry-run-badge">Dry Run</span>
              <span>
                {notesDryResult.daily_created > 0 && `${notesDryResult.daily_created} daily to create · `}
                {notesDryResult.meeting_created > 0 && `${notesDryResult.meeting_created} meeting to create · `}
                {notesDryResult.meeting_updated > 0 && `${notesDryResult.meeting_updated} to update · `}
                {(notesDryResult.daily_created === 0 && notesDryResult.meeting_created === 0 && notesDryResult.meeting_updated === 0) && 'all up to date'}
              </span>
            </div>
            {(notesDryResult.log ?? []).length > 0 && (
              <table className="ops-dry-run-table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Type</th>
                    <th>Would action</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {(notesDryResult.log ?? []).map((entry, i) => {
                    const obsidianPath = entry.type === 'daily'
                      ? `9%20Daily%2F${encodeURIComponent(entry.filename)}`
                      : `8%20Meetings%2F${encodeURIComponent(entry.filename)}`;
                    return (
                      <tr key={i}>
                        <td>
                          <a href={`obsidian://open?vault=MyNotes&file=${obsidianPath}`} className="ops-log-link">
                            {entry.filename.replace(/\.md$/, '')}
                          </a>
                        </td>
                        <td style={{ color: 'var(--color-text-light)' }}>{entry.type}</td>
                        <td className={`ops-dry-run-action--${entry.status}`}>{entry.status}</td>
                        <td style={{ color: '#888', fontStyle: entry.reason ? 'normal' : 'italic' }}>
                          {entry.reason ?? '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* Manifest Creation Card */}
      <div className="ops-card">
        <div className="ops-card-header">
          <div>
            <div className="ops-card-title">Create Missing Manifests</div>
            <div className="ops-card-desc">
              Creates a "Manifest" Google Doc for every active client that doesn't have one yet.
              Each doc is placed in the client's Coaching Docs folder and pre-populated with a
              Documents section (linking the template files) and an empty Others section.
            </div>
          </div>
        </div>

        <div className="ops-card-controls">
          <button
            className="ops-run-btn"
            onClick={handleCreateManifests}
            disabled={manifestsRunning}
          >
            {manifestsRunning ? 'Creating…' : 'Create Missing Manifests'}
          </button>
        </div>

        {manifestsError && (
          <div className="ops-card-error">{manifestsError}</div>
        )}

        {manifestsResult && (
          <div className="ops-dry-run-wrap">
            <div className="ops-dry-run-header">
              <span>
                {manifestsResult.created} created
                {manifestsResult.skipped > 0 && ` · ${manifestsResult.skipped} skipped`}
                {manifestsResult.errors > 0 && ` · ${manifestsResult.errors} errors`}
                {manifestsResult.total === 0 && ' — all clients already have a Manifest'}
              </span>
            </div>
            {manifestsResult.results.length > 0 && (
              <table className="ops-dry-run-table">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Status</th>
                    <th>Manifest</th>
                  </tr>
                </thead>
                <tbody>
                  {manifestsResult.results.map((r) => (
                    <tr key={r.client_id}>
                      <td>{r.name}</td>
                      <td className={`ops-dry-run-action--${r.status === 'created' ? 'created' : r.status === 'error' ? 'error' : 'skipped'}`}>
                        {r.status}
                      </td>
                      <td>
                        {r.manifest_url
                          ? <a href={r.manifest_url} target="_blank" rel="noreferrer" className="ops-log-link">open</a>
                          : <span style={{ color: 'var(--color-text-light)' }}>{r.reason ?? r.error ?? '—'}</span>
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      <ClaudeUsagePanel />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Coaching Module Root — owns filter state, provides context
// ---------------------------------------------------------------------------

export function CoachingPage() {
  const { data, isLoading } = useCoachingClients();
  const { data: activeData } = useCoachingActive();
  const [selection, setSelection] = useState<FilterSelection[]>([]);
  const [allChip, setAllChip] = useState(true);
  const [demo, setDemo] = useState(false);
  const toggleDemo = useCallback(() => setDemo(d => !d), []);
  const hasAutoSelected = useRef(false);

  // Reimport seed
  const qc = useQueryClient();
  const [reimportToast, setReimportToast] = useState<{ ok: boolean; msg: string } | null>(null);
  const reimport = useMutation({
    mutationFn: () => api.post('/billing/seed/import?force=true', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['billing-companies'] });
      qc.invalidateQueries({ queryKey: ['coaching-clients'] });
      setReimportToast({ ok: true, msg: 'Reimport complete' });
      setTimeout(() => setReimportToast(null), 3000);
    },
    onError: (err: Error) => {
      setReimportToast({ ok: false, msg: `Reimport failed: ${err.message}` });
      setTimeout(() => setReimportToast(null), 4000);
    },
  });

  // Sort mode
  const [sortMode, setSortMode] = useState<'default' | 'last'>('default');
  // Input phase — tracked so parent can decide Row 2 visibility
  const [inputPhase, setInputPhase] = useState<'visible' | 'fading' | 'hidden'>('visible');

  // Date mode state (lifted here so DateModeBar can sit beside the filter)
  const [dateModeActive, setDateModeActive] = useState(false);
  const [dateMode, setDateMode] = useState<DateMode>('today');
  const [dateDays, setDateDays] = useState<number | undefined>(undefined);
  const [futureLabel, setFutureLabel] = useState('');
  const lastDateModeRef = useRef<DateMode>('today');
  const dateModeActiveRef = useRef(false);

  const location = useLocation();
  const navigate = useNavigate();
  const isClientsPage = location.pathname.endsWith('/clients') || location.pathname === '/coaching';
  const isClientsPageRef = useRef(isClientsPage);
  useEffect(() => { isClientsPageRef.current = isClientsPage; }, [isClientsPage]);

  // Navigate to clients page when activating date mode from another sub-page
  useEffect(() => {
    if (dateModeActive && !isClientsPage) navigate('/coaching/clients');
  }, [dateModeActive, isClientsPage, navigate]);

  // Keyboard handler — capture phase so keys are intercepted before the filter input.
  //
  // ; toggles date mode:
  //   • Not in date mode → enter date mode, activate Future.
  //   • In date mode     → exit date mode, restore All chip.
  //
  // While in date mode, valid keys change the date view (never exit):
  //   p/t/n/w/f → Past/Today/Next/Week/Future
  //   1–9       → Future N days
  //   A–Z       → Future 10–35 days (A=10 … Z=35)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // '/' on non-clients page → navigate to clients (filter auto-focuses on mount)
      if (e.key === '/' && !isClientsPageRef.current) {
        const focused = document.activeElement;
        const isInput = focused instanceof HTMLInputElement || focused instanceof HTMLTextAreaElement || (focused as HTMLElement)?.isContentEditable;
        if (!isInput) {
          e.preventDefault();
          navigate('/coaching/clients');
          return;
        }
      }

      // ';' always intercepts
      if (e.key === ';') {
        e.preventDefault();
        e.stopPropagation();
        if (dateModeActiveRef.current) {
          // Exit date mode
          dateModeActiveRef.current = false;
          setDateModeActive(false);
          setSelection([]);
          setAllChip(true);
        } else {
          // Enter date mode with Today
          dateModeActiveRef.current = true;
          lastDateModeRef.current = 'today';
          setDateMode('today');
          setDateDays(undefined);
          setDateModeActive(true);
        }
        return;
      }

      // While in date mode, intercept all valid date keys
      if (dateModeActiveRef.current) {
        const modeMap: Record<string, DateMode> = {
          p: 'past', t: 'today', n: 'next', w: 'week',
        };
        if (modeMap[e.key]) {
          e.preventDefault();
          e.stopPropagation();
          const m = modeMap[e.key];
          lastDateModeRef.current = m;
          setDateMode(m);
          setDateDays(undefined);
          return;
        }
        if (/^[1-9]$/.test(e.key)) {
          e.preventDefault();
          e.stopPropagation();
          setDateMode('today');
          setDateDays(parseInt(e.key, 10));
          return;
        }
        if (/^[A-Z]$/.test(e.key)) {
          e.preventDefault();
          e.stopPropagation();
          const days = e.key.charCodeAt(0) - 'A'.charCodeAt(0) + 10; // A=10 … Z=35
          setDateMode('today');
          setDateDays(days);
          return;
        }
      }
    };

    window.addEventListener('keydown', handler, true); // capture phase
    return () => window.removeEventListener('keydown', handler, true);
  }, []); // register once; refs keep values current

  // Auto-select active client/project on initial load (only once, only if still at default All state)
  useEffect(() => {
    if (hasAutoSelected.current) return;
    if (!activeData?.active) return;
    const groups = data?.groups ?? [];
    if (groups.length === 0) return;
    if (selection.length > 0 || !allChip) return; // user already made a selection
    let sel: FilterSelection | null = null;
    if (activeData.type === 'client' && activeData.client_id != null) {
      sel = { type: 'client', id: activeData.client_id, label: activeData.client_name };
    } else if (activeData.type === 'project' && activeData.project_id != null) {
      sel = { type: 'project', id: activeData.project_id, label: `◆ ${activeData.client_name}`, company_name: activeData.company_name ?? undefined };
    }
    if (sel) {
      hasAutoSelected.current = true;
      setSelection([sel]);
      setAllChip(false);
    }
  }, [activeData, data, selection, allChip]);

  const groups = data?.groups ?? [];

  const allClientIds = useMemo(
    () => groups.flatMap(g => g.clients.map(c => c.id)),
    [groups]
  );

  const allProjectIds = useMemo(
    () => groups.flatMap(g => (g.projects ?? []).map(p => p.id)),
    [groups]
  );

  const effectiveIds = useMemo(
    () => getEffectiveIds(selection, groups),
    [selection, groups]
  );

  const effectiveProjectIds = useMemo(
    () => getEffectiveProjectIds(selection, groups),
    [selection, groups]
  );

  const handleSelectionChange = useCallback((sel: FilterSelection[], chip: boolean) => {
    setSelection(sel);
    setAllChip(chip);
    // Deactivate date mode when selecting a specific client OR reverting to All (⌘a)
    if (sel.length > 0 || chip) { dateModeActiveRef.current = false; setDateModeActive(false); }
  }, []);

  const handleModeSelect = useCallback((m: DateMode) => {
    lastDateModeRef.current = m;
    dateModeActiveRef.current = true;
    setDateMode(m);
    setDateDays(undefined);
    setFutureLabel('');
  }, []);

  const handleDateToggle = useCallback(() => {
    setDateModeActive(prev => {
      dateModeActiveRef.current = !prev;
      return !prev;
    });
  }, []);

  // Clients button: deactivate date mode and navigate to clients
  const handleClientsClick = useCallback(() => {
    dateModeActiveRef.current = false;
    setDateModeActive(false);
    setSelection([]);
    setAllChip(true);
    navigate('/coaching/clients');
  }, [navigate]);

  const ctx: CoachingFilterCtx = useMemo(() => ({
    groups,
    selection,
    allChip,
    onSelectionChange: handleSelectionChange,
    effectiveIds,
    effectiveProjectIds,
    allClientIds,
    allProjectIds,
    demo,
    toggleDemo,
    activeResult: activeData ?? null,
    dateModeActive,
    dateMode,
    dateDays,
    futureLabel,
    setDateModeActive,
    setDateMode,
    setDateDays,
    setFutureLabel,
    sortMode,
    setSortMode,
  }), [groups, selection, allChip, handleSelectionChange, effectiveIds, effectiveProjectIds, allClientIds, allProjectIds, demo, toggleDemo, dateModeActive, dateMode, dateDays, futureLabel, sortMode, setSortMode]);

  return (
    <CoachingFilterContext.Provider value={ctx}>
      <div className="coaching-module">
        <h1>Coaching</h1>
        <div className="tab-bar">
          <NavLink to="/coaching/clients" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
            Clients
          </NavLink>
          <NavLink to="/coaching/wordcloud" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
            Cloud
          </NavLink>
          <NavLink to="/coaching/setup" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
            Setup
          </NavLink>
          <NavLink to="/coaching/vinny" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
            Vinny
          </NavLink>
          <NavLink to="/coaching/operations" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
            Operations
          </NavLink>
          <button
            onClick={() => reimport.mutate()}
            disabled={reimport.isPending}
            className="coaching-demo-btn"
            style={{ color: 'var(--color-text-light)', marginLeft: 'auto' }}
          >
            {reimport.isPending ? '…' : 'Reimport'}
          </button>
        </div>
        {reimportToast && (
          <div className={`coaching-reimport-toast${reimportToast.ok ? '' : ' coaching-reimport-toast--error'}`}>
            {reimportToast.msg}
          </div>
        )}

        {/* Topbar: filter + date mode bar (clients page only) */}
        {isClientsPage && !isLoading && groups.length > 0 && (
          <>
            {activeData && <ActiveClientBar result={activeData} />}

            {/* Row 1: Sort toggle + date bar + hint (when row 2 hidden) */}
            {(() => {
              const row2Visible = inputPhase !== 'hidden' || selection.length > 0 || allChip;
              return (
                <>
                  <div className="coaching-topbar">
                    {/* SORT group */}
                    <div className="coaching-toolbar-group">
                      <div className="coaching-toolbar-group-header">
                        <span className="coaching-toolbar-group-label">sort</span>
                        <div className="coaching-toolbar-group-line" />
                      </div>
                      <button
                        className={`coaching-date-btn${sortMode === 'last' ? ' coaching-date-btn--active' : ''}`}
                        onClick={() => setSortMode(sortMode === 'default' ? 'last' : 'default')}
                        title="Toggle sort: Default (by company) or Last (by days since last session)"
                      >
                        {sortMode === 'default' ? 'Default' : 'Last'}
                      </button>
                    </div>

                    {/* FILTER group */}
                    <div className="coaching-toolbar-group">
                      <div className="coaching-toolbar-group-header">
                        <span className="coaching-toolbar-group-label">filter</span>
                        <div className="coaching-toolbar-group-line" />
                      </div>
                      <DateModeBar
                        active={dateModeActive}
                        dateMode={dateMode}
                        dateDays={dateDays}
                        todayLabelSuffix={dateDays != null ? undefined : futureLabel}
                        onToggle={handleDateToggle}
                        onModeSelect={handleModeSelect}
                        onClientsClick={handleClientsClick}
                      />
                    </div>

                    {!row2Visible && (
                      <span className="coaching-date-bar-hints" style={{ alignSelf: 'flex-end', marginBottom: 4 }}>⌘a = all · ; = today</span>
                    )}
                  </div>

                  {/* Row 2: always mounted so '/' listener stays active; display:none when hidden */}
                  <div className="coaching-topbar-row2" style={{ display: row2Visible ? undefined : 'none' }}>
                    <ClientFilter
                      groups={groups}
                      selection={selection}
                      allChip={allChip}
                      onSelectionChange={handleSelectionChange}
                      hideChips
                      autoFocus
                      activeResult={activeData}
                      onPhaseChange={setInputPhase}
                    />
                    {!dateModeActive && (allChip || selection.length > 0) && (
                      <div className="coaching-filter-chips coaching-topbar-chips">
                          {allChip && selection.length === 0 ? (
                            <span className="coaching-filter-chip coaching-filter-chip--all">
                              All
                              <button className="coaching-filter-chip-remove" onClick={() => handleSelectionChange([], false)}>×</button>
                            </span>
                          ) : (
                            selection.map((item, i) => (
                              <span
                                key={i}
                                className={`coaching-filter-chip${item.type === 'company' ? ' coaching-filter-chip--company' : ''}`}
                                style={item.type === 'project' ? { color: '#7B52AB', borderColor: '#7B52AB' } : undefined}
                              >
                                {item.label}
                                <button
                                  className="coaching-filter-chip-remove"
                                  onClick={() => {
                                    const next = selection.filter(s => !(s.type === item.type && s.id === item.id));
                                    handleSelectionChange(next, allChip && next.length === 0);
                                  }}
                                >×</button>
                              </span>
                            ))
                          )}
                          {selection.length > 0 && (
                            <button className="coaching-filter-clear" onClick={() => handleSelectionChange([], true)}>clear</button>
                          )}
                        </div>
                      )}
                    <span className="coaching-date-bar-hints">⌘a = all · ; = today</span>
                  </div>
                </>
              );
            })()}
          </>
        )}

        <Routes>
          <Route index element={<Navigate to="clients" replace />} />
          <Route path="clients" element={<ClientsPage />} />
          <Route path="clients/:id/synopsis" element={<CoachingClientSynopsisPage />} />
          <Route path="wordcloud" element={<WordCloudPage />} />
          <Route path="setup" element={<SetupPage />} />
          <Route path="vinny" element={<VinnyPage />} />
          <Route path="operations" element={<OperationsPage />} />
        </Routes>
      </div>
    </CoachingFilterContext.Provider>
  );
}
