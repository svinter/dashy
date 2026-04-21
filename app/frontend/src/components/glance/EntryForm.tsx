import React, { useState } from 'react';
import type { GlanceMember } from '../../hooks/useGlanceData';
import { backdropStyle, modalStyle, saveBtnStyle, cancelBtnStyle } from './TripForm';

export interface EntryFormInitial {
  laneId: string;
  startDate: string;
  endDate: string;
}

interface EntryFormProps {
  initial: EntryFormInitial;
  editId?: number;
  existingData?: { label: string; notes?: string | null; member_id?: string | null; date: string };
  members: GlanceMember[];
  onSave: (entries: Array<{ lane: string; member_id?: string | null; date: string; label: string; notes?: string | null }>) => void;
  onCancel: () => void;
}

export function EntryForm({ initial, editId, existingData, members, onSave, onCancel }: EntryFormProps) {
  const [label, setLabel] = useState(existingData?.label ?? '');
  const [notes, setNotes] = useState(existingData?.notes ?? '');
  const [memberId, setMemberId] = useState(existingData?.member_id ?? '');
  const [startDate, setStartDate] = useState(existingData?.date ?? initial.startDate);
  const [endDate, setEndDate] = useState(initial.endDate);
  const [error, setError] = useState('');

  const needsMember = initial.laneId === 'fam_events';
  const isRange = startDate !== endDate && !editId;

  // Build dates in range
  function buildDates(): string[] {
    const dates: string[] = [];
    const s = new Date(startDate + 'T00:00:00');
    const e = new Date(endDate + 'T00:00:00');
    const d = new Date(s);
    while (d <= e) {
      dates.push(d.toISOString().slice(0, 10));
      d.setDate(d.getDate() + 1);
    }
    return dates;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!label.trim()) { setError('Label is required'); return; }
    if (needsMember && !memberId) { setError('Member is required'); return; }
    const dates = editId ? [existingData?.date ?? startDate] : buildDates();
    onSave(dates.map((date) => ({
      lane: initial.laneId,
      member_id: needsMember ? memberId : undefined,
      date,
      label: label.trim(),
      notes: notes.trim() || undefined,
    })));
  }

  return (
    <div style={backdropStyle} onClick={onCancel}>
      <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 16px', fontSize: '14px', fontWeight: 600 }}>
          {editId ? 'Edit Entry' : 'New Entry'}
          <span style={{ fontWeight: 400, color: 'var(--color-text-muted)', marginLeft: '8px', fontSize: '11px' }}>
            {initial.laneId}
          </span>
        </h3>
        <form onSubmit={handleSubmit}>
          {error && <p style={{ color: 'var(--color-danger, #c00)', fontSize: '12px', marginBottom: '8px' }}>{error}</p>}

          <label style={labelStyle}>
            Label *
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              style={inputStyle}
              autoFocus
              required
            />
          </label>

          {needsMember && (
            <label style={labelStyle}>
              Member *
              <select value={memberId} onChange={(e) => setMemberId(e.target.value)} style={inputStyle} required>
                <option value="">— select —</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>{m.display}</option>
                ))}
              </select>
            </label>
          )}

          <label style={labelStyle}>
            Notes
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} style={{ ...inputStyle, minHeight: '48px', resize: 'vertical' }} />
          </label>

          {!editId && (
            <div style={{ display: 'flex', gap: '8px' }}>
              <label style={{ ...labelStyle, flex: 1 }}>
                Start
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={inputStyle} />
              </label>
              <label style={{ ...labelStyle, flex: 1 }}>
                End
                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={inputStyle} />
              </label>
            </div>
          )}

          {isRange && (
            <p style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginBottom: '12px' }}>
              Creates an entry for each day from {startDate} to {endDate}.
            </p>
          )}

          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button type="button" onClick={onCancel} style={cancelBtnStyle}>Cancel</button>
            <button type="submit" style={saveBtnStyle}>{editId ? 'Save' : 'Create'}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: '4px',
  marginBottom: '12px', fontSize: '12px', fontWeight: 500,
};

const inputStyle: React.CSSProperties = {
  fontSize: '13px', padding: '4px 6px',
  border: '1px solid var(--color-border, #e0ddd1)',
  borderRadius: '3px', fontFamily: 'inherit',
  width: '100%', boxSizing: 'border-box',
};
