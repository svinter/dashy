import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useBillingPrepData, useGenerateInvoices } from '../api/hooks';
import type { BillingPrepCompany, BillingSession, BillingGenerateResult } from '../api/types';
import { BillingDateFilter, useDemoMode } from './BillingPage';
import type { BillingDateState } from './BillingPage';

// ---------------------------------------------------------------------------
// Local-only types (not persisted to API directly)
// ---------------------------------------------------------------------------

interface DraftLine {
  localId: string;
  type: 'sessions' | 'expense' | 'correction';
  description: string;
  date_range: string;
  unit_cost: number | null;
  quantity: number | null;
  amount: number;
  sort_order: number;
  session_ids: number[];
}

interface LocalExpense {
  localId: string;
  description: string;
  date: string;
  amount: number;
  type: 'expense' | 'correction';
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function uid() {
  return Math.random().toString(36).slice(2);
}


function formatSessionDates(dates: string[]): string {
  const sorted = [...new Set(dates)].sort();
  if (!sorted.length) return '';
  const parse = (d: string) => { const [y, m, day] = d.split('-').map(Number); return new Date(y, m - 1, day); };
  const parsed = sorted.map(parse);
  const first = parsed[0], last = parsed[parsed.length - 1];
  const mon = (d: Date) => d.toLocaleDateString('en-US', { month: 'long' });
  if (sorted.length === 1) return `${mon(first)} ${first.getDate()}, ${first.getFullYear()}`;
  if (first.getFullYear() === last.getFullYear() && first.getMonth() === last.getMonth()) {
    const days = parsed.map(d => d.getDate());
    const yr = first.getFullYear();
    if (days.length === 2) return `${mon(first)} ${days[0]} & ${days[1]}, ${yr}`;
    return `${mon(first)} ${days.slice(0, -1).join(', ')} & ${days[days.length - 1]}, ${yr}`;
  }
  const parts = parsed.map(d => `${mon(d)} ${d.getDate()}`);
  if (parts.length === 2) return `${parts[0]} & ${parts[1]}, ${last.getFullYear()}`;
  return `${parts.slice(0, -1).join(', ')} & ${parts[parts.length - 1]}, ${last.getFullYear()}`;
}

function buildDraftLines(
  company: BillingPrepCompany,
  includedProjectedIds: Set<number>,
  expenses: LocalExpense[],
): DraftLine[] {
  const included: BillingSession[] = [
    ...company.confirmed_sessions,
    ...company.projected_sessions.filter(s => includedProjectedIds.has(s.id)),
  ];

  // Group by client
  const byClient = new Map<number, BillingSession[]>();
  for (const s of included) {
    const cid = s.client_id ?? -1;
    if (!byClient.has(cid)) byClient.set(cid, []);
    byClient.get(cid)!.push(s);
  }

  const lines: DraftLine[] = [];
  let sort = 0;

  const clientEntries = [...byClient.entries()].sort(([, a], [, b]) =>
    (a[0].client_name ?? '').localeCompare(b[0].client_name ?? '')
  );

  for (const [, sessions] of clientEntries) {
    const isCompanyOnly = sessions[0].client_id == null;
    const clientName = sessions[0].client_name ?? null;
    const hours = sessions.reduce((s, r) => s + r.duration_hours, 0);
    const amount = sessions.reduce((s, r) => s + r.amount, 0);
    const rate = sessions[0].rate ?? company.default_rate ?? null;
    const description = isCompanyOnly
      ? `Advisory services — ${company.name}`
      : `Coaching for ${clientName}`;
    lines.push({
      localId: uid(),
      type: 'sessions',
      description,
      date_range: formatSessionDates(sessions.map(s => s.date)),
      unit_cost: rate,
      quantity: Math.round(hours * 100) / 100,
      amount: Math.round(amount * 100) / 100,
      sort_order: sort++,
      session_ids: sessions.map(s => s.id),
    });
  }

  for (const exp of expenses) {
    lines.push({
      localId: uid(),
      type: exp.type,
      description: exp.description,
      date_range: exp.date,
      unit_cost: exp.type === 'correction' ? exp.amount : Math.abs(exp.amount),
      quantity: 1,
      amount: exp.amount,
      sort_order: sort++,
      session_ids: [],
    });
  }

  return lines;
}

// ---------------------------------------------------------------------------
// Stage 1: Session Review
// ---------------------------------------------------------------------------

function Stage1({
  companies,
  includedProjectedIds,
  onToggle,
  onNext,
}: {
  companies: BillingPrepCompany[];
  includedProjectedIds: Set<number>;
  onToggle: (id: number) => void;
  onNext: () => void;
}) {
  const { demo } = useDemoMode();
  return (
    <div>
      <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-lg)' }}>
        Review sessions for this period. Confirmed sessions are always included. Toggle projected sessions to include them.
      </p>

      {companies.map(co => {
        const includedProjected = co.projected_sessions.filter(s => includedProjectedIds.has(s.id));
        const projTotal = includedProjected.reduce((s, r) => s + r.amount, 0);
        const hasActivity = co.confirmed_sessions.length > 0 || co.projected_sessions.length > 0;
        if (!hasActivity) return null;
        return (
          <div key={co.id} style={{ marginBottom: 'var(--space-xl)', border: '1px solid var(--color-border)', borderRadius: 4 }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ fontSize: 'var(--text-sm)' }}>{co.name}</strong>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>
                {co.billing_method}
                {co.existing_invoice && (
                  <span style={{ marginLeft: 8, color: '#e9a040' }}>
                    invoice {co.existing_invoice.invoice_number} already exists ({co.existing_invoice.status})
                  </span>
                )}
              </span>
            </div>

            {/* Confirmed sessions */}
            {co.confirmed_sessions.length > 0 && (
              <div style={{ padding: '8px 12px' }}>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 4, display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 600 }}>Confirmed</span>
                  <span>{co.confirmed_total_hours.toFixed(2)}h · <strong>{demo ? '—' : `$${co.confirmed_total_amount.toFixed(2)}`}</strong></span>
                </div>
                <SessionMiniTable sessions={co.confirmed_sessions} />
              </div>
            )}

            {/* Projected sessions */}
            {co.projected_sessions.length > 0 && (
              <div style={{ padding: '8px 12px', borderTop: co.confirmed_sessions.length > 0 ? '1px solid var(--color-border)' : undefined, background: 'color-mix(in srgb, #F6BF26 8%, transparent)' }}>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginBottom: 4, display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 600 }}>Projected (banana) — select to include</span>
                  {includedProjected.length > 0 && (
                    <span style={{ color: '#b8860b' }}>
                      {includedProjected.reduce((s, r) => s + r.duration_hours, 0).toFixed(2)}h · {demo ? '—' : `$${projTotal.toFixed(2)}`} selected
                    </span>
                  )}
                </div>
                {co.projected_sessions.map(s => (
                  <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0', fontSize: 'var(--text-sm)', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={includedProjectedIds.has(s.id)}
                      onChange={() => onToggle(s.id)}
                    />
                    <span style={{ width: 90, color: 'var(--color-text-light)', flexShrink: 0 }}>{s.date}</span>
                    <span style={{ flex: 1 }}>{s.client_name}</span>
                    <span style={{ color: 'var(--color-text-light)', width: 48, textAlign: 'right' }}>{s.duration_hours.toFixed(2)}h</span>
                    <span style={{ width: 72, textAlign: 'right' }}>{demo ? '—' : `$${s.amount.toFixed(2)}`}</span>
                  </label>
                ))}
              </div>
            )}

