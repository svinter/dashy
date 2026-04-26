import { useState, useMemo, useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api, openExternal } from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ReadingView = 'all' | 'now' | 'queue' | 'read' | 'discarded';

interface BookTopic {
  code: string;
  name: string;
}

interface ReadingBook {
  entry_id: number;
  title: string;
  amazon_url: string | null;
  amazon_short_url: string | null;
  obsidian_link: string | null;
  book_id: number;
  author: string | null;
  status: string;
  genre: string | null;
  owned_format: string | null;
  reading_priority: number | null;
  reading_notes: string | null;
  date_finished: string | null;
  date_added: string | null;
  year: number | null;
  publisher: string | null;
  isbn: string | null;
  subtitle: string | null;
  summary_path: string | null;
  gdoc_summary_id: string | null;
  highlights_path: string | null;
  external_summary_url: string | null;
  topics: BookTopic[];
}

interface ReadingResponse {
  books: ReadingBook[];
  view: ReadingView;
  count: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VIEWS: { id: ReadingView; label: string; key: string }[] = [
  { id: 'all',       label: 'All',       key: 'a' },
  { id: 'now',       label: 'Now',       key: 'n' },
  { id: 'queue',     label: 'Queue',     key: 'q' },
  { id: 'read',      label: 'Read',      key: 'r' },
  { id: 'discarded', label: 'Discarded', key: 'd' },
];

const VIEW_KEY_MAP: Record<string, ReadingView> = {
  a: 'all', n: 'now', q: 'queue', r: 'read', d: 'discarded',
};

const GENRE_OPTIONS = ['All', 'Fiction', 'Nonfiction', 'Coaching'];
const FORMAT_OPTIONS = ['All', 'Kindle', 'Audible', 'Libro', 'Unowned'];
const PRIORITY_OPTIONS = ['All', 'High', 'Medium', 'Normal'];

const FORMAT_ICON: Record<string, string> = {
  kindle:  '📱',
  audible: '🎧',
  libro:   '📖',
};

const STATUS_LABEL: Record<string, string> = {
  unread:    'unread',
  reading:   'reading',
  read:      'read',
  discarded: 'discarded',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function finishYear(dateStr: string | null): string | null {
  if (!dateStr) return null;
  return dateStr.slice(0, 4);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function isoToDisplay(iso: string): string {
  // "2025-01-15" → "01/15/25"
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return iso;
  return `${m[2]}/${m[3]}/${m[1].slice(2)}`;
}

function displayToIso(display: string): string | null {
  // "01/15/25" → "2025-01-15"
  const m = display.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
  if (!m) return null;
  const year = m[3].length === 2 ? `20${m[3]}` : m[3];
  const month = m[1].padStart(2, '0');
  const day = m[2].padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function ReadingRow({
  book,
  view,
  expanded,
  onToggle,
  onStatusChange,
  onCatalogNav,
}: {
  book: ReadingBook;
  view: ReadingView;
  expanded: boolean;
  onToggle: () => void;
  onStatusChange: (entryId: number, status: string, dateFinished?: string) => void;
  onCatalogNav: () => void;
}) {
  const [showReadPrompt, setShowReadPrompt] = useState(false);
  const [readDate, setReadDate] = useState('');

  const handleReadClick = () => {
    setReadDate(isoToDisplay(todayIso()));
    setShowReadPrompt(true);
  };

  const handleReadConfirm = () => {
    const iso = displayToIso(readDate);
    onStatusChange(book.entry_id, 'read', iso ?? undefined);
    setShowReadPrompt(false);
  };

  const handleReadCancel = () => {
    setShowReadPrompt(false);
  };

  const formatIcon = book.owned_format
    ? FORMAT_ICON[book.owned_format.toLowerCase()] ?? null
    : null;

  const shortNote = book.reading_notes
    ? book.reading_notes.length > 60
      ? book.reading_notes.slice(0, 60) + '…'
      : book.reading_notes
    : null;

  const amazonUrl = book.amazon_short_url ?? book.amazon_url;

  // Collapsed columns vary by view
  const colCount = view === 'read' || view === 'all' ? 6 : 5;

  return (
    <>
      <tr
        className={`libby-reading-row${expanded ? ' libby-reading-row--open' : ''}`}
        onClick={onToggle}
      >
        <td className="libby-reading-title">
          <span className="libby-reading-title-text">{book.title}</span>
          {book.author && <span className="libby-reading-author"> by {book.author}</span>}
        </td>
        {view === 'all' && (
          <td className="libby-reading-status-cell">
            <span className={`libby-reading-status-badge libby-reading-status-badge--${book.status}`}>
              {STATUS_LABEL[book.status] ?? book.status}
            </span>
          </td>
        )}
        <td className="libby-reading-genre">
          {book.genre && <span className="libby-reading-genre-badge">{book.genre}</span>}
        </td>
        <td className="libby-reading-format">
          {formatIcon && <span title={book.owned_format ?? undefined}>{formatIcon}</span>}
        </td>
        {view === 'read' && (
          <td className="libby-reading-finished">{book.date_finished ?? '—'}</td>
        )}
        <td className="libby-reading-note">
          {shortNote && <span className="libby-reading-note-text">{shortNote}</span>}
        </td>
        <td className="libby-reading-links" onClick={e => e.stopPropagation()}>
          {amazonUrl && (
            <button className="libby-result-quick-link" title="Amazon" onClick={() => openExternal(amazonUrl!)}>🔗</button>
          )}
          {book.obsidian_link && (
            <button className="libby-result-quick-link" title="Vault" onClick={() => openExternal(book.obsidian_link!)}>📓</button>
          )}
          <button className="libby-result-quick-link" title="Catalog" onClick={onCatalogNav}>📚</button>
        </td>
      </tr>

      {expanded && (
        <tr className="libby-reading-detail-row">
          <td colSpan={colCount}>
            <div className="libby-reading-detail">

              {/* Metadata */}
              <div className="libby-reading-detail-meta">
                <div className="libby-reading-detail-title">{book.title}</div>
                {book.subtitle && (
                  <div className="libby-reading-detail-subtitle">{book.subtitle}</div>
                )}
                {book.author && (
                  <div className="libby-reading-detail-field">
                    <span className="libby-reading-detail-label">Author</span> {book.author}
                  </div>
                )}
                {book.year && (
                  <div className="libby-reading-detail-field">
                    <span className="libby-reading-detail-label">Year</span> {book.year}
                    {book.publisher && <span> · {book.publisher}</span>}
                  </div>
                )}
                {book.isbn && (
                  <div className="libby-reading-detail-field">
                    <span className="libby-reading-detail-label">ISBN</span> {book.isbn}
                  </div>
                )}
                {(book.genre || book.owned_format || book.reading_priority) && (
                  <div className="libby-reading-detail-field">
                    {book.genre && <span className="libby-reading-genre-badge">{book.genre}</span>}
                    {book.owned_format && <span style={{ marginLeft: 6 }}>{formatIcon} {book.owned_format}</span>}
                    {book.reading_priority && <span style={{ marginLeft: 6 }} className="libby-reading-detail-label">priority {book.reading_priority}</span>}
                  </div>
                )}
                {book.topics.length > 0 && (
                  <div className="libby-reading-detail-field">
                    <span className="libby-reading-detail-label">Topics</span>{' '}
                    {book.topics.map(t => t.name).join(', ')}
                  </div>
                )}
                {book.reading_notes && (
                  <div className="libby-reading-detail-notes">{book.reading_notes}</div>
                )}
              </div>

              {/* Links */}
              <div className="libby-reading-detail-links" onClick={e => e.stopPropagation()}>
                {amazonUrl && (
                  <button className="libby-reading-detail-link-btn" onClick={() => openExternal(amazonUrl!)}>🔗 Amazon</button>
                )}
                {book.obsidian_link && (
                  <button className="libby-reading-detail-link-btn" onClick={() => openExternal(book.obsidian_link!)}>📓 Vault</button>
                )}
                <button className="libby-reading-detail-link-btn" onClick={onCatalogNav}>📚 Catalog</button>
                {book.gdoc_summary_id && (
                  <button className="libby-reading-detail-link-btn" onClick={() => openExternal(`https://docs.google.com/document/d/${book.gdoc_summary_id}`)}>📄 My Summary</button>
                )}
                {book.external_summary_url && (
                  <button className="libby-reading-detail-link-btn" onClick={() => openExternal(book.external_summary_url!)}>🌐 Summary</button>
                )}
              </div>

              {/* Status actions */}
              <div className="libby-reading-detail-actions" onClick={e => e.stopPropagation()}>
                {showReadPrompt ? (
                  <div className="libby-reading-date-prompt"
                    onKeyDown={e => {
                      if (e.key === 'Enter') { e.preventDefault(); handleReadConfirm(); }
                      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); handleReadCancel(); }
                    }}
                  >
                    <span className="libby-reading-date-prompt-label">Mark as read — Date finished:</span>
                    <input
                      className="libby-reading-date-input"
                      type="text"
                      placeholder="MM/DD/YY"
                      value={readDate}
                      onChange={e => setReadDate(e.target.value)}
                      autoFocus
                    />
                    <button className="libby-reading-date-confirm-btn" onClick={handleReadConfirm}>Confirm</button>
                    <button className="libby-reading-date-cancel-btn" onClick={handleReadCancel}>Cancel</button>
                  </div>
                ) : (
                  <>
                    {book.status !== 'reading' && (
                      <button className="libby-reading-status-btn" onClick={() => onStatusChange(book.entry_id, 'reading')}>▶ Reading</button>
                    )}
                    {book.status !== 'read' && (
                      <button className="libby-reading-status-btn" onClick={handleReadClick}>✓ Read</button>
                    )}
                    {book.status !== 'discarded' && (
                      <button className="libby-reading-status-btn libby-reading-status-btn--abandon" onClick={() => onStatusChange(book.entry_id, 'discarded')}>✗ Discard</button>
                    )}
                    {book.status !== 'unread' && (
                      <button className="libby-reading-status-btn" onClick={() => onStatusChange(book.entry_id, 'unread')}>↩ Unread</button>
                    )}
                  </>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function LibbyReadingPage() {
  const [view, setView] = useState<ReadingView>('queue');
  const [search, setSearch] = useState('');
  const [genreFilter, setGenreFilter] = useState('All');
  const [formatFilter, setFormatFilter] = useState('All');
  const [priorityFilter, setPriorityFilter] = useState('All');
  const [expandedEntryId, setExpandedEntryId] = useState<number | null>(null);

  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const filteredRef = useRef<ReadingBook[]>([]);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading } = useQuery<ReadingResponse>({
    queryKey: ['libby-reading', view],
    queryFn: () => api.get<ReadingResponse>(`/libby/reading?view=${view}`),
    staleTime: 60_000,
  });

  const books = data?.books ?? [];

  const filtered = useMemo(() => {
    let result = books;

    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        b =>
          b.title.toLowerCase().includes(q) ||
          (b.author && b.author.toLowerCase().includes(q))
      );
    }

    if (genreFilter !== 'All') {
      result = result.filter(b => b.genre?.toLowerCase() === genreFilter.toLowerCase());
    }

    if (formatFilter !== 'All') {
      if (formatFilter === 'Unowned') {
        result = result.filter(b => !b.owned_format);
      } else {
        result = result.filter(b => b.owned_format?.toLowerCase() === formatFilter.toLowerCase());
      }
    }

    if (priorityFilter !== 'All') {
      const pMap: Record<string, number> = { High: 1, Medium: 2, Normal: 3 };
      const p = pMap[priorityFilter];
      result = result.filter(b => b.reading_priority === p);
    }

    return result;
  }, [books, search, genreFilter, formatFilter, priorityFilter]);

  // Keep ref in sync for use inside keyboard handler
  filteredRef.current = filtered;

  // Group by year for 'read' view
  const groupedRead = useMemo(() => {
    if (view !== 'read') return null;
    const groups: Record<string, ReadingBook[]> = {};
    for (const b of filtered) {
      const yr = finishYear(b.date_finished) ?? 'Previously read';
      if (!groups[yr]) groups[yr] = [];
      groups[yr].push(b);
    }
    return groups;
  }, [view, filtered]);

  const handleStatusChange = async (entryId: number, status: string, dateFinished?: string) => {
    const body: { status: string; date_finished?: string } = { status };
    if (dateFinished) body.date_finished = dateFinished;
    await api.patch(`/libby/reading/${entryId}/status`, body);
    queryClient.invalidateQueries({ queryKey: ['libby-reading'] });
    setExpandedEntryId(null);
  };

  const handleCatalogNav = (title: string) => {
    navigate(`/libby/catalog?q=${encodeURIComponent(title)}`);
  };

  const handleToggle = (entryId: number) => {
    setExpandedEntryId(prev => (prev === entryId ? null : entryId));
  };

  // Keyboard shortcuts: a/n/q/r/d = switch view; e = open expanded book in Catalog
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (VIEW_KEY_MAP[e.key]) {
        e.stopImmediatePropagation();
        e.preventDefault();
        setView(VIEW_KEY_MAP[e.key]);
        setExpandedEntryId(null);
        return;
      }

      if (e.key === 'e' && expandedEntryId !== null) {
        const book = filteredRef.current.find(b => b.entry_id === expandedEntryId);
        if (book) {
          e.stopImmediatePropagation();
          e.preventDefault();
          navigate(`/libby/catalog?q=${encodeURIComponent(book.title)}`);
        }
        return;
      }

      if (e.key === 's') {
        e.stopImmediatePropagation();
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
        return;
      }
    };
    document.addEventListener('keydown', handler, true); // capture → fires before global shortcuts
    return () => document.removeEventListener('keydown', handler, true);
  }, [expandedEntryId, navigate]);

  // Table headers depend on view
  const tableHeaders = (
    <tr>
      <th>Title</th>
      {view === 'all' && <th>Status</th>}
      <th></th>
      <th></th>
      {view === 'read' && <th>Finished</th>}
      <th>Note</th>
      <th></th>
    </tr>
  );

  const renderRows = (rowBooks: ReadingBook[]) =>
    rowBooks.map(b => (
      <ReadingRow
        key={b.entry_id}
        book={b}
        view={view}
        expanded={expandedEntryId === b.entry_id}
        onToggle={() => handleToggle(b.entry_id)}
        onStatusChange={handleStatusChange}
        onCatalogNav={() => handleCatalogNav(b.title)}
      />
    ));

  return (
    <div className="libby-reading-page">
      {/* View tabs */}
      <div className="libby-reading-view-bar">
        {VIEWS.map(v => (
          <button
            key={v.id}
            className={`libby-reading-view-btn${view === v.id ? ' libby-reading-view-btn--active' : ''}`}
            onClick={() => { setView(v.id); setExpandedEntryId(null); }}
            title={`${v.key} key`}
          >
            {v.label}
          </button>
        ))}

        <div className="libby-reading-search-wrap">
          <input
            ref={searchInputRef}
            className="libby-reading-search"
            type="text"
            placeholder="search…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Escape') {
                setSearch('');
                e.currentTarget.blur();
                e.stopPropagation();
              }
            }}
          />
        </div>
      </div>

