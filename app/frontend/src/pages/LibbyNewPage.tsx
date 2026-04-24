import { useState, useEffect, useRef, useCallback } from 'react';
import { useLibbyContext } from '../contexts/LibbyContext';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

const ALL_TYPES = [
  { code: 'b', name: 'Book' },
  { code: 'a', name: 'Article' },
  { code: 'e', name: 'Essay' },
  { code: 'p', name: 'Podcast' },
  { code: 'v', name: 'Video' },
  { code: 'm', name: 'Movie' },
  { code: 't', name: 'Tool' },
  { code: 'w', name: 'Webpage' },
  { code: 's', name: 'Worksheet' },
  { code: 'z', name: 'Assessment' },
  { code: 'n', name: 'Note' },
  { code: 'd', name: 'Document' },
  { code: 'f', name: 'Framework' },
  { code: 'c', name: 'Course' },
  { code: 'r', name: 'Research' },
  { code: 'q', name: 'Quote' },
];

interface QueueEntry {
  id: number;
  name: string;
  type_code: string;
  created_at: string;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  retrying?: boolean;
}

interface LibraryTopic {
  id: number;
  code: string;
  name: string;
}

interface BookCandidate {
  google_books_id: string | null;
  title: string;
  author: string;
  isbn: string | null;
  publisher: string | null;
  year: string | null;
  page_count: number | null;
  description: string | null;
  cover_url: string | null;
  asin: string | null;
  amazon_url: string | null;
}

// ---------------------------------------------------------------------------
// CandidateGrid — card-based book candidate selector
// ---------------------------------------------------------------------------

