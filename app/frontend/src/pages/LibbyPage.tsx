import { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';

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
}

interface ActiveClient {
  id: number;
  name: string;
  obsidian_name: string | null;
}

interface CoachingClient {
  id: number;
  name: string;
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
// Client selector
// ---------------------------------------------------------------------------

function ClientSelector({
  activeClient,
  clients,
  selectedId,
  onSelect,
}: {
  activeClient: ActiveClient | null;
  clients: CoachingClient[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const selectedClient = clients.find(c => c.id === selectedId) ?? activeClient;

  return (
    <div className="libby-client-selector">
      <span className="libby-client-label">client:</span>
      <select
        className="libby-client-select"
        value={selectedId ?? activeClient?.id ?? ''}
        onChange={e => {
          const id = parseInt(e.target.value, 10);
          if (!isNaN(id)) onSelect(id);
        }}
      >
        {!selectedClient && <option value="">— select —</option>}
        {clients.map(c => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Find Page
// ---------------------------------------------------------------------------

function FindPage() {
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

  // Client context
  const [activeClient, setActiveClient] = useState<ActiveClient | null>(null);
  const [allClients, setAllClients] = useState<CoachingClient[]>([]);
  const [clientId, setClientId] = useState<number | null>(null);

  // Load active client + client list on mount
  useEffect(() => {
    fetch('/api/libby/active-client')
      .then(r => r.ok ? r.json() : null)
      .then((data: ActiveClient | null) => {
        if (data) {
          setActiveClient(data);
          setClientId(data.id);
        }
      })
      .catch(() => {});

    fetch('/api/coaching/clients')
      .then(r => r.ok ? r.json() : { groups: [] })
      .then((data: { groups: { clients: CoachingClient[] }[] }) => {
        const flat: CoachingClient[] = [];
        for (const group of data.groups ?? []) {
          for (const c of group.clients ?? []) {
            flat.push({ id: c.id, name: c.name });
          }
        }
        flat.sort((a, b) => a.name.localeCompare(b.name));
        setAllClients(flat);
      })
      .catch(() => {});
  }, []);

  const displayResults = uiState === 'SEARCH' ? results : frozenResults;
  const effectiveClientId = clientId ?? activeClient?.id ?? null;

  // --- Dismiss toast after delay ---
  const showToast = (msg: string, variant: 'default' | 'warning' = 'default') => {
    setToastMsg(msg);
    setToastVariant(variant);
    setTimeout(() => setToastMsg(null), 2500);
  };

  // --- Search ---
  const runSearch = async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams({ q });
      const resp = await fetch(`/api/libby/search?${params}`);
      if (resp.ok) {
        const data: LibraryEntry[] = await resp.json();
        setResults(data);
      }
    } catch {
      // silently ignore
    } finally {
      setLoading(false);
    }
  };

  // --- Input change (only in SEARCH state) ---
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (uiState !== 'SEARCH') return;
    const val = e.target.value;
    setQuery(val);
    runSearch(val);
  };

  // --- Copy action ---
  const handleCopy = async () => {
    if (!selected) return;
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/copy`, {
        method: 'POST',
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.url) {
          await navigator.clipboard.writeText(data.url);
          setStatusMsg('URL copied');
        } else {
          setStatusMsg('No URL available');
        }
      } else {
        setStatusMsg('Copy failed');
      }
    } catch {
      setStatusMsg('Copy failed');
    }
    setTimeout(() => setStatusMsg(null), 2500);
  };

  // --- Make action ---
  const handleMake = async () => {
    if (!selected) return;
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/make`, {
        method: 'POST',
      });
      const data = await resp.json();
      if (data.status === 'exists') {
        await navigator.clipboard.writeText(data.url).catch(() => {});
        setStatusMsg(`Page already exists: ${data.url}`);
        setSelectedWebpageUrl(data.url);
      } else if (data.status === 'created') {
        await navigator.clipboard.writeText(data.url).catch(() => {});
        setStatusMsg(`Page created: ${data.url}`);
        setSelectedWebpageUrl(data.url);
      } else {
        setStatusMsg(data.message ?? 'Make failed');
      }
    } catch {
      setStatusMsg('Make failed');
    }
    setTimeout(() => setStatusMsg(null), 4000);
  };

  // --- Record action ---
  const handleRecord = async () => {
    if (!selected) return;
    if (!effectiveClientId) {
      setStatusMsg('No client selected');
      setTimeout(() => setStatusMsg(null), 2500);
      return;
    }
    try {
      const resp = await fetch(`/api/libby/entries/${selected.id}/action/record`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: effectiveClientId }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setStatusMsg(data.message ?? 'Recorded');
        // Manifest warning: only show if it failed (not if client had no manifest URL)
        if (data.manifest_updated === false && data.manifest_skipped !== true) {
          showToast('Note: Manifest not updated', 'warning');
        }
      } else {
        const err = await resp.json().catch(() => ({}));
        setStatusMsg(err.detail ?? 'Record failed');
      }
    } catch {
      setStatusMsg('Record failed');
    }
    setTimeout(() => setStatusMsg(null), 3000);
  };

  // --- Window keyboard listener (handles all states, including ACTION where input is absent) ---
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
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
        if (e.key === 'Escape') {
          setQuery('');
          setResults([]);
          return;
        }
      }

