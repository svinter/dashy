import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLibbyContext } from '../contexts/LibbyContext';

// URL-based types where the URL field appears in collapsed form
const URL_TYPES = new Set(['a', 'e', 'p', 'v', 't', 'w', 'd', 'f', 'c', 'r']);

// Types that show article-level expanded fields (publication, published_date)
const ARTICLE_TYPES = new Set(['a', 'e', 'r']);

function extractGdocId(input: string): string {
  const match = input.match(/\/document\/d\/([a-zA-Z0-9_-]+)/);
  return match ? match[1] : input;
}

function VaultFindButton({
  name,
  typeCode,
  onFound,
}: {
  name: string;
  typeCode: string;
  onFound: (link: string) => void;
}) {
  const [status, setStatus] = useState<null | 'loading' | 'found' | 'notfound'>(null);

  const handleFind = async () => {
    if (!name.trim()) return;
    setStatus('loading');
    try {
      const params = new URLSearchParams({ name: name.trim(), type_code: typeCode });
      const resp = await fetch(`/api/libby/vault/find?${params}`);
      const data = await resp.json() as { found: boolean; obsidian_link?: string };
      if (data.found && data.obsidian_link) {
        onFound(data.obsidian_link);
        setStatus('found');
        setTimeout(() => setStatus(null), 3000);
      } else {
        setStatus('notfound');
        setTimeout(() => setStatus(null), 3000);
      }
    } catch {
      setStatus('notfound');
      setTimeout(() => setStatus(null), 3000);
    }
  };

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', marginLeft: '6px', flexShrink: 0 }}>
      <button
        type="button"
        onClick={handleFind}
        disabled={status === 'loading' || !name.trim()}
        style={{ fontSize: '11px', color: '#999', background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px', textDecoration: 'underline' }}
      >
        {status === 'loading' ? 'Searching…' : 'Find'}
      </button>
      {status === 'found' && <span style={{ fontSize: '11px', color: '#4a8' }}>Found</span>}
      {status === 'notfound' && <span style={{ fontSize: '11px', color: '#a44' }}>Not found</span>}
    </span>
  );
}

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

interface InboxEntry {
  id: number;
  name: string;
  type_code: string;
  ingest_source: string | null;
  ingest_original: string | null;
  url: string | null;
  comments: string | null;
  obsidian_link: string | null;
  created_at: string;
}

function _relTime(isoStr: string): string {
  const diff = Math.floor((Date.now() - new Date(isoStr + 'Z').getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
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
// Book creation form — unified search bar
// ---------------------------------------------------------------------------

function BookCreationForm({
  topics,
  onSaved,
  initialName,
  initialUrl,
  initialComments,
}: {
  topics: LibraryTopic[];
  onSaved: (name: string) => void;
  initialName?: string;
  initialUrl?: string;
  initialComments?: string;
}) {
  // Lookup inputs
  const [searchTitle, setSearchTitle] = useState('');
  const [searchAuthor, setSearchAuthor] = useState('');
  const [lookupUrl, setLookupUrl] = useState('');
  const [candidates, setCandidates] = useState<BookCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  // Pre-filled form fields
  const [name, setName] = useState(initialName ?? '');
  const [author, setAuthor] = useState('');
  const [isbn, setIsbn] = useState('');
  const [publisher, setPublisher] = useState('');
  const [year, setYear] = useState('');
  const [url, setUrl] = useState('');
  const [amazonUrl, setAmazonUrl] = useState('');
  const [googleBooksId, setGoogleBooksId] = useState('');
  const [comments, setComments] = useState(initialComments ?? '');
  const [priority, setPriority] = useState<'high' | 'medium' | 'low'>('medium');
  const [selectedTopicIds, setSelectedTopicIds] = useState<Set<number>>(new Set());

  // Expand/collapse + expanded book fields
  const [expanded, setExpanded] = useState(false);
  const [obsidianLink, setObsidianLink] = useState('');
  const [gdocInput, setGdocInput] = useState('');
  const [genre, setGenre] = useState('');
  const [readingStatus, setReadingStatus] = useState('unread');
  const [dateFinished, setDateFinished] = useState('');
  const [ownedFormat, setOwnedFormat] = useState('');
  const [readingPriority, setReadingPriority] = useState('');
  const [readingNotes, setReadingNotes] = useState('');
  const [isPrivate, setIsPrivate] = useState(false);

  // Save state
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const fillFromCandidate = (c: BookCandidate) => {
    setName(c.title || '');
    setAuthor(c.author || '');
    setIsbn(c.isbn || '');
    setPublisher(c.publisher || '');
    setYear(c.year || '');
    setAmazonUrl(c.amazon_url || '');
    setGoogleBooksId(c.google_books_id || '');
    if (c.description) setComments(c.description.slice(0, 300));
    // Clear all three search fields and candidates
    setCandidates([]);
    setSearched(false);
    setSearchTitle('');
    setSearchAuthor('');
    setLookupUrl('');
  };

  const handleUnifiedSearch = async (urlOverride?: string) => {
    const hasUrl = (urlOverride ?? lookupUrl).trim();
    const hasTitle = searchTitle.trim();
    console.log('[BookSearch] handleUnifiedSearch called', { hasUrl: !!hasUrl, hasTitle: !!hasTitle });
    if (!hasUrl && !hasTitle) return;
    setSearching(true);
    setSearchError(null);
    setCandidates([]);
    setSearched(false);
    try {
      const params = new URLSearchParams();
      if (hasUrl) {
        params.set('url', hasUrl);
        console.log('[BookSearch] URL path:', hasUrl);
      } else {
        params.set('title', hasTitle);
        if (searchAuthor.trim()) params.set('author', searchAuthor.trim());
        console.log('[BookSearch] Title path:', hasTitle);
      }
      const resp = await fetch(`/api/libby/books/lookup?${params}`);
      const data = await resp.json();
      const cands: BookCandidate[] = data.candidates ?? [];
      console.log('[BookSearch] candidates:', cands.length, cands.map(c => c.title));

      if (hasUrl && cands.length > 0) {
        const first = cands[0];
        const isStub = !first.title;
        if (isStub) {
          // Amazon page was blocked — set URL fields only, show message
          if (first.amazon_url) {
            setAmazonUrl(first.amazon_url);
            setUrl(first.amazon_url);
          }
          setSearchError("Couldn't extract metadata from Amazon — enter title above and search again, or fill fields manually");
        } else {
          // Full candidate: auto-fill form
          setName(first.title || '');
          setAuthor(first.author || '');
          setIsbn(first.isbn || '');
          setPublisher(first.publisher || '');
          setYear(first.year || '');
          setAmazonUrl(first.amazon_url || '');
          if (first.amazon_url) setUrl(first.amazon_url);
          setGoogleBooksId(first.google_books_id || '');
          if (first.description) setComments(first.description.slice(0, 300));
          // Show additional candidates (different editions) in grid
          setCandidates(cands.length > 1 ? cands.slice(1) : []);
        }
      } else {
        setCandidates(cands);
      }
      setSearched(true);
    } catch (err) {
      console.error('[BookSearch] error:', err);
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
    setSearchTitle(''); setSearchAuthor(''); setLookupUrl('');
    setExpanded(false); setObsidianLink(''); setGdocInput(''); setGenre('');
    setReadingStatus('unread'); setDateFinished(''); setOwnedFormat('');
    setReadingPriority(''); setReadingNotes(''); setIsPrivate(false);
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
          obsidian_link: obsidianLink.trim() || null,
          gdoc_id: gdocInput.trim() ? extractGdocId(gdocInput.trim()) : null,
          private: isPrivate,
          genre: genre.trim() || null,
          reading_status: readingStatus || null,
          date_finished: dateFinished.trim() || null,
          owned_format: ownedFormat.trim() || null,
          reading_priority: readingPriority ? parseInt(readingPriority, 10) : null,
          reading_notes: readingNotes.trim() || null,
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

  const triggerSearch = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); handleUnifiedSearch(); }
  };

  return (
    <div className="libby-book-form">
      {/* Unified search bar */}
      <div className="libby-book-lookup">
        <div className="libby-book-lookup-row">
          <input
            className="libby-form-input"
            style={{ flex: 2 }}
            value={searchTitle}
            onChange={e => setSearchTitle(e.target.value)}
            onKeyDown={triggerSearch}
            placeholder="Title..."
            autoFocus
          />
          <input
            className="libby-form-input"
            style={{ flex: 1 }}
            value={searchAuthor}
            onChange={e => setSearchAuthor(e.target.value)}
            onKeyDown={triggerSearch}
            placeholder="Author"
          />
          <input
            className="libby-form-input"
            style={{ flex: 2 }}
            value={lookupUrl}
            onChange={e => setLookupUrl(e.target.value)}
            onKeyDown={triggerSearch}
            onPaste={e => {
              const pasted = e.clipboardData.getData('text');
              if (!pasted.includes('amazon.com/dp/')) return;
              setLookupUrl(pasted);
              setSearchTitle('');
              setSearchAuthor('');
              e.preventDefault();
              setTimeout(() => handleUnifiedSearch(pasted), 300);
            }}
            onBlur={e => {
              const val = e.target.value.trim();
              if (val.includes('amazon.com/dp/') && !searching) {
                setSearchTitle('');
                setSearchAuthor('');
                handleUnifiedSearch(val);
              }
            }}
            placeholder="amazon.com/dp/..."
          />
          <button
            type="button"
            className="libby-admin-btn libby-admin-btn--primary"
            onClick={() => handleUnifiedSearch()}
            disabled={searching || (!searchTitle.trim() && !lookupUrl.trim())}
          >
            {searching ? '…' : 'Search'}
          </button>
        </div>
        {searchError && <div className="libby-admin-error">{searchError}</div>}
        {searched && candidates.length === 0 && !lookupUrl.trim() && (
          <div className="libby-book-no-results">No results — fill fields manually below</div>
        )}
        {candidates.length > 0 && (
          <CandidateGrid candidates={candidates} onConfirm={c => fillFromCandidate(c)} />
        )}
      </div>

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

        {/* Expand toggle */}
        <div className="libby-form-row">
          <button type="button" className="libby-expand-toggle" onClick={() => setExpanded(x => !x)}>
            {expanded ? '− fewer fields ▲' : '+ more fields ▼'}
          </button>
        </div>

        {/* Expanded book fields */}
        {expanded && (
          <>
            <div className="libby-form-row">
              <label className="libby-form-label">obsidian</label>
              <div style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
                <input className="libby-form-input" style={{ flex: 1 }} value={obsidianLink} onChange={e => setObsidianLink(e.target.value)} placeholder="[[Note title]]" spellCheck={false} />
                <VaultFindButton name={name} typeCode="b" onFound={setObsidianLink} />
              </div>
            </div>
            <div className="libby-form-row">
              <label className="libby-form-label">gdoc</label>
              <input className="libby-form-input" value={gdocInput} onChange={e => setGdocInput(e.target.value)} placeholder="GDoc URL or ID…" spellCheck={false} />
            </div>
            <div className="libby-form-row">
              <label className="libby-form-label">genre</label>
              <select className="libby-form-input libby-form-select" value={genre} onChange={e => setGenre(e.target.value)}>
                <option value="">—</option>
                <option value="fiction">fiction</option>
                <option value="nonfiction">nonfiction</option>
                <option value="coaching">coaching</option>
              </select>
            </div>
            <div className="libby-form-row">
              <label className="libby-form-label">status</label>
              <select className="libby-form-input libby-form-select" value={readingStatus} onChange={e => setReadingStatus(e.target.value)}>
                <option value="unread">unread</option>
                <option value="reading">reading</option>
                <option value="read">read</option>
                <option value="discarded">discarded</option>
              </select>
            </div>
            {readingStatus === 'read' && (
              <div className="libby-form-row">
                <label className="libby-form-label">finished</label>
                <input className="libby-form-input libby-form-input--short" value={dateFinished} onChange={e => setDateFinished(e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
            )}
            <div className="libby-form-row">
              <label className="libby-form-label">format</label>
              <select className="libby-form-input libby-form-select" value={ownedFormat} onChange={e => setOwnedFormat(e.target.value)}>
                <option value="">—</option>
                <option value="kindle">kindle</option>
                <option value="audible">audible</option>
                <option value="libro">libro</option>
              </select>
            </div>
            <div className="libby-form-row">
              <label className="libby-form-label">read priority</label>
              <select className="libby-form-input libby-form-select" value={readingPriority} onChange={e => setReadingPriority(e.target.value)}>
                <option value="">—</option>
                <option value="1">1 — high</option>
                <option value="2">2 — medium</option>
              </select>
            </div>
            <div className="libby-form-row">
              <label className="libby-form-label">reading notes</label>
              <textarea className="libby-form-input libby-form-textarea" value={readingNotes} onChange={e => setReadingNotes(e.target.value)} placeholder="Notes on this book…" rows={3} />
            </div>
            <div className="libby-form-row" style={{ alignItems: 'center', gap: '8px' }}>
              <label className="libby-form-label">private</label>
              <input type="checkbox" checked={isPrivate} onChange={e => setIsPrivate(e.target.checked)} style={{ width: 'auto', marginTop: '1px' }} />
            </div>
          </>
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
  initialName,
  initialUrl,
  initialComments,
}: {
  typeCode: string;
  typeName: string;
  onSaved: (name: string) => void;
  initialName?: string;
  initialUrl?: string;
  initialComments?: string;
}) {
  const isQuote   = typeCode === 'q';
  const hasUrl    = URL_TYPES.has(typeCode);
  const isArticle = ARTICLE_TYPES.has(typeCode);
  const isPodcast = typeCode === 'p';
  const isTool    = typeCode === 't';
  const isWebpage = typeCode === 'w';

  // Collapsed fields
  const [name, setName]               = useState(initialName ?? '');
  const [author, setAuthor]           = useState('');
  const [url, setUrl]                 = useState(initialUrl ?? '');
  const [obsidianLink, setObsidianLink] = useState('');
  const [priority, setPriority]       = useState<'high' | 'medium' | 'low'>('medium');
  // Quote-specific collapsed fields
  const [itemText, setItemText]       = useState('');
  const [attribution, setAttribution] = useState('');
  const [context, setContext]         = useState('');

  // Expand/collapse
  const [expanded, setExpanded]       = useState(false);

  // Expanded fields
  const [synopsis, setSynopsis]       = useState(initialComments ?? '');
  const [itemNotes, setItemNotes]     = useState('');
  const [isPrivate, setIsPrivate]     = useState(false);
  const [gdocInput, setGdocInput]     = useState('');
  // Article / essay / research + podcast
  const [publication, setPublication] = useState('');
  const [publishedDate, setPublishedDate] = useState('');
  // Podcast
  const [showName, setShowName]       = useState('');
  const [episode, setEpisode]         = useState('');
  const [host, setHost]               = useState('');
  // Tool
  const [platform, setPlatform]       = useState('');
  const [pricing, setPricing]         = useState('');
  const [vendor, setVendor]           = useState('');
  // Webpage
  const [siteName, setSiteName]       = useState('');

  const [saving, setSaving]           = useState(false);
  const [saveError, setSaveError]     = useState<string | null>(null);

  const resetForm = () => {
    setName(''); setAuthor(''); setUrl(''); setObsidianLink('');
    setPriority('medium'); setItemText(''); setAttribution(''); setContext('');
    setExpanded(false); setSynopsis(''); setItemNotes(''); setIsPrivate(false);
    setGdocInput(''); setPublication(''); setPublishedDate('');
    setShowName(''); setEpisode(''); setHost('');
    setPlatform(''); setPricing(''); setVendor('');
    setSiteName(''); setSaveError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const finalName = isQuote && !name.trim()
      ? itemText.trim().slice(0, 80)
      : name.trim();
    if (!finalName) return;
    setSaving(true);
    setSaveError(null);
    try {
      const resp = await fetch('/api/libby/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: finalName,
          type_code: typeCode,
          url: url.trim() || null,
          priority,
          obsidian_link: obsidianLink.trim() || null,
          gdoc_id: gdocInput.trim() ? extractGdocId(gdocInput.trim()) : null,
          private: isPrivate,
          author: !isQuote ? (author.trim() || null) : null,
          item_text: isQuote ? (itemText.trim() || null) : null,
          attribution: isQuote ? (attribution.trim() || null) : null,
          context: isQuote ? (context.trim() || null) : null,
          synopsis: synopsis.trim() || null,
          notes: itemNotes.trim() || null,
          publication: publication.trim() || null,
          published_date: publishedDate.trim() || null,
          show_name: showName.trim() || null,
          episode: episode.trim() || null,
          host: host.trim() || null,
          site_name: siteName.trim() || null,
          platform: platform.trim() || null,
          pricing: pricing.trim() || null,
          vendor: vendor.trim() || null,
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

  const canSave = isQuote ? (itemText.trim().length > 0 || name.trim().length > 0) : name.trim().length > 0;

  return (
    <form className="libby-new-form" onSubmit={handleSubmit}>
      <div className="libby-new-form-heading">New {typeName}</div>

      {/* Quote text + attribution + context in collapsed (quotes only) */}
      {isQuote && (
        <>
          <div className="libby-form-row">
            <label className="libby-form-label">quote *</label>
            <textarea className="libby-form-input libby-form-textarea" value={itemText} onChange={e => setItemText(e.target.value)} placeholder="Enter the quote…" rows={3} autoFocus />
          </div>
          <div className="libby-form-row">
            <label className="libby-form-label">attribution</label>
            <input className="libby-form-input" value={attribution} onChange={e => setAttribution(e.target.value)} placeholder="Source or author…" />
          </div>
          <div className="libby-form-row">
            <label className="libby-form-label">context</label>
            <input className="libby-form-input" value={context} onChange={e => setContext(e.target.value)} placeholder="Where or when encountered…" />
          </div>
        </>
      )}

      {/* Name */}
      <div className="libby-form-row">
        <label className="libby-form-label">{isQuote ? 'name' : 'name *'}</label>
        <input
          className="libby-form-input"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={isQuote ? 'Optional — defaults to first 80 chars of quote' : 'Title or name'}
          required={!isQuote}
          autoFocus={!isQuote}
          spellCheck={false}
        />
      </div>

      {/* Author (all types except Quote) */}
      {!isQuote && (
        <div className="libby-form-row">
          <label className="libby-form-label">author</label>
          <input className="libby-form-input" value={author} onChange={e => setAuthor(e.target.value)} placeholder="Author name…" spellCheck={false} />
        </div>
      )}

      {/* URL (URL-based types only) */}
      {hasUrl && (
        <div className="libby-form-row">
          <label className="libby-form-label">url</label>
          <input className="libby-form-input" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" spellCheck={false} />
        </div>
      )}

      {/* Obsidian link */}
      <div className="libby-form-row">
        <label className="libby-form-label">obsidian</label>
        <div style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
          <input className="libby-form-input" style={{ flex: 1 }} value={obsidianLink} onChange={e => setObsidianLink(e.target.value)} placeholder="[[Note title]]" spellCheck={false} />
          <VaultFindButton name={name} typeCode={typeCode} onFound={setObsidianLink} />
        </div>
      </div>

      {/* Priority */}
      <div className="libby-form-row">
        <label className="libby-form-label">priority</label>
        <select className="libby-form-input libby-form-select" value={priority} onChange={e => setPriority(e.target.value as 'high' | 'medium' | 'low')}>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
      </div>

      {/* Expand toggle */}
      <div className="libby-form-row">
        <button type="button" className="libby-expand-toggle" onClick={() => setExpanded(x => !x)}>
          {expanded ? '− fewer fields ▲' : '+ more fields ▼'}
        </button>
      </div>

      {/* Expanded fields */}
      {expanded && (
        <>
          <div className="libby-form-row">
            <label className="libby-form-label">synopsis</label>
            <textarea className="libby-form-input libby-form-textarea" value={synopsis} onChange={e => setSynopsis(e.target.value)} placeholder="Brief summary…" rows={3} />
          </div>
          <div className="libby-form-row">
            <label className="libby-form-label">notes</label>
            <textarea className="libby-form-input libby-form-textarea" value={itemNotes} onChange={e => setItemNotes(e.target.value)} placeholder="Private notes…" rows={2} />
          </div>
          <div className="libby-form-row">
            <label className="libby-form-label">gdoc</label>
            <input className="libby-form-input" value={gdocInput} onChange={e => setGdocInput(e.target.value)} placeholder="GDoc URL or ID…" spellCheck={false} />
          </div>
          <div className="libby-form-row" style={{ alignItems: 'center', gap: '8px' }}>
            <label className="libby-form-label">private</label>
            <input type="checkbox" checked={isPrivate} onChange={e => setIsPrivate(e.target.checked)} style={{ width: 'auto', marginTop: '1px' }} />
          </div>

          {/* Article / Essay / Research */}
          {isArticle && (
            <>
              <div className="libby-form-row">
                <label className="libby-form-label">publication</label>
                <input className="libby-form-input" value={publication} onChange={e => setPublication(e.target.value)} placeholder="Publication name…" />
              </div>
              <div className="libby-form-row">
                <label className="libby-form-label">published</label>
                <input className="libby-form-input libby-form-input--short" value={publishedDate} onChange={e => setPublishedDate(e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
            </>
          )}

          {/* Podcast */}
          {isPodcast && (
            <>
              <div className="libby-form-row">
                <label className="libby-form-label">show</label>
                <input className="libby-form-input" value={showName} onChange={e => setShowName(e.target.value)} placeholder="Show name…" />
              </div>
              <div className="libby-form-row">
                <label className="libby-form-label">episode</label>
                <input className="libby-form-input" value={episode} onChange={e => setEpisode(e.target.value)} placeholder="Episode title or number…" />
              </div>
              <div className="libby-form-row">
                <label className="libby-form-label">host</label>
                <input className="libby-form-input" value={host} onChange={e => setHost(e.target.value)} placeholder="Host name…" />
              </div>
              <div className="libby-form-row">
                <label className="libby-form-label">published</label>
                <input className="libby-form-input libby-form-input--short" value={publishedDate} onChange={e => setPublishedDate(e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
            </>
          )}

          {/* Tool */}
          {isTool && (
            <>
              <div className="libby-form-row">
                <label className="libby-form-label">platform</label>
                <input className="libby-form-input" value={platform} onChange={e => setPlatform(e.target.value)} placeholder="macOS, web, iOS…" />
              </div>
              <div className="libby-form-row">
                <label className="libby-form-label">pricing</label>
                <input className="libby-form-input" value={pricing} onChange={e => setPricing(e.target.value)} placeholder="free, $9/mo…" />
              </div>
              <div className="libby-form-row">
                <label className="libby-form-label">vendor</label>
                <input className="libby-form-input" value={vendor} onChange={e => setVendor(e.target.value)} placeholder="Company or maker…" />
              </div>
            </>
          )}

          {/* Webpage */}
          {isWebpage && (
            <div className="libby-form-row">
              <label className="libby-form-label">site</label>
              <input className="libby-form-input" value={siteName} onChange={e => setSiteName(e.target.value)} placeholder="Site name…" />
            </div>
          )}
        </>
      )}

      {saveError && <div className="libby-admin-error">{saveError}</div>}
      <div className="libby-form-actions">
        <button type="submit" className="libby-admin-btn libby-admin-btn--primary" disabled={saving || !canSave}>
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
  const [searchParams] = useSearchParams();

  const [selectedType, setSelectedType] = useState<string | null>(() => {
    const t = searchParams.get('type');
    const valid = new Set(ALL_TYPES.map(x => x.code));
    return t && valid.has(t) ? t : null;
  });
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [topics, setTopics] = useState<LibraryTopic[]>([]);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  // Inbox state
  const [inbox, setInbox] = useState<InboxEntry[]>([]);
  const [classifyingEntry, setClassifyingEntry] = useState<InboxEntry | null>(null);

  const loadQueue = () => {
    fetch('/api/libby/queue')
      .then(r => r.ok ? r.json() : { entries: [], count: 0 })
      .then(d => { setQueue(d.entries ?? []); setLoadingQueue(false); })
      .catch(() => setLoadingQueue(false));
  };

  const loadInbox = () => {
    fetch('/api/libby/inbox')
      .then(r => r.ok ? r.json() : { entries: [] })
      .then(d => setInbox(d.entries ?? []))
      .catch(() => {});
  };

  useEffect(loadQueue, []);
  useEffect(loadInbox, []);

  // Poll every 3s while any entry is still pending/processing
  useEffect(() => {
    const hasActive = queue.some(e => e.status === 'pending' || e.status === 'processing');
    if (!hasActive) return;
    const timer = setInterval(loadQueue, 3000);
    return () => clearInterval(timer);
  }, [queue]);

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
    setClassifyingEntry(null);
    setSaveSuccess(null);
  };

  const handleInboxClick = (entry: InboxEntry) => {
    setClassifyingEntry(entry);
    setSelectedType(null);  // show type selector first
    setSaveSuccess(null);
  };

  const handleDismissInbox = async (entryId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    await fetch(`/api/libby/inbox/${entryId}`, { method: 'DELETE' });
    setInbox(prev => prev.filter(x => x.id !== entryId));
    if (classifyingEntry?.id === entryId) setClassifyingEntry(null);
  };

  // Keyboard shortcuts: Escape deselects type; letter keys select type when none is active
  const TYPE_CODES = new Set(ALL_TYPES.map(t => t.code));
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement)?.tagName ?? '';
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

      if (e.key === 'Escape') {
        if (!inInput) { setSelectedType(null); setClassifyingEntry(null); }
        return;
      }

      // Type-letter selection: only when no type is selected and focus is not in a form field
      if (!selectedType && !inInput && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const key = e.key.toLowerCase();
        if (TYPE_CODES.has(key)) {
          e.preventDefault();
          setSelectedType(key);
          setSaveSuccess(null);
        }
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [selectedType]);

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
    // Dismiss inbox entry if we were classifying one
    if (classifyingEntry) {
      fetch(`/api/libby/inbox/${classifyingEntry.id}`, { method: 'DELETE' }).catch(() => {});
      setInbox(prev => prev.filter(x => x.id !== classifyingEntry.id));
      setClassifyingEntry(null);
      setSelectedType(null);
    }
  };

  const selectedTypeDef = ALL_TYPES.find(t => t.code === selectedType);

  // Key to force form remount when classifying entry changes
  const formKey = classifyingEntry ? `inbox-${classifyingEntry.id}-${selectedType}` : `new-${selectedType}`;

  return (
    <div className="libby-new-page">

      {/* ── Inbox section ── */}
      {inbox.length > 0 && (
        <div className="libby-inbox-section">
          <div className="libby-inbox-header">
            Inbox
            <span className="libby-inbox-count">{inbox.length}</span>
          </div>
          <div className="libby-inbox-list">
            {inbox.map(entry => (
              <div
                key={entry.id}
                className={`libby-inbox-item${classifyingEntry?.id === entry.id ? ' libby-inbox-item--active' : ''}`}
                onClick={() => handleInboxClick(entry)}
                role="button"
                tabIndex={0}
                onKeyDown={e => { if (e.key === 'Enter') handleInboxClick(entry); }}
              >
                <span className="libby-inbox-item-name">{entry.name}</span>
                <span className="libby-inbox-item-meta">
                  {entry.ingest_source === 'file' ? '📄' : '🔗'}
                  {' '}
                  {entry.ingest_original || entry.url || ''}
                </span>
                <span className="libby-inbox-item-time">{_relTime(entry.created_at)}</span>
                <button
                  className="libby-inbox-item-dismiss"
                  title="Dismiss"
                  onClick={e => handleDismissInbox(entry.id, e)}
                >×</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Type selector ── */}
      {classifyingEntry && !selectedType && (
        <div className="libby-inbox-classifying-banner">
          Classifying: <strong>{classifyingEntry.name}</strong>
          <button className="libby-cancel-type" onClick={handleCancelType} title="Cancel">✕</button>
        </div>
      )}
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
            <span className="libby-form-type-label">
              {classifyingEntry ? `Classifying: ${classifyingEntry.name}` : selectedTypeDef.name}
            </span>
            <button className="libby-cancel-type" onClick={handleCancelType} title="Cancel (Escape)">✕</button>
          </div>
          {selectedType === 'b' ? (
            <BookCreationForm
              key={formKey}
              topics={topics}
              onSaved={handleSaved}
              initialName={classifyingEntry?.name}
              initialUrl={classifyingEntry?.url ?? undefined}
              initialComments={classifyingEntry?.comments ?? undefined}
            />
          ) : (
            <GenericCreationForm
              key={formKey}
              typeCode={selectedType}
              typeName={selectedTypeDef.name}
              onSaved={handleSaved}
              initialName={classifyingEntry?.name}
              initialUrl={classifyingEntry?.url ?? undefined}
              initialComments={classifyingEntry?.comments ?? undefined}
            />
          )}
        </div>
      ) : (
        !classifyingEntry && <div className="libby-new-prompt">Select a type above to add a new entry</div>
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
