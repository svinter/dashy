import { useState, useRef, useEffect, createContext, useContext } from 'react';
import { NavLink, Link, Routes, Route, Navigate, useMatch, useNavigate, useParams } from 'react-router-dom';
import { InvoicePrepPage } from './InvoicePrepPage';
import {
  useBillingUnprocessed,
  useConfirmBillingSession,
  useDismissBillingEvent,
  useBillingCompanies,
  useBillingSessions,
  useBillingPrepaidBlocks,
  useBillingNextSessionNumber,
  useCreateBillingSession,
  useUpdateBillingSession,
  useDeleteBillingSession,
  useUnprocessBillingSession,
  useRefreshSessionsFromCalendar,
  useBillingInvoices,
  useBillingInvoice,
  useUpdateBillingInvoice,
  useDeleteBillingInvoice,
  useDeleteBillingInvoicesBulk,
  useBillingGeneratePdf,
  useBillingInvoicesDir,
  useCreateBillingInvoice,
  useBulkImportInvoices,
  useComposeInvoiceEmail,
  useSaveInvoiceDraft,
  useSendInvoiceEmail,
  useBillingSummary,
  useBillingPayments,
  useSyncLunchMoney,
  useAssignBillingPayment,
  useRemoveBillingPaymentAssignment,
  useUpdateBillingPayment,
  useInvoiceUnlinkedSessions,
  useReconcileInvoiceSessions,
  useAddInvoiceLine,
  useBillingDismissedSessions,
  useBillingSyncCalendar,
} from '../api/hooks';
import type { BillingUnprocessedEvent, BillingCompany, BillingSession, BillingPrepaidBlock, BillingInvoice, BillingInvoiceDetail, BillingSummaryData, BillingSummaryCell, BillingPayment, BillingLunchMoneySyncResult, InvoiceLineInput, InvoiceBulkImportRow, InvoiceBulkImportResult } from '../api/types';

// ---------------------------------------------------------------------------
// Demo Mode context — hides all dollar amounts across the billing module
// ---------------------------------------------------------------------------

interface DemoModeCtx { demo: boolean; toggle: () => void; }
const DemoModeContext = createContext<DemoModeCtx>({ demo: false, toggle: () => {} });
export function useDemoMode() { return useContext(DemoModeContext); }

// ---------------------------------------------------------------------------
// Billing scope context — global year / month / company persisted for session
// ---------------------------------------------------------------------------

// company is a string: '' = all, numeric string = single company ID,
// or a group key constant below.
const SCOPE_COMPANY_PREPAID  = 'g:prepaid';   // companies with at least one prepaid client
const SCOPE_COMPANY_PERIODIC = 'g:periodic';  // invoice-billed companies with no prepaid clients

interface BillingScopeCtx {
  year: number;
  month: number | null;   // 1–12, null = all months
  company: string;        // '' | numeric-string | group key
  setYear: (y: number) => void;
  setMonth: (m: number | null) => void;
  setCompany: (c: string) => void;
}

function defaultScope(): Pick<BillingScopeCtx, 'year' | 'month' | 'company'> {
  const d = new Date();
  // d.getMonth() is 0-based; its value equals the previous month in 1-based numbering
  const prevMonth = d.getMonth(); // 0 means January → previous month is December
  return {
    year: prevMonth === 0 ? d.getFullYear() - 1 : d.getFullYear(),
    month: prevMonth === 0 ? 12 : prevMonth,
    company: '',
  };
}

/**
 * For group filter keys, returns the set of company IDs that match.
 * Returns null when company is '' (all) or a single numeric company.
 */
function resolveGroupIds(company: string, companies: BillingCompany[]): Set<number> | null {
  if (company === SCOPE_COMPANY_PREPAID)
    return new Set(companies.filter(co => co.clients.some(cl => cl.prepaid)).map(co => co.id));
  if (company === SCOPE_COMPANY_PERIODIC)
    return new Set(companies.filter(co => co.billing_method === 'invoice' && !co.clients.some(cl => cl.prepaid)).map(co => co.id));
  return null;
}

const BillingScopeContext = createContext<BillingScopeCtx>({
  ...defaultScope(),
  setYear: () => {},
  setMonth: () => {},
  setCompany: () => {},
});
function useBillingScope() { return useContext(BillingScopeContext); }

// ---------------------------------------------------------------------------
// Date / grouping helpers
// ---------------------------------------------------------------------------


/** ISO date string → Monday of that week (YYYY-MM-DD) */
function getWeekStart(dateStr: string): string {
  const [y, m, d] = dateStr.slice(0, 10).split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const day = date.getDay(); // 0=Sun
  date.setDate(date.getDate() + (day === 0 ? -6 : 1 - day));
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
}

function getWeekLabel(weekStart: string): string {
  const [y, m, d] = weekStart.split('-').map(Number);
  const start = new Date(y, m - 1, d);
  const end = new Date(y, m - 1, d + 6);
  const fmt = (dt: Date) => dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `${fmt(start)} – ${fmt(end)}`;
}

function getMonthLabel(monthKey: string): string {
  const [y, mo] = monthKey.split('-').map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

/** "Tue 4/10" — short weekday + month/day, no year, no leading zeros */
function formatSessionDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const weekday = date.toLocaleDateString('en-US', { weekday: 'short' });
  return `${weekday} ${m}/${d}`;
}

function formatDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function colorBadge(colorId: string) {
  if (colorId === '3') return <span style={{ background: '#7B52AB', color: '#fff', borderRadius: 3, padding: '1px 6px', fontSize: 'var(--text-xs)' }}>grape</span>;
  if (colorId === '5') return <span style={{ background: '#F6BF26', color: '#555', borderRadius: 3, padding: '1px 6px', fontSize: 'var(--text-xs)' }}>banana</span>;
  return null;
}

function confidenceBadge(score: number) {
  if (score >= 0.9) return null;
  if (score >= 0.6) return <span style={{ color: '#e9a040', fontSize: 'var(--text-xs)' }}>◑</span>;
  return <span style={{ color: '#f0c040', fontSize: 'var(--text-xs)' }}>○</span>;
}

// Sort company entries: named companies alphabetically, null/"(no company)"/"(unassigned)" last
function sortedCompanyEntries<T>(entries: [string, T][]): [string, T][] {
  return [...entries].sort(([a], [b]) => {
    const aNull = a === '(no company)' || a === '(unassigned)';
    const bNull = b === '(no company)' || b === '(unassigned)';
    if (aNull !== bNull) return aNull ? 1 : -1;
    return a.localeCompare(b);
  });
}

// ---------------------------------------------------------------------------
// BillingDateFilter — unified date filter bar shared across billing views
// ---------------------------------------------------------------------------

export interface BillingDateState {
  year: number;
  month: number | null;   // 1–12, null = all months
  week: number | null;    // 1–5, null = all weeks
}

export function defaultDateFilter(): BillingDateState {
  const d = new Date();
  const m = d.getMonth() + 1; // 1-based current month (getMonth() is 0-based)
  return { year: d.getFullYear(), month: m, week: null };
}

/** Returns sorted list of distinct week-start dates (Mon) for weeks that touch the given month. */
function weeksInMonth(year: number, month: number): string[] {
  const seen = new Set<string>();
  const daysInMonth = new Date(year, month, 0).getDate(); // month is 1-based
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    seen.add(getWeekStart(dateStr));
  }
  return [...seen].sort();
}

/** Returns 1-based week number within month, or null if not found. */
function getWeekNumberInMonth(dateStr: string, year: number, month: number): number | null {
  const weekStart = getWeekStart(dateStr);
  const weeks = weeksInMonth(year, month);
  const idx = weeks.indexOf(weekStart);
  return idx >= 0 ? idx + 1 : null;
}

/** Returns true if dateStr (YYYY-MM-DD) matches the given BillingDateState. */
export function matchesDateFilter(dateStr: string, filter: BillingDateState): boolean {
  const yr = Number(dateStr.slice(0, 4));
  const mo = Number(dateStr.slice(5, 7));
  if (yr !== filter.year) return false;
  if (filter.month !== null && mo !== filter.month) return false;
  if (filter.week !== null && filter.month !== null) {
    const weekNum = getWeekNumberInMonth(dateStr, filter.year, filter.month);
    if (weekNum !== filter.week) return false;
  }
  return true;
}

/** Converts BillingDateState to a month/year string for API queries. */
export function dateFilterToMonthParam(f: BillingDateState): string {
  if (f.month !== null) return `${f.year}-${String(f.month).padStart(2, '0')}`;
  return String(f.year);
}

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

interface BillingDateFilterProps {
  value: BillingDateState;
  onChange: (next: BillingDateState) => void;
  hideWeeks?: boolean;
}

