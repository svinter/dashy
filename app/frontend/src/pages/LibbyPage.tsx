import { useState, useEffect, useRef, useMemo, useCallback, Fragment } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Routes, Route, Navigate, NavLink } from 'react-router-dom';
import { useLibbyContext } from '../contexts/LibbyContext';
import type { LibbyFilterSelection, LibbyGroup } from '../contexts/LibbyContext';
import { ClientFilterBar } from '../components/shared/ClientFilterBar';
import type { HelpShortcut } from '../components/shared/ClientFilterBar';
import { LibbyTopicsPage } from './LibbyTopicsPage';
import { LibbyTypesPage } from './LibbyTypesPage';
import { LibbyNewPage } from './LibbyNewPage';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LibraryTopic {
  id: number;
  code: string;
  name: string;
}

interface LibraryEntry {
  id: number;
  name: string;
  type_code: string;
  priority: 'high' | 'medium' | 'low';
  frequency: number;
  url: string | null;
  amazon_url: string | null;
  amazon_short_url: string | null;
  webpage_url: string | null;
  gdoc_id: string | null;
  obsidian_link: string | null;
  author?: string | null;
  author_match?: boolean;
  description: string | null;
  categories: string[];
  topics: LibraryTopic[];
  last_shared_at: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPE_LABELS: Record<string, string> = {
  b: 'book',
  a: 'article',
  p: 'podcast',
  t: 'tool',
  w: 'webpage',
};

const ALL_TYPE_LABELS: Record<string, string> = {
  b: 'book',      a: 'article',
  e: 'essay',     p: 'podcast',
  v: 'video',     m: 'movie',
  t: 'tool',      w: 'webpage',
  s: 'worksheet', z: 'assessment',
  n: 'note',      d: 'document',
  f: 'framework', c: 'course',
  r: 'research',  q: 'quote',
};

// Pairs for retype grid (original layout, not alphabetized)
const TYPE_GRID_ROWS: [string, string][] = [
  ['b', 'a'], ['e', 'p'], ['v', 'm'], ['t', 'w'],
  ['s', 'z'], ['n', 'd'], ['f', 'c'], ['r', 'q'],
];

// Alphabetical by type name — left column (first 8), right column (last 8)
// article, assessment, book, course, document, essay, framework, movie
const TYPE_GRID_LEFT  = ['a', 'z', 'b', 'c', 'd', 'e', 'f', 'm'];
// note, podcast, quote, research, tool, video, webpage, worksheet
const TYPE_GRID_RIGHT = ['n', 'p', 'q', 'r', 't', 'v', 'w', 's'];

const RESULT_LABELS = 'abcdefghijklmnopqrstuvwxyz';

type UiState = 'SEARCH' | 'PICK' | 'ACTION' | 'LABEL' | 'RETYPE';

// ---------------------------------------------------------------------------
// Help popup content
// ---------------------------------------------------------------------------

const HELP_TYPES = [
  ['b', 'Book'],       ['a', 'Article'],   ['e', 'Essay'],
  ['p', 'Podcast'],    ['v', 'Video'],      ['m', 'Movie'],
  ['t', 'Tool'],       ['w', 'Webpage'],    ['s', 'Worksheet'],
  ['z', 'Assessment'], ['n', 'Note'],       ['d', 'Document'],
  ['f', 'Framework'],  ['c', 'Course'],     ['r', 'Research'],
  ['q', 'Quote'],
];

function LibbyHelpPopup({ onClose }: { onClose: () => void }) {
  return (
    <div className="libby-help-backdrop" onClick={onClose}>
      <div className="libby-help-popup" onClick={e => e.stopPropagation()}>
        <div className="libby-help-header">
          <span className="libby-help-title">Libby Help</span>
          <span className="libby-help-shortcut">⌘?</span>
        </div>
        <div className="libby-help-body">
          {/* Left: Types */}
          <div className="libby-help-col">
            <div className="libby-help-col-title">Types</div>
            <table className="libby-help-type-table">
              <tbody>
                {HELP_TYPES.map(([code, name]) => (
                  <tr key={code}>
                    <td className="libby-help-type-code">{code}</td>
                    <td className="libby-help-type-name">{name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Right: Syntax + Actions */}
          <div className="libby-help-col">
            <div className="libby-help-col-title">Search Syntax</div>
            <div className="libby-help-syntax">[type] [.topic] [name]</div>
            <div className="libby-help-examples">
              <div className="libby-help-ex-label">Examples:</div>
              <code>b .le atomic</code>
              <code>.co habits</code>
              <code>b clear</code>
            </div>

            <div className="libby-help-col-title" style={{ marginTop: '16px' }}>Selection</div>
            <table className="libby-help-keys">
              <tbody>
                <tr><td className="libby-help-key">Return</td><td>select (1 result) or pick mode</td></tr>
                <tr><td className="libby-help-key">a–z</td><td>pick from results</td></tr>
                <tr><td className="libby-help-key">b</td><td>back to previous state</td></tr>
                <tr><td className="libby-help-key">Esc</td><td>return to search</td></tr>
              </tbody>
            </table>

            <div className="libby-help-col-title" style={{ marginTop: '16px' }}>Global</div>
            <table className="libby-help-keys">
              <tbody>
                <tr><td className="libby-help-key">⌥G</td><td>Go to… (module navigation)</td></tr>
                <tr><td className="libby-help-key">⌘?</td><td>this help</td></tr>
              </tbody>
            </table>

            <div className="libby-help-col-title" style={{ marginTop: '16px' }}>Actions</div>
            <table className="libby-help-keys">
              <tbody>
                <tr><td className="libby-help-key">c</td><td>copy URL</td></tr>
                <tr><td className="libby-help-key">p</td><td>print (copy title + link)</td></tr>
                <tr><td className="libby-help-key">d</td><td>doc copy to client folder</td></tr>
                <tr><td className="libby-help-key">r</td><td>record share with client</td></tr>
                <tr><td className="libby-help-key">a</td><td>apply last label</td></tr>
                <tr><td className="libby-help-key">l</td><td>label (add/remove topic)</td></tr>
                <tr><td className="libby-help-key">o</td><td>open URL in browser</td></tr>
                <tr><td className="libby-help-key">m</td><td>make webpage</td></tr>
                <tr><td className="libby-help-key">v</td><td>vault (open in Obsidian)</td></tr>
                <tr><td className="libby-help-key">y</td><td>retype (change type)</td></tr>
                <tr><td className="libby-help-key">b</td><td>back to pick</td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">s</td><td className="libby-help-soon">synopsis <span>(coming soon)</span></td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">f</td><td className="libby-help-soon">full copy <span>(coming soon)</span></td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">x</td><td className="libby-help-soon">find related <span>(future)</span></td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Priority dots
// ---------------------------------------------------------------------------

function PriorityDots({ priority }: { priority: string }) {
  return (
    <span className="libby-priority-dots" title={priority}>
      <span className={priority === 'high' || priority === 'medium' || priority === 'low' ? 'libby-dot libby-dot--on' : 'libby-dot libby-dot--off'}>●</span>
      <span className={priority === 'high' || priority === 'medium' ? 'libby-dot libby-dot--on' : 'libby-dot libby-dot--off'}>●</span>
      <span className={priority === 'high' ? 'libby-dot libby-dot--on' : 'libby-dot libby-dot--off'}>●</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Libby client filter — keyboard shortcuts
// ---------------------------------------------------------------------------

const LIBBY_CLIENT_SHORTCUTS: HelpShortcut[] = [
  { keys: '⌘F',       description: 'Focus client search' },
  { keys: '⌘A',       description: 'Clear selection' },
  { keys: '⌘.',       description: 'Collapse autocomplete' },
  { keys: 'Escape',   description: 'Clear search text' },
  { keys: '← →',      description: 'Cycle multiple matches' },
  { keys: 'Return',   description: 'Select current match' },
  { keys: '. prefix', description: 'Match company name (e.g. .cfs)' },
  { keys: ', prefix', description: 'Match person first/last name (e.g. ,berg)' },
  { keys: '- prefix', description: 'Deselect (e.g. -berg)' },
  { keys: '⌘/ or ⌘?', description: 'Show this help' },
];

// ---------------------------------------------------------------------------
// Search index helpers
// ---------------------------------------------------------------------------

function buildLibbySearchIndex(groups: LibbyGroup[]) {
  const companies: { label: string; id: number | null }[] = [];
  const clients: { label: string; id: number; company_name: string }[] = [];

  for (const g of groups) {
    companies.push({ label: g.company_name, id: g.company_id });
    for (const c of g.clients) {
      clients.push({ label: c.name, id: c.id, company_name: g.company_name });
    }
  }
  companies.sort((a, b) => a.label.localeCompare(b.label));
  clients.sort((a, b) => a.label.localeCompare(b.label));
  return { companies, clients };
}

function matchLibbyItems(
  text: string,
  companies: { label: string; id: number | null }[],
  clients: { label: string; id: number; company_name: string }[],
): LibbyFilterSelection[] {
  if (!text) return [];

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
      .map(c => ({ type: 'client' as const, id: c.id, label: c.label, company_name: c.company_name }));
  }

  // Default: company prefix OR any word in person name
  const q = text.toLowerCase();
  const matchedCompanies: LibbyFilterSelection[] = companies
    .filter(c => c.label.toLowerCase().startsWith(q))
    .map(c => ({ type: 'company' as const, id: c.id, label: c.label }));
  const matchedClients: LibbyFilterSelection[] = clients
    .filter(c => c.label.toLowerCase().split(' ').some(p => p.startsWith(q)))
    .map(c => ({ type: 'client' as const, id: c.id, label: c.label, company_name: c.company_name }));
  return [...matchedCompanies, ...matchedClients];
}

// ---------------------------------------------------------------------------
// LibbyClientFilter — thin wrapper around shared ClientFilterBar
// ---------------------------------------------------------------------------

function LibbyClientFilter() {
  const { groups, selection, allChip, onSelectionChange } = useLibbyContext();
  const { companies, clients } = useMemo(() => buildLibbySearchIndex(groups), [groups]);
  const matchFn = useCallback(
    (text: string) => matchLibbyItems(text, companies, clients),
    [companies, clients],
  );

  return (
    <ClientFilterBar<LibbyFilterSelection>
      selection={selection}
      allChip={allChip}
      onSelectionChange={onSelectionChange}
      matchFn={matchFn}
      placeholder="client… (⌘F · ⌘? help)"
      helpTitle="Libby client shortcuts"
      shortcuts={LIBBY_CLIENT_SHORTCUTS}
      chipClassName={item =>
        `coaching-filter-chip${item.type === 'company' ? ' coaching-filter-chip--company' : ''}`
      }
      autocompleteLabel={item =>
        item.type === 'company'
          ? <span className="coaching-filter-ac-company">{item.label}</span>
          : <span>{item.label}</span>
      }
      style={{ marginBottom: '10px', maxWidth: '420px' }}
    />
  );
}

// ---------------------------------------------------------------------------
// Libby Layout — sub-nav + help popup (shared across all Libby pages)
// ---------------------------------------------------------------------------

function LibbyLayout({ children }: { children: React.ReactNode }) {
  const { isHelpOpen, setHelpOpen, queueCount } = useLibbyContext();

  // ⌘? opens help; Escape closes it (without interfering with Catalog machine)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey && e.shiftKey && e.key === '/') {
        e.preventDefault();
        setHelpOpen(true);
        return;
      }
      if (isHelpOpen && e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        setHelpOpen(false);
      }
    };
    window.addEventListener('keydown', handler, true); // capture phase so it runs before Catalog
    return () => window.removeEventListener('keydown', handler, true);
  }, [isHelpOpen, setHelpOpen]);

  return (
    <div className="libby-layout">
      <h1>Library</h1>
      <div className="tab-bar">
        <NavLink to="/libby/catalog" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
          Catalog
        </NavLink>
        <NavLink to="/libby/topics" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
          Topics
        </NavLink>
        <NavLink to="/libby/types" className={({ isActive }) => `tab${isActive ? ' active' : ''}`}>
          Types
        </NavLink>
        <NavLink to="/libby/new" className={({ isActive }) => `tab${isActive ? ' active' : ''}${queueCount > 0 ? ' libby-sub-nav-link--badge' : ''}`}>
          {queueCount > 0 ? `New (${queueCount})` : 'New'}
        </NavLink>
      </div>
      {children}
      {isHelpOpen && <LibbyHelpPopup onClose={() => setHelpOpen(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Topic prefix helpers
// ---------------------------------------------------------------------------

function normalizeQuery(query: string): string {
  // Mirror backend: insert space before '.' when preceded by a non-space char
  // so "b.leader" → "b .leader" before tokenizing.
  return query.replace(/(\S)\./g, '$1 .');
}

function parseTopicPrefix(query: string): string | null {
  const normalized = normalizeQuery(query);
  for (const token of normalized.trim().split(/\s+/)) {
    if (token.startsWith('.') && token.length > 1) {
      return token.slice(1).toLowerCase();
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Catalog Page (was FindPage)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// ManifestOverlay
// ---------------------------------------------------------------------------

interface ManifestDoc { name: string; url: string | null }
interface ManifestOther { name: string; url: string | null; date: string | null }
interface ManifestData {
  manifest_url: string;
  documents: ManifestDoc[];
  others: ManifestOther[];
}

function ManifestOverlay({
  clientId,
  clientName,
  onClose,
  flashName,
}: {
  clientId: number;
  clientName: string;
  onClose: () => void;
  flashName: string | null;
}) {
  const [data, setData] = useState<ManifestData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [docsOpen, setDocsOpen] = useState(true);
  const [othersOpen, setOthersOpen] = useState(true);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [flashedName, setFlashedName] = useState<string | null>(null);

  const fetchManifest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`/api/libby/manifest/${clientId}`);
      if (!resp.ok) throw new Error(`${resp.status}`);
      setData(await resp.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load manifest');
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { fetchManifest(); }, [fetchManifest]);

  // Flash newly added entry in Others
  useEffect(() => {
    if (!flashName || loading) return;
    setFlashedName(flashName);
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => setFlashedName(null), 2000);
    return () => { if (flashTimerRef.current) clearTimeout(flashTimerRef.current); };
  }, [flashName, loading]);

  // Escape key closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose(); }
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  }, [onClose]);

  return (
    <>
      {/* Backdrop */}
      <div className="libby-manifest-backdrop" onClick={onClose} />
      {/* Panel */}
      <div className="libby-manifest-panel">
        <div className="libby-manifest-header">
          <span className="libby-manifest-title">{clientName}</span>
          <div className="libby-manifest-header-actions">
            {data && (
              <a
                href={data.manifest_url}
                target="_blank"
                rel="noreferrer"
                className="libby-manifest-open-link"
                title="Open full manifest"
              >
                manifest ↗
              </a>
            )}
            <button className="libby-manifest-close" onClick={onClose} title="Close (Esc)">×</button>
          </div>
        </div>

        <div className="libby-manifest-body">
          {loading && <div className="libby-manifest-loading">Loading…</div>}
          {error && <div className="libby-manifest-error">Error: {error}</div>}
          {data && (
            <>
              {/* Documents section */}
              <div className="libby-manifest-section">
                <button
                  className="libby-manifest-section-toggle"
                  onClick={() => setDocsOpen(o => !o)}
                >
                  <span className="libby-manifest-section-caret">{docsOpen ? '▾' : '▸'}</span>
                  Documents
                </button>
                {docsOpen && (
                  <ul className="libby-manifest-list">
                    {data.documents.length === 0 && (
                      <li className="libby-manifest-empty">—</li>
                    )}
                    {data.documents.map((doc, i) => (
                      <li key={i} className="libby-manifest-item">
                        {doc.url
                          ? <a href={doc.url} target="_blank" rel="noreferrer">{doc.name}</a>
                          : <span>{doc.name}</span>
                        }
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Others section */}
              <div className="libby-manifest-section">
                <button
                  className="libby-manifest-section-toggle"
                  onClick={() => setOthersOpen(o => !o)}
                >
                  <span className="libby-manifest-section-caret">{othersOpen ? '▾' : '▸'}</span>
                  Others
                </button>
                {othersOpen && (
                  <ul className="libby-manifest-list">
                    {data.others.length === 0 && (
                      <li className="libby-manifest-empty">—</li>
                    )}
                    {data.others.map((item, i) => (
                      <li
                        key={i}
                        className={`libby-manifest-item${flashedName && item.name.startsWith(flashedName.substring(0, 20)) ? ' libby-manifest-item--flash' : ''}`}
                      >
                        {item.url
                          ? <a href={item.url} target="_blank" rel="noreferrer">{item.name}</a>
                          : <span>{item.name}</span>
                        }
                        {item.date && <span className="libby-manifest-item-date">{item.date}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// QuickAddModal — create non-book entries without leaving Catalog
// ---------------------------------------------------------------------------

// Non-book types sorted alphabetically by name
const NONBOOK_TYPES_ALPHA = [
  { code: 'a', name: 'article' },
  { code: 'z', name: 'assessment' },
  { code: 'c', name: 'course' },
  { code: 'd', name: 'document' },
  { code: 'e', name: 'essay' },
  { code: 'f', name: 'framework' },
  { code: 'm', name: 'movie' },
  { code: 'n', name: 'note' },
  { code: 'p', name: 'podcast' },
  { code: 'q', name: 'quote' },
  { code: 'r', name: 'research' },
  { code: 't', name: 'tool' },
  { code: 'v', name: 'video' },
  { code: 'w', name: 'webpage' },
  { code: 's', name: 'worksheet' },
];

// Types where we fetch og: metadata from a URL
const URL_FETCH_TYPES = new Set(['a', 'p', 'v', 'w']);
// Types where content is text (name derived from it)
const TEXT_TYPES = new Set(['q', 'n']);

interface MovieCandidate {
  title: string;
  year: string | null;
  poster: string | null;
  imdb_id: string | null;
}

function QuickAddModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (name: string, typeCode: string) => void;
}) {
  const backdropRef = useRef<HTMLDivElement>(null);

  const [step, setStep] = useState<'TYPE' | 'FILL'>('TYPE');
  const [typeCode, setTypeCode] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [author, setAuthor] = useState('');
  const [text, setText] = useState('');
  const [priority, setPriority] = useState<'high' | 'medium' | 'low'>('medium');

  const [fetchLoading, setFetchLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [fetchedDescription, setFetchedDescription] = useState<string | null>(null);

  const [movieQuery, setMovieQuery] = useState('');
  const [movieCandidates, setMovieCandidates] = useState<MovieCandidate[]>([]);
  const [movieLoading, setMovieLoading] = useState(false);
  const [movieSelectedIdx, setMovieSelectedIdx] = useState<number | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Escape closes modal; in TYPE step, letter keys select a type
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose(); return; }
      if (step === 'TYPE' && !e.metaKey && !e.altKey && !e.ctrlKey) {
        const match = NONBOOK_TYPES_ALPHA.find(t => t.code === e.key.toLowerCase());
        if (match) { e.preventDefault(); e.stopPropagation(); selectType(match.code); }
      }
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose, step]);

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === backdropRef.current) onClose();
  };

  const selectType = (code: string) => {
    setTypeCode(code);
    setStep('FILL');
    setName(''); setUrl(''); setAuthor(''); setText('');
    setFetchError(null); setFetchedDescription(null);
    setMovieQuery(''); setMovieCandidates([]); setMovieSelectedIdx(null);
    setSaveError(null);
  };

  const handleFetchMetadata = async () => {
    if (!url.trim()) return;
    setFetchLoading(true);
    setFetchError(null);
    setFetchedDescription(null);
    try {
      const resp = await fetch('/api/libby/fetch-metadata', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.title && !name) setName(data.title);
        if (data.author && !author) setAuthor(data.author);
        if (data.description) setFetchedDescription(data.description.slice(0, 200));
      } else {
        const err = await resp.json().catch(() => ({}));
        setFetchError(err.detail ?? 'Could not fetch metadata');
      }
    } catch {
      setFetchError('Network error');
    } finally {
      setFetchLoading(false);
    }
  };

  const handleMovieLookup = async () => {
    if (!movieQuery.trim()) return;
    setMovieLoading(true);
    setMovieCandidates([]);
    setMovieSelectedIdx(null);
    try {
      const resp = await fetch(`/api/libby/movies/lookup?title=${encodeURIComponent(movieQuery.trim())}`);
      if (resp.ok) {
        const data = await resp.json();
        setMovieCandidates(data.candidates ?? []);
      }
    } catch { /* ignore */ }
    finally { setMovieLoading(false); }
  };

  const handleSave = async () => {
    if (!typeCode) return;
    let finalName = name.trim();
    let finalUrl = url.trim() || undefined;
    let finalAttribution: string | undefined;

    if (TEXT_TYPES.has(typeCode) && !finalName) {
      finalName = text.trim().slice(0, 80);
    }
    if (typeCode === 'm' && movieSelectedIdx !== null) {
      const m = movieCandidates[movieSelectedIdx];
      if (!finalName) finalName = m.title ?? '';
      if (!finalUrl && m.imdb_id) finalUrl = `https://www.imdb.com/title/${m.imdb_id}/`;
    }
    if (typeCode === 'q' && author.trim()) {
      finalAttribution = author.trim();
    }

    if (!finalName) { setSaveError('Name is required'); return; }

    const body: Record<string, unknown> = {
      name: finalName,
      type_code: typeCode,
      priority,
      url: finalUrl ?? null,
      comments: null,
      author: author.trim() || null,
      item_text: TEXT_TYPES.has(typeCode) ? (text.trim() || null) : null,
      attribution: finalAttribution ?? null,
    };

    setSaving(true);
    setSaveError(null);
    try {
      const resp = await fetch('/api/libby/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (resp.ok) {
        onCreated(finalName, typeCode);
        onClose();
      } else {
        const err = await resp.json().catch(() => ({}));
        setSaveError(err.detail ?? 'Save failed');
      }
    } catch {
      setSaveError('Network error');
    } finally {
      setSaving(false);
    }
  };

  const typeName = typeCode ? (ALL_TYPE_LABELS[typeCode] ?? typeCode) : '';
  const isUrlType = typeCode ? URL_FETCH_TYPES.has(typeCode) : false;
  const isTextType = typeCode ? TEXT_TYPES.has(typeCode) : false;
  const isMovie = typeCode === 'm';

  const canSave = (() => {
    if (!typeCode) return false;
    if (isMovie) return movieSelectedIdx !== null || name.trim().length > 0;
    if (isTextType) return text.trim().length > 0 || name.trim().length > 0;
    return name.trim().length > 0;
  })();

  const leftCol = NONBOOK_TYPES_ALPHA.slice(0, 8);
  const rightCol = NONBOOK_TYPES_ALPHA.slice(8);

  return (
    <div className="libby-quickadd-backdrop" ref={backdropRef} onClick={handleBackdropClick}>
      <div className="libby-quickadd-modal" role="dialog" aria-modal="true">
        <div className="libby-quickadd-header">
          <span className="libby-quickadd-title">
            {step === 'TYPE' ? 'quick add' : `add ${typeName}`}
          </span>
          <button className="libby-quickadd-close" onClick={onClose} title="Close (Esc)">×</button>
        </div>

        {step === 'TYPE' && (
          <div className="libby-quickadd-body">
            <div className="libby-quickadd-type-hint">pick a type (or press its letter)</div>
            <div className="libby-quickadd-type-grid">
              {leftCol.map((t, i) => {
                const r = rightCol[i];
                return (
                  <Fragment key={t.code}>
                    <button className="libby-quickadd-type-btn" onClick={() => selectType(t.code)}>
                      <span className="libby-quickadd-type-key">{t.code}</span>
                      <span className="libby-quickadd-type-name">{t.name}</span>
                    </button>
                    {r ? (
                      <button className="libby-quickadd-type-btn" onClick={() => selectType(r.code)}>
                        <span className="libby-quickadd-type-key">{r.code}</span>
                        <span className="libby-quickadd-type-name">{r.name}</span>
                      </button>
                    ) : <div />}
                  </Fragment>
                );
              })}
            </div>
          </div>
        )}

        {step === 'FILL' && typeCode && (
          <div className="libby-quickadd-body">
            <button className="libby-quickadd-back" onClick={() => setStep('TYPE')}>← back</button>

            {/* URL-based types */}
            {isUrlType && (
              <div className="libby-quickadd-field">
                <label className="libby-quickadd-label">URL</label>
                <div className="libby-quickadd-url-row">
                  <input
                    className="libby-quickadd-input"
                    type="url"
                    placeholder="https://…"
                    value={url}
                    onChange={e => setUrl(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleFetchMetadata(); } }}
                    autoFocus
                  />
                  <button
                    className="libby-quickadd-fetch-btn"
                    onClick={handleFetchMetadata}
                    disabled={fetchLoading || !url.trim()}
                  >
                    {fetchLoading ? '…' : 'fetch'}
                  </button>
                </div>
                {fetchError && <div className="libby-quickadd-error">{fetchError}</div>}
                {fetchedDescription && (
                  <div className="libby-quickadd-fetched-desc">{fetchedDescription}</div>
                )}
              </div>
            )}

            {/* Movie search */}
            {isMovie && (
              <div className="libby-quickadd-field">
                <label className="libby-quickadd-label">Movie title</label>
                <div className="libby-quickadd-url-row">
                  <input
                    className="libby-quickadd-input"
                    type="text"
                    placeholder="search…"
                    value={movieQuery}
                    onChange={e => setMovieQuery(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleMovieLookup(); } }}
                    autoFocus
                  />
                  <button
                    className="libby-quickadd-fetch-btn"
                    onClick={handleMovieLookup}
                    disabled={movieLoading || !movieQuery.trim()}
                  >
                    {movieLoading ? '…' : 'search'}
                  </button>
                </div>
                {movieCandidates.length > 0 && (
                  <ul className="libby-quickadd-movie-list">
                    {movieCandidates.map((m, i) => (
                      <li
                        key={m.imdb_id ?? i}
                        className={`libby-quickadd-movie-item${movieSelectedIdx === i ? ' libby-quickadd-movie-item--selected' : ''}`}
                        onClick={() => { setMovieSelectedIdx(i); setName(m.title ?? ''); }}
                      >
                        {m.poster && <img className="libby-quickadd-movie-poster" src={m.poster} alt="" />}
                        <span className="libby-quickadd-movie-meta">
                          <span className="libby-quickadd-movie-title">{m.title}</span>
                          {m.year && <span className="libby-quickadd-movie-year">{m.year}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* Text types (quote, note) */}
            {isTextType && (
              <div className="libby-quickadd-field">
                <label className="libby-quickadd-label">{typeCode === 'q' ? 'quote' : 'note'}</label>
                <textarea
                  className="libby-quickadd-textarea"
                  placeholder={typeCode === 'q' ? 'Enter the quote…' : 'Enter note text…'}
                  value={text}
                  onChange={e => setText(e.target.value)}
                  rows={4}
                  autoFocus
                />
              </div>
            )}

            {/* Name field */}
            {!isTextType ? (
              <div className="libby-quickadd-field">
                <label className="libby-quickadd-label">name</label>
                <input
                  className="libby-quickadd-input"
                  type="text"
                  placeholder="Title or name…"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  autoFocus={!isUrlType && !isMovie}
                />
              </div>
            ) : (
              <div className="libby-quickadd-field">
                <label className="libby-quickadd-label">name <span className="libby-quickadd-optional">(optional — defaults to first 80 chars)</span></label>
                <input
                  className="libby-quickadd-input"
                  type="text"
                  placeholder="Override name…"
                  value={name}
                  onChange={e => setName(e.target.value)}
                />
              </div>
            )}

            {/* Author — for URL and quote types */}
            {(isUrlType || typeCode === 'q') && (
              <div className="libby-quickadd-field">
                <label className="libby-quickadd-label">
                  {typeCode === 'q' ? 'attribution' : 'author'}
                  {' '}<span className="libby-quickadd-optional">(optional)</span>
                </label>
                <input
                  className="libby-quickadd-input"
                  type="text"
                  placeholder={typeCode === 'q' ? 'Source or author…' : 'Author name…'}
                  value={author}
                  onChange={e => setAuthor(e.target.value)}
                />
              </div>
            )}

            {/* Priority */}
            <div className="libby-quickadd-field">
              <label className="libby-quickadd-label">priority</label>
              <div className="libby-quickadd-priority-row">
                {(['high', 'medium', 'low'] as const).map(p => (
                  <button
                    key={p}
                    className={`libby-quickadd-pri-btn${priority === p ? ' libby-quickadd-pri-btn--active' : ''}`}
                    onClick={() => setPriority(p)}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            {saveError && <div className="libby-quickadd-error">{saveError}</div>}

            <div className="libby-quickadd-footer">
              <button
                className="libby-quickadd-save-btn"
                onClick={handleSave}
                disabled={!canSave || saving}
              >
                {saving ? 'saving…' : 'save'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// CatalogPage
// ---------------------------------------------------------------------------

function CatalogPage() {
  const { activeClientId, activeClientName, activeCompanyId, activeClientManifestUrl, isHelpOpen, onSelectionChange } = useLibbyContext();
  const { data: typeCounts } = useQuery<Record<string, number>>({
    queryKey: ['libby-type-counts'],
    queryFn: () => fetch('/api/libby/type-counts').then(r => r.json()),
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  const searchInputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const labelInputRef = useRef<HTMLInputElement>(null);
  const repeatRef = useRef<{ action: 'add' | 'remove'; topic: LibraryTopic } | null>(null);

  const [query, setQuery] = useState('');
  const [uiState, setUiState] = useState<UiState>('SEARCH');
  const [results, setResults] = useState<LibraryEntry[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [selected, setSelected] = useState<LibraryEntry | null>(null);
  const [selectedWebpageUrl, setSelectedWebpageUrl] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [toastVariant, setToastVariant] = useState<'default' | 'warning'>('default');
  const [loading, setLoading] = useState(false);
  const [allTopics, setAllTopics] = useState<LibraryTopic[]>([]);

  // Label popup state
  const [labelQuery, setLabelQuery] = useState('');
  const [labelHighlight, setLabelHighlight] = useState(0);
  const [labelMsg, setLabelMsg] = useState<string | null>(null);

  // Repeat indicator (display only — actual state in repeatRef)
  const [repeatDisplay, setRepeatDisplay] = useState<string | null>(null);

  // Retype state
  const [retypeSelected, setRetypeSelected] = useState<string | null>(null);

  // Per-entry session copy / record tracking (reset when selected entry changes)
  const [sessionCopied, setSessionCopied] = useState(false);
  const [sessionRecorded, setSessionRecorded] = useState(false);

  // Manifest overlay
  const [manifestOpen, setManifestOpen] = useState(false);
  const [manifestFlashName, setManifestFlashName] = useState<string | null>(null);

  // Quick-add modal
  const [quickAddOpen, setQuickAddOpen] = useState(false);

  // Reset session copy/record state when a new entry is selected
  useEffect(() => {
    setSessionCopied(false);
    setSessionRecorded(false);
  }, [selected?.id]);

  // Focus management: LABEL → label input; PICK/ACTION/RETYPE → container; SEARCH → input
  useEffect(() => {
    if (uiState === 'LABEL') {
      labelInputRef.current?.focus();
    } else if (uiState === 'PICK' || uiState === 'ACTION' || uiState === 'RETYPE') {
      containerRef.current?.focus();
    } else {
      searchInputRef.current?.focus();
    }
  }, [uiState]);

  // Auto-focus search box when a client is selected
  useEffect(() => {
    if (activeClientId !== null) {
      searchInputRef.current?.focus();
    }
  }, [activeClientId]);

  // Load all topics once on mount
  useEffect(() => {
    fetch('/api/libby/topics')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.topics) setAllTopics(d.topics); })
      .catch(() => {});
  }, []);

  // --- Toast ---
  const showToast = (msg: string, variant: 'default' | 'warning' = 'default') => {
    setToastMsg(msg);
    setToastVariant(variant);
    setTimeout(() => setToastMsg(null), 2500);
  };

  // --- Search ---
  const runSearch = async (q: string, clientId: number | null) => {
    if (!q.trim()) { setResults([]); setSearchTotal(0); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams({ q: normalizeQuery(q) });
      if (clientId != null) params.set('client_id', String(clientId));
      const resp = await fetch(`/api/libby/search?${params}`);
      if (resp.ok) {
        const data = await resp.json();
        setResults(data.results);
        setSearchTotal(data.total);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  // Re-run search when active client changes (updates shared indicators)
  useEffect(() => {
    if (query.trim() && uiState === 'SEARCH') {
      runSearch(query, activeClientId);
    }
  }, [activeClientId]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Input change ---
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    runSearch(val, activeClientId);
  };

  // --- Search input keydown (SEARCH state only) ---
  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      setQuery('');
      setResults([]);
      setSearchTotal(0);
      return;
    }
    if (e.metaKey && e.key === 'a') {
      e.preventDefault();
      onSelectionChange([], true);
      return;
    }
    // + or = opens quick-add modal
    if ((e.key === '+' || e.key === '=') && !e.metaKey && !e.altKey) {
      e.preventDefault();
      setQuickAddOpen(true);
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (results.length === 0) return;
      if (results.length === 1) {
        setSelected(results[0]);
        setSelectedWebpageUrl(results[0].webpage_url ?? null);
        setUiState('ACTION');
      } else {
        setUiState('PICK');
      }
    }
  };

  // --- Copy action ---
  const handleCopy = async () => {
    if (!selected) return;
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/copy`, { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.url) { await navigator.clipboard.writeText(data.url); setStatusMsg('URL copied'); setSessionCopied(true); }
        else setStatusMsg('No URL available');
      } else setStatusMsg('Copy failed');
    } catch { setStatusMsg('Copy failed'); }
    setTimeout(() => setStatusMsg(null), 2500);
  };

  // --- Make action ---
  const handleMake = async () => {
    if (!selected) return;
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/make`, { method: 'POST' });
      const data = await resp.json();
      if (data.status === 'exists') {
        await navigator.clipboard.writeText(data.url).catch(() => {});
        setStatusMsg(`Page already exists: ${data.url}`);
        setSelectedWebpageUrl(data.url);
      } else if (data.status === 'created') {
        await navigator.clipboard.writeText(data.url).catch(() => {});
        setStatusMsg(`Page created: ${data.url}`);
        setSelectedWebpageUrl(data.url);
      } else setStatusMsg(data.message ?? 'Make failed');
    } catch { setStatusMsg('Make failed'); }
    setTimeout(() => setStatusMsg(null), 4000);
  };

  // --- Record action ---
  const handleRecord = async () => {
    if (!selected) return;
    if (!activeClientId) {
      const msg = activeCompanyId
        ? 'Company selected — pick an individual client to record'
        : 'No client selected';
      setStatusMsg(msg);
      setTimeout(() => setStatusMsg(null), 2500);
      return;
    }
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/record`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: activeClientId }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSessionRecorded(true);
        showToast(`Recorded — ${selected.name} shared with ${activeClientName ?? 'client'}`);
        if (data.manifest_updated === false && data.manifest_skipped !== true) {
          setTimeout(() => showToast('Note: Manifest not updated', 'warning'), 2600);
        }
        if (activeClientManifestUrl && data.entry_name) {
          setManifestFlashName(data.entry_name);
        }
      } else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail ?? 'Record failed');
      }
    } catch { showToast('Record failed'); }
  };

  // --- Label action ---
  const executeLabelAction = async () => {
    if (!selected) return;
    const filtered = labelQuery
      ? allTopics.filter(t => t.name.toLowerCase().includes(labelQuery.toLowerCase()))
      : allTopics;
    const topic = filtered[labelHighlight];
    if (!topic) return;

    const isAssigned = selected.topics.some(t => t.id === topic.id);
    const action = isAssigned ? 'remove' : 'add';

    try {
      if (action === 'add') {
        await fetch(`/api/libby/entries/${selected.id}/topics/${topic.id}`, { method: 'POST' });
        setSelected(s => s ? { ...s, topics: [...s.topics, topic] } : s);
      } else {
        await fetch(`/api/libby/entries/${selected.id}/topics/${topic.id}`, { method: 'DELETE' });
        setSelected(s => s ? { ...s, topics: s.topics.filter(t => t.id !== topic.id) } : s);
      }
      repeatRef.current = { action, topic };
      setRepeatDisplay((action === 'add' ? '+ ' : '− ') + topic.name);
      setLabelMsg((action === 'add' ? 'added ' : 'removed ') + topic.name);
      setLabelQuery('');
      setLabelHighlight(0);
      setTimeout(() => {
        setLabelMsg(null);
        setUiState('ACTION');
      }, 1000);
    } catch {
      setLabelMsg('error');
      setTimeout(() => setLabelMsg(null), 2000);
    }
  };

  // --- Print action ---
  const handlePrint = async () => {
    if (!selected) return;
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/print`, { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        await navigator.clipboard.writeText(data.text);
        showToast(`Copied: ${selected.name}`);
        setSessionCopied(true);
      } else {
        showToast('Print failed');
      }
    } catch {
      showToast('Print failed');
    }
  };

  // --- Retype action ---
  const handleRetypeConfirm = async () => {
    if (!selected || !retypeSelected) return;
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/retype`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_type_code: retypeSelected }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setSelected(s => s ? { ...s, type_code: data.new_type } : s);
        showToast(`Changed to ${ALL_TYPE_LABELS[data.new_type] ?? data.new_type}`);
      } else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail ?? 'Retype failed');
      }
    } catch {
      showToast('Retype failed');
    }
    setRetypeSelected(null);
    setUiState('ACTION');
  };

  // --- Open URL in browser ---
  const handleOpenUrl = () => {
    if (!selected) return;
    const url = selected.webpage_url ?? selected.amazon_short_url ?? selected.amazon_url ?? selected.url;
    if (!url) {
      showToast('No URL for this entry');
      return;
    }
    window.open(url, '_blank');
  };

  // --- Vault (Obsidian) action ---
  const handleVault = () => {
    if (!selected?.obsidian_link) {
      showToast('No Obsidian page for this entry');
      return;
    }
    const a = document.createElement('a');
    a.href = selected.obsidian_link;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('Opening in Obsidian…');
  };

  // --- Copy Doc action ---
  const handleCopyDoc = async () => {
    if (!selected || !activeClientId) return;
    if (!selected.gdoc_id) {
      showToast('No Google Doc for this entry');
      return;
    }
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/copy_doc`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: activeClientId }),
      });
      if (resp.ok) {
        const data = await resp.json();
        await navigator.clipboard.writeText(data.print_text);
        showToast(`Copied doc + link: ${data.filename}`);
        setSessionCopied(true);
      } else {
        const err = await resp.json().catch(() => ({}));
        showToast(err.detail ?? 'Copy doc failed');
      }
    } catch {
      showToast('Copy doc failed');
    }
  };

  // --- Apply action (was: repeat) ---
  const handleApply = async () => {
    if (!selected || !repeatRef.current) {
      showToast('no label set');
      return;
    }
    const { action, topic } = repeatRef.current;
    try {
      if (action === 'add') {
        await fetch(`/api/libby/entries/${selected.id}/topics/${topic.id}`, { method: 'POST' });
        setSelected(s => s && !s.topics.some(t => t.id === topic.id)
          ? { ...s, topics: [...s.topics, topic] }
          : s);
      } else {
        await fetch(`/api/libby/entries/${selected.id}/topics/${topic.id}`, { method: 'DELETE' });
        setSelected(s => s ? { ...s, topics: s.topics.filter(t => t.id !== topic.id) } : s);
      }
      showToast((action === 'add' ? 'added ' : 'removed ') + topic.name);
    } catch {
      showToast('repeat failed');
    }
  };

  // --- Container keydown handler (PICK and ACTION states) ---
  // Fires for keydown on the container div and events bubbling up from its children.
  // In SEARCH state the input has focus so we return early — input handles its own keys.
  const handleContainerKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (uiState === 'SEARCH') return;
    if (isHelpOpen) return;

    if (uiState === 'PICK') {
      e.preventDefault();
      if (e.key === 'Escape' || e.key === 'b') {
        setUiState('SEARCH');
        return;
      }
      // + or = opens quick-add modal
      if (e.key === '+' || e.key === '=') {
        setQuickAddOpen(true);
        return;
      }
      const idx = RESULT_LABELS.indexOf(e.key.toLowerCase());
      if (idx >= 0 && idx < results.length) {
        const entry = results[idx];
        setSelected(entry);
        setSelectedWebpageUrl(entry.webpage_url ?? null);
        setUiState('ACTION');
      }
      return;
    }

    if (uiState === 'ACTION') {
      // Stop propagation immediately so global app-level keyboard shortcuts
      // (e.g. sidebar navigation) don't also fire on single-letter keys.
      e.stopPropagation();
      if (e.key === 'Escape') {
        e.preventDefault();
        repeatRef.current = null;
        setRepeatDisplay(null);
        setQuery('');
        setResults([]);
        setSearchTotal(0);
        setSelected(null);
        setSelectedWebpageUrl(null);
        setStatusMsg(null);
        setUiState('SEARCH');
        return;
      }
      if (e.key === 'b') { e.preventDefault(); setUiState('PICK'); return; }
      if (e.key === 'c') { e.preventDefault(); handleCopy(); return; }
      if (e.key === 'p') { e.preventDefault(); handlePrint(); return; }
      if (e.key === 'd') { e.preventDefault(); handleCopyDoc(); return; }
      if (e.key === 'r') { e.preventDefault(); if (!sessionCopied || sessionRecorded) return; handleRecord(); return; }
      if (e.key === 'a') { e.preventDefault(); handleApply(); return; }
      if (e.key === 'l') { e.preventDefault(); setLabelQuery(''); setLabelHighlight(0); setLabelMsg(null); setUiState('LABEL'); return; }
      if (e.key === 'o') { e.preventDefault(); handleOpenUrl(); return; }
      if (e.key === 'm') { e.preventDefault(); handleMake(); return; }
      if (e.key === 'v') { e.preventDefault(); handleVault(); return; }
      if (e.key === 'y') { e.preventDefault(); setRetypeSelected(null); setUiState('RETYPE'); return; }
      if (e.key === 's') { e.preventDefault(); showToast('synopsis: coming soon'); return; }
      if (e.key === 'f') { e.preventDefault(); showToast('full: coming soon'); return; }
      if (e.key === 'x') { e.preventDefault(); showToast('find related: future'); return; }
    }

    if (uiState === 'RETYPE') {
      e.stopPropagation();
      if (e.key === 'Escape') {
        e.preventDefault();
        if (retypeSelected) {
          setRetypeSelected(null);
        } else {
          setUiState('ACTION');
        }
        return;
      }
      if (retypeSelected && e.key === 'Enter') {
        e.preventDefault();
        handleRetypeConfirm();
        return;
      }
      // Type letter selection in grid mode
      const letter = e.key.toLowerCase();
      if (!retypeSelected && letter in ALL_TYPE_LABELS) {
        e.preventDefault();
        if (letter === selected?.type_code) {
          showToast(`Already type: ${ALL_TYPE_LABELS[letter]}`);
          setUiState('ACTION');
        } else {
          setRetypeSelected(letter);
        }
      }
    }
  };

  const formatSharedDate = (iso: string) => {
    try { return iso.slice(0, 10); } catch { return iso; }
  };

  // Topic filter feedback (SEARCH only)
  const activeTopicPrefix = parseTopicPrefix(uiState === 'SEARCH' ? query : '');
  const matchingTopics = activeTopicPrefix
    ? allTopics.filter(t => t.name.toLowerCase().startsWith(activeTopicPrefix))
    : [];
  const topicPrefixColor = matchingTopics.length === 1 ? 'var(--color-text)' : 'var(--color-text-light)';

  const showSharedColumn = activeClientId !== null;

  return (
    <div
      ref={containerRef}
      className="libby-find-page"
      tabIndex={-1}
      onKeyDown={handleContainerKeyDown}
    >
      <div className="libby-catalog-topbar">
        <LibbyClientFilter />
        <div className="libby-catalog-topbar-actions">
          {activeClientManifestUrl && activeClientId && activeClientName && (
            <button
              className="libby-manifest-btn"
              onClick={() => setManifestOpen(o => !o)}
              title="Open manifest"
            >
              manifest
            </button>
          )}
          <button
            className="libby-quickadd-trigger"
            onClick={() => setQuickAddOpen(true)}
            title="Quick add entry (+ or =)"
          >
            +
          </button>
        </div>
      </div>

      {/* Search input — SEARCH state only */}
      {uiState === 'SEARCH' && (
        <div className="libby-search-wrap libby-search-wrap--search">
          <input
            ref={searchInputRef}
            className="libby-search-input"
            type="text"
            placeholder="b .le atomic…"
            value={query}
            onChange={handleInputChange}
            onKeyDown={handleSearchKeyDown}
            autoFocus
            spellCheck={false}
          />
          {loading && <span className="libby-search-spinner">…</span>}
        </div>
      )}

      {/* PICK prompt — replaces input, shows result labels as selectable */}
      {uiState === 'PICK' && (
        <div className="libby-search-wrap libby-search-wrap--pick">
          <span className="libby-pick-prompt">
            Pick a result (a–{RESULT_LABELS[results.length - 1]}) · <strong>escape</strong> to search again
          </span>
        </div>
      )}

      {/* ACTION: selected title shown in place of input */}
      {uiState === 'ACTION' && selected && (
        <div className="libby-search-wrap libby-search-wrap--action">
          <div className="libby-search-action-label">
            <span className="libby-search-action-name">{selected.name}</span>
          </div>
        </div>
      )}

      {/* Topic filter feedback bar — SEARCH only */}
      {uiState === 'SEARCH' && activeTopicPrefix && (
        <div className="libby-topic-feedback">
          <span className="libby-topic-feedback-prefix" style={{ color: topicPrefixColor }}>.{activeTopicPrefix}</span>
          {matchingTopics.length > 0 && (
            <span className="libby-topic-feedback-names">
              {matchingTopics.map(t => t.name).join(', ')}
            </span>
          )}
          {matchingTopics.length === 0 && (
            <span className="libby-topic-feedback-names libby-topic-feedback-names--none">no matching topics</span>
          )}
        </div>
      )}

      {/* Type reference grid — empty SEARCH only */}
      {uiState === 'SEARCH' && !query && (
        <div className="libby-type-ref">
          <div className="libby-type-grid">
            {/* Header row — 7 cells */}
            <span className="libby-type-grid-hdr">key</span>
            <span className="libby-type-grid-hdr">type</span>
            <span className="libby-type-grid-hdr libby-type-grid-hdr--r">#</span>
            <span className="libby-type-grid-hdr libby-type-grid-hdr--spacer" />
            <span className="libby-type-grid-hdr">key</span>
            <span className="libby-type-grid-hdr">type</span>
            <span className="libby-type-grid-hdr libby-type-grid-hdr--r">#</span>
            {/* Data rows — only types with entries, split into two columns */}
            {(() => {
              const activeTypes = [...TYPE_GRID_LEFT, ...TYPE_GRID_RIGHT]
                .filter((code, idx, arr) => arr.indexOf(code) === idx) // dedupe (they're disjoint but be safe)
                .filter(code => (typeCounts?.[code] ?? 0) > 0)
                .sort((a, b) => ALL_TYPE_LABELS[a].localeCompare(ALL_TYPE_LABELS[b]));
              const mid = Math.ceil(activeTypes.length / 2);
              const leftCol = activeTypes.slice(0, mid);
              const rightCol = activeTypes.slice(mid);
              return leftCol.map((lCode, i) => {
                const rCode = rightCol[i];
                const lCount = typeCounts?.[lCode] ?? 0;
                const rCount = rCode ? (typeCounts?.[rCode] ?? 0) : 0;
                return (
                  <Fragment key={lCode}>
                    <span className="libby-type-grid-key">{lCode}</span>
                    <span className="libby-type-grid-name">{ALL_TYPE_LABELS[lCode]}</span>
                    <span className="libby-type-count">{lCount.toLocaleString()}</span>
                    <span />
                    <span className="libby-type-grid-key">{rCode ?? ''}</span>
                    <span className="libby-type-grid-name">{rCode ? ALL_TYPE_LABELS[rCode] : ''}</span>
                    <span className="libby-type-count">{rCode && rCount > 0 ? rCount.toLocaleString() : ''}</span>
                  </Fragment>
                );
              });
            })()}
          </div>
        </div>
      )}

      {/* Column headers + Results list — SEARCH and PICK */}
      {uiState !== 'ACTION' && uiState !== 'LABEL' && uiState !== 'RETYPE' && results.length > 0 && (
        <>
          <div className="libby-results-header">
            <span className="libby-result-label">key</span>
            <span className="libby-result-name-cell" style={{ flexDirection: 'row', alignItems: 'baseline', gap: '4px' }}>
              <span style={{ color: '#000' }}>title</span>
              <span style={{ color: 'var(--color-text-light)', fontWeight: 'normal' }}>by author</span>
            </span>
            <span className="libby-result-type">type</span>
            <span className="libby-priority-dots">pri</span>
            <span className="libby-result-freq">shared</span>
            {showSharedColumn && <span className="libby-result-shared">with</span>}
          </div>
          <ul className="libby-results">
            {results.map((entry, i) => {
              const label = RESULT_LABELS[i];
              const isHighlit = uiState === 'PICK';
              const rowTopics = activeTopicPrefix
                ? entry.topics.filter(t => t.name.toLowerCase().startsWith(activeTopicPrefix))
                : [];
              return (
                <li
                  key={entry.id}
                  className={`libby-result-row${isHighlit ? ' libby-result-row--select' : ''}`}
                  onClick={() => {
                    if (uiState === 'PICK') {
                      setSelected(entry);
                      setSelectedWebpageUrl(entry.webpage_url ?? null);
                      setUiState('ACTION');
                    }
                  }}
                >
                  <span className={`libby-result-label${isHighlit ? ' libby-result-label--active' : ''}`}>{label}</span>
                  <span className="libby-result-name-cell">
                    <span className="libby-result-name">
                      {entry.name}
                      {entry.author && (
                        <span className="libby-result-author-inline"> by {entry.author}</span>
                      )}
                    </span>
                    {rowTopics.length > 0 && (
                      <span className="libby-result-name-topics"><em>{rowTopics.map(t => t.name).join(', ')}</em></span>
                    )}
                  </span>
                  <span className="libby-result-type">{TYPE_LABELS[entry.type_code] ?? entry.type_code}</span>
                  <PriorityDots priority={entry.priority} />
                  {entry.frequency > 0 && (
                    <span className="libby-result-freq">{entry.frequency}</span>
                  )}
                  {showSharedColumn && entry.last_shared_at && (
                    <span
                      className="libby-result-shared-icon"
                      title={`Shared with ${activeClientName ?? 'client'} on ${formatSharedDate(entry.last_shared_at)}`}
                    >
                      ✓
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          {results.length === 26 && searchTotal > 26 && (
            <div className="libby-result-count libby-result-count--capped">
              showing 26 of {searchTotal.toLocaleString()} — refine your search
            </div>
          )}
          {results.length > 0 && results.length < 26 && (
            <div className="libby-result-count">
              {results.length} {results.length === 1 ? 'result' : 'results'}
            </div>
          )}
        </>
      )}

      {/* Action section */}
      {uiState === 'ACTION' && selected && (
        <div className="libby-action-section">
          <div className="libby-selected-detail">
            <span className="libby-selected-type">{TYPE_LABELS[selected.type_code] ?? selected.type_code}</span>
            {selected.author && <span className="libby-selected-author">{selected.author}</span>}
            {selected.topics.length > 0 && (
              <span className="libby-selected-topics">
                <em>{selected.topics.map(t => t.name).join(', ')}</em>
              </span>
            )}
            <PriorityDots priority={selected.priority} />
          </div>

          {(selected.description || (selected.categories && selected.categories.length > 0)) && (
            <div className="libby-selected-expanded">
              {selected.description && (() => {
                const raw = selected.description!;
                const prefix = selected.author ? `by ${selected.author}` : null;
                const desc = prefix && raw.toLowerCase().startsWith(prefix.toLowerCase())
                  ? raw.slice(prefix.length).trimStart()
                  : raw;
                const truncated = desc.length > 150 ? desc.slice(0, 150) + '…' : desc;
                return (
                  <p className="libby-selected-description">{truncated}</p>
                );
              })()}
              {selected.categories && selected.categories.length > 0 && (
                <p className="libby-selected-categories-text">
                  {selected.categories.join(', ')}
                </p>
              )}
            </div>
          )}

          <div className="libby-action-bar">
            <button className="libby-action-btn" onClick={handleCopy} title="c — copy URL">
              <span className="libby-action-key">c</span> copy
            </button>
            <button className="libby-action-btn" onClick={handlePrint} title="p — print (copy title + link)">
              <span className="libby-action-key">p</span> print
            </button>
            <button
              className={`libby-action-btn${(!selected.gdoc_id || !activeClientId) ? ' libby-action-btn--disabled' : ''}`}
              onClick={handleCopyDoc}
              disabled={!selected.gdoc_id || !activeClientId}
              title={!selected.gdoc_id ? 'd — no doc attached' : !activeClientId ? 'd — select a client first' : 'd — copy doc to client folder'}
            >
              <span className="libby-action-key">d</span> doc copy
            </button>
            <button
              className={`libby-action-btn${(!sessionCopied || sessionRecorded) ? ' libby-action-btn--disabled' : ''}`}
              onClick={handleRecord}
              disabled={!sessionCopied || sessionRecorded}
              title={sessionRecorded ? 'r — already recorded this session' : !sessionCopied ? 'r — copy first (c/p/d), then record' : 'r — record share with client'}
            >
              <span className="libby-action-key">r</span> record{sessionRecorded ? ' ✓' : ''}
            </button>
            <button
              className={`libby-action-btn${!repeatDisplay ? ' libby-action-btn--disabled' : ''}`}
              onClick={handleApply}
              disabled={!repeatDisplay}
              title={repeatDisplay ? `a — apply: ${repeatDisplay}` : 'a — no label set (use l first)'}
            >
              <span className="libby-action-key">a</span> apply
            </button>
            <button className="libby-action-btn" onClick={() => { setLabelQuery(''); setLabelHighlight(0); setLabelMsg(null); setUiState('LABEL'); }} title="l — label (add/remove topic)">
              <span className="libby-action-key">l</span> label
            </button>
            <button
              className="libby-action-btn"
              onClick={handleOpenUrl}
              title="o — open URL in browser"
            >
              <span className="libby-action-key">o</span> open
            </button>
            <button
              className={`libby-action-btn${selectedWebpageUrl ? ' libby-action-btn--has-page' : ''}`}
              onClick={handleMake}
              title={selectedWebpageUrl ? `m — page exists: ${selectedWebpageUrl}` : 'm — generate page'}
            >
              <span className="libby-action-key">m</span> make{selectedWebpageUrl ? ' ✓' : ''}
            </button>
            <button
              className={`libby-action-btn${!selected.obsidian_link ? ' libby-action-btn--disabled' : ''}`}
              onClick={handleVault}
              disabled={!selected.obsidian_link}
              title={selected.obsidian_link ? 'v — open in Obsidian vault' : 'v — no Obsidian page'}
            >
              <span className="libby-action-key">v</span> vault
            </button>
            <button
              className="libby-action-btn"
              onClick={() => { setRetypeSelected(null); setUiState('RETYPE'); }}
              title="y — retype (change type)"
            >
              <span className="libby-action-key">y</span> retype
            </button>
          </div>

          <div className="libby-action-legend">
            <table className="libby-legend-table">
              <tbody>
                <tr><td className="libby-legend-key">a</td><td className="libby-legend-name">apply</td><td className="libby-legend-desc">repeat last label</td></tr>
                <tr><td className="libby-legend-key">b</td><td className="libby-legend-name">back</td><td className="libby-legend-desc">previous state</td></tr>
                <tr><td className="libby-legend-key">c</td><td className="libby-legend-name">copy</td><td className="libby-legend-desc">copy URL to clipboard</td></tr>
                <tr><td className="libby-legend-key">d</td><td className="libby-legend-name">doc copy</td><td className="libby-legend-desc">copy doc to client folder + link</td></tr>
                <tr className="libby-legend-row--future"><td className="libby-legend-key">x</td><td className="libby-legend-name">find related</td><td className="libby-legend-desc"><span className="libby-legend-tag">future</span></td></tr>
                <tr className="libby-legend-row--soon"><td className="libby-legend-key">f</td><td className="libby-legend-name">full</td><td className="libby-legend-desc">full clipboard payload <span className="libby-legend-tag">coming soon</span></td></tr>
                <tr><td className="libby-legend-key">l</td><td className="libby-legend-name">label</td><td className="libby-legend-desc">add or remove a topic</td></tr>
                <tr><td className="libby-legend-key">m</td><td className="libby-legend-name">make</td><td className="libby-legend-desc">publish webpage, copy URL</td></tr>
                <tr><td className="libby-legend-key">o</td><td className="libby-legend-name">open</td><td className="libby-legend-desc">open URL in browser</td></tr>
                <tr><td className="libby-legend-key">p</td><td className="libby-legend-name">print</td><td className="libby-legend-desc">copy formatted title + link</td></tr>
                <tr><td className="libby-legend-key">r</td><td className="libby-legend-name">record</td><td className="libby-legend-desc">log share to Obsidian + Manifest</td></tr>
                <tr><td className="libby-legend-key">y</td><td className="libby-legend-name">retype</td><td className="libby-legend-desc">change the type of this entry</td></tr>
                <tr className="libby-legend-row--soon"><td className="libby-legend-key">s</td><td className="libby-legend-name">synopsis</td><td className="libby-legend-desc">generates synopsis <span className="libby-legend-tag">coming soon</span></td></tr>
                <tr><td className="libby-legend-key">v</td><td className="libby-legend-name">vault</td><td className="libby-legend-desc">open entry page in Obsidian</td></tr>
              </tbody>
            </table>
            {repeatDisplay && (
              <div className="libby-repeat-indicator">
                <span className="libby-legend-key">a</span> applies: {repeatDisplay}
              </div>
            )}
          </div>

          {statusMsg && <div className="libby-status-msg">{statusMsg}</div>}
        </div>
      )}

      {/* RETYPE type selector */}
      {uiState === 'RETYPE' && selected && (
        <div className="libby-retype-section">
          {retypeSelected ? (
            <div className="libby-retype-confirm">
              Change from <strong>{ALL_TYPE_LABELS[selected.type_code] ?? selected.type_code}</strong> to{' '}
              <strong>{ALL_TYPE_LABELS[retypeSelected] ?? retypeSelected}</strong>?{' '}
              <span className="libby-retype-hint">Return to confirm · Esc to cancel</span>
            </div>
          ) : (
            <>
              <div className="libby-type-ref-header">retype: pick new type · <span style={{ fontStyle: 'normal' }}>Esc to cancel</span></div>
              <div className="libby-type-ref-grid">
                {TYPE_GRID_ROWS.map(([left, right]) => (
                  <span key={left} className="libby-type-ref-row">
                    <span
                      className={`libby-type-ref-code libby-type-ref-code--btn${left === selected.type_code ? ' libby-type-ref-code--current' : ''}`}
                      onClick={() => {
                        if (left === selected.type_code) { showToast(`Already type: ${ALL_TYPE_LABELS[left]}`); setUiState('ACTION'); }
                        else setRetypeSelected(left);
                      }}
                    >{left}</span>
                    <span className="libby-type-ref-name">{ALL_TYPE_LABELS[left]}</span>
                    <span
                      className={`libby-type-ref-code libby-type-ref-code--btn${right === selected.type_code ? ' libby-type-ref-code--current' : ''}`}
                      onClick={() => {
                        if (right === selected.type_code) { showToast(`Already type: ${ALL_TYPE_LABELS[right]}`); setUiState('ACTION'); }
                        else setRetypeSelected(right);
                      }}
                    >{right}</span>
                    <span className="libby-type-ref-name">{ALL_TYPE_LABELS[right]}</span>
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* LABEL popup */}
      {uiState === 'LABEL' && selected && (() => {
        const filtered = labelQuery
          ? allTopics.filter(t => t.name.toLowerCase().includes(labelQuery.toLowerCase()))
          : allTopics;
        const clampedHighlight = Math.min(labelHighlight, filtered.length - 1);
        return (
          <div className="libby-label-popup">
            <div className="libby-label-popup-header">
              label: <em>{selected.name}</em>
            </div>
            <input
              ref={labelInputRef}
              className="libby-label-input"
              placeholder="filter topics…"
              value={labelQuery}
              onChange={e => { setLabelQuery(e.target.value); setLabelHighlight(0); }}
              onKeyDown={e => {
                if (e.key === 'Escape' || e.key === 'b') {
                  e.preventDefault(); e.stopPropagation();
                  setUiState('ACTION'); setLabelQuery(''); setLabelHighlight(0); setLabelMsg(null);
                } else if (e.key === 'ArrowDown') {
                  e.preventDefault(); e.stopPropagation();
                  setLabelHighlight(h => Math.min(h + 1, filtered.length - 1));
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault(); e.stopPropagation();
                  setLabelHighlight(h => Math.max(h - 1, 0));
                } else if (e.key === 'Enter') {
                  e.preventDefault(); e.stopPropagation();
                  executeLabelAction();
                }
              }}
            />
            {labelMsg ? (
              <div className="libby-label-msg">{labelMsg}</div>
            ) : (
              <ul className="libby-label-list">
                {filtered.map((t, i) => {
                  const isAssigned = selected.topics.some(st => st.id === t.id);
                  return (
                    <li
                      key={t.id}
                      className={`libby-label-item${i === clampedHighlight ? ' libby-label-item--active' : ''}`}
                      onClick={() => { setLabelHighlight(i); executeLabelAction(); }}
                    >
                      <span className="libby-label-check">{isAssigned ? '✓' : ' '}</span>
                      <span className="libby-label-topic-code">{t.code}</span>
                      <span className="libby-label-topic-name">{t.name}</span>
                    </li>
                  );
                })}
                {filtered.length === 0 && (
                  <li className="libby-label-empty">no matching topics</li>
                )}
              </ul>
            )}
          </div>
        );
      })()}

      {/* Toast */}
      {toastMsg && (
        <div className={`libby-toast${toastVariant === 'warning' ? ' libby-toast--warning' : ''}`}>{toastMsg}</div>
      )}

      {/* Empty state */}
      {uiState === 'SEARCH' && query && !loading && results.length === 0 && (
        <div className="libby-empty">No results for "{query}"</div>
      )}

      {/* Manifest overlay */}
      {manifestOpen && activeClientId && activeClientName && (
        <ManifestOverlay
          clientId={activeClientId}
          clientName={activeClientName}
          onClose={() => { setManifestOpen(false); setManifestFlashName(null); }}
          flashName={manifestFlashName}
        />
      )}

      {/* Quick-add modal */}
      {quickAddOpen && (
        <QuickAddModal
          onClose={() => setQuickAddOpen(false)}
          onCreated={(createdName, createdType) => {
            showToast(`Added: ${createdName} (${ALL_TYPE_LABELS[createdType] ?? createdType})`);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LibbyPage root — owns sub-routes
// ---------------------------------------------------------------------------

export function LibbyPage() {
  return (
    <div className="libby-module">
      <LibbyLayout>
        <Routes>
          <Route index element={<Navigate to="catalog" replace />} />
          <Route path="find" element={<Navigate to="/libby/catalog" replace />} />
          <Route path="catalog" element={<CatalogPage />} />
          <Route path="tags" element={<Navigate to="/libby/topics" replace />} />
          <Route path="topics" element={<LibbyTopicsPage />} />
          <Route path="types" element={<LibbyTypesPage />} />
          <Route path="new" element={<LibbyNewPage />} />
        </Routes>
      </LibbyLayout>
    </div>
  );
}