function CandidateGrid({
  candidates,
  onConfirm,
}: {
  candidates: BookCandidate[];
  onConfirm: (c: BookCandidate) => void;
}) {
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  // Reset selection when candidate list changes
  useEffect(() => { setSelectedIdx(null); }, [candidates]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (candidates.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx(i => (i === null ? 0 : Math.min(i + 1, candidates.length - 1)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx(i => (i === null ? 0 : Math.max(i - 1, 0)));
    } else if (e.key === 'Enter' && selectedIdx !== null) {
      e.preventDefault();
      onConfirm(candidates[selectedIdx]);
    }
  }, [candidates, selectedIdx, onConfirm]);

  return (
    <div
      className="libby-book-candidates"
      ref={gridRef}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      style={{ outline: 'none' }}
    >
      {candidates.map((c, i) => {
        const selected = i === selectedIdx;
        const details: string[] = [];
        if (c.year) details.push(c.year);
        if (c.page_count) details.push(`${c.page_count} pages`);
        return (
          <div
            key={c.google_books_id ?? i}
            className={`libby-book-candidate${selected ? ' selected' : ''}`}
            onClick={() => setSelectedIdx(i)}
          >
            {c.cover_url ? (
              <img
                className="libby-book-candidate-cover"
                src={c.cover_url}
                alt=""
                loading="lazy"
              />
            ) : (
              <div className="libby-book-candidate-cover-placeholder">📖</div>
            )}
            <div className="libby-book-candidate-meta">
              <span className="libby-book-candidate-title">{c.title}</span>
              {c.author && <span className="libby-book-candidate-author">{c.author}</span>}
              {details.length > 0 && (
                <span className="libby-book-candidate-details">{details.join(' · ')}</span>
              )}
              {c.isbn && (
                <span className="libby-book-candidate-isbn">ISBN: {c.isbn}</span>
              )}
            </div>
          </div>
        );
      })}
      {selectedIdx !== null && (
        <button
          type="button"
          className="libby-admin-btn libby-admin-btn--primary"
          style={{ alignSelf: 'flex-start', marginTop: '0.25rem' }}
          onClick={() => onConfirm(candidates[selectedIdx])}
        >
          Use this book
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Book creation form — search + Amazon URL modes
// ---------------------------------------------------------------------------

function BookCreationForm({
  topics,
  onSaved,
}: {
  topics: LibraryTopic[];
  onSaved: (name: string) => void;
}) {
  const [mode, setMode] = useState<'search' | 'url'>('search');

  // Lookup inputs
  const [searchTitle, setSearchTitle] = useState('');
  const [searchAuthor, setSearchAuthor] = useState('');
  const [lookupUrl, setLookupUrl] = useState('');
  const [candidates, setCandidates] = useState<BookCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [urlFallback, setUrlFallback] = useState(false); // true when ASIN lookup found nothing

  // Pre-filled form fields
  const [name, setName] = useState('');
  const [author, setAuthor] = useState('');
  const [isbn, setIsbn] = useState('');
  const [publisher, setPublisher] = useState('');
  const [year, setYear] = useState('');
  const [url, setUrl] = useState('');
  const [amazonUrl, setAmazonUrl] = useState('');
  const [googleBooksId, setGoogleBooksId] = useState('');
  const [comments, setComments] = useState('');
  const [priority, setPriority] = useState<'high' | 'medium' | 'low'>('medium');
  const [selectedTopicIds, setSelectedTopicIds] = useState<Set<number>>(new Set());

  // Save state
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const fillFromCandidate = (c: BookCandidate, clearCandidates = true) => {
    setName(c.title || '');
    setAuthor(c.author || '');
    setIsbn(c.isbn || '');
    setPublisher(c.publisher || '');
    setYear(c.year || '');
    setAmazonUrl(c.amazon_url || '');
    setGoogleBooksId(c.google_books_id || '');
    if (c.description) setComments(c.description.slice(0, 300));
    if (clearCandidates) { setCandidates([]); setSearched(false); }
  };

  const handleSearch = async () => {
    if (!searchTitle.trim() && !searchAuthor.trim()) return;
    setSearching(true);
    setSearchError(null);
    setCandidates([]);
    setSearched(false);
    try {
      const params = new URLSearchParams();
      if (searchTitle.trim()) params.set('title', searchTitle.trim());
      if (searchAuthor.trim()) params.set('author', searchAuthor.trim());
      const resp = await fetch(`/api/libby/books/lookup?${params}`);
      const data = await resp.json();
      setCandidates(data.candidates ?? []);
      setSearched(true);
    } catch {
      setSearchError('Lookup failed');
    } finally {
      setSearching(false);
    }
  };

  const handleUrlLookup = async () => {
    if (!lookupUrl.trim()) return;
    setSearching(true);
    setSearchError(null);
    setCandidates([]);
    setSearched(false);
    setUrlFallback(false);
    try {
      const params = new URLSearchParams({ url: lookupUrl.trim() });
      const resp = await fetch(`/api/libby/books/lookup?${params}`);
      const data = await resp.json();
      const cands: BookCandidate[] = data.candidates ?? [];
      const first = cands[0];
      if (first) {
        fillFromCandidate(first);
        if (first.amazon_url) setUrl(first.amazon_url);
      } else {
        // Pre-fill amazon_url so the user doesn't lose the URL they pasted
        setAmazonUrl(lookupUrl.trim());
        setUrlFallback(true);
      }
      setCandidates(cands);
      setSearched(true);
    } catch {
      setSearchError('Lookup failed');
    } finally {
      setSearching(false);
    }
  };

  const toggleTopic = (id: number) => {
    setSelectedTopicIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const resetForm = () => {
    setName(''); setAuthor(''); setIsbn(''); setPublisher('');
    setYear(''); setUrl(''); setAmazonUrl(''); setGoogleBooksId('');
    setComments(''); setPriority('medium'); setSelectedTopicIds(new Set());
    setCandidates([]); setSearched(false); setSearchError(null); setSaveError(null);
    setSearchTitle(''); setSearchAuthor(''); setLookupUrl(''); setUrlFallback(false);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const resp = await fetch('/api/libby/books', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          author: author.trim() || null,
          isbn: isbn.trim() || null,
          publisher: publisher.trim() || null,
          year: year.trim() || null,
          url: url.trim() || null,
          amazon_url: amazonUrl.trim() || null,
          cover_url: null,
          google_books_id: googleBooksId.trim() || null,
          comments: comments.trim() || null,
          priority,
          topic_ids: Array.from(selectedTopicIds),
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        onSaved(data.name);
        resetForm();
      } else {
        setSaveError(data.detail ?? 'Save failed');
      }
    } catch {
      setSaveError('Save failed — server error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="libby-book-form">
      {/* Mode toggle */}
      <div className="libby-book-mode-toggle">
        <button
          type="button"
          className={`libby-book-mode-btn${mode === 'search' ? ' active' : ''}`}
          onClick={() => { setMode('search'); setSearched(false); setCandidates([]); }}
        >
          Search
        </button>
        <button
          type="button"
          className={`libby-book-mode-btn${mode === 'url' ? ' active' : ''}`}
          onClick={() => { setMode('url'); setSearched(false); setCandidates([]); }}
        >
          Amazon URL
        </button>
      </div>

      {/* Lookup section */}
      {mode === 'search' ? (
        <div className="libby-book-lookup">
          <div className="libby-book-lookup-row">
            <input
              className="libby-form-input"
              value={searchTitle}
              onChange={e => setSearchTitle(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleSearch(); } }}
              placeholder="Title…"
              autoFocus
            />
            <input
              className="libby-form-input"
              value={searchAuthor}
              onChange={e => setSearchAuthor(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleSearch(); } }}
              placeholder="Author…"
            />
            <button
              type="button"
              className="libby-admin-btn libby-admin-btn--primary"
              onClick={handleSearch}
              disabled={searching || (!searchTitle.trim() && !searchAuthor.trim())}
            >
              {searching ? '…' : 'Search'}
            </button>
          </div>
          {searchError && <div className="libby-admin-error">{searchError}</div>}
          {searched && candidates.length === 0 && (
            <div className="libby-book-no-results">No results — fill fields manually below</div>
          )}
          {candidates.length > 0 && (
            <CandidateGrid candidates={candidates} onConfirm={c => fillFromCandidate(c)} />
          )}
        </div>
      ) : (
        <div className="libby-book-lookup">
          <div className="libby-book-lookup-row">
            <input
              className="libby-form-input"
              value={lookupUrl}
              onChange={e => setLookupUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleUrlLookup(); } }}
              placeholder="https://www.amazon.com/dp/…"
              autoFocus
            />
            <button
              type="button"
              className="libby-admin-btn libby-admin-btn--primary"
              onClick={handleUrlLookup}
              disabled={searching || !lookupUrl.trim()}
            >
              {searching ? '…' : 'Lookup'}
            </button>
          </div>
          {searchError && <div className="libby-admin-error">{searchError}</div>}
          {urlFallback && (
            <>
              <div className="libby-book-no-results libby-book-no-results--warn">
                Could not find this book automatically — please fill in the details manually.
              </div>
              <div className="libby-book-fallback-search">
                <span className="libby-book-fallback-label">Or search by title/author:</span>
                <div className="libby-book-lookup-row">
                  <input
                    className="libby-form-input"
                    value={searchTitle}
                    onChange={e => setSearchTitle(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleSearch(); } }}
                    placeholder="Title…"
                  />
                  <input
                    className="libby-form-input"
                    value={searchAuthor}
                    onChange={e => setSearchAuthor(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleSearch(); } }}
                    placeholder="Author…"
                  />
                  <button
                    type="button"
                    className="libby-admin-btn libby-admin-btn--primary"
                    onClick={handleSearch}
                    disabled={searching || (!searchTitle.trim() && !searchAuthor.trim())}
                  >
                    {searching ? '…' : 'Search'}
                  </button>
                </div>
                {candidates.length > 0 && (
                  <CandidateGrid
                    candidates={candidates}
                    onConfirm={c => { fillFromCandidate(c); setAmazonUrl(lookupUrl.trim()); setUrlFallback(false); }}
                  />
                )}
              </div>
            </>
          )}
          {!urlFallback && candidates.length > 1 && (
            <CandidateGrid candidates={candidates.slice(1)} onConfirm={c => fillFromCandidate(c)} />
          )}
        </div>
      )}

      {/* Pre-filled / manual form */}
      <form className="libby-new-form" onSubmit={handleSave}>
        <div className="libby-new-form-heading">Book details</div>

        <div className="libby-form-row">
          <label className="libby-form-label">title *</label>
          <input className="libby-form-input" value={name} onChange={e => setName(e.target.value)} required placeholder="Title" />
        </div>
        <div className="libby-form-row">
          <label className="libby-form-label">author</label>
          <input className="libby-form-input" value={author} onChange={e => setAuthor(e.target.value)} placeholder="Author name(s)" />
        </div>
        <div className="libby-form-row">
          <label className="libby-form-label">isbn</label>
          <input className="libby-form-input libby-form-input--short" value={isbn} onChange={e => setIsbn(e.target.value)} placeholder="ISBN-13" />
          <label className="libby-form-label" style={{ marginLeft: '12px' }}>year</label>
          <input className="libby-form-input libby-form-input--short" value={year} onChange={e => setYear(e.target.value)} placeholder="2018" />
        </div>
        <div className="libby-form-row">
          <label className="libby-form-label">publisher</label>
          <input className="libby-form-input" value={publisher} onChange={e => setPublisher(e.target.value)} placeholder="Publisher" />
        </div>
        <div className="libby-form-row">
          <label className="libby-form-label">url</label>
          <input className="libby-form-input" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" />
        </div>
        <div className="libby-form-row">
          <label className="libby-form-label">amazon url</label>
          <input className="libby-form-input" value={amazonUrl} onChange={e => setAmazonUrl(e.target.value)} placeholder="https://www.amazon.com/dp/…" />
        </div>
        <div className="libby-form-row">
          <label className="libby-form-label">comments</label>
          <textarea
            className="libby-form-input libby-form-textarea"
            value={comments}
            onChange={e => setComments(e.target.value)}
            placeholder="Brief annotation (optional)"
            rows={3}
          />
        </div>
        <div className="libby-form-row">
          <label className="libby-form-label">priority</label>
          <select className="libby-form-input libby-form-select" value={priority} onChange={e => setPriority(e.target.value as 'high' | 'medium' | 'low')}>
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
        </div>

        {/* Topics */}
        {topics.length > 0 && (
          <div className="libby-form-row libby-form-row--topics">
            <label className="libby-form-label" style={{ paddingTop: '2px' }}>topics</label>
            <div className="libby-book-topics">
              {topics.map(t => (
                <label key={t.id} className="libby-book-topic-chip">
                  <input
                    type="checkbox"
                    checked={selectedTopicIds.has(t.id)}
                    onChange={() => toggleTopic(t.id)}
                  />
                  <span className="libby-book-topic-code">{t.code}</span>
                  <span className="libby-book-topic-name">{t.name}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {saveError && <div className="libby-admin-error">{saveError}</div>}
        <div className="libby-form-actions">
          <button
            type="submit"
            className="libby-admin-btn libby-admin-btn--primary"
            disabled={saving || !name.trim()}
          >
            {saving ? 'Saving…' : 'Add book'}
          </button>
          <button type="button" className="libby-admin-btn" onClick={resetForm}>
            clear
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Generic creation form (non-book types)
// ---------------------------------------------------------------------------

function GenericCreationForm({
  typeCode,
  typeName,
  onSaved,
}: {
  typeCode: string;
  typeName: string;
  onSaved: (name: string) => void;
}) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [comments, setComments] = useState('');
  const [priority, setPriority] = useState<'high' | 'medium' | 'low'>('medium');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const resetForm = () => {
    setName(''); setUrl(''); setComments(''); setPriority('medium'); setSaveError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const resp = await fetch('/api/libby/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          type_code: typeCode,
          url: url.trim() || null,
          comments: comments.trim() || null,
          priority,
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        onSaved(data.name);
        resetForm();
      } else {
        setSaveError(data.detail ?? 'Save failed');
      }
    } catch {
      setSaveError('Save failed — server error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="libby-new-form" onSubmit={handleSubmit}>
      <div className="libby-new-form-heading">New {typeName}</div>
      <div className="libby-form-row">
        <label className="libby-form-label">name *</label>
        <input className="libby-form-input" value={name} onChange={e => setName(e.target.value)} placeholder="Title or name" required autoFocus spellCheck={false} />
      </div>
      <div className="libby-form-row">
        <label className="libby-form-label">url</label>
        <input className="libby-form-input" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" spellCheck={false} />
      </div>
      <div className="libby-form-row">
        <label className="libby-form-label">comments</label>
        <textarea className="libby-form-input libby-form-textarea" value={comments} onChange={e => setComments(e.target.value)} placeholder="Brief annotation (optional)" rows={3} />
      </div>
      <div className="libby-form-row">
        <label className="libby-form-label">priority</label>
        <select className="libby-form-input libby-form-select" value={priority} onChange={e => setPriority(e.target.value as 'high' | 'medium' | 'low')}>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
      </div>
      {saveError && <div className="libby-admin-error">{saveError}</div>}
      <div className="libby-form-actions">
        <button type="submit" className="libby-admin-btn libby-admin-btn--primary" disabled={saving || !name.trim()}>
          {saving ? 'Saving…' : 'Add to library'}
        </button>
        <button type="button" className="libby-admin-btn" onClick={resetForm}>clear</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// LibbyNewPage
// ---------------------------------------------------------------------------

export function LibbyNewPage() {
  const { refreshQueueCount } = useLibbyContext();

  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [topics, setTopics] = useState<LibraryTopic[]>([]);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const loadQueue = () => {
    fetch('/api/libby/queue')
      .then(r => r.ok ? r.json() : { entries: [], count: 0 })
      .then(d => { setQueue(d.entries ?? []); setLoadingQueue(false); })
      .catch(() => setLoadingQueue(false));
  };

  useEffect(loadQueue, []);

  useEffect(() => {
    fetch('/api/libby/topics')
      .then(r => r.ok ? r.json() : { topics: [] })
      .then(d => setTopics(d.topics ?? []))
      .catch(() => {});
  }, []);

  const handleTypeSelect = (code: string) => {
    setSelectedType(prev => prev === code ? null : code);
    setSaveSuccess(null);
  };

  const handleCancelType = () => {
    setSelectedType(null);
    setSaveSuccess(null);
  };

  // Escape key deselects type when not in a text input
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const tag = (e.target as HTMLElement).tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      setSelectedType(null);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const handleRetry = async (entryId: number) => {
    setQueue(q => q.map(e => e.id === entryId ? { ...e, retrying: true } : e));
    try {
      await fetch(`/api/libby/entries/${entryId}/enrich`, { method: 'POST' });
      setQueue(q => q.map(e => e.id === entryId ? { ...e, status: 'processing', retrying: false } : e));
      setTimeout(loadQueue, 3000);
    } catch {
      setQueue(q => q.map(e => e.id === entryId ? { ...e, retrying: false } : e));
    }
  };

  const handleSaved = (name: string) => {
    setSaveSuccess(`Added: "${name}"`);
    setTimeout(() => setSaveSuccess(null), 4000);
    loadQueue();
    refreshQueueCount();
  };

  const selectedTypeDef = ALL_TYPES.find(t => t.code === selectedType);

  return (
    <div className="libby-new-page">

      {/* ── Type selector ── */}
      <div className="libby-type-selector">
        {ALL_TYPES.map(t => (
          <button
            key={t.code}
            className={`libby-type-btn${selectedType === t.code ? ' libby-type-btn--selected' : ''}`}
            onClick={() => handleTypeSelect(t.code)}
            type="button"
          >
            <span className="libby-type-btn-code">{t.code}</span>
            <span className="libby-type-btn-name">{t.name}</span>
          </button>
        ))}
      </div>

      {saveSuccess && <div className="libby-save-success">{saveSuccess}</div>}

      {/* ── Creation form ── */}
      {selectedType && selectedTypeDef ? (
        <div>
          <div className="libby-form-header">
            <span className="libby-form-type-label">{selectedTypeDef.name}</span>
            <button className="libby-cancel-type" onClick={handleCancelType} title="Cancel (Escape)">✕</button>
          </div>
          {selectedType === 'b' ? (
            <BookCreationForm topics={topics} onSaved={handleSaved} />
          ) : (
            <GenericCreationForm
              typeCode={selectedType}
              typeName={selectedTypeDef.name}
              onSaved={handleSaved}
            />
          )}
        </div>
      ) : (
        <div className="libby-new-prompt">Select a type above to add a new entry</div>
      )}

      {/* ── Processing queue ── */}
      <div className="libby-queue-section">
        <h3 className="libby-queue-title">Processing queue</h3>
        <p className="libby-admin-desc">
          Entries are auto-tagged and summarized in the background. Click retry if a task failed.
        </p>
        {loadingQueue ? (
          <div className="libby-admin-loading">Loading…</div>
        ) : queue.filter(e => e.status !== 'ready').length === 0 ? (
          <div className="libby-queue-empty">No entries pending</div>
        ) : (
          <table className="libby-admin-table libby-queue-table">
            <thead>
              <tr>
                <th>name</th>
                <th>type</th>
                <th>added</th>
                <th>status</th>
              </tr>
            </thead>
            <tbody>
              {queue.filter(e => e.status !== 'ready').map(entry => (
                <tr key={entry.id} className="libby-admin-row libby-queue-row">
                  <td className="libby-queue-name">{entry.name}</td>
                  <td className="libby-admin-code">{entry.type_code}</td>
                  <td className="libby-queue-date">{entry.created_at.slice(0, 10)}</td>
                  <td>
                    {entry.status === 'failed' ? (
                      <span className="libby-queue-status libby-queue-status--failed">
                        failed
                        <button
                          className="libby-queue-retry"
                          disabled={entry.retrying}
                          onClick={() => handleRetry(entry.id)}
                        >{entry.retrying ? '…' : 'retry?'}</button>
                      </span>
                    ) : (
                      <span className={`libby-queue-status libby-queue-status--${entry.status}`}>
                        {entry.status}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