export function BillingDateFilter({ value, onChange, hideWeeks = false }: BillingDateFilterProps) {
  const curYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 5 }, (_, i) => curYear - 2 + i);
  const weeks = value.month !== null ? weeksInMonth(value.year, value.month) : [];

  const pill = (active: boolean): React.CSSProperties => ({
    padding: '2px 7px',
    borderRadius: 3,
    background: active ? 'var(--color-bg-alt, #e8e8e8)' : 'none',
    border: 'none',
    fontSize: 'var(--text-sm)',
    cursor: 'pointer',
    fontWeight: active ? 600 : 400,
    color: active ? 'var(--color-fg)' : 'var(--color-text-light)',
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
      <select
        value={value.year}
        onChange={e => onChange({ year: Number(e.target.value), month: null, week: null })}
        style={{ fontSize: 'var(--text-sm)', marginRight: 6 }}
      >
        {yearOptions.map(y => <option key={y} value={y}>{y}</option>)}
      </select>
      <button style={pill(value.month === null)} onClick={() => onChange({ ...value, month: null, week: null })}>All</button>
      {MONTH_LABELS.map((label, i) => {
        const mo = i + 1;
        return (
          <button key={mo} style={pill(value.month === mo)} onClick={() => onChange({ year: value.year, month: mo, week: null })}>
            {label}
          </button>
        );
      })}
      {!hideWeeks && value.month !== null && weeks.length > 0 && (
        <>
          <span style={{ color: 'var(--color-text-light)', margin: '0 4px', fontSize: 'var(--text-xs)' }}>Week:</span>
          <button style={pill(value.week === null)} onClick={() => onChange({ ...value, week: null })}>All</button>
          {weeks.map((_, i) => {
            const wk = i + 1;
            return (
              <button key={wk} style={pill(value.week === wk)} onClick={() => onChange({ ...value, week: wk })}>{wk}</button>
            );
          })}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grouping functions
// ---------------------------------------------------------------------------

type WeekSessionMap = Map<string, Map<string, BillingSession[]>>;   // weekStart → company → sessions
type MonthSessionMap = Map<string, WeekSessionMap>;                  // monthKey → …

function groupSessions(sessions: BillingSession[]): MonthSessionMap {
  const months: MonthSessionMap = new Map();
  for (const s of sessions) {
    const monthKey = s.date.slice(0, 7);
    const weekStart = getWeekStart(s.date);
    const company = s.company_name ?? '(no company)';
    if (!months.has(monthKey)) months.set(monthKey, new Map());
    const weeks = months.get(monthKey)!;
    if (!weeks.has(weekStart)) weeks.set(weekStart, new Map());
    const companies = weeks.get(weekStart)!;
    if (!companies.has(company)) companies.set(company, []);
    companies.get(company)!.push(s);
  }
  return months;
}



// Sorted descending (newest first) for display
function sortedMonthEntries<V>(map: Map<string, V>): [string, V][] {
  return [...map.entries()].sort(([a], [b]) => b.localeCompare(a));
}

function sortedWeekEntries<V>(map: Map<string, V>): [string, V][] {
  return [...map.entries()].sort(([a], [b]) => b.localeCompare(a));
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Session number inline-edit cell
// ---------------------------------------------------------------------------

function SessionNumberCell({ value, onCommit }: { value: number | null; onCommit: (v: number | null) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const ref = useRef<HTMLInputElement>(null);

  function start() { setDraft(value != null ? String(value) : ''); setEditing(true); }
  function commit() {
    setEditing(false);
    const n = draft !== '' ? parseInt(draft) : null;
    if (n !== value) onCommit(n);
  }

  useEffect(() => { if (editing) ref.current?.select(); }, [editing]);

  if (editing) {
    return (
      <input
        ref={ref}
        type="number"
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false); }}
        style={{ width: 40, fontSize: 'inherit', padding: '1px 2px', textAlign: 'right' }}
      />
    );
  }
  return (
    <span onClick={start} title="Click to set session number" style={{ cursor: 'text', borderBottom: '1px dashed var(--color-border)' }}>
      {value != null ? `#${value}` : <span style={{ opacity: 0.3 }}>—</span>}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Session row
// ---------------------------------------------------------------------------

interface SessionRowProps {
  showCompanyCol?: boolean;
  showPrepaidCol?: boolean;
  session: BillingSession;
  companies: BillingCompany[];
  blocks?: BillingPrepaidBlock[];
  onUpdate: (id: number, fields: Partial<BillingSession>) => void;
  onDelete: (id: number) => void;
  onUnprocess: (id: number) => void;
}

function SessionRow({ session: s, companies, blocks = [], onUpdate, onDelete, onUnprocess, showCompanyCol = false, showPrepaidCol = false }: SessionRowProps) {
  const { demo } = useDemoMode();
  const effectiveRate = s.rate ?? null;
  const [editOpen, setEditOpen] = useState(false);

  // Shared edit form state — initialized fresh each time the form opens
  const allClients = companies.flatMap(co => co.clients.map(cl => ({ ...cl, company_name: co.name })));
  const [fDate, setFDate] = useState(s.date);
  const [fCompanyId, setFCompanyId] = useState<number | ''>(s.company_id ?? '');
  const [fClientId, setFClientId] = useState<number | '' | typeof NO_CLIENT>(
    s.client_id != null ? s.client_id : (s.company_id != null ? NO_CLIENT : '')
  );
  const [fDuration, setFDuration] = useState(s.duration_hours.toFixed(2));
  const [fRate, setFRate] = useState(s.rate != null ? String(s.rate) : '');
  const [fNotes, setFNotes] = useState(s.notes ?? '');
  const [fConfirmed, setFConfirmed] = useState(s.is_confirmed);

  // Re-sync form state when the row's session data changes (e.g. after a save)
  useEffect(() => {
    if (!editOpen) {
      setFDate(s.date);
      setFCompanyId(s.company_id ?? '');
      setFClientId(s.client_id != null ? s.client_id : (s.company_id != null ? NO_CLIENT : ''));
      setFDuration(s.duration_hours.toFixed(2));
      setFRate(s.rate != null ? String(s.rate) : '');
      setFNotes(s.notes ?? '');
      setFConfirmed(s.is_confirmed);
    }
  }, [s, editOpen]);

  const fClient = fClientId !== NO_CLIENT && fClientId !== '' ? allClients.find(cl => cl.id === Number(fClientId)) : null;
  const fCompany = fCompanyId !== '' ? companies.find(co => co.id === fCompanyId) : null;
  const defaultRate = fClient?.rate_override ?? fCompany?.default_rate ?? null;
  const resolvedRate = fRate !== '' ? parseFloat(fRate) : (defaultRate ?? null);
  const previewAmt = fClient?.prepaid ? 0 : Math.round(parseFloat(fDuration || '0') * (resolvedRate ?? 0) * 100) / 100;
  const fFilteredClients = fCompanyId
    ? companies.find(co => co.id === fCompanyId)?.clients.filter(cl => cl.active) ?? []
    : companies.flatMap(co => co.clients.filter(cl => cl.active));

  function handleClientChange(val: string) {
    if (val === NO_CLIENT) { setFClientId(NO_CLIENT); return; }
    if (!val) { setFClientId(''); return; }
    const id = Number(val);
    setFClientId(id);
    const cl = allClients.find(c => c.id === id);
    if (cl) setFCompanyId(cl.company_id);
    setFRate('');
  }

  function handleSave(confirmOverride?: boolean) {
    const cId = fClientId === NO_CLIENT || fClientId === '' ? null : Number(fClientId);
    const coId = cId ? null : (fCompanyId || null);
    const hrs = parseFloat(fDuration || '0');
    const rate = resolvedRate;
    const amt = fClient?.prepaid ? 0 : previewAmt;
    onUpdate(s.id, {
      date: fDate,
      client_id: cId ?? undefined,
      company_id: Number(coId) || undefined,
      duration_hours: hrs,
      rate: rate ?? undefined,
      amount: amt,
      notes: fNotes || null,
      is_confirmed: confirmOverride ?? fConfirmed,
    } as Partial<BillingSession>);
    setEditOpen(false);
  }

  function handleDismiss() {
    if (window.confirm(`Dismiss session on ${s.date}?`)) {
      onUpdate(s.id, { dismissed: true } as Partial<BillingSession>);
    }
  }

  const canSave = !!(fCompanyId || (fClientId !== '' && fClientId !== NO_CLIENT));

  // Prepaid block lookup: use explicit link first, then fall back to most recent block for this client
  const linkedBlock = s.prepaid_block_id != null
    ? (blocks.find(b => b.id === s.prepaid_block_id) ?? null)
    : (s.prepaid && s.client_id != null
        ? (blocks.find(b => b.client_id === s.client_id) ?? null)
        : null);
  // colSpan for edit mode: base = Date + Client + # + Hrs + Rate + Amount + Status + Invoice + Note + Notes + Actions = 11
  // +1 for Co col, +1 for Prepaid col
  const editColSpan = 11 + (showCompanyCol ? 1 : 0) + (showPrepaidCol ? 1 : 0);

  if (editOpen) {
    return (
      <tr style={{ background: 'var(--color-bg-subtle, #f8f8f8)' }}>
        <td colSpan={editColSpan} style={{ padding: '10px 12px', borderBottom: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', alignItems: 'flex-end', fontSize: 'var(--text-sm)' }}>
            {/* Date */}
            <input type="date" value={fDate} onChange={e => setFDate(e.target.value)}
              style={{ fontSize: 'var(--text-sm)' }} />

            {/* Company */}
            <select value={fCompanyId}
              onChange={e => { setFCompanyId(e.target.value ? Number(e.target.value) : ''); setFClientId(''); setFRate(''); }}
              style={{ minWidth: 130, fontSize: 'var(--text-sm)' }}>
              <option value="">— company —</option>
              {companies.filter(co => co.active).map(co => <option key={co.id} value={co.id}>{co.name}</option>)}
            </select>

            {/* Client */}
            <select value={fClientId === NO_CLIENT ? NO_CLIENT : String(fClientId)}
              onChange={e => handleClientChange(e.target.value)}
              style={{ minWidth: 160, fontSize: 'var(--text-sm)' }}>
              <option value="">— client —</option>
              {fFilteredClients.map(cl => <option key={cl.id} value={cl.id}>{cl.name}</option>)}
              <option value={NO_CLIENT}>— no specific client —</option>
            </select>

            {/* Duration */}
            <input type="number" step="0.25" min="0" value={fDuration}
              onChange={e => setFDuration(e.target.value)}
              style={{ width: 70, fontSize: 'var(--text-sm)' }} />
            <span style={{ color: 'var(--color-text-light)' }}>h</span>

            {/* Rate */}
            <input type="number" step="1" min="0" value={fRate}
              onChange={e => setFRate(e.target.value)}
              placeholder={defaultRate ? `$${defaultRate}` : '$/hr'}
              style={{ width: 80, fontSize: 'var(--text-sm)' }} />

            {resolvedRate != null && (
              <span style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}>
                → <strong>{demo ? '—' : `$${previewAmt.toFixed(2)}`}</strong>
                {fClient?.prepaid && ' (prepaid)'}
              </span>
            )}

            {/* Notes */}
            <input type="text" value={fNotes} onChange={e => setFNotes(e.target.value)}
              placeholder="notes" style={{ flex: 1, minWidth: 120, fontSize: 'var(--text-sm)' }} />

            {/* Status toggle */}
            <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 'var(--text-xs)', cursor: 'pointer', whiteSpace: 'nowrap' }}>
              <input type="checkbox" checked={fConfirmed} onChange={e => setFConfirmed(e.target.checked)} />
              Confirmed
            </label>
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-xs)' }}>
            {s.is_confirmed ? (
              <button className="btn-primary" style={{ fontSize: 'var(--text-xs)', padding: '3px 10px' }}
                disabled={!canSave} onClick={() => handleSave()}>Save</button>
            ) : (
              <>
                <button className="btn-primary" style={{ fontSize: 'var(--text-xs)', padding: '3px 10px' }}
                  disabled={!canSave} onClick={() => handleSave(true)}>Confirm</button>
                <button className="btn-secondary" style={{ fontSize: 'var(--text-xs)', padding: '3px 10px' }}
                  disabled={!canSave} onClick={() => handleSave(false)}>Save as Projected</button>
              </>
            )}
            <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: '#c0392b' }}
              onClick={handleDismiss}>Dismiss</button>
            <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}
              onClick={() => setEditOpen(false)}>Cancel</button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td style={{ whiteSpace: 'nowrap', fontSize: 'var(--text-sm)', paddingLeft: 24 }}>{formatSessionDate(s.date)}</td>
      {showCompanyCol && (
        <td style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', whiteSpace: 'nowrap' }}>
          {s.company_abbrev ?? s.company_name ?? ''}
        </td>
      )}
      <td style={{ fontSize: 'var(--text-sm)' }}>{s.client_name ?? <span style={{ color: 'var(--color-text-light)' }}>{s.company_name ?? '—'}</span>}</td>
      {/* Session number — click to edit */}
      <td style={{ textAlign: 'right', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {s.client_id != null
          ? <SessionNumberCell
              value={s.display_session_number}
              onCommit={v => onUpdate(s.id, { session_number: v } as Partial<BillingSession>)}
            />
          : <span style={{ opacity: 0.3 }}>—</span>}
      </td>
      <td style={{ textAlign: 'right', fontSize: 'var(--text-sm)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {s.duration_hours.toFixed(2)}h
      </td>
      <td style={{ textAlign: 'right', fontSize: 'var(--text-sm)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {demo ? '—' : effectiveRate != null ? `$${effectiveRate}` : <span style={{ opacity: 0.4, fontSize: 'var(--text-xs)' }}>—</span>}
      </td>
      <td style={{ textAlign: 'right', fontSize: 'var(--text-sm)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
        {demo ? '—' : `$${s.amount.toFixed(2)}`}
      </td>
      <td style={{ textAlign: 'center', fontSize: 'var(--text-xs)' }}>
        {!s.is_confirmed ? (
          <button
            className="btn-link"
            style={{ background: '#f6e5b0', color: '#8a6200', borderRadius: 3, padding: '1px 6px', fontSize: 'var(--text-xs)', border: 'none', cursor: 'pointer' }}
            title="Click to edit or confirm this session"
            onClick={() => setEditOpen(true)}
          >
            unprocessed
          </button>
        ) : (
          <span style={{ background: '#7B52AB', color: '#fff', borderRadius: 3, padding: '1px 6px', fontSize: 'var(--text-xs)' }}>confirmed</span>
        )}
      </td>
      <td style={{ textAlign: 'center', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>
        {s.invoice_line_id
          ? <Link
              to={s.invoice_id ? `/billing/invoices/${s.invoice_id}` : '/billing/invoices'}
              style={{ color: 'var(--color-accent)', textDecoration: 'none', fontSize: 'var(--text-xs)' }}
            >invoiced</Link>
          : '—'}
      </td>
      <td style={{ textAlign: 'center' }}>
        {s.obsidian_link
          ? <a href={s.obsidian_link} title="Open in Obsidian" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', textDecoration: 'none' }}>◆</a>
          : <span style={{ opacity: 0.2, fontSize: 'var(--text-xs)' }}>◇</span>}
      </td>
      <td style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {s.notes || ''}
      </td>
      {/* Prepaid block progress — only rendered when showPrepaidCol */}
      {showPrepaidCol && (
        <td style={{ fontSize: 'var(--text-xs)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
          {linkedBlock && linkedBlock.hours_purchased != null && s.cumulative_block_hours != null ? (() => {
            const displayHours = s.cumulative_block_hours + (linkedBlock.hours_offset ?? 0);
            const exhausted = displayHours >= linkedBlock.hours_purchased;
            return (
              <span style={{ color: exhausted ? 'var(--color-error, #c00)' : 'var(--color-text-light)' }}>
                {displayHours.toFixed(1)}/{linkedBlock.hours_purchased.toFixed(1)}h
              </span>
            );
          })() : null}
        </td>
      )}
      <td style={{ whiteSpace: 'nowrap' }}>
        <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginRight: 6 }}
          title="Edit session" onClick={() => setEditOpen(true)}>✎</button>
        {s.is_confirmed && (
          <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginRight: 6 }}
            title="Move back to unprocessed"
            onClick={() => { if (window.confirm(`Unprocess session on ${s.date}?`)) onUnprocess(s.id); }}>↩</button>
        )}
        <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}
          title="Delete session" onClick={() => { if (window.confirm(`Delete session on ${s.date}?`)) onDelete(s.id); }}>×</button>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Company group (within a week, within the session table)
// ---------------------------------------------------------------------------

interface CompanyGroupProps {
  companyName: string;
  sessions: BillingSession[];
  companies: BillingCompany[];
  blocks?: BillingPrepaidBlock[];
  showPrepaidCol?: boolean;
  onUpdate: (id: number, fields: Partial<BillingSession>) => void;
  onDelete: (id: number) => void;
  onUnprocess: (id: number) => void;
}

function CompanyGroup({ companyName, sessions, companies, blocks = [], showPrepaidCol = false, onUpdate, onDelete, onUnprocess }: CompanyGroupProps) {
  const { demo } = useDemoMode();
  const totalHours = sessions.reduce((s, r) => s + r.duration_hours, 0);
  const totalAmount = sessions.reduce((s, r) => s + r.amount, 0);
  // Date + Client + # + Hrs + Rate + Amount + Status + Invoice + Note + Notes + Prepaid(cond) + Actions
  const colCount = 11 + (showPrepaidCol ? 1 : 0);

  const byClient = new Map<string, BillingSession[]>();
  for (const s of sessions) {
    const key = s.client_name ?? '(no client)';
    if (!byClient.has(key)) byClient.set(key, []);
    byClient.get(key)!.push(s);
  }

  return (
    <>
      <tr>
        <td colSpan={colCount} style={{
          fontWeight: 600, fontSize: 'var(--text-sm)', padding: '3px 8px 3px 16px',
          borderTop: '1px solid var(--color-border)',
          color: 'var(--color-text-light)',
        }}>
          {companyName}
          <span style={{ float: 'right', fontWeight: 400 }}>
            {totalHours.toFixed(2)}h · {demo ? '—' : `$${totalAmount.toFixed(2)}`}
          </span>
        </td>
      </tr>
      {Array.from(byClient.entries()).map(([clientName, clientSessions]) => {
        const ch = clientSessions.reduce((s, r) => s + r.duration_hours, 0);
        const ca = clientSessions.reduce((s, r) => s + r.amount, 0);
        return (
          <>
            {byClient.size > 1 && (
              <tr key={`client-${clientName}`}>
                <td colSpan={colCount} style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', padding: '2px 8px 2px 28px', fontStyle: 'italic' }}>
                  {clientName}
                  <span style={{ float: 'right' }}>{ch.toFixed(2)}h · {demo ? '—' : `$${ca.toFixed(2)}`}</span>
                </td>
              </tr>
            )}
            {clientSessions.map(s => (
              <SessionRow key={s.id} session={s} companies={companies} blocks={blocks} showPrepaidCol={showPrepaidCol} onUpdate={onUpdate} onDelete={onDelete} onUnprocess={onUnprocess} />
            ))}
          </>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// New Session form
// ---------------------------------------------------------------------------

interface NewSessionFormProps {
  companies: BillingCompany[];
  defaultDate?: string;
  onCreated: () => void;
  onCancel: () => void;
}

function NewSessionForm({ companies, defaultDate, onCreated, onCancel }: NewSessionFormProps) {
  const { demo } = useDemoMode();
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(defaultDate ?? today);
  const [companyId, setCompanyId] = useState<number | ''>('');
  const [clientId, setClientId] = useState<number | '' | typeof NO_CLIENT>('');
  const [duration, setDuration] = useState('1.00');
  const [rateOverride, setRateOverride] = useState('');
  const [notes, setNotes] = useState('');
  const [isConfirmed, setIsConfirmed] = useState(true);
  const createMut = useCreateBillingSession();

  const allClients = companies.flatMap(co => co.clients.map(cl => ({ ...cl, company_name: co.name })));
  const filteredClients = companyId
    ? companies.find(co => co.id === companyId)?.clients.filter(cl => cl.active) ?? []
    : companies.flatMap(co => co.clients.filter(cl => cl.active));

  const selectedClient = clientId !== NO_CLIENT && clientId !== '' ? allClients.find(cl => cl.id === Number(clientId)) : null;
  const selectedCompany = companyId ? companies.find(co => co.id === companyId) : null;
  const defaultRate = selectedClient?.rate_override ?? selectedCompany?.default_rate ?? null;
  const effectiveRate = rateOverride !== '' ? parseFloat(rateOverride) : defaultRate;
  const previewAmount = selectedClient?.prepaid ? 0 : Math.round(parseFloat(duration || '0') * (effectiveRate ?? 0) * 100) / 100;

  function handleClientChange(val: string) {
    if (val === NO_CLIENT) { setClientId(NO_CLIENT); return; }
    if (!val) { setClientId(''); return; }
    const id = Number(val);
    setClientId(id);
    const cl = allClients.find(c => c.id === id);
    if (cl) setCompanyId(cl.company_id);
    setRateOverride('');
  }

  function handleCompanyChange(val: string) {
    setCompanyId(val ? Number(val) : '');
    const curCl = clientId !== NO_CLIENT && clientId !== '' ? allClients.find(c => c.id === Number(clientId)) : null;
    if (curCl && curCl.company_id !== Number(val)) setClientId('');
    setRateOverride('');
  }

  function handleSubmit() {
    const cId = clientId === NO_CLIENT || clientId === '' ? null : Number(clientId);
    const coId = cId ? null : (companyId || null);
    createMut.mutate({
      date,
      client_id: cId,
      company_id: Number(coId) || null,
      duration_hours: parseFloat(duration || '0'),
      rate: rateOverride !== '' ? parseFloat(rateOverride) : null,
      notes: notes || null,
      is_confirmed: isConfirmed,
    }, { onSuccess: onCreated });
  }

  const canSubmit = !!date && parseFloat(duration || '0') > 0 && (!!clientId || !!companyId);

  return (
    <div style={{ border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-md)', marginBottom: 'var(--space-md)', background: 'var(--color-bg-subtle, #f8f8f8)' }}>
      <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)', marginBottom: 'var(--space-sm)' }}>New Session</div>
      <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', alignItems: 'flex-end', fontSize: 'var(--text-sm)' }}>
        {/* Date */}
        <div>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Date</label>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} style={{ fontSize: 'var(--text-sm)' }} />
        </div>

        {/* Company */}
        <div>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Company</label>
          <select value={companyId} onChange={e => handleCompanyChange(e.target.value)} style={{ minWidth: 140, fontSize: 'var(--text-sm)' }}>
            <option value="">— all —</option>
            {companies.filter(co => co.active).map(co => <option key={co.id} value={co.id}>{co.name}</option>)}
          </select>
        </div>

        {/* Client */}
        <div>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Client</label>
          <select
            value={clientId === NO_CLIENT ? NO_CLIENT : String(clientId)}
            onChange={e => handleClientChange(e.target.value)}
            style={{ minWidth: 160, fontSize: 'var(--text-sm)' }}
          >
            <option value="">— select —</option>
            {filteredClients.map(cl => <option key={cl.id} value={cl.id}>{cl.name}</option>)}
            <option value={NO_CLIENT}>— no specific client —</option>
          </select>
        </div>

        {/* Duration */}
        <div>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Hours</label>
          <input type="number" step="0.25" min="0" value={duration} onChange={e => setDuration(e.target.value)} style={{ width: 80, fontSize: 'var(--text-sm)' }} />
        </div>

        {/* Rate */}
        <div>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>
            Rate {defaultRate ? `(default $${defaultRate})` : ''}
          </label>
          <input type="number" step="1" min="0" value={rateOverride}
            onChange={e => setRateOverride(e.target.value)}
            placeholder={defaultRate ? String(defaultRate) : '$/hr'}
            style={{ width: 90, fontSize: 'var(--text-sm)' }} />
        </div>

        {/* Amount preview */}
        {effectiveRate != null && (
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', paddingBottom: 4 }}>
            → <strong>{demo ? '—' : `$${previewAmount.toFixed(2)}`}</strong>
            {selectedClient?.prepaid && ' (prepaid)'}
          </span>
        )}

        {/* Notes */}
        <div style={{ flex: 1, minWidth: 140 }}>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Notes</label>
          <input type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="optional" style={{ width: '100%', fontSize: 'var(--text-sm)' }} />
        </div>

        {/* Confirmed toggle */}
        <div style={{ paddingBottom: 4 }}>
          <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 'var(--text-sm)', cursor: 'pointer' }}>
            <input type="checkbox" checked={isConfirmed} onChange={e => setIsConfirmed(e.target.checked)} />
            Confirmed
          </label>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-sm)' }}>
        <button className="btn-primary" disabled={!canSubmit || createMut.isPending} onClick={handleSubmit}>
          {createMut.isPending ? 'Saving…' : 'Create Session'}
        </button>
        <button className="btn-link" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sessions view
// ---------------------------------------------------------------------------

const TH: React.CSSProperties = { padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-light)', whiteSpace: 'nowrap' };

type SessionSortKey = 'date-desc' | 'date-asc' | 'company' | 'amount';
type SessionViewTab = 'grouped' | 'flat' | 'summary';

function SessionsView() {
  const { demo } = useDemoMode();
  const { year, month, company, setCompany } = useBillingScope();
  const [unconfirmedOnly, setUnconfirmedOnly] = useState(false);
  const [unlinkedOnly, setUnlinkedOnly] = useState(false);
  const [viewTab, setViewTab] = useState<SessionViewTab>('flat');
  const [showNewForm, setShowNewForm] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState('');
  const refreshMut = useRefreshSessionsFromCalendar();
  const [sortKey, setSortKey] = useState<SessionSortKey>('date-desc');

  const monthParam = month !== null ? `${year}-${String(month).padStart(2, '0')}` : String(year);
  const { data: companies = [] } = useBillingCompanies();
  const groupIds = resolveGroupIds(company, companies);
  const apiCompanyId = !groupIds && company ? Number(company) : undefined;
  const { data: sessions = [], isLoading, refetch } = useBillingSessions({
    month: monthParam,
    company_id: apiCompanyId,
    unconfirmed_only: unconfirmedOnly || undefined,
  });
  // Load invoices for the current period for side-by-side comparison in summary tab
  const periodMonthParam = month !== null
    ? `${year}-${String(month).padStart(2, '0')}`
    : undefined;
  const { data: periodInvoices = [] } = useBillingInvoices({
    period_month: periodMonthParam,
    period_year: month === null ? year : undefined,
  });
  const update = useUpdateBillingSession();
  const del = useDeleteBillingSession();
  const unprocess = useUnprocessBillingSession();
  const { data: allBlocks = [] } = useBillingPrepaidBlocks();

  function handleUpdate(id: number, fields: Partial<BillingSession>) { update.mutate({ id, ...fields }); }
  function handleDelete(id: number) { del.mutate(id); }
  function handleUnprocess(id: number) { unprocess.mutate(id); }

  // Apply unlinked and group-company filters client-side
  const visibleSessions = sessions.filter(s =>
    (!groupIds || (s.company_id !== null && groupIds.has(s.company_id))) &&
    (!unlinkedOnly || (s.is_confirmed && s.invoice_line_id === null))
  );

  const grouped = groupSessions(visibleSessions);
  const grandHours = visibleSessions.reduce((s, r) => s + r.duration_hours, 0);
  const grandAmount = visibleSessions.reduce((s, r) => s + r.amount, 0);
  const hasPrepaidSessions = visibleSessions.some(s => s.prepaid);

  const sessionsSorted = [...visibleSessions].sort((a, b) => {
    if (sortKey === 'date-desc') return b.date.localeCompare(a.date);
    if (sortKey === 'date-asc') return a.date.localeCompare(b.date);
    if (sortKey === 'company') return (a.company_name ?? '').localeCompare(b.company_name ?? '');
    if (sortKey === 'amount') return b.amount - a.amount;
    return 0;
  });

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '2px 10px', fontSize: 'var(--text-sm)', cursor: 'pointer',
    background: 'none', border: 'none',
    borderBottom: active ? '2px solid var(--color-fg)' : '2px solid transparent',
    color: active ? 'var(--color-fg)' : 'var(--color-text-light)',
  });

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginBottom: 'var(--space-sm)', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Sessions</h2>
        <label style={{ fontSize: 'var(--text-sm)', display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={unconfirmedOnly} onChange={e => setUnconfirmedOnly(e.target.checked)} />
          Unprocessed only
        </label>
        <label style={{ fontSize: 'var(--text-sm)', display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={unlinkedOnly} onChange={e => setUnlinkedOnly(e.target.checked)} />
          Unlinked only
        </label>
        {viewTab === 'flat' && (
          <select value={sortKey} onChange={e => setSortKey(e.target.value as SessionSortKey)} style={{ fontSize: 'var(--text-sm)' }}>
            <option value="date-desc">Sort: newest first</option>
            <option value="date-asc">Sort: oldest first</option>
            <option value="company">Sort: company</option>
            <option value="amount">Sort: amount</option>
          </select>
        )}
        {viewTab === 'summary' && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>
            {periodMonthParam ? `invoices for ${periodMonthParam} (excl. prepaid)` : `invoices for ${year} (excl. prepaid)`}
          </span>
        )}
        {visibleSessions.length > 0 && (
          <span style={{ marginLeft: 'auto', fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
            {grandHours.toFixed(2)}h · <strong>{demo ? '—' : `$${grandAmount.toFixed(2)}`}</strong>
          </span>
        )}
        <button className="btn-secondary" style={{ fontSize: 'var(--text-sm)' }}
          onClick={() => setShowNewForm(f => !f)}>
          {showNewForm ? 'Cancel' : '+ New Session'}
        </button>
        <button
          className="btn-link"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}
          disabled={refreshMut.isPending}
          title="Promote sessions whose calendar event changed from banana to grape"
          onClick={() => {
            setRefreshMsg('');
            refreshMut.mutate(undefined, {
              onSuccess: (r) => {
                setRefreshMsg(r.promoted > 0 ? `↑ ${r.promoted} promoted` : 'No changes');
                refetch();
              },
            });
          }}
        >
          {refreshMut.isPending ? '…' : '↺ Refresh from Calendar'}
        </button>
        {refreshMsg && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>{refreshMsg}</span>}
        <button className="btn-link" style={{ fontSize: 'var(--text-sm)' }} onClick={() => refetch()}>↻</button>
      </div>

      {showNewForm && (
        <NewSessionForm
          companies={companies}
          onCreated={() => { setShowNewForm(false); refetch(); }}
          onCancel={() => setShowNewForm(false)}
        />
      )}

      {/* View tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 'var(--space-md)', borderBottom: '1px solid var(--color-border)' }}>
        <button style={tabStyle(viewTab === 'flat')} onClick={() => setViewTab('flat')}>By Date</button>
        <button style={tabStyle(viewTab === 'grouped')} onClick={() => setViewTab('grouped')}>By Company & Date</button>
        <button style={tabStyle(viewTab === 'summary')} onClick={() => setViewTab('summary')}>Summary</button>
      </div>

      {isLoading && <p className="empty-state">Loading…</p>}
      {!isLoading && visibleSessions.length === 0 && <p className="empty-state">No sessions match the current filters.</p>}

      {/* Tab A: grouped by company & date */}
      {!isLoading && visibleSessions.length > 0 && viewTab === 'grouped' && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                <th style={TH}>Date</th>
                <th style={TH}>Client</th>
                <th style={{ ...TH, textAlign: 'right' }}>#</th>
                <th style={{ ...TH, textAlign: 'right' }}>Hrs</th>
                <th style={{ ...TH, textAlign: 'right' }}>Rate</th>
                <th style={{ ...TH, textAlign: 'right' }}>Amount</th>
                <th style={{ ...TH, textAlign: 'center' }}>Status</th>
                <th style={{ ...TH, textAlign: 'center' }}>Invoice</th>
                <th style={{ ...TH, textAlign: 'center' }}>Note</th>
                <th style={TH}>Notes</th>
                {hasPrepaidSessions && <th style={TH}>Prepaid</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {sortedMonthEntries(grouped).map(([monthKey, weekMap]) => {
                const mh = [...weekMap.values()].flatMap(wm => [...wm.values()].flat()).reduce((s, r) => s + r.duration_hours, 0);
                const ma = [...weekMap.values()].flatMap(wm => [...wm.values()].flat()).reduce((s, r) => s + r.amount, 0);
                const colCount = hasPrepaidSessions ? 12 : 11;
                return (
                  <>
                    <tr key={`month-${monthKey}`}>
                      <td colSpan={colCount} style={{
                        fontWeight: 700, fontSize: 'var(--text-sm)', padding: '6px 8px',
                        borderTop: '2px solid var(--color-border)',
                        background: 'var(--color-bg-subtle, color-mix(in srgb, var(--color-border) 40%, transparent))',
                      }}>
                        {getMonthLabel(monthKey)}
                        <span style={{ float: 'right', fontWeight: 400, color: 'var(--color-text-light)' }}>
                          {mh.toFixed(2)}h · {demo ? '—' : `$${ma.toFixed(2)}`}
                        </span>
                      </td>
                    </tr>
                    {sortedWeekEntries(weekMap).map(([weekStart, companyMap]) => {
                      const wh = [...companyMap.values()].flat().reduce((s, r) => s + r.duration_hours, 0);
                      const wa = [...companyMap.values()].flat().reduce((s, r) => s + r.amount, 0);
                      return (
                        <>
                          <tr key={`week-${weekStart}`}>
                            <td colSpan={colCount} style={{
                              fontSize: 'var(--text-xs)', padding: '3px 8px 3px 12px',
                              color: 'var(--color-text-light)',
                              borderTop: '1px solid var(--color-border)',
                            }}>
                              {getWeekLabel(weekStart)}
                              <span style={{ float: 'right' }}>{wh.toFixed(2)}h · {demo ? '—' : `$${wa.toFixed(2)}`}</span>
                            </td>
                          </tr>
                          {sortedCompanyEntries([...companyMap.entries()]).map(([companyName, companySessions]) => (
                            <CompanyGroup
                              key={`${weekStart}-${companyName}`}
                              companyName={companyName}
                              sessions={companySessions}
                              companies={companies}
                              blocks={allBlocks}
                              showPrepaidCol={hasPrepaidSessions}
                              onUpdate={handleUpdate}
                              onDelete={handleDelete}
                              onUnprocess={handleUnprocess}
                            />
                          ))}
                        </>
                      );
                    })}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab B: by date, grouped by week */}
      {!isLoading && visibleSessions.length > 0 && viewTab === 'flat' && (() => {
        // Group sorted sessions into weeks, preserving sort order
        const weekGroups: { weekStart: string; sessions: typeof sessionsSorted }[] = [];
        for (const s of sessionsSorted) {
          const ws = getWeekStart(s.date);
          const last = weekGroups[weekGroups.length - 1];
          if (last && last.weekStart === ws) {
            last.sessions.push(s);
          } else {
            weekGroups.push({ weekStart: ws, sessions: [s] });
          }
        }
        const colCount = hasPrepaidSessions ? 13 : 12;
        return (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                  <th style={TH}>Date</th>
                  <th style={TH}>Co</th>
                  <th style={TH}>Client</th>
                  <th style={{ ...TH, textAlign: 'right' }}>#</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Hrs</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Rate</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Amount</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Status</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Invoice</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Note</th>
                  <th style={TH}>Notes</th>
                  {hasPrepaidSessions && <th style={TH}>Prepaid</th>}
                  <th />
                </tr>
              </thead>
              <tbody>
                {weekGroups.map(({ weekStart, sessions: wkSessions }) => {
                  const wh = wkSessions.reduce((s, r) => s + r.duration_hours, 0);
                  const wa = wkSessions.reduce((s, r) => s + r.amount, 0);
                  return (
                    <>
                      <tr key={`week-${weekStart}`}>
                        <td colSpan={colCount} style={{
                          fontSize: 'var(--text-xs)', padding: '3px 8px',
                          color: 'var(--color-text-light)',
                          borderTop: '1px solid var(--color-border)',
                        }}>
                          {getWeekLabel(weekStart)}
                          <span style={{ float: 'right' }}>{wh.toFixed(2)}h · {demo ? '—' : `$${wa.toFixed(2)}`}</span>
                        </td>
                      </tr>
                      {wkSessions.map(s => (
                        <SessionRow
                          key={s.id}
                          session={s}
                          companies={companies}
                          blocks={allBlocks}
                          showPrepaidCol={hasPrepaidSessions}
                          onUpdate={handleUpdate}
                          onDelete={handleDelete}
                          onUnprocess={handleUnprocess}
                          showCompanyCol
                        />
                      ))}
                    </>
                  );
                })}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '2px solid var(--color-border)', fontWeight: 600 }}>
                  <td colSpan={4} style={{ padding: '5px 8px', fontSize: 'var(--text-sm)' }}>
                    Total ({sessionsSorted.length})
                  </td>
                  <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {grandHours.toFixed(2)}h
                  </td>
                  <td />
                  <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {demo ? '—' : `$${grandAmount.toFixed(2)}`}
                  </td>
                  <td colSpan={hasPrepaidSessions ? 5 : 4} />
                </tr>
              </tfoot>
            </table>
          </div>
        );
      })()}

      {/* Tab C: Summary by company */}
      {!isLoading && viewTab === 'summary' && (() => {
        // Aggregate visible sessions by company
        const byCompany = new Map<number, {
          id: number; name: string; abbrev: string | null;
          confirmed: number; projected: number;
          confirmedAmt: number; projectedAmt: number;
          unreconciledCount: number; unreconciledAmt: number;
        }>();
        for (const s of visibleSessions) {
          const id = s.company_id ?? -1;
          if (!byCompany.has(id)) {
            byCompany.set(id, {
              id,
              name: s.company_name ?? '(no company)',
              abbrev: s.company_abbrev ?? null,
              confirmed: 0, projected: 0,
              confirmedAmt: 0, projectedAmt: 0,
              unreconciledCount: 0, unreconciledAmt: 0,
            });
          }
          const row = byCompany.get(id)!;
          if (s.is_confirmed) {
            row.confirmed += s.duration_hours;
            row.confirmedAmt += s.amount;
            // Prepaid sessions with amount=0 will never be invoiced — don't flag as unlinked
            if (s.invoice_line_id === null && !(s.prepaid && s.amount === 0)) {
              row.unreconciledCount += 1;
              row.unreconciledAmt += s.amount;
            }
          } else {
            row.projected += s.duration_hours;
            row.projectedAmt += s.amount;
          }
        }

        // Build invoice totals per company, excluding prepaid block invoices (invoice # ends with -P).
        // When multiple invoices exist for a company in the period (year view), sum them.
        const billingInvoices = periodInvoices.filter(inv => !inv.invoice_number.endsWith('-P'));
        const invoicedAmtByCompany = new Map<number, number>();
        const invoicesByCompany = new Map<number, BillingInvoice[]>();
        for (const inv of billingInvoices) {
          if (inv.company_id == null) continue;
          invoicedAmtByCompany.set(inv.company_id, (invoicedAmtByCompany.get(inv.company_id) ?? 0) + (inv.total_amount ?? 0));
          const list = invoicesByCompany.get(inv.company_id) ?? [];
          list.push(inv);
          invoicesByCompany.set(inv.company_id, list);
        }

        const companyById = new Map(companies.map(co => [co.id, co]));
        // Suppress the Unreconciled column for companies where sessions are intentionally unbilled:
        // - billing_method = null (pro bono)
        // - billing_method = 'payasgo' (no regular invoices)
        // - default_rate = 0 (zero-rate regardless of billing_method, e.g. Continua)
        const skipReconcileCheck = (id: number) => {
          const co = companyById.get(id);
          if (!co) return false;
          return co.billing_method === null || co.billing_method === 'payasgo' || co.default_rate === 0;
        };

        const rows = [...byCompany.values()].sort((a, b) => a.name.localeCompare(b.name));
        const totalConfirmedHrs = rows.reduce((s, r) => s + r.confirmed, 0);
        const totalProjectedHrs = rows.reduce((s, r) => s + r.projected, 0);
        const totalConfirmedAmt = rows.reduce((s, r) => s + r.confirmedAmt, 0);
        const totalProjectedAmt = rows.reduce((s, r) => s + r.projectedAmt, 0);
        const totalInvoiced = rows.reduce((s, r) => s + (invoicedAmtByCompany.get(r.id) ?? 0), 0);
        const totalUnreconciledCount = rows.reduce((s, r) => skipReconcileCheck(r.id) ? s : s + r.unreconciledCount, 0);
        const totalUnreconciledAmt = rows.reduce((s, r) => skipReconcileCheck(r.id) ? s : s + r.unreconciledAmt, 0);

        const periodLabel = periodMonthParam
          ? periodMonthParam
          : `all of ${year}`;

        if (rows.length === 0) return <p className="empty-state">No sessions match the current filters.</p>;

        return (
          <>
            <div style={{ marginBottom: 'var(--space-sm)', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
              <span>
                Invoice $ = non-prepaid invoices for <strong>{periodLabel}</strong> &nbsp;·&nbsp;
                Unreconciled = confirmed sessions with no invoice line link
              </span>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                  <th style={TH}>Company</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Conf. Hrs</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Confirmed $</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Proj. Hrs</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Projected $</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Invoice $</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Unreconciled</th>
                  <th style={TH}>Invoice(s)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const invoicedAmt = invoicedAmtByCompany.get(r.id) ?? 0;
                  const invList = invoicesByCompany.get(r.id) ?? [];
                  return (
                    <tr key={r.id} style={{ borderBottom: '1px solid var(--color-border-faint)' }}>
                      <td style={{ padding: '6px 8px' }}>
                        {r.abbrev
                          ? <><span style={{ color: 'var(--color-text-light)', marginRight: 6 }}>{r.abbrev}</span>{r.name}</>
                          : r.name}
                      </td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--color-text-light)' }}>
                        {r.confirmed.toFixed(2)}h
                      </td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
                        {demo ? '—' : `$${r.confirmedAmt.toFixed(2)}`}
                      </td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--color-text-light)' }}>
                        {r.projected > 0 ? `${r.projected.toFixed(2)}h` : '—'}
                      </td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--color-text-light)' }}>
                        {r.projectedAmt > 0 ? (demo ? '—' : `$${r.projectedAmt.toFixed(2)}`) : '—'}
                      </td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                        {invoicedAmt > 0 ? (demo ? '—' : `$${invoicedAmt.toFixed(2)}`) : <span style={{ color: 'var(--color-text-light)' }}>—</span>}
                      </td>
                      <td style={{
                        padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums',
                        color: r.confirmed === 0 || skipReconcileCheck(r.id) ? 'var(--color-text-light)'
                          : r.unreconciledCount > 0 ? '#c0392b'
                          : 'var(--color-text-light)',
                        fontWeight: !skipReconcileCheck(r.id) && r.unreconciledCount > 0 ? 600 : undefined,
                      }}>
                        {r.confirmed === 0 || skipReconcileCheck(r.id)
                          ? '—'
                          : r.unreconciledCount > 0
                            ? (
                                <button
                                  className="btn-link"
                                  style={{ color: '#c0392b', fontWeight: 600, fontSize: 'inherit', fontVariantNumeric: 'tabular-nums' }}
                                  title={`${r.unreconciledCount} confirmed session${r.unreconciledCount === 1 ? '' : 's'} not linked to an invoice line — click to filter`}
                                  onClick={() => {
                                    setCompany(String(r.id));
                                    setUnlinkedOnly(true);
                                    setUnconfirmedOnly(false);
                                    setViewTab('flat');
                                  }}
                                >
                                  {r.unreconciledCount} unlinked {demo ? '' : `($${r.unreconciledAmt.toFixed(2)})`}
                                </button>
                              )
                            : '✓'}
                      </td>
                      <td style={{ padding: '6px 8px', fontSize: 'var(--text-xs)' }}>
                        {invList.length === 0
                          ? <span style={{ color: 'var(--color-text-light)' }}>—</span>
                          : invList.map((inv, i) => (
                              <span key={inv.id}>
                                {i > 0 && ', '}
                                <Link to={`/billing/invoices/${inv.id}`} style={{ color: 'var(--color-accent)', textDecoration: 'none' }}>{inv.invoice_number}</Link>
                              </span>
                            ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '2px solid var(--color-border)', fontWeight: 600 }}>
                  <td style={{ padding: '6px 8px', fontSize: 'var(--text-sm)' }}>Total</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--color-text-light)' }}>
                    {totalConfirmedHrs.toFixed(2)}h
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{demo ? '—' : `$${totalConfirmedAmt.toFixed(2)}`}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--color-text-light)' }}>
                    {totalProjectedHrs > 0 ? `${totalProjectedHrs.toFixed(2)}h` : '—'}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--color-text-light)' }}>
                    {totalProjectedAmt > 0 ? (demo ? '—' : `$${totalProjectedAmt.toFixed(2)}`) : '—'}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{demo ? '—' : `$${totalInvoiced.toFixed(2)}`}</td>
                  <td style={{
                    padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums',
                    color: totalUnreconciledCount > 0 ? '#c0392b' : 'var(--color-text-light)',
                    fontWeight: 600,
                  }}>
                    {totalUnreconciledCount > 0
                      ? `${totalUnreconciledCount} unlinked${demo ? '' : ` ($${totalUnreconciledAmt.toFixed(2)})`}`
                      : totalConfirmedAmt > 0 ? '✓' : '—'}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </>
        );
      })()}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unprocessed queue row (unchanged)
// ---------------------------------------------------------------------------

// Sentinel value for "no specific client" selection
const NO_CLIENT = '__no_client__';

interface RowProps {
  event: BillingUnprocessedEvent;
  companies: BillingCompany[];
  companyAbbrev?: string | null;
  expectedRevenue?: number | null;
  onConfirm: (
    ev: BillingUnprocessedEvent,
    clientId: number | null,
    companyId: number | null,
    durationHours: number,
    notes: string,
  ) => void;
  onDismiss: (ev: BillingUnprocessedEvent) => void;
}

function UnprocessedRow({ event: ev, companies, companyAbbrev, expectedRevenue, onConfirm, onDismiss }: RowProps) {
  const { demo } = useDemoMode();
  const [expanded, setExpanded] = useState(false);

  // Company selector — pre-filled from inferred company
  const [companyId, setCompanyId] = useState<number | ''>(ev.inferred_company_id ?? '');

  // Client selector — pre-filled from inferred client; NO_CLIENT = company-only
  const [clientId, setClientId] = useState<number | '' | typeof NO_CLIENT>(ev.inferred_client_id ?? '');

  const [duration, setDuration] = useState(String(ev.duration_hours.toFixed(2)));
  const [notes, setNotes] = useState('');

  // When company changes, reset client unless the current client still belongs to the new company
  function handleCompanyChange(newCoId: number | '') {
    setCompanyId(newCoId);
    if (clientId !== '' && clientId !== NO_CLIENT) {
      const cl = companies.flatMap(co => co.clients).find(c => c.id === Number(clientId));
      if (cl && cl.company_id !== newCoId) setClientId('');
    }
  }

  // When client changes, sync company to the client's company
  function handleClientChange(val: string) {
    if (val === NO_CLIENT) {
      setClientId(NO_CLIENT);
    } else if (val === '') {
      setClientId('');
    } else {
      const numId = Number(val);
      setClientId(numId);
      const cl = companies.flatMap(co => co.clients).find(c => c.id === numId);
      if (cl) setCompanyId(cl.company_id);
    }
  }

  const noClient = clientId === NO_CLIENT;
  const filteredClients = companyId
    ? companies.find(co => co.id === companyId)?.clients.filter(cl => cl.active) ?? []
    : companies.flatMap(co => co.clients.filter(cl => cl.active));

  const selectedClient = !noClient && clientId !== ''
    ? companies.flatMap(co => co.clients).find(cl => cl.id === Number(clientId))
    : null;
  const selectedCompany = companyId ? companies.find(co => co.id === companyId) : null;
  const effectiveRate = selectedClient?.rate_override
    ?? selectedCompany?.default_rate
    ?? null;

  const isConfidenceHigh = ev.inferred_confidence >= 0.75;
  const canConfirm = noClient ? !!companyId && notes.trim().length > 0 : !!clientId;

  // Session number preview — fetched when a client is selected
  const nextNumClientId = (!noClient && clientId !== '' && typeof clientId === 'number') ? clientId : null;
  const { data: nextNumData } = useBillingNextSessionNumber(nextNumClientId);
  if (nextNumClientId != null) console.log('[next-number] client_id=', nextNumClientId, '→', nextNumData);

  // Derive display values from local state so edits are reflected immediately in the collapsed row
  const displayAbbrev = selectedCompany?.abbrev ?? companyAbbrev ?? null;
  const displayClient = selectedClient?.name ?? (noClient ? null : ev.inferred_client_name ?? null);
  const displayRevenue = effectiveRate != null
    ? Math.round(parseFloat(duration || '0') * effectiveRate * 100) / 100
    : expectedRevenue ?? null;

  return (
    <div style={{ border: '1px solid var(--color-border)', borderRadius: 4, marginBottom: 'var(--space-xs)', background: expanded ? 'var(--color-bg)' : undefined }}>
      {/* Collapsed header */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', padding: '6px 10px', cursor: 'pointer' }}
        onClick={() => setExpanded(e => !e)}
      >
        <span style={{ fontSize: '0.65em', opacity: 0.4 }}>{expanded ? '▾' : '▸'}</span>
        {colorBadge(ev.color_id)}
        <span style={{ width: 90, fontSize: 'var(--text-sm)', flexShrink: 0, color: 'var(--color-text-light)' }}>{formatDate(ev.start_time)}</span>
        {displayAbbrev && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', flexShrink: 0, minWidth: 28 }}>
            {displayAbbrev}
          </span>
        )}
        {displayClient && (
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', width: 160, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {confidenceBadge(ev.inferred_confidence)} {displayClient}
          </span>
        )}
        {ev.obsidian?.found && (
          <a href={ev.obsidian.obsidian_link} title="Open in Obsidian"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', textDecoration: 'none', flexShrink: 0 }}
            onClick={e => e.stopPropagation()}>◆</a>
        )}
        <span style={{ width: 314, flexShrink: 0, fontSize: 'var(--text-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.summary}</span>
        <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', width: 52, flexShrink: 0 }}>
          {Math.round(ev.duration_hours * 60)}min
        </span>
        {displayRevenue != null && (
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', width: 60, flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
            {demo ? '—' : `$${displayRevenue.toFixed(2)}`}
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 'var(--space-xs)', flexShrink: 0 }}>
          {ev.inferred_client_id && !expanded && (
            <button
              className="btn-primary"
              style={{ fontSize: 'var(--text-xs)', padding: '2px 8px',
                ...(isConfidenceHigh ? {} : { background: '#e9a040', borderColor: '#c8861a' }) }}
              title={isConfidenceHigh
                ? `Confirm: ${ev.inferred_client_name}`
                : `Low confidence (${Math.round(ev.inferred_confidence * 100)}%) — review client assignment before confirming`}
              onClick={e => { e.stopPropagation(); onConfirm(ev, ev.inferred_client_id!, ev.inferred_company_id ?? null, ev.duration_hours, ''); }}
            >
              {isConfidenceHigh ? '✓' : '⚠ ✓'}
            </button>
          )}
          <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}
            title="Skip this event" onClick={e => { e.stopPropagation(); onDismiss(ev); }}>×</button>
        </span>
      </div>

      {/* Expanded form */}
      {expanded && (
        <div style={{ padding: '8px 12px 12px', borderTop: '1px solid var(--color-border)', display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
          {/* Event meta */}
          <div style={{ display: 'flex', gap: 'var(--space-md)', flexWrap: 'wrap', fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
            <span>{formatDate(ev.start_time)} {formatTime(ev.start_time)}–{formatTime(ev.end_time)}</span>
            <span>Slot: {ev.slot_hours.toFixed(2)}h</span>
            {ev.obsidian?.found
              ? <a href={ev.obsidian.obsidian_link} style={{ color: 'var(--color-accent)' }}>
                  {ev.obsidian.duration_hours ? `Note: ${ev.obsidian.duration_hours.toFixed(2)}h` : 'Note found (no duration)'}
                </a>
              : <span>No Obsidian note</span>}
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            {/* Company selector */}
            <div>
              <label style={{ fontSize: 'var(--text-xs)', display: 'block', color: 'var(--color-text-light)', marginBottom: 2 }}>Company</label>
              <select
                value={companyId}
                onChange={e => handleCompanyChange(e.target.value ? Number(e.target.value) : '')}
                style={{ minWidth: 160 }}
              >
                <option value="">— all companies —</option>
                {companies.filter(co => co.active).map(co => (
                  <option key={co.id} value={co.id}>{co.name}</option>
                ))}
              </select>
            </div>

            {/* Client selector */}
            <div>
              <label style={{ fontSize: 'var(--text-xs)', display: 'block', color: 'var(--color-text-light)', marginBottom: 2 }}>Client</label>
              <select
                value={clientId === NO_CLIENT ? NO_CLIENT : (clientId === '' ? '' : String(clientId))}
                onChange={e => handleClientChange(e.target.value)}
                style={{ minWidth: 180 }}
              >
                <option value="">— select client —</option>
                {companyId
                  ? filteredClients.map(cl => <option key={cl.id} value={cl.id}>{cl.name}</option>)
                  : companies.map(co => (
                      <optgroup key={co.id} label={co.name}>
                        {co.clients.filter(cl => cl.active).map(cl => <option key={cl.id} value={cl.id}>{cl.name}</option>)}
                      </optgroup>
                    ))
                }
                <option value={NO_CLIENT}>— no specific client —</option>
              </select>
            </div>

            {/* Duration */}
            <div>
              <label style={{ fontSize: 'var(--text-xs)', display: 'block', color: 'var(--color-text-light)', marginBottom: 2 }}>Duration (hrs)</label>
              <input type="number" step="0.25" min="0" value={duration} onChange={e => setDuration(e.target.value)} style={{ width: 80 }} />
            </div>

            {/* Session number preview */}
            {nextNumData && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', alignSelf: 'flex-end', paddingBottom: 6 }}>
                Session <strong>#{nextNumData.next_number}</strong>
              </div>
            )}

            {/* Rate preview (client path) */}
            {selectedClient && effectiveRate && !noClient && (
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', alignSelf: 'flex-end', paddingBottom: 4 }}>
                {demo ? '—' : `$${effectiveRate}/hr → `}{demo ? '' : <strong>{`$${(parseFloat(duration || '0') * effectiveRate).toFixed(2)}`}</strong>}
                {selectedClient.prepaid && <span style={{ marginLeft: 6 }}>(prepaid)</span>}
              </div>
            )}

            {/* Company rate preview (no-client path) */}
            {noClient && selectedCompany?.default_rate && (
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', alignSelf: 'flex-end', paddingBottom: 4 }}>
                {demo ? '—' : `$${selectedCompany.default_rate}/hr → `}{demo ? '' : <strong>{`$${(parseFloat(duration || '0') * selectedCompany.default_rate).toFixed(2)}`}</strong>}
              </div>
            )}
          </div>

          {/* Description / notes — required for no-client, optional otherwise */}
          <div>
            <label style={{ fontSize: 'var(--text-xs)', display: 'block', color: 'var(--color-text-light)', marginBottom: 2 }}>
              {noClient ? 'Description (required — used on invoice)' : 'Notes'}
            </label>
            <input
              type="text"
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder={noClient ? 'e.g. Offsite planning, Team workshop' : 'optional'}
              style={{ width: '100%', borderColor: noClient && !notes.trim() ? 'var(--color-error)' : undefined }}
            />
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
            <button
              className="btn-primary"
              disabled={!canConfirm}
              onClick={() => {
                if (!canConfirm) return;
                const cId = noClient ? null : Number(clientId);
                const coId = noClient ? Number(companyId) : null;
                onConfirm(ev, cId, coId, parseFloat(duration || '0'), notes);
              }}
            >
              Confirm session
            </button>
            <button className="btn-link" onClick={() => onDismiss(ev)}>Dismiss</button>
            <button className="btn-link" style={{ color: 'var(--color-text-light)' }} onClick={() => {
              setCompanyId(ev.inferred_company_id ?? '');
              setClientId(ev.inferred_client_id ?? '');
              setDuration(String(ev.duration_hours.toFixed(2)));
              setNotes('');
              setExpanded(false);
            }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unprocessed queue
// ---------------------------------------------------------------------------

function UnprocessedQueue() {
  const { demo } = useDemoMode();
  const { data, isLoading } = useBillingUnprocessed();
  const { data: companies = [] } = useBillingCompanies();
  const confirm = useConfirmBillingSession();
  const dismiss = useDismissBillingEvent();
  const unprocess = useUnprocessBillingSession();
  const syncCalendar = useBillingSyncCalendar();

  const { year, month, company } = useBillingScope();
  const [showBanana, setShowBanana] = useState(true);
  const [showDismissed, setShowDismissed] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');
  const { data: dismissedSessions = [] } = useBillingDismissedSessions();
  const [blockWarnings, setBlockWarnings] = useState<string[]>([]);

  // Helper: look up effective rate for an event from companies data
  function effectiveRate(ev: BillingUnprocessedEvent): number | null {
    if (ev.inferred_client_id) {
      const cl = companies.flatMap(co => co.clients).find(c => c.id === ev.inferred_client_id);
      if (cl?.rate_override != null) return cl.rate_override;
      const co = companies.find(c => c.id === cl?.company_id);
      return co?.default_rate ?? null;
    }
    if (ev.inferred_company_id) {
      return companies.find(co => co.id === ev.inferred_company_id)?.default_rate ?? null;
    }
    return null;
  }

  function expectedRevenue(ev: BillingUnprocessedEvent): number | null {
    const r = effectiveRate(ev);
    return r != null ? Math.round(ev.duration_hours * r * 100) / 100 : null;
  }

  function companyAbbrev(ev: BillingUnprocessedEvent): string | null {
    const coId = ev.inferred_company_id
      ?? (ev.inferred_client_id
        ? companies.flatMap(co => co.clients).find(c => c.id === ev.inferred_client_id)?.company_id
        : null);
    if (coId == null) return null;
    const co = companies.find(c => c.id === coId);
    return co?.abbrev ?? co?.name ?? null;
  }

  const groupIds = resolveGroupIds(company, companies);
  const singleCoId = !groupIds && company ? Number(company) : null;

  const events = data?.events ?? [];
  const visible = events
    .filter(ev => {
      if (!showBanana && ev.color_id === '5') return false;
      const dateStr = ev.start_time.slice(0, 10);
      const evYear = Number(dateStr.slice(0, 4));
      const evMonth = Number(dateStr.slice(5, 7));
      if (evYear !== year) return false;
      if (month !== null && evMonth !== month) return false;
      if (company) {
        const coId = ev.inferred_company_id;
        if (groupIds !== null) {
          if (!coId || !groupIds.has(coId)) return false;
        } else {
          if (coId !== singleCoId) return false;
        }
      }
      return true;
    })
    .sort((a, b) => a.start_time.localeCompare(b.start_time));

  const grapeCount = events.filter(e => e.color_id === '3').length;
  const bananaCount = events.filter(e => e.color_id === '5').length;
  const totalHours = visible.reduce((s, e) => s + e.duration_hours, 0);
  const totalRevenue = visible.reduce((s, e) => s + (expectedRevenue(e) ?? 0), 0);

  // Group into months (for month headers) while keeping flat date order within each month
  const byMonth = new Map<string, BillingUnprocessedEvent[]>();
  for (const ev of visible) {
    const mk = ev.start_time.slice(0, 7); // YYYY-MM
    if (!byMonth.has(mk)) byMonth.set(mk, []);
    byMonth.get(mk)!.push(ev);
  }
  const monthEntries = [...byMonth.entries()].sort(([a], [b]) => a.localeCompare(b));

  if (isLoading) return <p className="empty-state">Loading…</p>;

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginBottom: 'var(--space-md)', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Unprocessed Sessions</h2>
        <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
          {grapeCount} grape · {bananaCount} banana
        </span>
        <label style={{ fontSize: 'var(--text-sm)', display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={showBanana} onChange={e => setShowBanana(e.target.checked)} />
          Show banana
        </label>
        {visible.length > 0 && (
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
            {visible.length} events · {totalHours.toFixed(2)}h · <strong>{demo ? '—' : `$${totalRevenue.toFixed(2)}`}</strong>
          </span>
        )}
        {(() => {
          const confirmable = visible.filter(ev => ev.inferred_client_id);
          if (confirmable.length === 0) return null;
          return (
            <button
              className="btn-primary"
              style={{ fontSize: 'var(--text-xs)', padding: '2px 8px', background: '#5a8a5a', borderColor: '#3d6b3d' }}
              title={`Confirm all ${confirmable.length} events with inferred clients`}
              onClick={() => {
                if (!window.confirm(`Confirm all ${confirmable.length} events using their inferred client assignments?`)) return;
                for (const ev of confirmable) {
                  confirm.mutate({ calendar_event_id: ev.calendar_event_id, client_id: ev.inferred_client_id!, company_id: ev.inferred_company_id ?? null, duration_hours: ev.duration_hours, notes: '' });
                }
              }}
            >
              ✓ All ({confirmable.length})
            </button>
          );
        })()}
        <label style={{ fontSize: 'var(--text-sm)', display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={showDismissed} onChange={e => setShowDismissed(e.target.checked)} />
          Show dismissed
        </label>
        {syncMsg && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>{syncMsg}</span>
        )}
        <button
          className="btn-link"
          style={{ marginLeft: 'auto' }}
          disabled={syncCalendar.isPending}
          title="Sync Google Calendar, promote banana→grape, then reload queue"
          onClick={() => {
            setSyncMsg('');
            syncCalendar.mutate(undefined, {
              onSuccess: (r) => {
                const parts = [];
                if (r.synced) parts.push(`${r.synced} events synced`);
                if (r.promoted) parts.push(`${r.promoted} promoted`);
                setSyncMsg(parts.length ? parts.join(', ') : 'Up to date');
              },
              onError: () => setSyncMsg('Sync failed'),
            });
          }}
        >
          {syncCalendar.isPending ? '…' : '↻ Refresh'}
        </button>
      </div>

      {visible.length === 0 && (
        <p className="empty-state">
          {events.length === 0 ? 'No unprocessed sessions.' : 'No sessions match the current filters.'}
        </p>
      )}

      {blockWarnings.length > 0 && (
        <div style={{
          padding: 'var(--space-sm) var(--space-md)',
          marginBottom: 'var(--space-md)',
          background: 'color-mix(in srgb, #f59e0b 15%, transparent)',
          border: '1px solid #f59e0b',
          borderRadius: 4,
          fontSize: 'var(--text-sm)',
        }}>
          <strong>⚠️ No active prepaid block:</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
            {blockWarnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
          <button className="btn-link" style={{ fontSize: 'var(--text-xs)', marginTop: 4 }} onClick={() => setBlockWarnings([])}>Dismiss</button>
        </div>
      )}

      {monthEntries.map(([monthKey, mEvents]) => {
        const mHours = mEvents.reduce((s, e) => s + e.duration_hours, 0);
        const mRevenue = mEvents.reduce((s, e) => s + (expectedRevenue(e) ?? 0), 0);
        return (
          <div key={monthKey} style={{ marginBottom: 'var(--space-xl)' }}>
            <div style={{
              fontWeight: 700, fontSize: 'var(--text-sm)', padding: '5px 8px',
              borderBottom: '2px solid var(--color-border)',
              marginBottom: 'var(--space-sm)',
              display: 'flex', justifyContent: 'space-between',
            }}>
              <span>{getMonthLabel(monthKey)}</span>
              <span style={{ fontWeight: 400, color: 'var(--color-text-light)' }}>
                {mEvents.length} events · {mHours.toFixed(2)}h · <strong style={{ color: 'var(--color-fg)' }}>{demo ? '—' : `$${mRevenue.toFixed(2)}`}</strong>
              </span>
            </div>

            {mEvents.map(ev => {
              const abbrev = companyAbbrev(ev);
              const rev = expectedRevenue(ev);
              return (
                <UnprocessedRow
                  key={ev.calendar_event_id}
                  event={ev}
                  companies={companies}
                  companyAbbrev={abbrev}
                  expectedRevenue={rev}
                  onConfirm={(ev, clientId, companyId, durationHours, notes) => {
                    confirm.mutate(
                      { calendar_event_id: ev.calendar_event_id, client_id: clientId, company_id: companyId, duration_hours: durationHours, notes },
                      {
                        onSuccess: (session) => {
                          if (session.no_active_prepaid_block) {
                            setBlockWarnings(w => [...w, `${session.client_name ?? 'Client'} — session confirmed but no active prepaid block found`]);
                          }
                        },
                      }
                    );
                  }}
                  onDismiss={ev => {
                    if (window.confirm(`Dismiss "${ev.summary}"?`)) dismiss.mutate(ev.calendar_event_id);
                  }}
                />
              );
            })}
          </div>
        );
      })}

      {showDismissed && (
        <div style={{ marginTop: 'var(--space-xl)' }}>
          <div style={{
            fontWeight: 700, fontSize: 'var(--text-sm)', padding: '5px 8px',
            borderBottom: '2px solid var(--color-border)',
            marginBottom: 'var(--space-sm)',
          }}>
            Dismissed ({dismissedSessions.length})
          </div>
          {dismissedSessions.length === 0 && (
            <p className="empty-state">No dismissed sessions.</p>
          )}
          {dismissedSessions.map(s => (
            <div key={s.id} style={{
              display: 'flex', alignItems: 'center', gap: 'var(--space-sm)',
              padding: '5px 10px', fontSize: 'var(--text-sm)',
              border: '1px solid var(--color-border)', borderRadius: 4,
              marginBottom: 'var(--space-xs)',
              opacity: 0.7,
            }}>
              {s.color_id && colorBadge(s.color_id)}
              <span style={{ width: 90, flexShrink: 0, color: 'var(--color-text-light)' }}>
                {s.start_time ? formatDate(s.start_time) : s.date}
              </span>
              {s.client_name && (
                <span style={{ color: 'var(--color-text-light)', width: 160, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {s.client_name}
                </span>
              )}
              {s.company_name && !s.client_name && (
                <span style={{ color: 'var(--color-text-light)', width: 160, flexShrink: 0 }}>{s.company_name}</span>
              )}
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {s.summary ?? '—'}
              </span>
              <button
                className="btn-link"
                style={{ flexShrink: 0, fontSize: 'var(--text-xs)' }}
                title="Restore to queue"
                onClick={() => unprocess.mutate(s.id)}
              >
                Restore
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Invoice helpers
// ---------------------------------------------------------------------------

function statusBadge(status: string) {
  const colors: Record<string, { bg: string; fg: string }> = {
    draft:   { bg: '#e8e8e8', fg: '#555' },
    sent:    { bg: '#d0e8ff', fg: '#1a5fa8' },
    paid:    { bg: '#d4edda', fg: '#1a6631' },
    partial: { bg: '#fde8c0', fg: '#a05a00' },
  };
  const c = colors[status] ?? colors.draft;
  return (
    <span style={{ background: c.bg, color: c.fg, borderRadius: 3, padding: '1px 7px', fontSize: 'var(--text-xs)', fontWeight: 500 }}>
      {status}
    </span>
  );
}

function formatPeriod(periodMonth: string | null) {
  if (!periodMonth) return '—';
  const [y, m] = periodMonth.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

// ---------------------------------------------------------------------------
// Invoice list view — /billing/invoices
// ---------------------------------------------------------------------------



// ---------------------------------------------------------------------------
// Send Invoice Modal
// ---------------------------------------------------------------------------

interface SendInvoiceModalProps {
  invoiceId: number;
  onClose: () => void;
}

function SendInvoiceModal({ invoiceId, onClose }: SendInvoiceModalProps) {
  const { data: composed, isLoading, error } = useComposeInvoiceEmail(invoiceId);
  const saveDraft = useSaveInvoiceDraft();
  const sendEmail = useSendInvoiceEmail();

  const [to, setTo] = useState('');
  const [cc, setCc] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [initialized, setInitialized] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  // Pre-fill fields once compose data arrives
  useEffect(() => {
    if (composed && !initialized) {
      setTo(composed.to);
      setCc(composed.cc);
      setSubject(composed.subject);
      setBody(composed.body);
      setInitialized(true);
    }
  }, [composed, initialized]);

  function handleSaveDraft() {
    setFeedback(null);
    saveDraft.mutate(
      { invoiceId, to, cc, subject, body },
      {
        onSuccess: () => { setFeedback('Draft saved to Gmail.'); setTimeout(onClose, 1200); },
        onError: (e: unknown) => setFeedback(`Draft failed: ${e instanceof Error ? e.message : String(e)}`),
      },
    );
  }

  function handleSend() {
    if (!composed?.pdf_path) {
      setFeedback('Generate the PDF first before sending.');
      return;
    }
    setFeedback(null);
    sendEmail.mutate(
      { invoiceId, to, cc, subject, body },
      {
        onSuccess: () => { setFeedback('Sent!'); setTimeout(onClose, 1200); },
        onError: (e: unknown) => setFeedback(`Send failed: ${e instanceof Error ? e.message : String(e)}`),
      },
    );
  }

  const busy = saveDraft.isPending || sendEmail.isPending;

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 6, padding: 'var(--space-lg)', width: 620, maxWidth: '95vw', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
        <h3 style={{ margin: 0 }}>Send Invoice</h3>

        {isLoading && <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-sm)' }}>Composing…</p>}
        {error && <p style={{ color: 'var(--color-error)', fontSize: 'var(--text-sm)' }}>Failed to compose email.</p>}

        {initialized && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr', gap: 6, alignItems: 'center', fontSize: 'var(--text-sm)' }}>
              <label style={{ color: 'var(--color-text-light)', textAlign: 'right' }}>To</label>
              <input value={to} onChange={e => setTo(e.target.value)} style={{ fontSize: 'var(--text-sm)' }} />
              <label style={{ color: 'var(--color-text-light)', textAlign: 'right' }}>CC</label>
              <input value={cc} onChange={e => setCc(e.target.value)} style={{ fontSize: 'var(--text-sm)' }} />
              <label style={{ color: 'var(--color-text-light)', textAlign: 'right' }}>Subject</label>
              <input value={subject} onChange={e => setSubject(e.target.value)} style={{ fontSize: 'var(--text-sm)' }} />
            </div>
            <textarea
              value={body}
              onChange={e => setBody(e.target.value)}
              rows={10}
              style={{ width: '100%', fontSize: 'var(--text-sm)', resize: 'vertical', fontFamily: 'monospace', boxSizing: 'border-box' }}
            />
            {composed && (
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', margin: 0 }}>
                Attachment: {composed.pdf_filename}
                {!composed.pdf_path && <span style={{ color: 'var(--color-error)', marginLeft: 8 }}>⚠ PDF not generated — generate it first to send with attachment</span>}
              </p>
            )}
            {feedback && <p style={{ fontSize: 'var(--text-sm)', color: feedback.startsWith('Send') || feedback.startsWith('Draft failed') ? 'var(--color-error)' : 'var(--color-accent)', margin: 0 }}>{feedback}</p>}
            <div style={{ display: 'flex', gap: 'var(--space-sm)', justifyContent: 'flex-end', marginTop: 'var(--space-xs)' }}>
              <button className="btn-link" onClick={onClose} disabled={busy}>Cancel</button>
              <button className="btn-secondary" onClick={handleSaveDraft} disabled={busy || !to}>
                {saveDraft.isPending ? 'Saving…' : 'Save Draft'}
              </button>
              <button className="btn-primary" onClick={handleSend} disabled={busy || !to}>
                {sendEmail.isPending ? 'Sending…' : 'Send'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CSV Import Modal
// ---------------------------------------------------------------------------

interface CsvRow {
  company_name: string;
  invoice_number: string;
  period_month: string;
  invoice_date: string;
  total_amount: string;
  status: string;
  notes: string;
  // client-side validation
  errors: string[];
}

const CSV_REQUIRED = ['company_name', 'invoice_number', 'period_month', 'total_amount'] as const;
const PERIOD_RE = /^\d{4}-\d{2}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function parseCsv(text: string): { headers: string[]; rows: Record<string, string>[] } {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 1) return { headers: [], rows: [] };

  function splitLine(line: string): string[] {
    const fields: string[] = [];
    let cur = '';
    let inQuote = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuote && line[i + 1] === '"') { cur += '"'; i++; }
        else { inQuote = !inQuote; }
      } else if (ch === ',' && !inQuote) {
        fields.push(cur.trim()); cur = '';
      } else {
        cur += ch;
      }
    }
    fields.push(cur.trim());
    return fields;
  }

  const headers = splitLine(lines[0]).map(h => h.toLowerCase().replace(/\s+/g, '_'));
  const rows = lines.slice(1).filter(l => l.trim()).map(l => {
    const vals = splitLine(l);
    const obj: Record<string, string> = {};
    headers.forEach((h, i) => { obj[h] = vals[i] ?? ''; });
    return obj;
  });
  return { headers, rows };
}

function validateCsvRow(row: Record<string, string>, knownCompanies: Set<string>): CsvRow {
  const errors: string[] = [];

  for (const f of CSV_REQUIRED) {
    if (!row[f]?.trim()) errors.push(`Missing ${f}`);
  }

  if (row.total_amount && isNaN(parseFloat(row.total_amount))) {
    errors.push('total_amount must be a number');
  }
  if (row.period_month && !PERIOD_RE.test(row.period_month.trim())) {
    errors.push('period_month must be YYYY-MM');
  }
  if (row.invoice_date && row.invoice_date.trim() && !DATE_RE.test(row.invoice_date.trim())) {
    errors.push('invoice_date must be YYYY-MM-DD');
  }
  if (row.company_name?.trim() && !knownCompanies.has(row.company_name.trim().toLowerCase())) {
    errors.push(`Unknown company: "${row.company_name.trim()}"`);
  }

  return {
    company_name: row.company_name?.trim() ?? '',
    invoice_number: row.invoice_number?.trim() ?? '',
    period_month: row.period_month?.trim() ?? '',
    invoice_date: row.invoice_date?.trim() ?? '',
    total_amount: row.total_amount?.trim() ?? '',
    status: row.status?.trim() || 'sent',
    notes: row.notes?.trim() ?? '',
    errors,
  };
}

interface ImportCsvModalProps {
  companies: BillingCompany[];
  onClose: () => void;
}

function ImportCsvModal({ companies, onClose }: ImportCsvModalProps) {
  const importMut = useBulkImportInvoices();
  const [step, setStep] = useState<'upload' | 'preview' | 'result'>('upload');
  const [rows, setRows] = useState<CsvRow[]>([]);
  const [result, setResult] = useState<InvoiceBulkImportResult | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const knownCompanies = new Set(companies.map(c => c.name.toLowerCase()));

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setParseError(null);
    const reader = new FileReader();
    reader.onload = ev => {
      const text = ev.target?.result as string;
      try {
        const { headers, rows: rawRows } = parseCsv(text);
        const missing = CSV_REQUIRED.filter(f => !headers.includes(f));
        if (missing.length) {
          setParseError(`CSV is missing required columns: ${missing.join(', ')}`);
          return;
        }
        const parsed = rawRows.map(r => validateCsvRow(r, knownCompanies));
        if (parsed.length === 0) { setParseError('CSV contains no data rows.'); return; }
        setRows(parsed);
        setStep('preview');
      } catch {
        setParseError('Failed to parse CSV file.');
      }
    };
    reader.readAsText(file);
  }

  function handleImport() {
    const valid = rows.filter(r => r.errors.length === 0);
    if (!valid.length) return;
    const payload: InvoiceBulkImportRow[] = valid.map(r => ({
      company_name: r.company_name,
      invoice_number: r.invoice_number,
      period_month: r.period_month,
      invoice_date: r.invoice_date || undefined,
      total_amount: parseFloat(r.total_amount),
      status: r.status,
      notes: r.notes || undefined,
    }));
    importMut.mutate(payload, {
      onSuccess: res => { setResult(res); setStep('result'); },
    });
  }

  const validCount = rows.filter(r => r.errors.length === 0).length;
  const invalidCount = rows.length - validCount;

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 6, padding: 'var(--space-lg)', width: 820, maxWidth: '97vw', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>

        {/* Upload step */}
        {step === 'upload' && (
          <>
            <h3 style={{ margin: 0 }}>Import Invoices from CSV</h3>
            <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
              <p style={{ margin: '0 0 8px' }}>Upload a CSV file with historical invoices. Required columns: <code>company_name</code>, <code>invoice_number</code>, <code>period_month</code> (YYYY-MM), <code>total_amount</code>. Optional: <code>invoice_date</code> (YYYY-MM-DD), <code>status</code> (default: sent), <code>notes</code>.</p>
              <a
                href="/api/billing/invoices/csv-template"
                download="invoice_import_template.csv"
                style={{ color: 'var(--color-accent)', fontSize: 'var(--text-sm)' }}
              >
                ↓ Download CSV template
              </a>
            </div>
            <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={handleFile} style={{ fontSize: 'var(--text-sm)' }} />
            {parseError && <p style={{ color: 'var(--color-error)', fontSize: 'var(--text-sm)', margin: 0 }}>{parseError}</p>}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button className="btn-link" onClick={onClose}>Cancel</button>
            </div>
          </>
        )}

        {/* Preview step */}
        {step === 'preview' && (
          <>
            <h3 style={{ margin: 0 }}>Preview — {rows.length} row{rows.length !== 1 ? 's' : ''}</h3>
            {invalidCount > 0 && (
              <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-error)' }}>
                {invalidCount} row{invalidCount !== 1 ? 's' : ''} have errors and will be skipped. {validCount} will be imported.
              </p>
            )}
            {invalidCount === 0 && (
              <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
                All {validCount} rows are valid.
              </p>
            )}
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 'var(--text-xs)', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                    <th style={{ padding: '4px 6px' }}>#</th>
                    <th style={{ padding: '4px 6px' }}>Company</th>
                    <th style={{ padding: '4px 6px' }}>Invoice #</th>
                    <th style={{ padding: '4px 6px' }}>Period</th>
                    <th style={{ padding: '4px 6px' }}>Date</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Amount</th>
                    <th style={{ padding: '4px 6px' }}>Status</th>
                    <th style={{ padding: '4px 6px' }}>Notes</th>
                    <th style={{ padding: '4px 6px' }}>Validation</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => {
                    const ok = row.errors.length === 0;
                    return (
                      <tr
                        key={i}
                        style={{
                          borderBottom: '1px solid var(--color-border)',
                          background: ok ? undefined : 'rgba(220,50,50,0.06)',
                        }}
                      >
                        <td style={{ padding: '4px 6px', color: 'var(--color-text-light)' }}>{i + 1}</td>
                        <td style={{ padding: '4px 6px' }}>{row.company_name || <span style={{ color: 'var(--color-error)' }}>—</span>}</td>
                        <td style={{ padding: '4px 6px', fontFamily: 'monospace' }}>{row.invoice_number || <span style={{ color: 'var(--color-error)' }}>—</span>}</td>
                        <td style={{ padding: '4px 6px' }}>{row.period_month}</td>
                        <td style={{ padding: '4px 6px', color: 'var(--color-text-light)' }}>{row.invoice_date || '—'}</td>
                        <td style={{ padding: '4px 6px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                          {row.total_amount ? `$${parseFloat(row.total_amount).toFixed(2)}` : <span style={{ color: 'var(--color-error)' }}>—</span>}
                        </td>
                        <td style={{ padding: '4px 6px' }}>{row.status}</td>
                        <td style={{ padding: '4px 6px', color: 'var(--color-text-light)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.notes || '—'}</td>
                        <td style={{ padding: '4px 6px' }}>
                          {ok
                            ? <span style={{ color: 'var(--color-accent)' }}>✓</span>
                            : <span style={{ color: 'var(--color-error)', fontSize: 'var(--text-xs)' }}>{row.errors.join('; ')}</span>
                          }
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-sm)', justifyContent: 'flex-end', alignItems: 'center' }}>
              <button className="btn-link" onClick={() => { setStep('upload'); setRows([]); if (fileRef.current) fileRef.current.value = ''; }}>← Back</button>
              <button className="btn-link" onClick={onClose}>Cancel</button>
              <button
                className="btn-primary"
                onClick={handleImport}
                disabled={validCount === 0 || importMut.isPending}
              >
                {importMut.isPending ? 'Importing…' : `Import ${validCount} invoice${validCount !== 1 ? 's' : ''}`}
              </button>
            </div>
          </>
        )}

        {/* Result step */}
        {step === 'result' && result && (
          <>
            <h3 style={{ margin: 0 }}>Import Complete</h3>
            <p style={{ margin: 0, fontSize: 'var(--text-sm)' }}>
              <strong style={{ color: 'var(--color-accent)' }}>{result.created} created</strong>
              {result.skipped > 0 && <span style={{ color: 'var(--color-error)', marginLeft: 12 }}>{result.skipped} skipped</span>}
            </p>
            {result.results.some(r => r.status === 'error') && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: 'var(--text-xs)', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                      <th style={{ padding: '4px 6px' }}>Row</th>
                      <th style={{ padding: '4px 6px' }}>Invoice #</th>
                      <th style={{ padding: '4px 6px' }}>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.results.filter(r => r.status === 'error').map((r, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--color-border)' }}>
                        <td style={{ padding: '4px 6px', color: 'var(--color-text-light)' }}>{r.row}</td>
                        <td style={{ padding: '4px 6px', fontFamily: 'monospace' }}>{r.invoice_number}</td>
                        <td style={{ padding: '4px 6px', color: 'var(--color-error)' }}>{r.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button className="btn-primary" onClick={onClose}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// New Invoice Modal
// ---------------------------------------------------------------------------

interface NewInvoiceModalProps {
  companies: BillingCompany[];
  onClose: () => void;
}

function NewInvoiceModal({ companies, onClose }: NewInvoiceModalProps) {
  const create = useCreateBillingInvoice();
  const navigate = useNavigate();

  const today = new Date().toISOString().slice(0, 10);
  const thisMonth = today.slice(0, 7);

  const [companyId, setCompanyId] = useState<number | ''>(companies[0]?.id ?? '');
  const [invoiceNumber, setInvoiceNumber] = useState('');
  const [periodMonth, setPeriodMonth] = useState(thisMonth);
  const [invoiceDate, setInvoiceDate] = useState(today);
  const [servicesDate, setServicesDate] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [status, setStatus] = useState('sent');
  const [totalAmount, setTotalAmount] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<InvoiceLineInput[]>([]);
  const [error, setError] = useState<string | null>(null);

  function addLine() {
    setLines(ls => [...ls, { description: '', amount: 0 }]);
  }

  function updateLine(i: number, field: keyof InvoiceLineInput, value: string) {
    setLines(ls => ls.map((l, idx) =>
      idx === i ? { ...l, [field]: field === 'amount' ? parseFloat(value) || 0 : value } : l
    ));
  }

  function removeLine(i: number) {
    setLines(ls => ls.filter((_, idx) => idx !== i));
  }

  function handleSave() {
    setError(null);
    if (!companyId) { setError('Select a company.'); return; }
    if (!invoiceNumber.trim()) { setError('Invoice number is required.'); return; }
    if (!periodMonth) { setError('Period month is required.'); return; }
    const amount = parseFloat(totalAmount);
    if (isNaN(amount)) { setError('Total amount must be a number.'); return; }

    const validLines = lines.filter(l => l.description.trim());

    create.mutate(
      {
        company_id: Number(companyId),
        invoice_number: invoiceNumber.trim(),
        period_month: periodMonth,
        invoice_date: invoiceDate || undefined,
        services_date: servicesDate || undefined,
        due_date: dueDate || undefined,
        status,
        total_amount: amount,
        notes: notes || undefined,
        lines: validLines.length ? validLines : undefined,
      },
      {
        onSuccess: (inv) => {
          onClose();
          navigate(`/billing/invoices/${inv.id}`);
        },
        onError: (e: unknown) => {
          const msg = e instanceof Error ? e.message : String(e);
          setError(msg.includes('409') || msg.toLowerCase().includes('already') ? `Invoice number '${invoiceNumber}' already exists.` : msg);
        },
      },
    );
  }

  const labelStyle: React.CSSProperties = { fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 2, display: 'block' };
  const fieldStyle: React.CSSProperties = { fontSize: 'var(--text-sm)', width: '100%' };

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 6, padding: 'var(--space-lg)', width: 560, maxWidth: '95vw', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
        <h3 style={{ margin: 0 }}>New Invoice</h3>

        {/* Main fields */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-sm)' }}>
          <div style={{ gridColumn: '1 / -1' }}>
            <label style={labelStyle}>Company *</label>
            <select value={companyId} onChange={e => setCompanyId(Number(e.target.value))} style={{ ...fieldStyle }}>
              {companies.filter(c => c.active).map(co => (
                <option key={co.id} value={co.id}>{co.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={labelStyle}>Invoice Number *</label>
            <input
              value={invoiceNumber}
              onChange={e => setInvoiceNumber(e.target.value)}
              placeholder="e.g. 2025-ACME-03"
              style={fieldStyle}
            />
          </div>

          <div>
            <label style={labelStyle}>Status</label>
            <select value={status} onChange={e => setStatus(e.target.value)} style={fieldStyle}>
              <option value="sent">Sent</option>
              <option value="paid">Paid</option>
              <option value="partial">Partial</option>
              <option value="draft">Draft</option>
            </select>
          </div>

          <div>
            <label style={labelStyle}>Period Month *</label>
            <input type="month" value={periodMonth} onChange={e => setPeriodMonth(e.target.value)} style={fieldStyle} />
          </div>

          <div>
            <label style={labelStyle}>Total Amount *</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={totalAmount}
              onChange={e => setTotalAmount(e.target.value)}
              placeholder="0.00"
              style={fieldStyle}
            />
          </div>

          <div>
            <label style={labelStyle}>Invoice Date</label>
            <input type="date" value={invoiceDate} onChange={e => setInvoiceDate(e.target.value)} style={fieldStyle} />
          </div>

          <div>
            <label style={labelStyle}>Due Date</label>
            <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} style={fieldStyle} />
          </div>

          <div style={{ gridColumn: '1 / -1' }}>
            <label style={labelStyle}>Services Through</label>
            <input type="date" value={servicesDate} onChange={e => setServicesDate(e.target.value)} style={fieldStyle} />
          </div>

          <div style={{ gridColumn: '1 / -1' }}>
            <label style={labelStyle}>Notes</label>
            <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional" style={fieldStyle} />
          </div>
        </div>

        {/* Optional line items */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', marginBottom: 'var(--space-xs)' }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Line Items</span>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>(optional)</span>
            <button className="btn-link" style={{ fontSize: 'var(--text-xs)' }} onClick={addLine}>+ Add line</button>
          </div>
          {lines.map((line, i) => (
            <div key={i} style={{ display: 'flex', gap: 'var(--space-xs)', alignItems: 'center', marginBottom: 4 }}>
              <input
                value={line.description}
                onChange={e => updateLine(i, 'description', e.target.value)}
                placeholder="Description"
                style={{ flex: 3, fontSize: 'var(--text-sm)' }}
              />
              <input
                type="number"
                step="0.01"
                value={line.amount || ''}
                onChange={e => updateLine(i, 'amount', e.target.value)}
                placeholder="Amount"
                style={{ flex: 1, fontSize: 'var(--text-sm)' }}
              />
              <input
                value={line.date_range || ''}
                onChange={e => updateLine(i, 'date_range', e.target.value)}
                placeholder="Date range"
                style={{ flex: 1, fontSize: 'var(--text-sm)' }}
              />
              <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', flexShrink: 0 }} onClick={() => removeLine(i)}>×</button>
            </div>
          ))}
          {lines.length === 0 && (
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', margin: 0 }}>
              No line items — only the invoice total will be recorded.
            </p>
          )}
        </div>

        {error && <p style={{ color: 'var(--color-error)', fontSize: 'var(--text-sm)', margin: 0 }}>{error}</p>}

        <div style={{ display: 'flex', gap: 'var(--space-sm)', justifyContent: 'flex-end' }}>
          <button className="btn-link" onClick={onClose} disabled={create.isPending}>Cancel</button>
          <button className="btn-primary" onClick={handleSave} disabled={create.isPending}>
            {create.isPending ? 'Saving…' : 'Save Invoice'}
          </button>
        </div>
      </div>
    </div>
  );
}

function InvoicesListView() {
  const { demo } = useDemoMode();
  const { year, month, company } = useBillingScope();
  const navigate = useNavigate();
  const [filterStatus, setFilterStatus] = useState('');
  const [filterUnlinked, setFilterUnlinked] = useState(false);
  const { data: companies = [] } = useBillingCompanies();
  const groupIds = resolveGroupIds(company, companies);
  const apiCompanyId = !groupIds && company ? Number(company) : undefined;
  const { data: allInvoices = [], isLoading, refetch } = useBillingInvoices({
    company_id: apiCompanyId,
    status: filterStatus || undefined,
    period_month: month !== null ? `${year}-${String(month).padStart(2, '0')}` : undefined,
    period_year: month === null ? year : undefined,
  });
  const invoices = allInvoices
    .filter(inv => !groupIds || (inv.company_id !== null && groupIds.has(inv.company_id)))
    .filter(inv => !filterUnlinked || inv.unlinked_session_count > 0);
  const deleteMut = useDeleteBillingInvoice();
  const deleteAllMut = useDeleteBillingInvoicesBulk();
  const generatePdf = useBillingGeneratePdf();
  const { data: invoicesDirData } = useBillingInvoicesDir();
  const invoicesDir = invoicesDirData?.path ?? null;
  const [pdfGenerating, setPdfGenerating] = useState<Set<number>>(new Set());
  const [sendingInvoiceId, setSendingInvoiceId] = useState<number | null>(null);
  const [showNewInvoice, setShowNewInvoice] = useState(false);
  const [showImportCsv, setShowImportCsv] = useState(false);

  async function handleGeneratePdf(e: React.MouseEvent, inv: BillingInvoice) {
    e.stopPropagation();
    setPdfGenerating(s => new Set(s).add(inv.id));
    try { await generatePdf.mutateAsync(inv.id); } finally {
      setPdfGenerating(s => { const n = new Set(s); n.delete(inv.id); return n; });
    }
  }

  async function handleBulkGenerate() {
    for (const inv of invoices) {
      setPdfGenerating(s => new Set(s).add(inv.id));
      try { await generatePdf.mutateAsync(inv.id); } catch { /* continue */ } finally {
        setPdfGenerating(s => { const n = new Set(s); n.delete(inv.id); return n; });
      }
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginBottom: 'var(--space-sm)', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Invoices</h2>
        <button className="btn-secondary" style={{ fontSize: 'var(--text-sm)' }} onClick={() => setShowNewInvoice(true)}>+ New Invoice</button>
        <button className="btn-link" style={{ fontSize: 'var(--text-sm)' }} onClick={() => setShowImportCsv(true)}>Import CSV</button>
        <button className="btn-link" style={{ marginLeft: 'auto', fontSize: 'var(--text-sm)' }} onClick={() => refetch()}>↻</button>
      </div>
      <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginBottom: 'var(--space-md)', flexWrap: 'wrap' }}>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={{ fontSize: 'var(--text-sm)' }}>
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="sent">Sent</option>
          <option value="paid">Paid</option>
          <option value="partial">Partial</option>
        </select>
        <button
          className="btn-link"
          style={{ fontSize: 'var(--text-sm)', color: filterUnlinked ? '#e67e22' : 'var(--color-text-light)', fontWeight: filterUnlinked ? 600 : undefined }}
          onClick={() => setFilterUnlinked(v => !v)}
          title="Show only invoices with unlinked confirmed sessions"
        >
          {filterUnlinked ? '● ' : '○ '}Needs reconciliation
        </button>
        {allInvoices.length > 0 && (
          <button
            className="btn-link"
            style={{ fontSize: 'var(--text-sm)', color: '#c0392b', marginLeft: 'auto' }}
            disabled={deleteAllMut.isPending}
            onClick={() => {
              const label = month !== null
                ? `${MONTH_LABELS[month - 1]} ${year}`
                : String(year);
              if (window.confirm(`Delete all ${allInvoices.length} invoice(s) for ${label}? This cannot be undone.`)) {
                deleteAllMut.mutate(allInvoices.map(inv => inv.id));
              }
            }}
          >
            Delete All ({allInvoices.length})
          </button>
        )}
      </div>

      {isLoading && <p className="empty-state">Loading…</p>}
      {!isLoading && invoices.length === 0 && <p className="empty-state">No invoices found.</p>}

      {!isLoading && invoices.length > 0 && (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                  <th style={TH}>Invoice #</th>
                  <th style={TH}>Company</th>
                  <th style={TH}>Period</th>
                  <th style={TH}>Invoice Date</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Total</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Sessions</th>
                  <th style={{ ...TH, textAlign: 'center' }}>Status</th>
                  <th style={TH}>PDF</th>
                  <th style={TH} />
                </tr>
              </thead>
              <tbody>
                {invoices.map(inv => (
                  <tr
                    key={inv.id}
                    style={{ borderBottom: '1px solid var(--color-border)', cursor: 'pointer' }}
                    onClick={() => navigate(`/billing/invoices/${inv.id}`)}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-bg-subtle, #f8f8f8)')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >
                    <td style={{ padding: '6px 8px', fontWeight: 500 }}>{inv.invoice_number}</td>
                    <td style={{ padding: '6px 8px' }}>{inv.company_name ?? '—'}</td>
                    <td style={{ padding: '6px 8px', color: 'var(--color-text-light)' }}>{formatPeriod(inv.period_month)}</td>
                    <td style={{ padding: '6px 8px', color: 'var(--color-text-light)' }}>{inv.invoice_date ? formatDate(inv.invoice_date) : '—'}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                      {demo ? '—' : inv.total_amount != null ? `$${inv.total_amount.toFixed(2)}` : '—'}
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'center', color: 'var(--color-text-light)' }}>
                      {inv.session_count}
                      {inv.unlinked_session_count > 0 && (
                        <span
                          title={`${inv.unlinked_session_count} confirmed session${inv.unlinked_session_count === 1 ? '' : 's'} not linked to this invoice`}
                          style={{ marginLeft: 5, display: 'inline-block', background: '#e67e22', color: '#fff', borderRadius: 8, fontSize: '0.68em', fontWeight: 700, padding: '1px 5px', verticalAlign: 'middle', lineHeight: 1.4 }}
                        >
                          +{inv.unlinked_session_count}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'center' }}>{statusBadge(inv.status)}</td>
                    <td style={{ padding: '4px 8px', whiteSpace: 'nowrap' }} onClick={e => e.stopPropagation()}>
                      <button
                        className="btn-link"
                        style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginRight: 6 }}
                        disabled={pdfGenerating.has(inv.id)}
                        onClick={e => handleGeneratePdf(e, inv)}
                        title={invoicesDir ? `Generate PDF → ${invoicesDir}` : 'Generate PDF'}
                      >
                        {pdfGenerating.has(inv.id) ? '…' : inv.pdf_path ? '↻ PDF' : '⬡ PDF'}
                      </button>
                      {inv.pdf_path && (
                        <a
                          href={`/api/billing/invoices/${inv.id}/pdf`}
                          target="_blank"
                          rel="noreferrer"
                          onClick={e => e.stopPropagation()}
                          style={{ fontSize: 'var(--text-xs)', color: 'var(--color-accent)', textDecoration: 'none' }}
                          title={`PDF saved at ${inv.pdf_path}`}
                        >
                          ↓
                        </a>
                      )}
                    </td>
                    <td style={{ padding: '4px 8px', whiteSpace: 'nowrap' }} onClick={e => e.stopPropagation()}>
                      <button
                        className="btn-link"
                        style={{ fontSize: 'var(--text-xs)', color: 'var(--color-accent)', marginRight: 6 }}
                        onClick={e => { e.stopPropagation(); setSendingInvoiceId(inv.id); }}
                        title="Send invoice via Gmail"
                      >
                        ✉
                      </button>
                      {inv.status === 'draft' && (
                        <button
                          className="btn-link"
                          style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}
                          disabled={deleteMut.isPending}
                          onClick={e => {
                            e.stopPropagation();
                            if (window.confirm(`Delete draft invoice ${inv.invoice_number}? This cannot be undone.`)) {
                              deleteMut.mutate(inv.id);
                            }
                          }}
                          title="Delete draft invoice"
                        >
                          ×
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '2px solid var(--color-border)', fontWeight: 600 }}>
                  <td colSpan={4} style={{ padding: '6px 8px', fontSize: 'var(--text-sm)' }}>
                    Total ({invoices.length} invoice{invoices.length !== 1 ? 's' : ''})
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 'var(--text-sm)' }}>
                    {demo ? '—' : `$${invoices.reduce((sum, inv) => sum + (inv.total_amount ?? 0), 0).toFixed(2)}`}
                  </td>
                  <td colSpan={4} />
                </tr>
              </tfoot>
            </table>
          </div>

          {/* Bulk actions */}
          <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginTop: 'var(--space-lg)', paddingTop: 'var(--space-md)', borderTop: '1px solid var(--color-border)', flexWrap: 'wrap' }}>
            <button
              className="btn-secondary"
              style={{ fontSize: 'var(--text-sm)' }}
              disabled={pdfGenerating.size > 0}
              onClick={handleBulkGenerate}
              title={`Generate PDFs for all ${invoices.length} listed invoices${invoicesDir ? ` → ${invoicesDir}` : ''}`}
            >
              {pdfGenerating.size > 0 ? `Generating… (${pdfGenerating.size} left)` : `Generate All PDFs (${invoices.length})`}
            </button>
            {invoices.some(inv => inv.pdf_path) && (
              <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
                Download: {invoices.filter(inv => inv.pdf_path).map(inv => (
                  <a
                    key={inv.id}
                    href={`/api/billing/invoices/${inv.id}/pdf`}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: 'var(--color-accent)', textDecoration: 'none', marginRight: 8 }}
                    title={`PDF at ${inv.pdf_path}`}
                  >
                    {inv.invoice_number}
                  </a>
                ))}
              </span>
            )}
            {invoicesDir && (
              <button
                className="btn-link"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginLeft: 'auto' }}
                title={`Open folder: ${invoicesDir}`}
                onClick={() => fetch('/api/open-folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: invoicesDir }) })}
              >
                PDFs → {invoicesDir} ↗
              </button>
            )}
          </div>
        </>
      )}
      {sendingInvoiceId != null && (
        <SendInvoiceModal invoiceId={sendingInvoiceId} onClose={() => setSendingInvoiceId(null)} />
      )}
      {showNewInvoice && (
        <NewInvoiceModal companies={companies} onClose={() => setShowNewInvoice(false)} />
      )}
      {showImportCsv && (
        <ImportCsvModal companies={companies} onClose={() => setShowImportCsv(false)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reconcile panel — link unlinked confirmed sessions to an invoice line
// ---------------------------------------------------------------------------

function ReconcilePanel({ invoice }: { invoice: BillingInvoiceDetail }) {
  const { demo } = useDemoMode();
  const { data: unlinked = [], isLoading } = useInvoiceUnlinkedSessions(invoice.id);
  const reconcile = useReconcileInvoiceSessions();
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [selectedLineId, setSelectedLineId] = useState<number | ''>('');
  const [open, setOpen] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Reset checked set when unlinked list changes
  const unlinkedIds = unlinked.map(s => s.id).join(',');
  useEffect(() => { setChecked(new Set()); }, [unlinkedIds]);

  const sessionLines = invoice.lines.filter(l => l.type === 'sessions');

  if (!open) {
    const count = isLoading ? null : unlinked.length;
    return (
      <div style={{ marginBottom: 'var(--space-xl)' }}>
        <button
          className="btn-link"
          style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}
          onClick={() => setOpen(true)}
        >
          Reconcile sessions {count != null && count > 0 ? `(${count} unlinked)` : count === 0 ? '(none unlinked)' : '…'}
        </button>
      </div>
    );
  }

  function toggleAll(all: boolean) {
    setChecked(all ? new Set(unlinked.map(s => s.id)) : new Set());
  }

  function toggle(id: number) {
    setChecked(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const hasLines = invoice.lines.length > 0;

  function handleSave() {
    if (checked.size === 0) return;
    if (hasLines && !selectedLineId) return;
    reconcile.mutate(
      { invoiceId: invoice.id, session_ids: [...checked], line_id: hasLines ? Number(selectedLineId) : undefined },
      {
        onSuccess: (res) => {
          setSuccessMsg(`Linked ${res.linked} session${res.linked === 1 ? '' : 's'}.`);
          setChecked(new Set());
          setTimeout(() => setSuccessMsg(null), 3000);
        },
      },
    );
  }

  return (
    <div style={{ marginBottom: 'var(--space-xl)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-md)' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-md)', marginBottom: 'var(--space-sm)' }}>
        <h3 style={{ margin: 0, fontSize: 'var(--text-base)' }}>Reconcile Sessions</h3>
        <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }} onClick={() => setOpen(false)}>hide</button>
      </div>
      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', margin: '0 0 var(--space-sm)' }}>
        Confirmed sessions for {invoice.company_name} in {invoice.period_month} with no invoice link.
      </p>

      {isLoading && <p className="empty-state">Loading…</p>}

      {!isLoading && unlinked.length === 0 && (
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>No unlinked sessions found.</p>
      )}

      {unlinked.length > 0 && (
        <>
          <div style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-xs)', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>
            <button className="btn-link" style={{ fontSize: 'var(--text-xs)' }} onClick={() => toggleAll(true)}>Select all</button>
            <button className="btn-link" style={{ fontSize: 'var(--text-xs)' }} onClick={() => toggleAll(false)}>Deselect all</button>
          </div>
          <div style={{ overflowX: 'auto', marginBottom: 'var(--space-md)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                  <th style={{ ...TH, width: 32 }}></th>
                  <th style={TH}>Date</th>
                  <th style={TH}>Client</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Hours</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Amount</th>
                  <th style={TH}>Notes</th>
                </tr>
              </thead>
              <tbody>
                {unlinked.map(s => (
                  <tr
                    key={s.id}
                    style={{ borderBottom: '1px solid var(--color-border)', cursor: 'pointer', background: checked.has(s.id) ? 'var(--color-bg-subtle, rgba(0,0,0,0.03))' : undefined }}
                    onClick={() => toggle(s.id)}
                  >
                    <td style={{ padding: '5px 8px' }}>
                      <input type="checkbox" checked={checked.has(s.id)} onChange={() => toggle(s.id)} onClick={e => e.stopPropagation()} />
                    </td>
                    <td style={{ padding: '5px 8px', whiteSpace: 'nowrap' }}>{formatDate(s.date)}</td>
                    <td style={{ padding: '5px 8px' }}>{s.client_name ?? s.company_name ?? '—'}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{s.duration_hours.toFixed(2)}h</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>${s.amount.toFixed(2)}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--color-text-light)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.notes ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', flexWrap: 'wrap' }}>
            {hasLines ? (
              <label style={{ fontSize: 'var(--text-sm)' }}>
                Link to line:{' '}
                <select
                  value={selectedLineId}
                  onChange={e => setSelectedLineId(e.target.value === '' ? '' : Number(e.target.value))}
                  style={{ fontSize: 'var(--text-sm)', marginLeft: 4 }}
                >
                  <option value="">— choose line —</option>
                  {(sessionLines.length > 0 ? sessionLines : invoice.lines).map(l => (
                    <option key={l.id} value={l.id}>
                      {l.description ?? `Line #${l.id}`}{l.type !== 'sessions' ? ` (${l.type})` : ''}{l.amount != null && !demo ? ` ($${l.amount.toFixed(2)})` : ''}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
                No line items — a sessions line will be created automatically.
              </span>
            )}
            <button
              className="btn-primary"
              disabled={checked.size === 0 || (hasLines && !selectedLineId) || reconcile.isPending}
              onClick={handleSave}
            >
              {reconcile.isPending ? 'Saving…' : `Link ${checked.size} session${checked.size === 1 ? '' : 's'}`}
            </button>
            {successMsg && <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-success, #2a7a2a)' }}>{successMsg}</span>}
            {reconcile.isError && <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-error)' }}>Save failed.</span>}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Invoice detail view — /billing/invoices/:id
// ---------------------------------------------------------------------------

function InvoiceDetailView() {
  const { demo } = useDemoMode();
  const { id } = useParams<{ id: string }>();
  const invoiceId = id ? Number(id) : null;
  const { data: invoice, isLoading } = useBillingInvoice(invoiceId);
  const update = useUpdateBillingInvoice();
  const generatePdf = useBillingGeneratePdf();
  const [editNotes, setEditNotes] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [showSendModal, setShowSendModal] = useState(false);
  const [showAddLine, setShowAddLine] = useState(false);
  const addLine = useAddInvoiceLine();
  const [lineForm, setLineForm] = useState({ description: '', date_range: '', unit_cost: '', quantity: '', amount: '' });

  if (isLoading) return <p className="empty-state">Loading…</p>;
  if (!invoice) return <p className="empty-state">Invoice not found.</p>;

  const isDraft = invoice.status === 'draft';
  const isSent = invoice.status === 'sent';
  const isEditable = isDraft;

  function handleStatusChange(newStatus: string) {
    if (!invoiceId) return;
    update.mutate({ id: invoiceId, status: newStatus as 'draft' | 'sent' | 'paid' | 'partial' });
  }

  function commitNotes() {
    if (editNotes === null || !invoiceId) return;
    update.mutate({ id: invoiceId, notes: editNotes });
    setEditNotes(null);
  }

  function handleGeneratePdf() {
    if (!invoiceId) return;
    setPdfError(null);
    generatePdf.mutate(invoiceId, {
      onError: (err: unknown) => {
        const msg = err instanceof Error ? err.message : 'PDF generation failed';
        setPdfError(msg);
      },
    });
  }

  const notesValue = editNotes !== null ? editNotes : (invoice.notes ?? '');

  return (
    <div>
      {/* Back link */}
      <Link to="/billing/invoices" style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', textDecoration: 'none' }}>
        ← Invoices
      </Link>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-md)', marginTop: 'var(--space-sm)', marginBottom: 'var(--space-xs)', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>{invoice.invoice_number}</h2>
        {statusBadge(invoice.status)}
      </div>
      <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', marginBottom: 'var(--space-md)' }}>
        {invoice.company_name} · {formatPeriod(invoice.period_month)}
      </div>

      {/* Meta row */}
      <div style={{ display: 'flex', gap: 'var(--space-xl)', flexWrap: 'wrap', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-md)', color: 'var(--color-text-light)' }}>
        <span>Invoice date: <strong style={{ color: 'var(--color-fg)' }}>{invoice.invoice_date ? formatDate(invoice.invoice_date) : '—'}</strong></span>
        {invoice.services_date && <span>Services through: <strong style={{ color: 'var(--color-fg)' }}>{formatDate(invoice.services_date)}</strong></span>}
        <span>Due: <strong style={{ color: 'var(--color-fg)' }}>{invoice.due_date ? formatDate(invoice.due_date) : '—'}</strong></span>
        {invoice.total_amount != null && (
          <span>Total: <strong style={{ color: 'var(--color-fg)', fontSize: 'var(--text-base)' }}>{demo ? '—' : `$${invoice.total_amount.toFixed(2)}`}</strong></span>
        )}
      </div>

      {/* Notes */}
      <div style={{ marginBottom: 'var(--space-md)' }}>
        <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 3 }}>Notes</label>
        {isEditable ? (
          <input
            type="text"
            value={notesValue}
            onChange={e => setEditNotes(e.target.value)}
            onBlur={commitNotes}
            onKeyDown={e => { if (e.key === 'Enter') commitNotes(); if (e.key === 'Escape') setEditNotes(null); }}
            placeholder="Add notes…"
            style={{ width: '100%', maxWidth: 480, fontSize: 'var(--text-sm)' }}
          />
        ) : (
          <span style={{ fontSize: 'var(--text-sm)', color: invoice.notes ? 'var(--color-fg)' : 'var(--color-text-light)' }}>
            {invoice.notes || '—'}
          </span>
        )}
      </div>

      {/* Status actions */}
      <div style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-xl)', flexWrap: 'wrap', alignItems: 'center' }}>
        {isDraft && (
          <button
            className="btn-primary"
            disabled={update.isPending}
            onClick={() => handleStatusChange('sent')}
          >
            Mark as Sent
          </button>
        )}
        {(isSent || invoice.status === 'partial') && (
          <button
            className="btn-primary"
            disabled={update.isPending}
            onClick={() => handleStatusChange('paid')}
          >
            Mark as Paid
          </button>
        )}
        {!isDraft && (
          <button
            className="btn-link"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}
            onClick={() => { if (window.confirm('Revert this invoice to draft?')) handleStatusChange('draft'); }}
          >
            Revert to draft
          </button>
        )}
        <button
          className="btn-secondary"
          disabled={generatePdf.isPending}
          onClick={handleGeneratePdf}
          style={{ marginLeft: 'auto' }}
        >
          {generatePdf.isPending ? 'Generating…' : invoice.pdf_path ? 'Regenerate PDF' : 'Generate PDF'}
        </button>
        {invoice.pdf_path && !generatePdf.isPending && (
          <a
            href={`/api/billing/invoices/${invoiceId}/pdf`}
            target="_blank"
            rel="noreferrer"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--color-accent)', textDecoration: 'none' }}
          >
            Download PDF ↗
          </a>
        )}
        {generatePdf.isSuccess && !invoice.pdf_path && (
          <a
            href={`/api/billing/invoices/${invoiceId}/pdf`}
            target="_blank"
            rel="noreferrer"
            style={{ fontSize: 'var(--text-sm)', color: 'var(--color-accent)', textDecoration: 'none' }}
          >
            Download PDF ↗
          </a>
        )}
        {pdfError && (
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-error)' }}>{pdfError}</span>
        )}
        <button
          className="btn-primary"
          onClick={() => setShowSendModal(true)}
        >
          ✉ Send Invoice
        </button>
      </div>
      {showSendModal && invoiceId != null && (
        <SendInvoiceModal invoiceId={invoiceId} onClose={() => setShowSendModal(false)} />
      )}

      {/* Line items */}
      <div style={{ marginBottom: 'var(--space-xl)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-md)', marginBottom: 'var(--space-sm)' }}>
          <h3 style={{ margin: 0, fontSize: 'var(--text-base)' }}>Line Items</h3>
          {!showAddLine && (
            <button className="btn-link" style={{ fontSize: 'var(--text-sm)' }} onClick={() => setShowAddLine(true)}>
              + Add Line Item
            </button>
          )}
        </div>

        {invoice.lines.length > 0 && (
          <div style={{ overflowX: 'auto', marginBottom: showAddLine ? 'var(--space-sm)' : 0 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                  <th style={TH}>Type</th>
                  <th style={TH}>Description</th>
                  <th style={TH}>Date Range</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Qty</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Rate</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Amount</th>
                </tr>
              </thead>
              <tbody>
                {invoice.lines.map(line => (
                  <tr key={line.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                    <td style={{ padding: '5px 8px', color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}>{line.type}</td>
                    <td style={{ padding: '5px 8px' }}>{line.description ?? '—'}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--color-text-light)' }}>{line.date_range ?? '—'}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                      {line.quantity != null ? line.quantity.toFixed(2) : '—'}
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                      {line.unit_cost != null ? (demo ? '—' : `$${line.unit_cost.toFixed(2)}`) : '—'}
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>
                      {line.amount != null ? (demo ? '—' : `$${line.amount.toFixed(2)}`) : '—'}
                    </td>
                  </tr>
                ))}
                <tr style={{ borderTop: '2px solid var(--color-border)' }}>
                  <td colSpan={5} style={{ padding: '5px 8px', textAlign: 'right', fontWeight: 600 }}>Total</td>
                  <td style={{ padding: '5px 8px', textAlign: 'right', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                    {invoice.total_amount != null ? (demo ? '—' : `$${invoice.total_amount.toFixed(2)}`) : '—'}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

        {showAddLine && (
          <div style={{ border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-md)', marginTop: invoice.lines.length > 0 ? 'var(--space-sm)' : 0 }}>
            <div style={{ fontSize: 'var(--text-sm)', fontWeight: 500, marginBottom: 'var(--space-sm)' }}>New Line Item</div>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', gap: 'var(--space-sm)', marginBottom: 'var(--space-sm)' }}>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 2 }}>Description *</label>
                <input
                  type="text"
                  value={lineForm.description}
                  onChange={e => setLineForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="e.g. Prior-period correction"
                  style={{ width: '100%', fontSize: 'var(--text-sm)', boxSizing: 'border-box' }}
                  autoFocus
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 2 }}>Date Range</label>
                <input
                  type="text"
                  value={lineForm.date_range}
                  onChange={e => setLineForm(f => ({ ...f, date_range: e.target.value }))}
                  placeholder="e.g. Jan 2026"
                  style={{ width: '100%', fontSize: 'var(--text-sm)', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 2 }}>Qty</label>
                <input
                  type="number"
                  value={lineForm.quantity}
                  onChange={e => setLineForm(f => ({ ...f, quantity: e.target.value }))}
                  placeholder="—"
                  min="0"
                  step="0.01"
                  style={{ width: '100%', fontSize: 'var(--text-sm)', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 2 }}>Unit Cost</label>
                <input
                  type="number"
                  value={lineForm.unit_cost}
                  onChange={e => setLineForm(f => ({ ...f, unit_cost: e.target.value }))}
                  placeholder="—"
                  min="0"
                  step="0.01"
                  style={{ width: '100%', fontSize: 'var(--text-sm)', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 2 }}>Amount *</label>
                <input
                  type="number"
                  value={lineForm.amount}
                  onChange={e => setLineForm(f => ({ ...f, amount: e.target.value }))}
                  placeholder="0.00"
                  step="0.01"
                  style={{ width: '100%', fontSize: 'var(--text-sm)', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
              <button
                className="btn-primary"
                disabled={!lineForm.description.trim() || !lineForm.amount || addLine.isPending}
                onClick={() => {
                  if (!invoiceId) return;
                  addLine.mutate({
                    invoiceId,
                    description: lineForm.description.trim(),
                    date_range: lineForm.date_range.trim() || undefined,
                    unit_cost: lineForm.unit_cost ? Number(lineForm.unit_cost) : undefined,
                    quantity: lineForm.quantity ? Number(lineForm.quantity) : undefined,
                    amount: Number(lineForm.amount),
                  }, {
                    onSuccess: () => {
                      setShowAddLine(false);
                      setLineForm({ description: '', date_range: '', unit_cost: '', quantity: '', amount: '' });
                    },
                  });
                }}
              >
                {addLine.isPending ? 'Saving…' : 'Add Line'}
              </button>
              <button
                className="btn-link"
                style={{ fontSize: 'var(--text-sm)' }}
                onClick={() => { setShowAddLine(false); setLineForm({ description: '', date_range: '', unit_cost: '', quantity: '', amount: '' }); }}
              >
                Cancel
              </button>
              {addLine.isError && <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-error)' }}>Save failed.</span>}
            </div>
          </div>
        )}
      </div>

      {/* Sessions */}
      {invoice.sessions.length > 0 && (
        <div>
          <h3 style={{ fontSize: 'var(--text-base)', marginBottom: 'var(--space-sm)' }}>Sessions ({invoice.sessions.length})</h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)', textAlign: 'left' }}>
                  <th style={TH}>Date</th>
                  <th style={TH}>Client</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Hours</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Rate</th>
                  <th style={{ ...TH, textAlign: 'right' }}>Amount</th>
                  <th style={TH}>Notes</th>
                </tr>
              </thead>
              <tbody>
                {invoice.sessions.map(s => (
                  <tr key={s.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                    <td style={{ padding: '5px 8px', whiteSpace: 'nowrap' }}>{formatDate(s.date)}</td>
                    <td style={{ padding: '5px 8px' }}>{s.client_name ?? s.company_name ?? '—'}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{s.duration_hours.toFixed(2)}h</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: 'var(--color-text-light)', fontVariantNumeric: 'tabular-nums' }}>
                      {s.rate != null ? (demo ? '—' : `$${s.rate}`) : '—'}
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{demo ? '—' : `$${s.amount.toFixed(2)}`}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--color-text-light)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.notes ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Reconcile — link unlinked confirmed sessions */}
      <ReconcilePanel invoice={invoice} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Summary helpers
// ---------------------------------------------------------------------------

function fmtAmt(n: number, demo = false) {
  if (demo) return '—';
  return n === 0 ? '—' : `$${Math.round(n).toLocaleString('en-US')}`;
}

function monthShort(monthKey: string) {
  const [y, m] = monthKey.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short' });
}

const STATUS_DOT: Record<string, string> = {
  draft: '#aaa', sent: 'var(--color-accent)', paid: '#2a7a2a', partial: '#e9a040',
};

// Return the highest-priority status from a comma-separated GROUP_CONCAT string.
// Priority: paid > partial > sent > draft (SQLite GROUP_CONCAT order is arbitrary).
const STATUS_PRIORITY = ['paid', 'partial', 'sent', 'draft'];
function bestStatus(statuses: string | null | undefined): string {
  if (!statuses) return 'draft';
  const parts = statuses.split(',');
  for (const s of STATUS_PRIORITY) {
    if (parts.includes(s)) return s;
  }
  return parts[0] ?? 'draft';
}

function SummaryCell({ cell, isCurrent }: { cell: BillingSummaryCell | null; isCurrent: boolean }) {
  const { demo } = useDemoMode();
  if (!cell) return <span style={{ color: 'var(--color-border)' }}>—</span>;

  if (cell.invoiced !== null) {
    const status = bestStatus(cell.statuses);
    return (
      <span>
        <span style={{ color: STATUS_DOT[status] ?? '#aaa', fontSize: '0.65em', marginRight: 3 }}>●</span>
        {fmtAmt(cell.invoiced, demo)}
      </span>
    );
  }

  const confirmed = cell.confirmed ?? 0;
  const projected = cell.projected ?? 0;

  if (!confirmed && !projected) return <span style={{ color: 'var(--color-border)' }}>—</span>;

  if (confirmed && projected) {
    return (
      <span>
        <span style={{ color: isCurrent ? 'var(--color-fg)' : 'var(--color-accent)' }}>{fmtAmt(confirmed, demo)}</span>
        <br />
        <span style={{ color: 'var(--color-text-light)', fontSize: '0.85em' }}>~{fmtAmt(projected, demo)}</span>
      </span>
    );
  }
  if (confirmed) return <span style={{ color: isCurrent ? 'var(--color-fg)' : 'var(--color-accent)' }}>{fmtAmt(confirmed, demo)}</span>;
  return <span style={{ color: 'var(--color-text-light)', fontStyle: 'italic' }}>~{fmtAmt(projected, demo)}</span>;
}

// ---------------------------------------------------------------------------
// Billing grid (shared between SummaryView and AnnualSummaryView)
// ---------------------------------------------------------------------------

type StatusFilter = 'all' | 'paid' | 'sent';

function cellVisible(cell: BillingSummaryCell | null, filter: StatusFilter): boolean {
  if (!cell) return false;
  if (filter === 'all') return true;
  if (cell.invoiced !== null) {
    const s = bestStatus(cell.statuses);
    return filter === 'paid' ? s === 'paid' : s !== 'paid';
  }
  // Session-only cell (no invoice) — counts as unpaid/pending
  return filter !== 'paid';
}

function BillingGrid({ data, statusFilter = 'all' }: { data: BillingSummaryData; statusFilter?: StatusFilter }) {
  const { demo } = useDemoMode();
  const { months, companies, current_month } = data;

  // Compute per-cell visibility then totals from visible cells only
  function cellAmt(cell: BillingSummaryCell | null): number {
    if (!cell) return 0;
    if (cell.invoiced !== null) return cell.invoiced;
    return (cell.confirmed ?? 0) + (cell.projected ?? 0);
  }

  const monthTotals = months.map(m =>
    companies.reduce((sum, co) => {
      const cell = co.monthly[m];
      return cellVisible(cell, statusFilter) ? sum + cellAmt(cell) : sum;
    }, 0)
  );
  const grandTotal = companies.reduce((sum, co) =>
    sum + months.reduce((s, m) => {
      const cell = co.monthly[m];
      return cellVisible(cell, statusFilter) ? s + cellAmt(cell) : s;
    }, 0)
  , 0);

  // Unpaid totals (only meaningful for 'all' filter)
  const monthUnpaidTotals = months.map(m =>
    companies.reduce((sum, co) => {
      const cell = co.monthly[m];
      if (!cell) return sum;
      if (cell.invoiced !== null) {
        if (bestStatus(cell.statuses) === 'paid') return sum;
        return sum + cell.invoiced;
      }
      return sum + (cell.confirmed ?? 0) + (cell.projected ?? 0);
    }, 0)
  );
  const grandUnpaid = companies.reduce((sum, co) =>
    sum + months.reduce((coSum, m) => {
      const cell = co.monthly[m];
      if (!cell) return coSum;
      if (cell.invoiced !== null) {
        if (bestStatus(cell.statuses) === 'paid') return coSum;
        return coSum + cell.invoiced;
      }
      return coSum + (cell.confirmed ?? 0) + (cell.projected ?? 0);
    }, 0)
  , 0);

  // Only show months that have any data or are <= current_month for the year
  const activeMonths = months.filter(m => m <= current_month || monthTotals[months.indexOf(m)] > 0);

  const TH: React.CSSProperties = {
    padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-light)',
    whiteSpace: 'nowrap', textAlign: 'right', fontSize: 'var(--text-xs)',
  };
  const TD: React.CSSProperties = {
    padding: '4px 8px', textAlign: 'right', fontSize: 'var(--text-sm)',
    whiteSpace: 'nowrap', borderBottom: '1px solid var(--color-border)',
  };

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 'var(--text-sm)', minWidth: '100%' }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
            <th style={{ ...TH, textAlign: 'left', minWidth: 160 }}>Company</th>
            {activeMonths.map(m => (
              <th key={m} style={{
                ...TH,
                background: m === current_month ? 'color-mix(in srgb, var(--color-border) 30%, transparent)' : undefined,
                fontWeight: m === current_month ? 700 : 500,
              }}>
                {monthShort(m)}
              </th>
            ))}
            <th style={{ ...TH, color: 'var(--color-fg)', fontWeight: 600 }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {companies.map(co => {
            const coRowTotal = activeMonths.reduce((s, m) => {
              const cell = co.monthly[m];
              return cellVisible(cell, statusFilter) ? s + cellAmt(cell) : s;
            }, 0);
            if (coRowTotal === 0 && statusFilter !== 'all') return null;
            return (
              <tr key={co.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                <td style={{ padding: '4px 8px', fontSize: 'var(--text-sm)', whiteSpace: 'nowrap' }}>
                  {co.name}
                </td>
                {activeMonths.map(m => {
                  const cell = co.monthly[m];
                  return (
                    <td key={m} style={{
                      ...TD,
                      background: m === current_month ? 'color-mix(in srgb, var(--color-border) 15%, transparent)' : undefined,
                    }}>
                      <SummaryCell cell={cellVisible(cell, statusFilter) ? cell : null} isCurrent={m === current_month} />
                    </td>
                  );
                })}
                <td style={{ ...TD, fontWeight: 600, borderLeft: '1px solid var(--color-border)' }}>
                  {coRowTotal > 0 ? fmtAmt(coRowTotal, demo) : <span style={{ color: 'var(--color-border)' }}>—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr style={{ borderTop: '2px solid var(--color-border)', background: 'color-mix(in srgb, var(--color-border) 20%, transparent)' }}>
            <td style={{ padding: '4px 8px', fontWeight: 600, fontSize: 'var(--text-sm)' }}>Total</td>
            {activeMonths.map(m => (
              <td key={m} style={{ ...TD, fontWeight: 600 }}>
                {monthTotals[months.indexOf(m)] > 0 ? fmtAmt(monthTotals[months.indexOf(m)], demo) : <span style={{ color: 'var(--color-border)' }}>—</span>}
              </td>
            ))}
            <td style={{ ...TD, fontWeight: 700, borderLeft: '1px solid var(--color-border)' }}>
              {fmtAmt(grandTotal, demo)}
            </td>
          </tr>
          {statusFilter === 'all' && (
            <tr style={{ borderTop: '1px solid var(--color-border)' }}>
              <td style={{ padding: '4px 8px', fontWeight: 500, fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>Total unpaid</td>
              {activeMonths.map(m => {
                const amt = monthUnpaidTotals[months.indexOf(m)];
                return (
                  <td key={m} style={{ ...TD, fontWeight: 500, color: 'var(--color-text-light)' }}>
                    {amt > 0 ? fmtAmt(amt, demo) : <span style={{ color: 'var(--color-border)' }}>—</span>}
                  </td>
                );
              })}
              <td style={{ ...TD, fontWeight: 600, borderLeft: '1px solid var(--color-border)', color: 'var(--color-text-light)' }}>
                {grandUnpaid > 0 ? fmtAmt(grandUnpaid, demo) : '—'}
              </td>
            </tr>
          )}
        </tfoot>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cash received tab
// ---------------------------------------------------------------------------

function CashReceivedView({ data }: { data: BillingSummaryData }) {
  const { demo } = useDemoMode();
  const { months, current_month, payments_by_month, payments_total } = data;
  const activeMonths = months.filter(m => m <= current_month || payments_by_month[m] > 0);

  return (
    <div style={{ maxWidth: 420 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
            <th style={{ padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-light)', textAlign: 'left' }}>Month</th>
            <th style={{ padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-light)', textAlign: 'right' }}>Received</th>
          </tr>
        </thead>
        <tbody>
          {activeMonths.map(m => {
            const amt = payments_by_month[m] ?? 0;
            const [y, mo] = m.split('-').map(Number);
            const label = new Date(y, mo - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
            return (
              <tr key={m} style={{ borderBottom: '1px solid var(--color-border)' }}>
                <td style={{ padding: '4px 8px', color: m === current_month ? 'var(--color-fg)' : 'var(--color-text-light)' }}>
                  {label}
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {amt > 0 ? (demo ? '—' : `$${amt.toFixed(2)}`) : <span style={{ color: 'var(--color-border)' }}>—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr style={{ borderTop: '2px solid var(--color-border)' }}>
            <td style={{ padding: '4px 8px', fontWeight: 600 }}>Total</td>
            <td style={{ padding: '4px 8px', textAlign: 'right', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
              {payments_total > 0 ? (demo ? '—' : `$${payments_total.toFixed(2)}`) : <span style={{ color: 'var(--color-text-light)' }}>—</span>}
            </td>
          </tr>
        </tfoot>
      </table>
      {payments_total === 0 && (
        <p style={{ marginTop: 'var(--space-md)', fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
          No payments recorded yet. Payments will appear here once LunchMoney is connected.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Summary view — /billing/summary
// ---------------------------------------------------------------------------

function SummaryView() {
  const { year } = useBillingScope();
  const [tab, setTab] = useState<'billing' | 'cash'>('billing');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const { data, isLoading, refetch } = useBillingSummary(year);

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '3px 12px', fontSize: 'var(--text-sm)', cursor: 'pointer',
    color: active ? 'var(--color-text-light)' : 'var(--color-text-light)',
    background: 'none', border: 'none', borderBottom: active ? '2px solid #333' : '2px solid transparent',
    fontWeight: active ? 600 : undefined,
  });

  return (
    <div>
      <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginBottom: 'var(--space-md)', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Summary</h2>
        <Link to={`/billing/annual/${year}`} style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
          Annual view →
        </Link>
        <button className="btn-link" style={{ marginLeft: 'auto', fontSize: 'var(--text-sm)' }} onClick={() => refetch()}>↻</button>
      </div>

      <div style={{ display: 'flex', gap: 0, marginBottom: 'var(--space-lg)', borderBottom: '1px solid var(--color-border)' }}>
        <button style={tabStyle(tab === 'billing')} onClick={() => setTab('billing')}>Billing</button>
        <button style={tabStyle(tab === 'cash')} onClick={() => setTab('cash')}>Cash Received (Tax)</button>
      </div>

      {(isLoading || !data) && <p className="empty-state">Loading…</p>}
      {data && tab === 'billing' && (
        <>
          <div style={{ marginBottom: 'var(--space-sm)', display: 'flex', alignItems: 'center', gap: 'var(--space-lg)', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>
              <span style={{ color: STATUS_DOT.paid, fontSize: '0.7em' }}>●</span> paid &nbsp;
              <span style={{ color: STATUS_DOT.sent, fontSize: '0.7em' }}>●</span> sent &nbsp;
              <span style={{ color: STATUS_DOT.draft, fontSize: '0.7em' }}>●</span> draft &nbsp;&nbsp;
              <span style={{ color: 'var(--color-accent)' }}>$N</span> = confirmed &nbsp;
              <span style={{ fontStyle: 'italic' }}>~$N</span> = projected
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
              {(['all', 'sent', 'paid'] as StatusFilter[]).map(f => (
                <button key={f} onClick={() => setStatusFilter(f)} style={{
                  padding: '2px 10px', fontSize: 'var(--text-xs)', cursor: 'pointer',
                  background: statusFilter === f ? 'var(--color-fg)' : 'transparent',
                  color: statusFilter === f ? 'var(--color-bg)' : 'var(--color-text-light)',
                  border: '1px solid var(--color-border)', borderRadius: 3,
                }}>
                  {f === 'sent' ? 'unpaid' : f}
                </button>
              ))}
            </span>
          </div>
          <BillingGrid data={data} statusFilter={statusFilter} />
        </>
      )}
      {data && tab === 'cash' && <CashReceivedView data={data} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Annual summary view — /billing/annual/:year
// ---------------------------------------------------------------------------

function AnnualSummaryView() {
  const { year: yearParam } = useParams<{ year: string }>();
  const navigate = useNavigate();
  const yearNum = yearParam ? Number(yearParam) : new Date().getFullYear();
  const { data, isLoading } = useBillingSummary(yearNum);

  return (
    <div>
      <Link to="/billing/summary" style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)', textDecoration: 'none' }}>
        ← Summary
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', margin: 'var(--space-sm) 0 var(--space-lg)' }}>
        <h2 style={{ margin: 0 }}>Annual Summary {yearNum}</h2>
        <button className="btn-link" style={{ fontSize: 'var(--text-sm)' }} onClick={() => navigate(`/billing/annual/${yearNum - 1}`)}>← {yearNum - 1}</button>
        <button className="btn-link" style={{ fontSize: 'var(--text-sm)' }} onClick={() => navigate(`/billing/annual/${yearNum + 1}`)}>→ {yearNum + 1}</button>
      </div>

      {isLoading && <p className="empty-state">Loading…</p>}
      {data && (
        <>
          <div style={{ marginBottom: 'var(--space-sm)', fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'flex', gap: 'var(--space-lg)' }}>
            <span><span style={{ color: STATUS_DOT.paid, fontSize: '0.7em' }}>●</span> paid &nbsp;
              <span style={{ color: STATUS_DOT.sent, fontSize: '0.7em' }}>●</span> sent &nbsp;
              <span style={{ color: STATUS_DOT.draft, fontSize: '0.7em' }}>●</span> draft &nbsp;
              <span style={{ color: 'var(--color-accent)' }}>confirmed</span> &nbsp;
              <span style={{ color: 'var(--color-text-light)', fontStyle: 'italic' }}>~projected</span>
            </span>
          </div>
          <BillingGrid data={data} />
          <div style={{ marginTop: 'var(--space-xl)', borderTop: '1px solid var(--color-border)', paddingTop: 'var(--space-lg)' }}>
            <h3 style={{ fontSize: 'var(--text-base)', marginBottom: 'var(--space-sm)' }}>Cash Received</h3>
            <CashReceivedView data={data} />
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Payments view (LunchMoney)
// ---------------------------------------------------------------------------

// Per-invoice checkbox state in the assignment panel
type InvCheck = { checked: boolean; amount: string; assignmentId?: number };

function initPendingMap(p: BillingPayment): Record<number, InvCheck> {
  const map: Record<number, InvCheck> = {};
  for (const a of p.assignments) {
    map[a.invoice_id] = { checked: true, amount: String(a.amount_applied), assignmentId: a.id };
  }
  for (const invId of p.suggested_invoice_ids) {
    if (!map[invId]) {
      map[invId] = { checked: true, amount: String(Math.abs(p.amount)) };
    }
  }
  return map;
}

function PaymentsView() {
  const { demo } = useDemoMode();
  const { year, month } = useBillingScope();
  const [showUnmatchedOnly, setShowUnmatchedOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pendingMap, setPendingMap] = useState<Record<number, InvCheck>>({});
  const [saving, setSaving] = useState(false);
  const [syncMsg, setSyncMsg] = useState('');
  const [showAllInvoices, setShowAllInvoices] = useState(false);

  const { data: payments = [], isLoading } = useBillingPayments(showUnmatchedOnly);
  const { data: allInvoices = [] } = useBillingInvoices();
  const { data: allCompanies = [] } = useBillingCompanies(); // include inactive for matching
  const syncMut = useSyncLunchMoney();
  const assignMut = useAssignBillingPayment();
  const removeMut = useRemoveBillingPaymentAssignment();
  const updatePaymentMut = useUpdateBillingPayment();

  useEffect(() => { setSelectedId(null); setPendingMap({}); }, [year, month]);

  const filteredPayments = payments.filter(p => {
    const yr = Number(p.date.slice(0, 4));
    const mo = Number(p.date.slice(5, 7));
    return yr === year && (month === null || mo === month);
  });
  const openInvoices = allInvoices.filter(inv => !['paid', 'cancelled'].includes(inv.status));
  const selected = filteredPayments.find(p => p.id === selectedId) ?? null;
  const unmatchedCount = filteredPayments.filter(p => p.assignments.length === 0).length;

  // Find company name for the selected payment (for filtering invoices)
  const selectedCompanyName = selected?.company_id
    ? allCompanies.find(co => co.id === selected.company_id)?.name ?? null
    : null;

  // Filter open invoices: by company if known, by suggested IDs if no company set, else all
  const filteredOpenInvoices = showAllInvoices
    ? openInvoices
    : selectedCompanyName
      ? openInvoices.filter(inv => inv.company_name === selectedCompanyName)
      : selected
        ? openInvoices.filter(inv => selected.suggested_invoice_ids.includes(inv.id))
        : openInvoices;
  const hasOtherInvoices = filteredOpenInvoices.length < openInvoices.length;

  // Group filtered invoices by company for the checkbox list
  const byCompany: Record<string, BillingInvoice[]> = {};
  for (const inv of filteredOpenInvoices) {
    const key = inv.company_name ?? '(no company)';
    (byCompany[key] ??= []).push(inv);
  }
  const companiesSorted = Object.keys(byCompany).sort();

  function selectPayment(p: BillingPayment) {
    if (selectedId === p.id) { setSelectedId(null); setPendingMap({}); return; }
    const map = initPendingMap(p);
    // Auto-check the invoice matching the payment amount, if no assignments yet and exactly one candidate
    if (p.assignments.length === 0) {
      const paymentAmt = Math.abs(p.amount);
      const candidates = openInvoices.filter(inv =>
        (!p.company_id || inv.company_id === p.company_id) &&
        inv.total_amount != null &&
        Math.abs(inv.total_amount - paymentAmt) < 0.01
      );
      if (candidates.length === 1) {
        map[candidates[0].id] = { checked: true, amount: String(paymentAmt), assignmentId: undefined };
      }
    }
    setSelectedId(p.id);
    setPendingMap(map);
    setShowAllInvoices(false);
  }

  function toggleInvoice(invId: number, _inv: BillingInvoice, defaultAmt: number) {
    setPendingMap(prev => {
      const cur = prev[invId];
      if (cur) return { ...prev, [invId]: { ...cur, checked: !cur.checked } };
      return { ...prev, [invId]: { checked: true, amount: String(defaultAmt), assignmentId: undefined } };
    });
  }

  function setInvAmount(invId: number, val: string) {
    setPendingMap(prev => prev[invId] ? { ...prev, [invId]: { ...prev[invId], amount: val } } : prev);
  }

  async function handleSync(clear = false) {
    setSyncMsg('');
    try {
      const r: BillingLunchMoneySyncResult = await syncMut.mutateAsync({ daysBack: 365, clear });
      setSyncMsg(`${r.inserted} new · ${r.auto_matched} auto-matched · ${r.skipped} skipped${clear ? ' (cleared first)' : ''}`);
    } catch { setSyncMsg('Sync failed'); }
  }

  async function handleSave() {
    if (!selectedId || !selected) return;
    setSaving(true);
    const visibleIds = new Set(filteredOpenInvoices.map(inv => inv.id));
    const ops: Promise<unknown>[] = [];
    for (const [invIdStr, state] of Object.entries(pendingMap)) {
      const invId = Number(invIdStr);
      const amt = parseFloat(state.amount);
      if (visibleIds.has(invId)) {
        // Visible invoice: respect user's checkbox state
        if (state.checked && !isNaN(amt) && amt > 0 && !state.assignmentId) {
          ops.push(assignMut.mutateAsync({ paymentId: selectedId, invoiceId: invId, amountApplied: amt }));
        } else if (!state.checked && state.assignmentId) {
          ops.push(removeMut.mutateAsync(state.assignmentId));
        }
      } else {
        // Hidden invoice: auto-remove any wrong existing assignment
        if (state.assignmentId) {
          ops.push(removeMut.mutateAsync(state.assignmentId));
        }
      }
    }
    await Promise.all(ops);
    setSaving(false);
  }

  const pendingDirty = selected && (() => {
    const visibleIds = new Set(filteredOpenInvoices.map(inv => inv.id));
    return Object.entries(pendingMap).some(([invIdStr, state]) => {
      const invId = Number(invIdStr);
      const existing = selected.assignments.find(a => a.invoice_id === invId);
      if (visibleIds.has(invId)) {
        if (state.checked && !existing) return true;
        if (!state.checked && existing) return true;
        if (existing && String(existing.amount_applied) !== state.amount) return true;
      } else {
        // Hidden with a wrong assignment — dirty so Save fires cleanup
        if (state.assignmentId) return true;
      }
      return false;
    });
  })();

  return (
    <div>
      <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginBottom: 'var(--space-lg)', flexWrap: 'wrap' }}>
        <button onClick={() => handleSync(false)} disabled={syncMut.isPending}>
          {syncMut.isPending ? 'Syncing…' : 'Sync from LunchMoney'}
        </button>
        <button onClick={() => handleSync(true)} disabled={syncMut.isPending} style={{ color: 'var(--color-text-light)' }}>
          Clear &amp; re-sync
        </button>
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 'var(--text-sm)', cursor: 'pointer' }}>
          <input type="checkbox" checked={showUnmatchedOnly} onChange={e => setShowUnmatchedOnly(e.target.checked)} />
          Unmatched only
          {unmatchedCount > 0 && (
            <span style={{ background: '#c0392b', color: '#fff', borderRadius: 10, padding: '0 5px', fontSize: 'var(--text-xs)' }}>
              {unmatchedCount}
            </span>
          )}
        </label>
        {syncMsg && <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>{syncMsg}</span>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 'var(--space-xl)', alignItems: 'start' }}>
        {/* Payment list */}
        <div>
          {isLoading ? <p>Loading…</p> : filteredPayments.length === 0 ? (
            <p style={{ color: 'var(--color-text-light)' }}>
              {payments.length === 0
                ? (showUnmatchedOnly ? 'All payments are matched.' : 'No payments yet. Click "Sync from LunchMoney" to import transactions.')
                : 'No payments match the current date filter.'}
            </p>
          ) : (
            <table style={{ width: '100%', fontSize: 'var(--text-sm)', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500 }}>Date</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500 }}>Notes</th>
                  <th style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 500 }}>Amount</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500 }}>Company</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500 }}>Invoices</th>
                </tr>
              </thead>
              <tbody>
                {filteredPayments.map(p => (
                  <tr
                    key={p.id}
                    onClick={() => selectPayment(p)}
                    style={{
                      borderBottom: '1px solid var(--color-border-faint)',
                      cursor: 'pointer',
                      background: selectedId === p.id ? 'var(--color-bg-alt)' : undefined,
                    }}
                  >
                    <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>{p.date}</td>
                    <td style={{ padding: '6px 8px' }}>
                      {p.notes
                        ? <span>{p.notes}</span>
                        : <em style={{ color: 'var(--color-text-light)' }}>{p.payee || '—'}</em>}
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                      {fmtAmt(Math.abs(p.amount), demo)}
                    </td>
                    <td style={{ padding: '4px 8px' }} onClick={e => e.stopPropagation()}>
                      <select
                        value={p.company_id ?? ''}
                        onChange={e => updatePaymentMut.mutate({ id: p.id, company_id: e.target.value ? Number(e.target.value) : null })}
                        style={{ fontSize: 'var(--text-xs)', maxWidth: 120 }}
                      >
                        <option value="">—</option>
                        {allCompanies.map(co => (
                          <option key={co.id} value={co.id}>{co.name}</option>
                        ))}
                      </select>
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      {p.assignments.length > 0 ? (
                        <span style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {p.assignments.map(a => (
                            <span
                              key={a.id}
                              style={{ background: 'var(--color-bg-alt)', border: '1px solid var(--color-border)', borderRadius: 3, padding: '0 6px', fontSize: 'var(--text-xs)' }}
                            >
                              {a.invoice_number}
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span style={{ color: p.suggested_invoice_ids.length > 0 ? '#e9a040' : 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}>
                          {p.suggested_invoice_ids.length > 0 ? '◑ suggested' : '—'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '2px solid var(--color-border)', fontWeight: 600 }}>
                  <td colSpan={2} style={{ padding: '5px 8px', fontSize: 'var(--text-sm)' }}>
                    Total ({filteredPayments.length})
                  </td>
                  <td style={{ padding: '5px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {fmtAmt(filteredPayments.reduce((s, p) => s + Math.abs(p.amount), 0), demo)}
                  </td>
                  <td colSpan={2} />
                </tr>
              </tfoot>
            </table>
          )}
        </div>

        {/* Assignment panel */}
        <div style={{ background: 'var(--color-bg-alt)', borderRadius: 6, padding: 'var(--space-lg)', fontSize: 'var(--text-sm)', position: 'sticky', top: 24 }}>
          {selected ? (
            <>
              <p style={{ fontWeight: 600, marginBottom: 2 }}>{selected.notes || selected.payee || '(no payee)'}</p>
              <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)', marginBottom: 'var(--space-md)' }}>
                {selected.date} · {fmtAmt(Math.abs(selected.amount), demo)}
              </p>

              {openInvoices.length === 0 ? (
                <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}>
                  No open invoices. Generate invoices via Prepare first.
                </p>
              ) : (
                <>
                  {hasOtherInvoices && !showAllInvoices && (
                    <div style={{ marginBottom: 'var(--space-sm)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>
                        {selectedCompanyName ? `Showing ${selectedCompanyName} invoices` : 'Showing amount-matched invoices'}
                      </span>
                      <button
                        className="btn-link"
                        style={{ fontSize: 'var(--text-xs)' }}
                        onClick={() => setShowAllInvoices(true)}
                      >
                        Show all invoices
                      </button>
                    </div>
                  )}
                  {showAllInvoices && (
                    <div style={{ marginBottom: 'var(--space-sm)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>All open invoices</span>
                      <button
                        className="btn-link"
                        style={{ fontSize: 'var(--text-xs)' }}
                        onClick={() => setShowAllInvoices(false)}
                      >
                        {selectedCompanyName ? `${selectedCompanyName} only` : 'Matching only'}
                      </button>
                    </div>
                  )}
                  {filteredOpenInvoices.length === 0 ? (
                    <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}>
                      No matching open invoices.{' '}
                      <button className="btn-link" style={{ fontSize: 'var(--text-xs)' }} onClick={() => setShowAllInvoices(true)}>Show all</button>
                    </p>
                  ) : null}
                  {companiesSorted.map(company => (
                    <div key={company} style={{ marginBottom: 'var(--space-md)' }}>
                      <p style={{ fontWeight: 600, fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
                        {company}
                      </p>
                      {byCompany[company].map(inv => {
                        const state = pendingMap[inv.id];
                        const isChecked = state?.checked ?? false;
                        const amt = state?.amount ?? String(Math.abs(selected.amount));
                        const isSuggested = selected.suggested_invoice_ids.includes(inv.id);
                        return (
                          <div key={inv.id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => toggleInvoice(inv.id, inv, Math.abs(selected.amount))}
                              style={{ flexShrink: 0 }}
                            />
                            <span style={{ flex: 1, minWidth: 0 }}>
                              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{inv.invoice_number}</span>
                              {isSuggested && <span style={{ color: '#e9a040', marginLeft: 4 }}>◑</span>}
                              <span style={{ color: 'var(--color-text-light)', marginLeft: 4, fontSize: 'var(--text-xs)' }}>
                                {fmtAmt(inv.total_amount ?? 0, demo)}
                              </span>
                            </span>
                            {isChecked && (
                              <input
                                type="number"
                                step="0.01"
                                min="0"
                                value={amt}
                                onChange={e => setInvAmount(inv.id, e.target.value)}
                                style={{ width: 72, fontSize: 'var(--text-xs)', textAlign: 'right' }}
                                onClick={e => e.stopPropagation()}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                  <button
                    onClick={handleSave}
                    disabled={!pendingDirty || saving}
                    style={{ width: '100%', marginTop: 'var(--space-sm)' }}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                </>
              )}
            </>
          ) : (
            <p style={{ color: 'var(--color-text-light)' }}>Select a payment row to assign it to invoices.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Billing nav + page shell
// ---------------------------------------------------------------------------

function prepLink() {
  const now = new Date();
  const m = now.getMonth(); // 0-based; if 0 (Jan), go to Dec of prev year
  if (m === 0) return `/billing/prepare/${now.getFullYear() - 1}/12`;
  return `/billing/prepare/${now.getFullYear()}/${m}`;
}

const navStyle = ({ isActive }: { isActive: boolean }) => ({
  color: isActive ? 'var(--color-fg)' : 'var(--color-text-light)',
  textDecoration: 'none',
  fontWeight: isActive ? 600 : undefined,
} as React.CSSProperties);

function BillingScopeBar() {
  const { year, month, company, setYear, setMonth, setCompany } = useBillingScope();
  const { demo, toggle } = useDemoMode();
  const curYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 5 }, (_, i) => curYear - 2 + i);
  const { data: companies = [] } = useBillingCompanies();

  // Month button: use explicit colors (var(--color-fg) is not defined in tufte.css)
  const mBtn = (active: boolean): React.CSSProperties => ({
    padding: '2px 7px',
    fontSize: 'var(--text-xs)',
    border: active ? '1px solid #555' : '1px solid var(--color-border)',
    borderRadius: 3,
    background: active ? '#333' : 'transparent',
    color: active ? '#fff' : 'var(--color-text-light)',
    fontWeight: active ? 700 : 400,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  });

  return (
    <div style={{ display: 'flex', gap: 5, alignItems: 'center', marginBottom: 'var(--space-lg)', flexWrap: 'wrap', padding: '6px 0', borderBottom: '1px solid var(--color-border)' }}>
      <select value={year} onChange={e => setYear(Number(e.target.value))} style={{ fontSize: 'var(--text-sm)' }}>
        {yearOptions.map(y => <option key={y} value={y}>{y}</option>)}
      </select>
      {([null, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] as (number | null)[]).map(m => (
        <button key={m ?? 'all'} onClick={() => setMonth(m)} style={mBtn(month === m)}>
          {m === null ? 'All' : MONTH_LABELS[m - 1]}
        </button>
      ))}
      {/* Company dropdown: groups + individual companies */}
      <select
        value={company}
        onChange={e => setCompany(e.target.value)}
        style={{ fontSize: 'var(--text-sm)', marginLeft: 4 }}
      >
        <option value="">All companies</option>
        <optgroup label="── Groups ──">
          <option value={SCOPE_COMPANY_PREPAID}>Prepaid clients</option>
          <option value={SCOPE_COMPANY_PERIODIC}>Periodic billing</option>
        </optgroup>
        <optgroup label="── Companies ──">
          {companies.map(co => <option key={co.id} value={String(co.id)}>{co.name}</option>)}
        </optgroup>
      </select>
      <button
        onClick={toggle}
        style={{
          marginLeft: 'auto',
          fontSize: 'var(--text-xs)',
          padding: '2px 8px',
          border: '1px solid var(--color-border)',
          borderRadius: 3,
          background: demo ? 'var(--color-accent, #6b7280)' : 'transparent',
          color: demo ? '#fff' : 'var(--color-text-light)',
          cursor: 'pointer',
        }}
      >
        {demo ? 'Demo On' : 'Demo'}
      </button>
    </div>
  );
}

function BillingNav() {
  const { year, month } = useBillingScope();
  const onPrepare = useMatch('/billing/prepare/*');
  const onInvoices = useMatch('/billing/invoices/*');
  const onSummary = useMatch('/billing/summary') || useMatch('/billing/annual/*');
  const onPayments = useMatch('/billing/payments');
  // Prepare link: use scope year/month; if month is null (all), fall back to prepLink()
  const prepTo = month !== null ? `/billing/prepare/${year}/${month}` : prepLink();
  return (
    <nav style={{ display: 'flex', gap: 'var(--space-lg)', marginBottom: 'var(--space-md)', fontSize: 'var(--text-sm)', borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--space-sm)' }}>
      <NavLink to="/billing" end style={navStyle}>Queue</NavLink>
      <NavLink to="/billing/sessions" style={navStyle}>Sessions</NavLink>
      <NavLink to="/billing/invoices" style={() => navStyle({ isActive: !!onInvoices })}>Invoices</NavLink>
      <NavLink to="/billing/payments" style={() => navStyle({ isActive: !!onPayments })}>Payments</NavLink>
      <NavLink to="/billing/summary" style={() => navStyle({ isActive: !!onSummary })}>Summary</NavLink>
      <NavLink to={prepTo} style={() => navStyle({ isActive: !!onPrepare })}>Prepare</NavLink>
    </nav>
  );
}

export function BillingPage() {
  const [demo, setDemo] = useState<boolean>(() => localStorage.getItem('billing-demo-mode') === 'true');
  const toggle = () => setDemo(prev => {
    const next = !prev;
    localStorage.setItem('billing-demo-mode', String(next));
    return next;
  });

  const scopeInit = defaultScope();
  const [scopeYear, setScopeYear] = useState(scopeInit.year);
  const [scopeMonth, setScopeMonth] = useState<number | null>(scopeInit.month);
  const [scopeCompany, setScopeCompany] = useState<string>(scopeInit.company);
  const scope: BillingScopeCtx = {
    year: scopeYear, month: scopeMonth, company: scopeCompany,
    setYear: setScopeYear, setMonth: setScopeMonth, setCompany: setScopeCompany,
  };

  return (
    <DemoModeContext.Provider value={{ demo, toggle }}>
      <BillingScopeContext.Provider value={scope}>
        <div>
          <h1>Billing</h1>
          {demo && (
            <div style={{
              background: '#f59e0b',
              color: '#1c1917',
              padding: '6px 14px',
              borderRadius: 4,
              fontSize: 'var(--text-sm)',
              fontWeight: 600,
              marginBottom: 'var(--space-md)',
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-sm)',
            }}>
              Demo Mode — dollar amounts hidden.
              <button onClick={toggle} style={{ background: 'none', border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: 'var(--text-sm)', padding: 0, color: '#1c1917' }}>
                Turn off ×
              </button>
            </div>
          )}
          <BillingNav />
          <BillingScopeBar />
          <Routes>
            <Route path="/" element={<UnprocessedQueue />} />
            <Route path="/sessions" element={<SessionsView />} />
            <Route path="/invoices" element={<InvoicesListView />} />
            <Route path="/invoices/:id" element={<InvoiceDetailView />} />
            <Route path="/payments" element={<PaymentsView />} />
            <Route path="/summary" element={<SummaryView />} />
            <Route path="/annual/:year" element={<AnnualSummaryView />} />
            <Route path="/prepare/:year/:month" element={<InvoicePrepPage />} />
            <Route path="*" element={<Navigate to="/billing" replace />} />
          </Routes>
        </div>
      </BillingScopeContext.Provider>
    </DemoModeContext.Provider>
  );
}
