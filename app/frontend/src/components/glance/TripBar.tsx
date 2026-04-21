import React from 'react';
import type { GlanceTripDay } from '../../hooks/useGlanceData';

interface TripBarProps {
  trip: GlanceTripDay;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: () => void;
  /** Called when mousedown near the left edge of a departure-day cell. */
  onEdgeDragStart?: (edge: 'start' | 'end', e: React.MouseEvent) => void;
}

export function TripBar({ trip, onMouseEnter, onMouseLeave, onEdgeDragStart }: TripBarProps) {
  const bg = trip.location_color_bg ?? '#ccc';
  const fg = trip.location_color_text ?? '#000';
  const loc = trip.location_display ?? trip.location_id;
  const isFam = trip.lane === 'fam_travel';
  const hasNotes = Boolean(trip.day_notes || trip.trip_notes);

  const centerBorderLeft = isFam
    ? `3px solid ${trip.member_color_bg ?? '#ccc'}`
    : undefined;

  function handleMouseDown(e: React.MouseEvent) {
    if (!onEdgeDragStart) return;
    const cell = (e.currentTarget as HTMLElement).closest('td');
    if (!cell) return;
    const rect = cell.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if (trip.depart && x < 8) {
      e.stopPropagation();
      onEdgeDragStart('start', e);
    } else if (trip.return && x > rect.width - 8) {
      e.stopPropagation();
      onEdgeDragStart('end', e);
    }
  }

  return (
    <div
      style={{ display: 'flex', width: '100%', height: '17px', cursor: 'pointer' }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onMouseDown={handleMouseDown}
    >
      {/* Left zone — 25%: departure arrow */}
      <div
        style={{
          width: '25%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: fg,
          fontSize: '11px',
          opacity: trip.depart ? 0.7 : 0,
          userSelect: 'none',
        }}
      >
        →
      </div>

      {/* Center zone — 50%: colored label */}
      <div
        style={{
          width: '50%',
          background: bg,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderLeft: centerBorderLeft,
          fontSize: '10px',
          fontWeight: 500,
          color: fg,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          userSelect: 'none',
        }}
      >
        {loc}
        {hasNotes && (
          <sup style={{ fontSize: '8px', opacity: 0.5, marginLeft: '1px' }}>*</sup>
        )}
      </div>

      {/* Right zone — 25%: return arrow */}
      <div
        style={{
          width: '25%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: fg,
          fontSize: '11px',
          opacity: trip.return ? 0.7 : 0,
          userSelect: 'none',
        }}
      >
        ←
      </div>
    </div>
  );
}