            {/* Company subtotal */}
            <div style={{ padding: '6px 12px', borderTop: '1px solid var(--color-border)', fontSize: 'var(--text-sm)', display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-lg)', background: 'var(--color-bg-subtle, transparent)' }}>
              <span style={{ color: 'var(--color-text-light)' }}>confirmed <strong>{demo ? '—' : `$${co.confirmed_total_amount.toFixed(2)}`}</strong></span>
              {includedProjected.length > 0 && (
                <span style={{ color: '#b8860b' }}>+ projected <strong>{demo ? '—' : `$${projTotal.toFixed(2)}`}</strong></span>
              )}
              <span>= <strong>{demo ? '—' : `$${(co.confirmed_total_amount + projTotal).toFixed(2)}`}</strong></span>
            </div>
          </div>
        );
      })}

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--space-lg)' }}>
        <button className="btn-primary" onClick={onNext}>Next: Add Expenses →</button>
      </div>
    </div>
  );
}

function SessionMiniTable({ sessions }: { sessions: BillingSession[] }) {
  const { demo } = useDemoMode();
  return (
    <div>
      {sessions.map(s => (
        <div key={s.id} style={{ display: 'flex', gap: 8, padding: '2px 0', fontSize: 'var(--text-sm)', alignItems: 'center' }}>
          <span style={{ width: 90, color: 'var(--color-text-light)', flexShrink: 0 }}>{s.date}</span>
          <span style={{ flex: 1 }}>{s.client_name}</span>
          <span style={{ color: 'var(--color-text-light)', width: 48, textAlign: 'right', flexShrink: 0 }}>{s.duration_hours.toFixed(2)}h</span>
          <span style={{ width: 72, textAlign: 'right', flexShrink: 0 }}>{demo ? '—' : `$${s.amount.toFixed(2)}`}</span>
          {s.obsidian_link && (
            <a href={s.obsidian_link} title="Obsidian note" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', textDecoration: 'none', flexShrink: 0 }}>◆</a>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage 2: Expense Entry
// ---------------------------------------------------------------------------

function Stage2({
  companies,
  includedProjectedIds,
  expenses,
  onSetExpenses,
  onNext,
  onBack,
}: {
  companies: BillingPrepCompany[];
  includedProjectedIds: Set<number>;
  expenses: Map<number, LocalExpense[]>;
  onSetExpenses: (companyId: number, exps: LocalExpense[]) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const activeCompanies = companies.filter(co =>
    co.confirmed_sessions.length > 0 ||
    co.projected_sessions.some(s => includedProjectedIds.has(s.id))
  );

  return (
    <div>
      <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-lg)' }}>
        Add expenses or corrections for each company. Leave empty to skip.
      </p>

      {activeCompanies.map(co => (
        <ExpensePanel
          key={co.id}
          company={co}
          expenses={expenses.get(co.id) ?? []}
          onChange={exps => onSetExpenses(co.id, exps)}
        />
      ))}

      <div style={{ display: 'flex', gap: 'var(--space-md)', justifyContent: 'flex-end', marginTop: 'var(--space-lg)' }}>
        <button className="btn-link" onClick={onBack}>← Back</button>
        <button className="btn-primary" onClick={onNext}>Next: Review →</button>
      </div>
    </div>
  );
}

function ExpensePanel({
  company,
  expenses,
  onChange,
}: {
  company: BillingPrepCompany;
  expenses: LocalExpense[];
  onChange: (exps: LocalExpense[]) => void;
}) {
  const { demo } = useDemoMode();
  const [desc, setDesc] = useState('');
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState('');
  const [type, setType] = useState<'expense' | 'correction'>('expense');

  function add() {
    const amt = parseFloat(amount);
    if (!desc.trim() || isNaN(amt)) return;
    const finalAmt = type === 'correction' ? -Math.abs(amt) : Math.abs(amt);
    onChange([...expenses, { localId: uid(), description: desc.trim(), date, amount: finalAmt, type }]);
    setDesc(''); setAmount('');
  }

  function remove(localId: string) {
    onChange(expenses.filter(e => e.localId !== localId));
  }

  return (
    <div style={{ marginBottom: 'var(--space-lg)', border: '1px solid var(--color-border)', borderRadius: 4 }}>
      <div style={{ padding: '6px 12px', borderBottom: '1px solid var(--color-border)', fontWeight: 600, fontSize: 'var(--text-sm)' }}>
        {company.name}
      </div>
      <div style={{ padding: '8px 12px' }}>
        {/* Existing expenses */}
        {expenses.map(exp => (
          <div key={exp.localId} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0', fontSize: 'var(--text-sm)' }}>
            <span style={{ flex: 1 }}>{exp.description}</span>
            <span style={{ color: 'var(--color-text-light)', width: 90, flexShrink: 0 }}>{exp.date}</span>
            <span style={{ width: 80, textAlign: 'right', color: exp.amount < 0 ? 'var(--color-error)' : undefined, flexShrink: 0 }}>
              {demo ? '—' : `${exp.amount < 0 ? '-' : ''}$${Math.abs(exp.amount).toFixed(2)}`}
            </span>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', width: 70, flexShrink: 0 }}>{exp.type}</span>
            <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }} onClick={() => remove(exp.localId)}>×</button>
          </div>
        ))}

        {/* Add form */}
        <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', alignItems: 'flex-end', marginTop: expenses.length ? 'var(--space-sm)' : 0, paddingTop: expenses.length ? 'var(--space-sm)' : 0, borderTop: expenses.length ? '1px solid var(--color-border)' : undefined }}>
          <div style={{ flex: 2, minWidth: 140 }}>
            <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Description</label>
            <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="e.g. Travel reimbursement" style={{ width: '100%' }}
              onKeyDown={e => { if (e.key === 'Enter') add(); }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Date</label>
            <input type="date" value={date} onChange={e => setDate(e.target.value)} style={{ width: 130 }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Amount ($)</label>
            <input type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" style={{ width: 90 }}
              onKeyDown={e => { if (e.key === 'Enter') add(); }} />
          </div>
          <div>
            <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Type</label>
            <select value={type} onChange={e => setType(e.target.value as 'expense' | 'correction')} style={{ fontSize: 'var(--text-sm)' }}>
              <option value="expense">Expense</option>
              <option value="correction">Correction (negative)</option>
            </select>
          </div>
          <button className="btn-primary" style={{ fontSize: 'var(--text-sm)' }} onClick={add}>+ Add</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage 3: Review & Edit
// ---------------------------------------------------------------------------

function Stage3({
  companies,
  includedProjectedIds: _includedProjectedIds,
  expenses: _expenses,
  draftByCompany,
  invoiceDate,
  servicesDate,
  invoiceNumberOverrides,
  onSetDraft,
  onSetInvoiceDate,
  onSetServicesDate,
  onSetInvoiceNumber,
  onNext,
  onBack,
  isPending,
  error,
}: {
  companies: BillingPrepCompany[];
  includedProjectedIds: Set<number>;
  expenses: Map<number, LocalExpense[]>;
  draftByCompany: Map<number, DraftLine[]>;
  invoiceDate: string;
  servicesDate: string;
  invoiceNumberOverrides: Map<number, string>;
  onSetDraft: (companyId: number, lines: DraftLine[]) => void;
  onSetInvoiceDate: (d: string) => void;
  onSetServicesDate: (d: string) => void;
  onSetInvoiceNumber: (companyId: number, value: string) => void;
  onNext: () => void;
  onBack: () => void;
  isPending?: boolean;
  error?: string | null;
}) {
  const { demo } = useDemoMode();
  const activeCompanies = companies.filter(co => draftByCompany.has(co.id) && (draftByCompany.get(co.id)?.length ?? 0) > 0);

  const grandTotal = activeCompanies.reduce((sum, co) => {
    const lines = draftByCompany.get(co.id) ?? [];
    return sum + lines.reduce((s, l) => s + l.amount, 0);
  }, 0);

  return (
    <div>
      {/* Invoice date inputs */}
      <div style={{ display: 'flex', gap: 'var(--space-lg)', marginBottom: 'var(--space-lg)', flexWrap: 'wrap' }}>
        <div>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Invoice date</label>
          <input type="date" value={invoiceDate} onChange={e => onSetInvoiceDate(e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', display: 'block', marginBottom: 2 }}>Services delivered date</label>
          <input type="date" value={servicesDate} onChange={e => onSetServicesDate(e.target.value)} />
        </div>
        <div style={{ marginLeft: 'auto', alignSelf: 'flex-end', fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
          Grand total: <strong style={{ fontSize: 'var(--text-base)' }}>{demo ? '—' : `$${grandTotal.toFixed(2)}`}</strong>
        </div>
      </div>

      {activeCompanies.map(co => {
        const lines = draftByCompany.get(co.id) ?? [];
        const total = lines.reduce((s, l) => s + l.amount, 0);
        return (
          <div key={co.id} style={{ marginBottom: 'var(--space-xl)', border: '1px solid var(--color-border)', borderRadius: 4 }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ fontSize: 'var(--text-sm)' }}>{co.name}</strong>
              <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
                Invoice total: <strong style={{ color: 'var(--color-fg)' }}>{demo ? '—' : `$${total.toFixed(2)}`}</strong>
              </span>
            </div>
            <div style={{ padding: '6px 12px', borderBottom: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: 8, background: 'color-mix(in srgb, var(--color-border) 12%, transparent)' }}>
              <label style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', whiteSpace: 'nowrap' }}>Invoice #</label>
              <input
                value={invoiceNumberOverrides.get(co.id) ?? ''}
                onChange={e => onSetInvoiceNumber(co.id, e.target.value)}
                placeholder={`auto (${co.abbrev ?? co.name.slice(0, 4).toUpperCase()}-…)`}
                style={{ width: 200, fontSize: 'var(--text-sm)' }}
              />
              {invoiceNumberOverrides.get(co.id) && (
                <button
                  onClick={() => onSetInvoiceNumber(co.id, '')}
                  style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                >× clear</button>
              )}
            </div>
            <div style={{ padding: '8px 12px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-sm)' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-light)' }}>
                    <th style={{ textAlign: 'left', padding: '3px 6px', fontWeight: 500 }}>Description</th>
                    <th style={{ textAlign: 'left', padding: '3px 6px', fontWeight: 500 }}>Date(s)</th>
                    <th style={{ textAlign: 'right', padding: '3px 6px', fontWeight: 500 }}>Rate</th>
                    <th style={{ textAlign: 'right', padding: '3px 6px', fontWeight: 500 }}>Qty</th>
                    <th style={{ textAlign: 'right', padding: '3px 6px', fontWeight: 500 }}>Amount</th>
                    <th style={{ width: 24 }} />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, idx) => (
                    <DraftLineRow
                      key={line.localId}
                      line={line}
                      onChange={updated => {
                        const next = [...lines];
                        next[idx] = updated;
                        onSetDraft(co.id, next);
                      }}
                      onRemove={() => {
                        onSetDraft(co.id, lines.filter((_, i) => i !== idx));
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      <div style={{ display: 'flex', gap: 'var(--space-md)', justifyContent: 'flex-end', alignItems: 'center', marginTop: 'var(--space-lg)' }}>
        {error && <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-error)', marginRight: 'auto' }}>{error}</span>}
        <button className="btn-link" onClick={onBack} disabled={isPending}>← Back</button>
        <button className="btn-primary" onClick={onNext} disabled={activeCompanies.length === 0 || isPending}>
          {isPending ? 'Generating…' : `Generate ${activeCompanies.length} invoice${activeCompanies.length !== 1 ? 's' : ''} →`}
        </button>
      </div>
    </div>
  );
}

function DraftLineRow({
  line,
  onChange,
  onRemove,
}: {
  line: DraftLine;
  onChange: (l: DraftLine) => void;
  onRemove: () => void;
}) {
  function field<K extends keyof DraftLine>(key: K, val: DraftLine[K]) {
    onChange({ ...line, [key]: val });
  }

  const isNegative = line.amount < 0;

  return (
    <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
      <td style={{ padding: '3px 6px' }}>
        <input
          value={line.description}
          onChange={e => field('description', e.target.value)}
          style={{ width: '100%', fontSize: 'var(--text-sm)' }}
        />
      </td>
      <td style={{ padding: '3px 6px' }}>
        <input
          value={line.date_range}
          onChange={e => field('date_range', e.target.value)}
          style={{ width: '100%', fontSize: 'var(--text-sm)', minWidth: 160 }}
        />
      </td>
      <td style={{ padding: '3px 6px', textAlign: 'right' }}>
        {line.type === 'sessions' ? (
          <input
            type="number" step="1" value={line.unit_cost ?? ''}
            onChange={e => {
              const r = parseFloat(e.target.value);
              const newRate = isNaN(r) ? null : r;
              const newAmt = newRate !== null && line.quantity !== null ? newRate * line.quantity : line.amount;
              onChange({ ...line, unit_cost: newRate, amount: Math.round(newAmt * 100) / 100 });
            }}
            style={{ width: 64, textAlign: 'right', fontSize: 'var(--text-sm)' }}
          />
        ) : (
          <span style={{ color: 'var(--color-text-light)' }}>—</span>
        )}
      </td>
      <td style={{ padding: '3px 6px', textAlign: 'right' }}>
        {line.type === 'sessions' ? (
          <input
            type="number" step="0.25" value={line.quantity ?? ''}
            onChange={e => {
              const q = parseFloat(e.target.value);
              const newQty = isNaN(q) ? null : q;
              const newAmt = newQty !== null && line.unit_cost !== null ? line.unit_cost * newQty : line.amount;
              onChange({ ...line, quantity: newQty, amount: Math.round(newAmt * 100) / 100 });
            }}
            style={{ width: 56, textAlign: 'right', fontSize: 'var(--text-sm)' }}
          />
        ) : (
          <span style={{ color: 'var(--color-text-light)' }}>1</span>
        )}
      </td>
      <td style={{ padding: '3px 6px', textAlign: 'right' }}>
        <input
          type="number" step="0.01" value={line.amount}
          onChange={e => { const v = parseFloat(e.target.value); if (!isNaN(v)) field('amount', v); }}
          style={{ width: 72, textAlign: 'right', fontSize: 'var(--text-sm)', color: isNegative ? 'var(--color-error)' : undefined }}
        />
      </td>
      <td style={{ padding: '3px 6px', textAlign: 'center' }}>
        <button className="btn-link" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }} onClick={onRemove}>×</button>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Stage 4: Done
// ---------------------------------------------------------------------------

function Stage4({ result, onBack }: { result: BillingGenerateResult; onBack: () => void }) {
  const { demo } = useDemoMode();
  const navigate = useNavigate();
  return (
    <div>
      <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-lg)' }}>
        {result.invoices.length} draft invoice{result.invoices.length !== 1 ? 's' : ''} created.
      </p>
      <table style={{ borderCollapse: 'collapse', fontSize: 'var(--text-sm)', width: '100%', maxWidth: 500 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-text-light)' }}>
            <th style={{ textAlign: 'left', padding: '3px 8px', fontWeight: 500 }}>Company</th>
            <th style={{ textAlign: 'left', padding: '3px 8px', fontWeight: 500 }}>Invoice #</th>
            <th style={{ textAlign: 'right', padding: '3px 8px', fontWeight: 500 }}>Amount</th>
            <th style={{ textAlign: 'left', padding: '3px 8px', fontWeight: 500 }}>Status</th>
          </tr>
        </thead>
        <tbody>
          {result.invoices.map(inv => (
            <tr key={inv.invoice_number} style={{ borderBottom: '1px solid var(--color-border)' }}>
              <td style={{ padding: '4px 8px' }}>{inv.company_name}</td>
              <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{inv.invoice_number}</td>
              <td style={{ padding: '4px 8px', textAlign: 'right' }}>{demo ? '—' : `$${inv.total_amount.toFixed(2)}`}</td>
              <td style={{ padding: '4px 8px', color: 'var(--color-text-light)' }}>{inv.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: 'var(--space-lg)' }}>
        <button className="btn-primary" onClick={() => navigate('/billing/invoices')}>View Invoices</button>
        <button className="btn-secondary" onClick={() => navigate('/billing/sessions')}>View Sessions</button>
        <button className="btn-link" onClick={onBack}>← Start Over</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage breadcrumb
// ---------------------------------------------------------------------------

const STAGE_LABELS = ['Session Review', 'Add Expenses', 'Review & Edit', 'Done'];

function StageBreadcrumb({ stage }: { stage: number }) {
  return (
    <div style={{ display: 'flex', gap: 0, marginBottom: 'var(--space-xl)', borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--space-sm)' }}>
      {STAGE_LABELS.map((label, i) => {
        const n = i + 1;
        const active = n === stage;
        const done = n < stage;
        return (
          <span key={n} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {i > 0 && <span style={{ color: 'var(--color-text-light)', margin: '0 8px' }}>›</span>}
            <span style={{
              fontSize: 'var(--text-sm)',
              fontWeight: active ? 600 : undefined,
              color: done ? 'var(--color-text-light)' : active ? 'var(--color-fg)' : 'var(--color-text-light)',
              textDecoration: done ? 'line-through' : undefined,
            }}>
              {n}. {label}
            </span>
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function InvoicePrepPage() {
  const { year: yearStr, month: monthStr } = useParams<{ year: string; month: string }>();
  const navigate = useNavigate();
  const year = parseInt(yearStr ?? '0');
  const month = parseInt(monthStr ?? '0');

  const { data: prepData, isLoading } = useBillingPrepData(year, month);
  const generateMutation = useGenerateInvoices();

  const [stage, setStage] = useState<1 | 2 | 3 | 4>(1);
  const [includedProjectedIds, setIncludedProjectedIds] = useState<Set<number>>(new Set());
  const [expenses, setExpenses] = useState<Map<number, LocalExpense[]>>(new Map());
  const [draftByCompany, setDraftByCompany] = useState<Map<number, DraftLine[]>>(new Map());
  const [invoiceDate, setInvoiceDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  });
  const [servicesDate, setServicesDate] = useState(() => {
    // Last day of the prep month
    const last = new Date(year, month, 0);
    return last.toISOString().slice(0, 10);
  });
  const [generateResult, setGenerateResult] = useState<BillingGenerateResult | null>(null);
  const [invoiceNumberOverrides, setInvoiceNumberOverrides] = useState<Map<number, string>>(new Map());

  // Init projected: include all grape-promoted (is_confirmed but color_id '5' origin — they're already confirmed)
  // For true banana (is_confirmed=false), default OFF
  useEffect(() => {
    // No auto-selection — user opts in
  }, [prepData]);

  function setInvoiceNumberOverride(companyId: number, value: string) {
    setInvoiceNumberOverrides(prev => new Map(prev).set(companyId, value));
  }

  function toggleProjected(id: number) {
    setIncludedProjectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function setCompanyExpenses(companyId: number, exps: LocalExpense[]) {
    setExpenses(prev => new Map(prev).set(companyId, exps));
  }

  function setCompanyDraft(companyId: number, lines: DraftLine[]) {
    setDraftByCompany(prev => new Map(prev).set(companyId, lines));
  }

  function goToStage3() {
    if (!prepData) return;
    // Build draft lines for each active company that doesn't already have an invoice
    const newDraft = new Map<number, DraftLine[]>();
    for (const co of prepData.companies) {
      if (co.existing_invoice) continue; // already invoiced — skip
      const hasIncluded =
        co.confirmed_sessions.length > 0 ||
        co.projected_sessions.some(s => includedProjectedIds.has(s.id));
      if (!hasIncluded) continue;
      const coExpenses = expenses.get(co.id) ?? [];
      newDraft.set(co.id, buildDraftLines(co, includedProjectedIds, coExpenses));
    }
    setDraftByCompany(newDraft);
    setStage(3);
  }

  const [generateError, setGenerateError] = useState<string | null>(null);

  async function handleGenerate() {
    if (!prepData) return;
    setGenerateError(null);
    const companiesPayload = [];
    for (const co of prepData.companies) {
      const lines = draftByCompany.get(co.id);
      if (!lines?.length) continue;
      const invoiceNumOverride = invoiceNumberOverrides.get(co.id)?.trim() || undefined;
      companiesPayload.push({
        company_id: co.id,
        invoice_number: invoiceNumOverride,
        lines: lines.map(l => ({
          type: l.type,
          description: l.description,
          date_range: l.date_range || null,
          unit_cost: l.unit_cost,
          quantity: l.quantity,
          amount: l.amount,
          sort_order: l.sort_order,
          session_ids: l.session_ids,
        })),
      });
    }
    try {
      const result = await generateMutation.mutateAsync({
        year,
        month,
        invoice_date: invoiceDate,
        services_date: servicesDate,
        companies: companiesPayload,
      });
      setGenerateResult(result);
      setStage(4);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : 'Invoice generation failed');
    }
  }

  if (!year || !month) return <p className="empty-state">Invalid period.</p>;

  const prepDateFilter: BillingDateState = { year, month, week: null };
  function handlePrepDateChange(f: BillingDateState) {
    const m = f.month ?? month;
    navigate(`/billing/prepare/${f.year}/${m}`);
  }

  if (isLoading || !prepData) return (
    <div>
      <div style={{ marginBottom: 'var(--space-sm)' }}>
        <BillingDateFilter value={prepDateFilter} onChange={handlePrepDateChange} hideWeeks />
      </div>
      <p className="empty-state">Loading…</p>
    </div>
  );

  const companies = prepData.companies;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-md)', marginBottom: 'var(--space-xs)', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Invoice Prep</h2>
        <BillingDateFilter value={prepDateFilter} onChange={handlePrepDateChange} hideWeeks />
      </div>
      <StageBreadcrumb stage={stage} />


      {stage === 1 && (
        <Stage1
          companies={companies}
          includedProjectedIds={includedProjectedIds}
          onToggle={toggleProjected}
          onNext={() => setStage(2)}
        />
      )}
      {stage === 2 && (
        <Stage2
          companies={companies}
          includedProjectedIds={includedProjectedIds}
          expenses={expenses}
          onSetExpenses={setCompanyExpenses}
          onNext={goToStage3}
          onBack={() => setStage(1)}
        />
      )}
      {stage === 3 && (
        <Stage3
          companies={companies}
          includedProjectedIds={includedProjectedIds}
          expenses={expenses}
          draftByCompany={draftByCompany}
          invoiceDate={invoiceDate}
          servicesDate={servicesDate}
          invoiceNumberOverrides={invoiceNumberOverrides}
          onSetDraft={setCompanyDraft}
          onSetInvoiceDate={setInvoiceDate}
          onSetServicesDate={setServicesDate}
          onSetInvoiceNumber={setInvoiceNumberOverride}
          onNext={handleGenerate}
          onBack={() => setStage(2)}
          isPending={generateMutation.isPending}
          error={generateError}
        />
      )}
      {stage === 4 && generateResult && (
        <Stage4
          result={generateResult}
          onBack={() => { setStage(1); setGenerateResult(null); }}
        />
      )}
    </div>
  );
}
