import React, { useState, useEffect } from 'react';
import type { GlanceMember, GlanceLocation } from '../../hooks/useGlanceData';

export interface TripFormInitial {
  laneId: string;
  startDate: string;
  endDate: string;
}

interface TripFormProps {
  initial: TripFormInitial;
  editId?: number;
  /** Existing trip data when editing */
  existingData?: {
    member_id: string; location_id: string;
    start_date: string; end_date: string; notes?: string | null;
    days?: Array<{ date: string; depart: boolean; sleep: boolean; return: boolean; notes: string | null }>;
  };
  members: GlanceMember[];
  locations: GlanceLocation[];
  onSave: (data: {
    member_id: string; location_id: string;
    start_date: string; end_date: string;
    notes?: string; day_overrides?: object[];
  }) => void;
  onCancel: () => void;
}

export function TripForm({ initial, editId, existingData, members, locations, onSave, onCancel }: TripFormProps) {
  const defaultMemberId = initial.laneId === 'steve_travel' ? 'steve' : (existingData?.member_id ?? '');

  const [memberId, setMemberId] = useState(existingData?.member_id ?? defaultMemberId);
  const [locationId, setLocationId] = useState(existingData?.location_id ?? '');
  const [locationInput, setLocationInput] = useState('');
  const [startDate, setStartDate] = useState(existingData?.start_date ?? initial.startDate);
  const [endDate, setEndDate] = useState(existingData?.end_date ?? initial.endDate);
  const [notes, setNotes] = useState(existingData?.notes ?? '');
  const [showDayMarks, setShowDayMarks] = useState(false);
  const [locationSuggestions, setLocationSuggestions] = useState<GlanceLocation[]>([]);
  const [error, setError] = useState('');

  // Sync locationInput display with locationId
  useEffect(() => {
    const loc = locations.find((l) => l.id === locationId);
    setLocationInput(loc?.display ?? locationId);
  }, [locationId, locations]);

  function handleLocationInput(val: string) {
    setLocationInput(val);
    const filtered = locations.filter((l) =>
      l.display.toLowerCase().includes(val.toLowerCase())
    );
    setLocationSuggestions(filtered.slice(0, 6));
    // Clear selection if user is typing something new
    if (!locations.find((l) => l.display.toLowerCase() === val.toLowerCase())) {
      setLocationId('');
    }
  }

  function selectLocation(loc: GlanceLocation) {
    setLocationId(loc.id);
    setLocationInput(loc.display);
    setLocationSuggestions([]);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!memberId) { setError('Member is required'); return; }
    if (!locationId && !locationInput.trim()) { setError('Location is required'); return; }
    const resolvedLocationId = locationId || locationInput.trim().toLowerCase().replace(/\s+/g, '_');
    onSave({ member_id: memberId, location_id: resolvedLocationId, start_date: startDate, end_date: endDate, notes: notes || undefined });
  }

  // Compute day range for day marks section
  const dayDates: string[] = [];
  if (showDayMarks && startDate && endDate) {
    const s = new Date(startDate + 'T00:00:00');
    const e = new Date(endDate + 'T00:00:00');
    const d = new Date(s);
    while (d <= e) {
      dayDates.push(d.toISOString().slice(0, 10));
      d.setDate(d.getDate() + 1);
    }
  }

  const isTravel = initial.laneId === 'fam_travel' || initial.laneId === 'steve_travel';

  return (
    <div style={backdropStyle} onClick={onCancel}>
      <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 16px', fontSize: '14px', fontWeight: 600 }}>
          {editId ? 'Edit Trip' : 'New Trip'}
        </h3>
        <form onSubmit={handleSubmit}>
          {error && <p style={{ color: 'var(--color-danger, #c00)', fontSize: '12px', marginBottom: '8px' }}>{error}</p>}

          {/* Member */}
          {(initial.laneId === 'fam_travel' || editId) && (
            <label style={labelStyle}>
              Member
              <select value={memberId} onChange={(e) => setMemberId(e.target.value)} style={inputStyle} required>
                <option value="">— select —</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>{m.display}</option>
                ))}
              </select>
            </label>
          )}

          {/* Location */}
          <label style={labelStyle}>
            Location
            <div style={{ position: 'relative' }}>
              <input
                type="text"
                value={locationInput}
                onChange={(e) => handleLocationInput(e.target.value)}
                style={inputStyle}
                placeholder="Type to search…"
                autoComplete="off"
              />
              {locationSuggestions.length > 0 && (
                <div style={suggestionListStyle}>
                  {locationSuggestions.map((loc) => (
                    <div key={loc.id} style={suggestionItemStyle} onClick={() => selectLocation(loc)}>
                      {loc.display}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </label>

          {/* Dates */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <label style={{ ...labelStyle, flex: 1 }}>
              Start
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={inputStyle} required />
            </label>
            <label style={{ ...labelStyle, flex: 1 }}>
              End
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={inputStyle} required />
            </label>
          </div>

          {/* Notes */}
          <label style={labelStyle}>
            Notes
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} style={{ ...inputStyle, minHeight: '48px', resize: 'vertical' }} />
          </label>

          {/* Day marks toggle */}
          <div style={{ marginBottom: '12px' }}>
            <button type="button" onClick={() => setShowDayMarks((v) => !v)} style={toggleBtnStyle}>
              {showDayMarks ? '▲' : '▶'} override day marks ({dayDates.length} days)
            </button>
            {showDayMarks && (
              <div style={{ marginTop: '6px', fontSize: '11px', color: 'var(--color-text-muted)' }}>
                Day mark overrides are applied after save — edit per-day notes in the details panel.
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button type="button" onClick={onCancel} style={cancelBtnStyle}>Cancel</button>
            <button type="submit" style={saveBtnStyle}>{editId ? 'Save' : 'Create'}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared modal styles
// ---------------------------------------------------------------------------

export const backdropStyle: React.CSSProperties = {
  position: 'fixed', inset: 0,
  background: 'rgba(0,0,0,0.35)',
  zIndex: 500,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

export const modalStyle: React.CSSProperties = {
  background: '#fff',
  borderRadius: '6px',
  padding: '20px 24px',
  minWidth: '320px',
  maxWidth: '420px',
  width: '90vw',
  boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
};

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

const suggestionListStyle: React.CSSProperties = {
  position: 'absolute', top: '100%', left: 0, right: 0,
  background: '#fff', border: '1px solid var(--color-border)',
  borderRadius: '3px', zIndex: 10,
  maxHeight: '120px', overflowY: 'auto',
};

const suggestionItemStyle: React.CSSProperties = {
  padding: '4px 8px', cursor: 'pointer', fontSize: '12px',
};

const toggleBtnStyle: React.CSSProperties = {
  background: 'none', border: 'none', cursor: 'pointer',
  fontSize: '11px', color: 'var(--color-text-muted)', padding: 0,
};

export const saveBtnStyle: React.CSSProperties = {
  padding: '5px 16px', borderRadius: '3px', cursor: 'pointer',
  background: 'var(--color-accent, #a00)', color: '#fff',
  border: 'none', fontSize: '12px', fontWeight: 500,
};

export const cancelBtnStyle: React.CSSProperties = {
  padding: '5px 16px', borderRadius: '3px', cursor: 'pointer',
  background: 'none', color: 'var(--color-text-muted)',
  border: '1px solid var(--color-border)', fontSize: '12px',
};
