import { useState, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, openExternal } from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ReadingView = 'now' | 'queue' | 'read' | 'abandoned';

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
}

interface ReadingResponse {
  books: ReadingBook[];
  view: ReadingView;
  count: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VIEWS: { id: ReadingView; label: string }[] = [
  { id: 'now',       label: 'Now' },
  { id: 'queue',     label: 'Queue' },
  { id: 'read',      label: 'Read' },
  { id: 'abandoned', label: 'Abandoned' },
];

const GENRE_OPTIONS = ['All', 'Fiction', 'Nonfiction', 'Coaching'];
const FORMAT_OPTIONS = ['All', 'Kindle', 'Audible', 'Libro', 'Unowned'];
const PRIORITY_OPTIONS = ['All', 'High', 'Medium', 'Normal'];

const FORMAT_ICON: Record<string, string> = {
  kindle:  '📱',
  audible: '🎧',
  libro:   '📖',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function finishYear(dateStr: string | null): string | null {
  if (!dateStr) return null;
  return dateStr.slice(0, 4);
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function ReadingRow({
  book,
  view,
  onStatusChange,
}: {
  book: ReadingBook;
  view: ReadingView;
  onStatusChange: (entryId: number, status: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const formatIcon = book.owned_format
    ? FORMAT_ICON[book.owned_format.toLowerCase()] ?? null
    : null;

  const shortNote = book.reading_notes
    ? book.reading_notes.length > 60
      ? book.reading_notes.slice(0, 60) + '…'
      : book.reading_notes
    : null;

  return (
    <>
      <tr
        className={`libby-reading-row${expanded ? ' libby-reading-row--open' : ''}`}
        onClick={() => setExpanded(o => !o)}
      >
        <td className="libby-reading-title">
          <span className="libby-reading-title-text">{book.title}</span>
          {book.author && <span className="libby-reading-author"> by {book.author}</span>}
        </td>
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
          {book.amazon_short_url && (
            <button
              className="libby-result-quick-link"
              title="Amazon"
              onClick={() => openExternal(book.amazon_short_url!)}
            >🔗</button>
          )}
          {book.obsidian_link && (
            <button
              className="libby-result-quick-link"
              title="Vault"
              onClick={() => openExternal(book.obsidian_link!)}
            >📓</button>
          )}
        </td>
      </tr>

      {expanded && (
        <tr className="libby-reading-detail-row">
          <td colSpan={view === 'read' ? 6 : 5}>
            <div className="libby-reading-detail">
              {book.reading_notes && (
                <div className="libby-reading-detail-notes">{book.reading_notes}</div>
              )}
              <div className="libby-reading-detail-actions" onClick={e => e.stopPropagation()}>
                {book.status !== 'reading' && (
                  <button
                    className="libby-reading-status-btn"
                    onClick={() => onStatusChange(book.entry_id, 'reading')}
                  >▶ Reading</button>
                )}
                {book.status !== 'read' && (
                  <button
                    className="libby-reading-status-btn"
                    onClick={() => onStatusChange(book.entry_id, 'read')}
                  >✓ Read</button>
                )}
                {book.status !== 'abandoned' && (
                  <button
                    className="libby-reading-status-btn libby-reading-status-btn--abandon"
                    onClick={() => onStatusChange(book.entry_id, 'abandoned')}
                  >✗ Abandon</button>
                )}
                {book.status !== 'unread' && (
                  <button
                    className="libby-reading-status-btn"
                    onClick={() => onStatusChange(book.entry_id, 'unread')}
                  >↩ Unread</button>
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

  const queryClient = useQueryClient();

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
      const pMap: Record<string, number | null> = { High: 1, Medium: 2, Normal: 3 };
      const p = pMap[priorityFilter];
      result = result.filter(b => b.reading_priority === p);
    }

    return result;
  }, [books, search, genreFilter, formatFilter, priorityFilter]);

  // Group by year for 'read' view
  const groupedRead = useMemo(() => {
    if (view !== 'read') return null;
    const groups: Record<string, ReadingBook[]> = {};
    for (const b of filtered) {
      const yr = finishYear(b.date_finished) ?? 'Unknown';
      if (!groups[yr]) groups[yr] = [];
      groups[yr].push(b);
    }
    return groups;
  }, [view, filtered]);

  const handleStatusChange = async (entryId: number, status: string) => {
    await api.patch(`/libby/reading/${entryId}/status`, { status });
    queryClient.invalidateQueries({ queryKey: ['libby-reading'] });
  };

  const tableHeaders = (
    <tr>
      <th>Title</th>
      <th></th>
      <th></th>
      {view === 'read' && <th>Finished</th>}
      <th>Note</th>
      <th></th>
    </tr>
  );

  return (
    <div className="libby-reading-page">
      {/* View tabs */}
      <div className="libby-reading-view-bar">
        {VIEWS.map(v => (
          <button
            key={v.id}
            className={`libby-reading-view-btn${view === v.id ? ' libby-reading-view-btn--active' : ''}`}
            onClick={() => setView(v.id)}
          >
            {v.label}
          </button>
        ))}

        <div className="libby-reading-search-wrap">
          <input
            className="libby-reading-search"
            type="text"
            placeholder="search…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Filter bar */}
      <div className="libby-reading-filter-bar">
        <select
          className="libby-reading-filter-select"
          value={genreFilter}
          onChange={e => setGenreFilter(e.target.value)}
        >
          {GENRE_OPTIONS.map(o => (
            <option key={o}>{o === 'All' ? 'All genres' : o}</option>
          ))}
        </select>
        <select
          className="libby-reading-filter-select"
          value={formatFilter}
          onChange={e => setFormatFilter(e.target.value)}
        >
          {FORMAT_OPTIONS.map(o => (
            <option key={o}>{o === 'All' ? 'All formats' : o}</option>
          ))}
        </select>
        <select
          className="libby-reading-filter-select"
          value={priorityFilter}
          onChange={e => setPriorityFilter(e.target.value)}
        >
          {PRIORITY_OPTIONS.map(o => (
            <option key={o}>{o === 'All' ? 'All priorities' : o}</option>
          ))}
        </select>
        {data && (
          <span className="libby-reading-count">{filtered.length} of {data.count}</span>
        )}
      </div>

      {/* Table */}
      {isLoading && <div className="libby-reading-loading">Loading…</div>}

      {!isLoading && filtered.length === 0 && (
        <div className="libby-reading-empty">No books.</div>
      )}

      {!isLoading && filtered.length > 0 && view !== 'read' && (
        <table className="libby-reading-table">
          <thead>{tableHeaders}</thead>
          <tbody>
            {filtered.map(b => (
              <ReadingRow
                key={b.entry_id}
                book={b}
                view={view}
                onStatusChange={handleStatusChange}
              />
            ))}
          </tbody>
        </table>
      )}

      {!isLoading && view === 'read' && groupedRead && (
        <>
          {Object.entries(groupedRead)
            .sort(([a], [b]) => (a === 'Unknown' ? 1 : b === 'Unknown' ? -1 : b.localeCompare(a)))
            .map(([year, yearBooks]) => (
              <div key={year} className="libby-reading-year-group">
                <div className="libby-reading-year-label">{year}</div>
                <table className="libby-reading-table">
                  <thead>{tableHeaders}</thead>
                  <tbody>
                    {yearBooks.map(b => (
                      <ReadingRow
                        key={b.entry_id}
                        book={b}
                        view={view}
                        onStatusChange={handleStatusChange}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
        </>
      )}
    </div>
  );
}
