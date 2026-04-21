import React, { useState } from 'react';
import type { GlanceTripDay, GlanceEntry } from '../../hooks/useGlanceData';
import { backdropStyle, modalStyle, saveBtnStyle, cancelBtnStyle } from './TripForm';

interface ViewEditPopoverProps {
  date: string;
  laneId: string;
  laneLabel: string;
  trips: GlanceTripDay[];
  entries: GlanceEntry[];
  onEditTrip: (tripId: number) => void;
  onEditEntry: (entryId: number) => void;
  onDeleteTrip: (tripId: number) => void;
  onDeleteEntry: (entryId: number) => void;
  onClose: () => void;
}

type ConfirmState = { type: 'trip'; id: number } | { type: 'entry'; id: number } | null;

export function ViewEditPopover({
  date,
  laneId,
  laneLabel,
  trips,
  entries,
  onEditTrip,
  onEditEntry,
  onDeleteTrip,
  onDeleteEntry,
  onClose,
}: ViewEditPopoverProps) {
  const [confirm, setConfirm] = useState<ConfirmState>(null);

  const hasContent = trips.length > 0 || entries.length > 0;

  return (
    <div style={backdropStyle} onClick={onClose}>
      <div style={{ ...modalStyle, minWidth: '280px' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
          <h3 style={{ margin: 0, fontSize: '13px', fontWeight: 600 }}>
            {laneLabel} · {date}
          </h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '16px', color: 'var(--color-text-muted)', padding: '0 4px' }}>×</button>
        </div>

        {!hasContent && (
          <p style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '12px' }}>No entries on this day.</p>
        )}

        {trips.map((trip) => (
          <div key={trip.trip_id} style={itemStyle}>
            <div style={{ fontSize: '12px', fontWeight: 500 }}>
              {trip.location_display ?? trip.location_id}
              <span style={{ fontWeight: 400, color: 'var(--color-text-muted)', marginLeft: '6px', fontSize: '11px' }}>
                {trip.trip_start} – {trip.trip_end}
              </span>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginTop: '2px' }}>
              {trip.day_notes || trip.trip_notes || '(no notes)'}
            </div>
            {confirm?.type === 'trip' && confirm.id === trip.trip_id ? (
              <div style={{ marginTop: '8px', display: 'flex', gap: '6px', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>Delete this trip and all its days?</span>
                <button onClick={() => { onDeleteTrip(trip.trip_id); setConfirm(null); }} style={{ ...saveBtnStyle, padding: '3px 10px', fontSize: '11px' }}>Delete</button>
                <button onClick={() => setConfirm(null)} style={{ ...cancelBtnStyle, padding: '3px 10px', fontSize: '11px' }}>Cancel</button>
              </div>
            ) : (
              <div style={{ marginTop: '6px', display: 'flex', gap: '6px' }}>
                <button onClick={() => onEditTrip(trip.trip_id)} style={{ ...cancelBtnStyle, padding: '3px 10px', fontSize: '11px' }}>Edit</button>
                <button onClick={() => setConfirm({ type: 'trip', id: trip.trip_id })} style={{ ...cancelBtnStyle, padding: '3px 10px', fontSize: '11px', color: 'var(--color-danger, #c00)' }}>Delete</button>
              </div>
            )}
          </div>
        ))}

        {entries.map((entry) => (
          <div key={entry.id} style={itemStyle}>
            <div style={{ fontSize: '12px', fontWeight: 500 }}>{entry.label}</div>
            <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginTop: '2px' }}>
              {entry.notes || '(no notes)'}
            </div>
            {confirm?.type === 'entry' && confirm.id === entry.id ? (
              <div style={{ marginTop: '8px', display: 'flex', gap: '6px', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>Delete this entry?</span>
                <button onClick={() => { onDeleteEntry(entry.id); setConfirm(null); }} style={{ ...saveBtnStyle, padding: '3px 10px', fontSize: '11px' }}>Delete</button>
                <button onClick={() => setConfirm(null)} style={{ ...cancelBtnStyle, padding: '3px 10px', fontSize: '11px' }}>Cancel</button>
              </div>
            ) : (
              <div style={{ marginTop: '6px', display: 'flex', gap: '6px' }}>
                <button onClick={() => onEditEntry(entry.id)} style={{ ...cancelBtnStyle, padding: '3px 10px', fontSize: '11px' }}>Edit</button>
                <button onClick={() => setConfirm({ type: 'entry', id: entry.id })} style={{ ...cancelBtnStyle, padding: '3px 10px', fontSize: '11px', color: 'var(--color-danger, #c00)' }}>Delete</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const itemStyle: React.CSSProperties = {
  borderTop: '1px solid var(--color-border)',
  paddingTop: '10px',
  marginBottom: '10px',
};
