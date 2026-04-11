import {
  useState,
  useRef,
  useEffect,
  useCallback,
  createContext,
  useContext,
  useMemo,
} from 'react';
import { NavLink, Routes, Route, Navigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import cloud from 'd3-cloud';
import { api, openExternal } from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CoachingClient {
  id: number;
  name: string;
  client_type: 'company' | 'individual';
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

interface WordSession {
  date: string;
  client_name: string;
  obsidian_name: string;
  path: string;
}

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

// ---------------------------------------------------------------------------
// Help Popover — reusable component for module keyboard shortcuts
// ---------------------------------------------------------------------------

export interface HelpShortcut {
  keys: string;
  description: string;
}

interface HelpPopoverProps {
  title: string;
  shortcuts: HelpShortcut[];
  isOpen: boolean;
  onClose: () => void;
}

export function HelpPopover({ title, shortcuts, isOpen, onClose }: HelpPopoverProps) {
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="help-popover-backdrop" onClick={onClose}>
      <div className="help-popover" onClick={e => e.stopPropagation()}>
        <div className="help-popover-header">
          <span className="help-popover-title">{title}</span>
          <button className="help-popover-close" onClick={onClose}>×</button>
        </div>
        <table className="help-popover-table">
          <tbody>
            {shortcuts.map((s, i) => (
              <tr key={i}>
                <td className="help-popover-keys"><kbd>{s.keys}</kbd></td>
                <td className="help-popover-desc">{s.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const COACHING_SHORTCUTS: HelpShortcut[] = [
  { keys: '⌘F', description: 'Focus client search box' },
  { keys: '⌘A', description: 'Show all clients (clear filter)' },
  { keys: '⌘.', description: 'Finish editing (collapse autocomplete)' },
  { keys: 'Escape', description: 'Clear search text' },
  { keys: '← →', description: 'Cycle through multiple matches' },
  { keys: 'Return', description: 'Add current match to selection' },
  { keys: '. prefix', description: 'Match company name only  (e.g. .cfs)' },
  { keys: ', prefix', description: 'Match person first or last name  (e.g. ,berg)' },
  { keys: "' prefix", description: "Match project name  (e.g. 'offsite)" },
  { keys: '- prefix', description: 'Remove from selection  (e.g. -cfs)' },
  { keys: '⌘/ or ⌘?', description: 'Show this help' },
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
// Client Filter component
// ---------------------------------------------------------------------------

interface ClientFilterProps {
  groups: CoachingGroup[];
  selection: FilterSelection[];
  allChip: boolean;
  onSelectionChange: (sel: FilterSelection[], allChip: boolean) => void;
}

function ClientFilter({ groups, selection, allChip, onSelectionChange }: ClientFilterProps) {
  const [text, setText] = useState('');
  const [matchIndex, setMatchIndex] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const { companies, clients, projectItems } = buildSearchIndex(groups);
  const removing = text.startsWith('-');
  const queryText = removing ? text.slice(1) : text;
  const matches = matchItems(queryText, companies, clients, projectItems);
  const currentMatch = matches[matchIndex] ?? null;
  const multipleMatches = matches.length > 1;

  useEffect(() => { setMatchIndex(0); }, [text]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey && e.key === 'f') { e.preventDefault(); inputRef.current?.focus(); return; }
      if (e.metaKey && (e.key === '/' || e.key === '?')) { e.preventDefault(); setHelpOpen(h => !h); return; }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const addToSelection = useCallback((item: FilterSelection) => {
    if (!selection.find(s => s.type === item.type && s.id === item.id)) {
      onSelectionChange([...selection, item], false);
    }
  }, [selection, onSelectionChange]);

  const removeFromSelection = useCallback((item: FilterSelection) => {
    const next = selection.filter(s => !(s.type === item.type && s.id === item.id));
    onSelectionChange(next, allChip && next.length === 0);
  }, [selection, allChip, onSelectionChange]);

  const clearToAll = useCallback(() => {
    onSelectionChange([], true);
    setText('');
  }, [onSelectionChange]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') { e.preventDefault(); setText(''); return; }
    if ((e.metaKey || e.ctrlKey) && e.key === 'a') { e.preventDefault(); clearToAll(); return; }
    if ((e.metaKey || e.ctrlKey) && e.key === '.') { e.preventDefault(); inputRef.current?.blur(); setText(''); return; }
    if (e.key === 'ArrowLeft') { e.preventDefault(); if (multipleMatches) setMatchIndex(i => (i - 1 + matches.length) % matches.length); return; }
    if (e.key === 'ArrowRight') { e.preventDefault(); if (multipleMatches) setMatchIndex(i => (i + 1) % matches.length); return; }
    if (e.key === 'Enter' && currentMatch) {
      e.preventDefault();
      if (removing) removeFromSelection(currentMatch);
      else addToSelection(currentMatch);
      setText('');
    }
  };

  const showingAll = selection.length === 0;

  return (
    <div className="coaching-filter">
      <HelpPopover title="Coaching keyboard shortcuts" shortcuts={COACHING_SHORTCUTS} isOpen={helpOpen} onClose={() => setHelpOpen(false)} />

      {(allChip || selection.length > 0) && (
        <div className="coaching-filter-chips">
          {allChip && showingAll ? (
            <span className="coaching-filter-chip coaching-filter-chip--all">
              All
              <button className="coaching-filter-chip-remove" onClick={() => onSelectionChange([], false)}>×</button>
            </span>
          ) : (
            selection.map((item, i) => (
              <span key={i} className={`coaching-filter-chip${item.type === 'company' ? ' coaching-filter-chip--company' : ''}`}
                style={item.type === 'project' ? { color: '#7B52AB', borderColor: '#7B52AB' } : undefined}>
                {item.label}
                <button className="coaching-filter-chip-remove" onClick={() => removeFromSelection(item)}>×</button>
              </span>
            ))
          )}
          {selection.length > 0 && (
            <button className="coaching-filter-clear" onClick={clearToAll}>clear</button>
          )}
        </div>
      )}

      {text && (
        <div className="coaching-filter-autocomplete">
          {currentMatch ? (
            <span style={{ color: multipleMatches ? 'var(--color-text-light)' : 'var(--color-text)' }}>
              {removing && <span style={{ opacity: 0.5 }}>−</span>}
              {currentMatch.type === 'project'
                ? <span style={{ color: '#7B52AB' }}>{currentMatch.label}</span>
                : currentMatch.type === 'company'
                  ? <span className="coaching-filter-ac-company">{currentMatch.label}</span>
                  : <span>{currentMatch.label}</span>}
              {multipleMatches && <span className="coaching-filter-ac-hint"> ← → to cycle</span>}
            </span>
          ) : (
            <span style={{ color: 'var(--color-text-light)', fontStyle: 'italic' }}>no match</span>
          )}
        </div>
      )}

      <input
        ref={inputRef}
        className="coaching-filter-input"
        type="text"
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="filter clients… (⌘F · ⌘? help)"
        spellCheck={false}
      />
    </div>
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
// Clients Page
// ---------------------------------------------------------------------------

function ClientRow({ client }: { client: CoachingClient }) {
  return (
    <div className="coaching-client-row">
      <span className="coaching-client-name">{client.name}</span>
      <span className="coaching-client-sessions">
        {client.display_session_number != null
          ? `${client.display_session_number} sessions`
          : <span className="coaching-client-meta-dim">—</span>}
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
      </span>
    </div>
  );
}

function ProjectRow({ project }: { project: CoachingProject }) {
  return (
    <div className="coaching-client-row" style={{ borderLeft: '2px solid #7B52AB', paddingLeft: 8 }}>
      <span className="coaching-client-name" style={{ color: '#7B52AB' }}>◆ {project.name}</span>
      <span className="coaching-client-sessions">
        {project.session_count > 0
          ? `${project.session_count} session${project.session_count !== 1 ? 's' : ''}`
          : <span className="coaching-client-meta-dim">—</span>}
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
  const { groups, selection, effectiveIds, effectiveProjectIds, demo } = useCoachingFilter();

  if (groups.length === 0) return <div className="coaching-loading">Loading…</div>;

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
              <ClientRow key={client.id} client={client} />
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
// Setup Page (placeholder)
// ---------------------------------------------------------------------------

function SetupPage() {
  return (
    <div className="coaching-placeholder">
      <p>Setup — coming soon. Will support adding new clients, creating Obsidian client pages, and provisioning Google Drive coaching document folders.</p>
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
// Coaching Module Root — owns filter state, provides context
// ---------------------------------------------------------------------------

export function CoachingPage() {
  const { data, isLoading } = useCoachingClients();
  const [selection, setSelection] = useState<FilterSelection[]>([]);
  const [allChip, setAllChip] = useState(true);
  const [demo, setDemo] = useState(false);
  const toggleDemo = useCallback(() => setDemo(d => !d), []);

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
  }, []);

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
  }), [groups, selection, allChip, handleSelectionChange, effectiveIds, effectiveProjectIds, allClientIds, allProjectIds, demo, toggleDemo]);

  return (
    <CoachingFilterContext.Provider value={ctx}>
      <div className="coaching-module">
        <nav className="coaching-sub-nav">
          <NavLink to="/coaching/clients" className={({ isActive }) => isActive ? 'coaching-sub-nav-link active' : 'coaching-sub-nav-link'}>
            Clients
          </NavLink>
          <NavLink to="/coaching/wordcloud" className={({ isActive }) => isActive ? 'coaching-sub-nav-link active' : 'coaching-sub-nav-link'}>
            Cloud
          </NavLink>
          <NavLink to="/coaching/setup" className={({ isActive }) => isActive ? 'coaching-sub-nav-link active' : 'coaching-sub-nav-link'}>
            Setup
          </NavLink>
          <NavLink to="/coaching/vinny" className={({ isActive }) => isActive ? 'coaching-sub-nav-link active' : 'coaching-sub-nav-link'}>
            Vinny
          </NavLink>
          <button
            onClick={toggleDemo}
            className="coaching-demo-btn"
            style={{ background: demo ? 'var(--color-accent, #6b7280)' : 'transparent', color: demo ? '#fff' : 'var(--color-text-light)' }}
          >
            {demo ? 'Demo On' : 'Demo'}
          </button>
        </nav>

        {/* Shared client filter — visible on all Coaching pages */}
        {!isLoading && groups.length > 0 && (
          <ClientFilter
            groups={groups}
            selection={selection}
            allChip={allChip}
            onSelectionChange={handleSelectionChange}
          />
        )}

        <Routes>
          <Route index element={<Navigate to="clients" replace />} />
          <Route path="clients" element={<ClientsPage />} />
          <Route path="wordcloud" element={<WordCloudPage />} />
          <Route path="setup" element={<SetupPage />} />
          <Route path="vinny" element={<VinnyPage />} />
        </Routes>
      </div>
    </CoachingFilterContext.Provider>
  );
}
