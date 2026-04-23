import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionEntry {
  time: string;
  client: string;
  company: string;
  session_number: number | null;
}

interface NoteCreation {
  daily_created?: number;
  meeting_created?: number;
  meeting_updated?: number;
  skipped?: number;
  log?: Array<{ status: string; filename: string; reason?: string }>;
  error?: string;
}

interface GranolaSync {
  fetched?: number;
  matched?: number;
  written?: number;
  skipped?: number;
  unmatched?: string[];
}

interface UnprocessedSession {
  date: string;
  client: string;
  company: string;
}

interface BackupEntry {
  label: string;
  name: string;
  size: string;
  modified: string;
}

interface DigestRun {
  id: number;
  run_date: string;
  sent_at: string;
  today_sessions: SessionEntry[] | null;
  tomorrow_sessions: SessionEntry[] | null;
  note_creation: NoteCreation | null;
  granola_sync: GranolaSync | null;
  unprocessed_sessions: UnprocessedSession[] | null;
  backup_summary: BackupEntry[] | null;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchDigestRuns(): Promise<DigestRun[]> {
  const res = await fetch('/api/reports/digests');
  if (!res.ok) throw new Error('Failed to load digest runs');
  return res.json();
}

function useDigestRuns() {
  return useQuery<DigestRun[]>({
    queryKey: ['reports-digests'],
    queryFn: fetchDigestRuns,
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Date formatting
// ---------------------------------------------------------------------------

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const DAY_ABBR   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

function formatRunDate(isoDate: string): string {
  try {
    const [y, m, d] = isoDate.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    const dow = DAY_ABBR[dt.getDay() === 0 ? 6 : dt.getDay() - 1];
    return `${dow} ${MONTH_ABBR[m - 1]} ${d}`;
  } catch {
    return isoDate;
  }
}

// ---------------------------------------------------------------------------
// Sub-section renderers
// ---------------------------------------------------------------------------

function SessionTable({ sessions }: { sessions: SessionEntry[] }) {
  if (!sessions.length) return <p className="reports-none">No sessions.</p>;
  return (
    <table className="reports-table">
      <tbody>
        {sessions.map((s, i) => (
          <tr key={i}>
            <td className="reports-td-time">{s.time}</td>
            <td>{s.client}{s.company ? ` · ${s.company}` : ''}</td>
            <td className="reports-td-sno">{s.session_number ? `#${s.session_number}` : ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NoteCreationSection({ data }: { data: NoteCreation }) {
  if (data.error) return <p className="reports-none">Error: {data.error}</p>;
  const { daily_created = 0, meeting_created = 0, meeting_updated = 0, skipped = 0, log = [] } = data;
  const created = log.filter(e => e.status === 'created');
  return (
    <div>
      <p className="reports-stat-line">
        <span className="reports-stat-num">{daily_created}</span> daily
        {' · '}
        <span className="reports-stat-num">{meeting_created}</span> meeting notes created
        {' · '}
        <span className="reports-stat-num">{meeting_updated}</span> updated
        {' · '}
        <span className="reports-stat-num">{skipped}</span> skipped
      </p>
      {created.length > 0 && (
        <ul className="reports-file-list">
          {created.map((e, i) => {
            const stem = e.filename.replace('.md', '');
            const parts = stem.includes(' - ') ? stem.split(' - ') : [stem];
            return (
              <li key={i}>
                {parts.length === 2
                  ? <>{parts[0]} &mdash; {parts[1]}</>
                  : stem}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function GranolaSection({ data }: { data: GranolaSync }) {
  const { fetched = 0, matched = 0, written = 0, skipped = 0, unmatched = [] } = data;
  if (!fetched && !matched && !written && !skipped) {
    return <p className="reports-none">No Granola syncs recorded.</p>;
  }
  return (
    <div>
      <p className="reports-stat-line">
        <span className="reports-stat-num">{fetched}</span> fetched
        {' · '}
        <span className="reports-stat-num">{matched}</span> matched
        {' · '}
        <span className="reports-stat-num">{written}</span> written
        {' · '}
        <span className="reports-stat-num">{skipped}</span> skipped
      </p>
      {unmatched.length > 0 && (
        <ul className="reports-file-list reports-unmatched">
          {unmatched.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      )}
    </div>
  );
}

function UnprocessedSection({ sessions }: { sessions: UnprocessedSession[] }) {
  if (!sessions.length) return <p className="reports-none">All past sessions processed.</p>;
  return (
    <table className="reports-table">
      <tbody>
        {sessions.map((s, i) => (
          <tr key={i}>
            <td className="reports-td-time">{s.date}</td>
            <td>{s.client}{s.company ? ` · ${s.company}` : ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BackupSection({ backups }: { backups: BackupEntry[] }) {
  return (
    <table className="reports-table">
      <tbody>
        {backups.map((b, i) => (
          <tr key={i}>
            <td className="reports-td-label">{b.label}</td>
            <td>{b.name}</td>
            <td className="reports-td-meta">{b.size}</td>
            <td className="reports-td-meta">{b.modified}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// Single digest card
// ---------------------------------------------------------------------------

function DigestCard({ run, defaultOpen }: { run: DigestRun; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);

  const label = formatRunDate(run.run_date);

  return (
    <div className="reports-card">
      <button
        className="reports-card-header"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span className={`collapse-icon${open ? ' open' : ''}`}>&#9658;</span>
        <span className="reports-card-title">Daily Digest — {label}</span>
        <span className="reports-card-meta">{run.sent_at ? new Date(run.sent_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
      </button>

      {open && (
        <div className="reports-card-body">
          <div className="reports-section">
            <div className="reports-section-label">today's sessions — {label}</div>
            <SessionTable sessions={run.today_sessions ?? []} />
          </div>

          <div className="reports-section">
            <div className="reports-section-label">tomorrow's sessions</div>
            <SessionTable sessions={run.tomorrow_sessions ?? []} />
          </div>

          <div className="reports-section">
            <div className="reports-section-label">note creation</div>
            {run.note_creation
              ? <NoteCreationSection data={run.note_creation} />
              : <p className="reports-none">No data.</p>}
          </div>

          <div className="reports-section">
            <div className="reports-section-label">granola sync</div>
            {run.granola_sync
              ? <GranolaSection data={run.granola_sync} />
              : <p className="reports-none">No data.</p>}
          </div>

          <div className="reports-section">
            <div className="reports-section-label">unprocessed past sessions</div>
            <UnprocessedSection sessions={run.unprocessed_sessions ?? []} />
          </div>

          {run.backup_summary && (
            <div className="reports-section">
              <div className="reports-section-label">backup summary</div>
              <BackupSection backups={run.backup_summary} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function ReportsPage() {
  const { data: runs, isLoading, error } = useDigestRuns();

  return (
    <div className="page-container">
      <h1 className="page-title">Reports</h1>

      {isLoading && <p className="reports-none">Loading…</p>}
      {error && <p className="reports-none">Failed to load digest history.</p>}

      {runs && runs.length === 0 && (
        <p className="reports-none">No digest runs recorded yet. Runs are stored after each daily digest send.</p>
      )}

      {runs && runs.map((run, i) => (
        <DigestCard key={run.id} run={run} defaultOpen={i === 0} />
      ))}
    </div>
  );
}