      if (uiState === 'SELECT') {
        if (e.key === 'Backspace') {
          e.preventDefault();
          setUiState('SEARCH');
          return;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          setQuery('');
          setResults([]);
          setFrozenResults([]);
          setUiState('SEARCH');
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
          setQuery('');
          setResults([]);
          setFrozenResults([]);
          setSelected(null);
          setSelectedWebpageUrl(null);
          setStatusMsg(null);
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
  }, [uiState, results, frozenResults, selected, effectiveClientId]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Compute display query string ---
  const displayQuery = uiState === 'SELECT' ? query + ',' : uiState === 'ACTION' ? '' : query;

  return (
    <div className="libby-find-page">
      <div className="libby-header">
        <span className="libby-header-title">Libby Find</span>
        {uiState === 'ACTION' && (
          <ClientSelector
            activeClient={activeClient}
            clients={allClients}
            selectedId={clientId}
            onSelect={setClientId}
          />
        )}
      </div>

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
        {uiState === 'SEARCH' && (query ? `${results.length} result${results.length !== 1 ? 's' : ''} · , to select` : 'type to search')}
        {uiState === 'SELECT' && 'press a–t to select · Backspace to search'}
        {uiState === 'ACTION' && '⌥c copy · ⌥r record · ⌥m make · ⌥d doc · ⌥f full · Escape to reset'}
      </div>

      {/* Results list */}
      {uiState !== 'ACTION' && displayResults.length > 0 && (
        <div className="libby-results-header">
          <span className="libby-result-label">key</span>
          <span className="libby-result-name">title</span>
          <span className="libby-result-author">author</span>
          <span className="libby-result-type">type</span>
          <span className="libby-result-topics">topics</span>
          <span className="libby-priority-dots">pri</span>
          <span className="libby-result-freq">freq</span>
        </div>
      )}
      {uiState !== 'ACTION' && displayResults.length > 0 && (
        <ul className="libby-results">
          {displayResults.map((entry, i) => {
            const label = RESULT_LABELS[i];
            const isHighlit = uiState === 'SELECT';
            return (
              <li
                key={entry.id}
                className={`libby-result-row ${isHighlit ? 'libby-result-row--select' : ''}`}
                onClick={() => {
                  if (uiState === 'SELECT') {
                    setSelected(entry);
                    setUiState('ACTION');
                  }
                }}
              >
                <span className={`libby-result-label ${isHighlit ? 'libby-result-label--active' : ''}`}>{label}</span>
                <span className="libby-result-name">{entry.name}</span>
                {entry.author && <span className="libby-result-author">{entry.author}</span>}
                <span className="libby-result-type">{TYPE_LABELS[entry.type_code] ?? entry.type_code}</span>
                <span className="libby-result-topics">
                  {entry.topics.map(t => (
                    <span key={t.code} className="libby-topic-pill">{t.code}</span>
                  ))}
                </span>
                <PriorityDots priority={entry.priority} />
                {entry.frequency > 0 && (
                  <span className="libby-result-freq">{entry.frequency}</span>
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

          {statusMsg && (
            <div className="libby-status-msg">{statusMsg}</div>
          )}
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
      <Routes>
        <Route index element={<Navigate to="find" replace />} />
        <Route path="find" element={<FindPage />} />
      </Routes>
    </div>
  );
}