      {/* Filter bar */}
      <div className="libby-reading-filter-bar">
        <select className="libby-reading-filter-select" value={genreFilter} onChange={e => setGenreFilter(e.target.value)}>
          {GENRE_OPTIONS.map(o => <option key={o}>{o === 'All' ? 'All genres' : o}</option>)}
        </select>
        <select className="libby-reading-filter-select" value={formatFilter} onChange={e => setFormatFilter(e.target.value)}>
          {FORMAT_OPTIONS.map(o => <option key={o}>{o === 'All' ? 'All formats' : o}</option>)}
        </select>
        <select className="libby-reading-filter-select" value={priorityFilter} onChange={e => setPriorityFilter(e.target.value)}>
          {PRIORITY_OPTIONS.map(o => <option key={o}>{o === 'All' ? 'All priorities' : o}</option>)}
        </select>
        {data && (
          <span className="libby-reading-count">{filtered.length} of {data.count}</span>
        )}
      </div>

      {isLoading && <div className="libby-reading-loading">Loading…</div>}

      {!isLoading && filtered.length === 0 && (
        <div className="libby-reading-empty">No books.</div>
      )}

      {/* Non-read (and All) views */}
      {!isLoading && filtered.length > 0 && view !== 'read' && (
        <table className="libby-reading-table">
          <thead>{tableHeaders}</thead>
          <tbody>{renderRows(filtered)}</tbody>
        </table>
      )}

      {/* Read view — grouped by year */}
      {!isLoading && view === 'read' && groupedRead && filtered.length > 0 && (
        <>
          {Object.entries(groupedRead)
            .sort(([a], [b]) =>
              a === 'Previously read' ? 1
              : b === 'Previously read' ? -1
              : b.localeCompare(a)
            )
            .map(([year, yearBooks]) => (
              <div key={year} className="libby-reading-year-group">
                <div className="libby-reading-year-label">{year}</div>
                <table className="libby-reading-table">
                  <thead>{tableHeaders}</thead>
                  <tbody>{renderRows(yearBooks)}</tbody>
                </table>
              </div>
            ))}
        </>
      )}
    </div>
  );
}
