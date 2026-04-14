import { useState, useEffect, useMemo, useCallback } from 'react';
import { Routes, Route, Navigate, NavLink } from 'react-router-dom';
import { useLibbyContext } from '../contexts/LibbyContext';
import type { LibbyFilterSelection, LibbyGroup } from '../contexts/LibbyContext';
import { ClientFilterBar } from '../components/shared/ClientFilterBar';
import type { HelpShortcut } from '../components/shared/ClientFilterBar';
import { LibbyTagsPage } from './LibbyTagsPage';
import { LibbyTypesPage } from './LibbyTypesPage';
import { LibbyNewPage } from './LibbyNewPage';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LibraryTopic {
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
  webpage_url: string | null;
  gdoc_id: string | null;
  author?: string | null;
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

const RESULT_LABELS = 'abcdefghijklmnopqrst';

type UiState = 'SEARCH' | 'SELECT' | 'ACTION';

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
                <tr><td className="libby-help-key">,</td><td>enter select mode</td></tr>
                <tr><td className="libby-help-key">a–t</td><td>select entry</td></tr>
                <tr><td className="libby-help-key">Esc</td><td>reset</td></tr>
              </tbody>
            </table>

            <div className="libby-help-col-title" style={{ marginTop: '16px' }}>Actions</div>
            <table className="libby-help-keys">
              <tbody>
                <tr><td className="libby-help-key">⌥c</td><td>copy URL</td></tr>
                <tr><td className="libby-help-key">⌥r</td><td>record share</td></tr>
                <tr><td className="libby-help-key">⌥m</td><td>make webpage</td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">⌥s</td><td className="libby-help-soon">synopsis <span>(coming soon)</span></td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">⌥t</td><td className="libby-help-soon">edit tags <span>(coming soon)</span></td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">⌥d</td><td className="libby-help-soon">copy doc <span>(coming soon)</span></td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">⌥f</td><td className="libby-help-soon">full copy <span>(coming soon)</span></td></tr>
                <tr><td className="libby-help-key libby-help-key--soon">⌥x</td><td className="libby-help-soon">find related <span>(future)</span></td></tr>
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
      <nav className="libby-sub-nav">
        <NavLink to="/libby/catalog" className={({ isActive }) => `libby-sub-nav-link${isActive ? ' active' : ''}`}>
          Catalog
        </NavLink>
        <NavLink to="/libby/tags" className={({ isActive }) => `libby-sub-nav-link${isActive ? ' active' : ''}`}>
          Tags
        </NavLink>
        <NavLink to="/libby/types" className={({ isActive }) => `libby-sub-nav-link${isActive ? ' active' : ''}`}>
          Types
        </NavLink>
        <NavLink to="/libby/new" className={({ isActive }) => `libby-sub-nav-link${isActive ? ' active' : ''}${queueCount > 0 ? ' libby-sub-nav-link--badge' : ''}`}>
          {queueCount > 0 ? `New (${queueCount})` : 'New'}
        </NavLink>
      </nav>
      {children}
      {isHelpOpen && <LibbyHelpPopup onClose={() => setHelpOpen(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Topic prefix helpers
// ---------------------------------------------------------------------------

function parseTopicPrefix(query: string): string | null {
  for (const token of query.trim().split(/\s+/)) {
    if (token.startsWith('.') && token.length > 1) {
      return token.slice(1).toLowerCase();
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Catalog Page (was FindPage)
// ---------------------------------------------------------------------------

function CatalogPage() {
  const { activeClientId, activeClientName, activeCompanyId, isHelpOpen } = useLibbyContext();

  const [query, setQuery] = useState('');
  const [uiState, setUiState] = useState<UiState>('SEARCH');
  const [results, setResults] = useState<LibraryEntry[]>([]);
  const [frozenResults, setFrozenResults] = useState<LibraryEntry[]>([]);
  const [selected, setSelected] = useState<LibraryEntry | null>(null);
  const [selectedWebpageUrl, setSelectedWebpageUrl] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [toastVariant, setToastVariant] = useState<'default' | 'warning'>('default');
  const [loading, setLoading] = useState(false);
  const [allTopics, setAllTopics] = useState<LibraryTopic[]>([]);

  // Load all topics once on mount for client-side filtering feedback
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

  // --- Search (re-runs when active client changes to refresh shared indicators) ---
  const runSearch = async (q: string, clientId: number | null) => {
    if (!q.trim()) { setResults([]); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams({ q });
      if (clientId != null) params.set('client_id', String(clientId));
      const resp = await fetch(`/api/libby/search?${params}`);
      if (resp.ok) setResults(await resp.json());
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
    if (uiState !== 'SEARCH') return;
    const val = e.target.value;
    setQuery(val);
    runSearch(val, activeClientId);
  };

  // --- Copy action ---
  const handleCopy = async () => {
    if (!selected) return;
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/copy`, { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.url) { await navigator.clipboard.writeText(data.url); setStatusMsg('URL copied'); }
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
        setStatusMsg(data.message ?? 'Recorded');
        if (data.manifest_updated === false && data.manifest_skipped !== true) {
          showToast('Note: Manifest not updated', 'warning');
        }
      } else {
        const err = await resp.json().catch(() => ({}));
        setStatusMsg(err.detail ?? 'Record failed');
      }
    } catch { setStatusMsg('Record failed'); }
    setTimeout(() => setStatusMsg(null), 3000);
  };

  // --- Window keyboard listener ---
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // If help popup is open, don't process Catalog keys (except ⌘? toggle)
      if (isHelpOpen) return;

      if (uiState === 'SEARCH') {
        if (e.key === ',') {
          e.preventDefault();
          if (results.length === 0) return;
          setFrozenResults(results);
          setUiState('SELECT');
          return;
        }
        if (e.key === 'Enter') {
          if (results.length === 1) {
            setSelected(results[0]);
            setSelectedWebpageUrl(results[0].webpage_url ?? null);
            setFrozenResults(results);
            setUiState('ACTION');
          }
          e.preventDefault();
          return;
        }
        if (e.key === 'Escape') { setQuery(''); setResults([]); return; }
      }

      if (uiState === 'SELECT') {
        if (e.key === 'Backspace') { e.preventDefault(); setUiState('SEARCH'); return; }
        if (e.key === 'Escape') {
          e.preventDefault();
          setQuery(''); setResults([]); setFrozenResults([]); setUiState('SEARCH');
          return;
        }
        const idx = RESULT_LABELS.indexOf(e.key.toLowerCase());
        if (idx >= 0 && idx < frozenResults.length) {
          e.preventDefault();
          const entry = frozenResults[idx];
          setSelected(entry);
          setSelectedWebpageUrl(entry.webpage_url ?? null);
          setUiState('ACTION');
          return;
        }
      }

      if (uiState === 'ACTION') {
        if (e.key === 'Escape') {
          e.preventDefault();
          setQuery(''); setResults([]); setFrozenResults([]);
          setSelected(null); setSelectedWebpageUrl(null); setStatusMsg(null);
          setUiState('SEARCH');
          return;
        }
        if (e.altKey && e.key === 'c') { e.preventDefault(); handleCopy(); return; }
        if (e.altKey && e.key === 'r') { e.preventDefault(); handleRecord(); return; }
        if (e.altKey && e.key === 'm') { e.preventDefault(); handleMake(); return; }
        if (e.altKey && e.key === 'd') { e.preventDefault(); showToast('copy doc: not yet implemented'); return; }
        if (e.altKey && e.key === 'f') { e.preventDefault(); showToast('full: not yet implemented'); return; }
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [uiState, results, frozenResults, selected, activeClientId, isHelpOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const displayResults = uiState === 'SEARCH' ? results : frozenResults;
  const displayQuery = uiState === 'SELECT' ? query + ',' : uiState === 'ACTION' ? '' : query;

  const formatSharedDate = (iso: string) => {
    try { return iso.slice(0, 10); } catch { return iso; }
  };

  // Topic filter feedback
  const activeTopicPrefix = parseTopicPrefix(uiState === 'SEARCH' ? query : '');
  const matchingTopics = activeTopicPrefix
    ? allTopics.filter(t => t.name.toLowerCase().startsWith(activeTopicPrefix))
    : [];
  const topicPrefixColor = matchingTopics.length === 1 ? 'var(--color-text)' : 'var(--color-text-light)';


  // Show shared-indicator column when a specific client (not just company) is selected
  const showSharedColumn = activeClientId !== null;

  return (
    <div className="libby-find-page">
      <h2 className="libby-page-name">Catalog</h2>
      <LibbyClientFilter />

      {/* Search box */}
      <div className={`libby-search-wrap libby-search-wrap--${uiState.toLowerCase()}`}>
        {uiState === 'ACTION' && selected ? (
          <div className="libby-search-action-label">
            <span className="libby-search-action-name">{selected.name}</span>
          </div>
        ) : (
          <input
            className="libby-search-input"
            type="text"
            placeholder={uiState === 'SEARCH' ? 'b .le atomic…' : ''}
            value={displayQuery}
            onChange={handleInputChange}
            autoFocus
            readOnly={uiState === 'SELECT'}
            spellCheck={false}
          />
        )}
        {loading && <span className="libby-search-spinner">…</span>}
      </div>

      {/* State hint */}
      <div className="libby-state-hint">
        {uiState === 'SEARCH' && (
          query
            ? results.length === 0
              ? 'no results'
              : results.length === 1
                ? <>1 result — use <kbd>return</kbd> to select</>
                : <>{results.length} results — use <kbd>,</kbd><kbd>choice</kbd> to select</>
            : 'type to search · ⌘? for help'
        )}
        {uiState === 'SELECT' && 'press a–t to select · Backspace to search'}
        {uiState === 'ACTION' && '⌥c copy · ⌥r record · ⌥m make · ⌥d doc · ⌥f full · Escape to reset'}
      </div>

      {/* Topic filter feedback bar */}
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

      {/* Column headers */}
      {uiState !== 'ACTION' && displayResults.length > 0 && (
        <div className="libby-results-header">
          <span className="libby-result-label">key</span>
          <span className="libby-result-name-cell">
            title <span style={{ color: 'var(--color-text-light)', fontWeight: 'normal' }}>by author</span>
          </span>
          <span className="libby-result-type">type</span>
          <span className="libby-priority-dots">pri</span>
          <span className="libby-result-freq">shared</span>
          {showSharedColumn && <span className="libby-result-shared">with</span>}
        </div>
      )}

      {/* Results list */}
      {uiState !== 'ACTION' && displayResults.length > 0 && (
        <ul className="libby-results">
          {displayResults.map((entry, i) => {
            const label = RESULT_LABELS[i];
            const isHighlit = uiState === 'SELECT';
            // Topics that match the active prefix (for second-line display)
            const rowTopics = activeTopicPrefix
              ? entry.topics.filter(t => t.name.toLowerCase().startsWith(activeTopicPrefix))
              : [];
            return (
              <li
                key={entry.id}
                className={`libby-result-row ${isHighlit ? 'libby-result-row--select' : ''}`}
                onClick={() => {
                  if (uiState === 'SELECT') {
                    setSelected(entry);
                    setSelectedWebpageUrl(entry.webpage_url ?? null);
                    setUiState('ACTION');
                  }
                }}
              >
                <span className={`libby-result-label ${isHighlit ? 'libby-result-label--active' : ''}`}>{label}</span>
                <span className="libby-result-name-cell">
                  <span className="libby-result-name">
                    {entry.name}
                    {entry.author && (
                      <span className="libby-result-author-inline"> by {entry.author}</span>
                    )}
                  </span>
                  {rowTopics.length > 0 && (
                    <span className="libby-result-name-topics">{rowTopics.map(t => t.name).join(', ')}</span>
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
      )}

      {/* Action bar */}
      {uiState === 'ACTION' && selected && (
        <div className="libby-action-section">
          <div className="libby-selected-detail">
            <span className="libby-selected-type">{TYPE_LABELS[selected.type_code] ?? selected.type_code}</span>
            {selected.author && <span className="libby-selected-author">{selected.author}</span>}
            <span className="libby-selected-topics">
              {selected.topics.map(t => (
                <span key={t.code} className="libby-topic-pill">{t.code}</span>
              ))}
            </span>
            <PriorityDots priority={selected.priority} />
          </div>

          <div className="libby-action-bar">
            <button className="libby-action-btn" onClick={handleCopy} title="⌥c">
              <span className="libby-action-key">⌥c</span> copy url
            </button>
            <button className="libby-action-btn" onClick={handleRecord} title="⌥r">
              <span className="libby-action-key">⌥r</span> record
            </button>
            <button
              className={`libby-action-btn${selectedWebpageUrl ? ' libby-action-btn--has-page' : ''}`}
              onClick={handleMake}
              title={selectedWebpageUrl ? `⌥m — page exists: ${selectedWebpageUrl}` : '⌥m — generate page'}
            >
              <span className="libby-action-key">⌥m</span> make{selectedWebpageUrl ? ' ✓' : ''}
            </button>
            <button
              className="libby-action-btn libby-action-btn--unimplemented"
              onClick={() => showToast('copy doc: not yet implemented')}
              title="⌥d"
            >
              <span className="libby-action-key">⌥d</span> doc
            </button>
            <button
              className="libby-action-btn libby-action-btn--unimplemented"
              onClick={() => showToast('full: not yet implemented')}
              title="⌥f"
            >
              <span className="libby-action-key">⌥f</span> full
            </button>
          </div>

          {statusMsg && <div className="libby-status-msg">{statusMsg}</div>}
        </div>
      )}

      {/* Toast */}
      {toastMsg && (
        <div className={`libby-toast${toastVariant === 'warning' ? ' libby-toast--warning' : ''}`}>{toastMsg}</div>
      )}

      {/* Empty state */}
      {uiState === 'SEARCH' && query && !loading && results.length === 0 && (
        <div className="libby-empty">No results for "{query}"</div>
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
          <Route path="tags" element={<LibbyTagsPage />} />
          <Route path="types" element={<LibbyTypesPage />} />
          <Route path="new" element={<LibbyNewPage />} />
        </Routes>
      </LibbyLayout>
    </div>
  );
}
