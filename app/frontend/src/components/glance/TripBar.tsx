import React from 'react';
import type { GlanceTripDay } from '../../hooks/useGlanceData';

interface TripBarProps {
  trip: GlanceTripDay;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: () => void;
  onEdgeDragStart?: (edge: 'start' | 'end', e: React.MouseEvent) => void;
}

export function TripBar({ trip, onMouseEnter, onMouseLeave, onEdgeDragStart }: TripBarProps) {
  const locationColorBg   = trip.location_color_bg  ?? '#ccc';
  const locationColorText = trip.location_color_text ?? '#000';
  const locationDisplay   = trip.location_display   ?? trip.location_id;
  const memberColorBg     = trip.lane === 'fam_travel' ? (trip.member_color_bg ?? null) : null;
  const isDepart  = trip.depart;
  const isReturn  = trip.return;
  const hasNotes  = Boolean(trip.day_notes || trip.trip_notes);

  function handleMouseDown(e: React.MouseEvent) {
    if (!onEdgeDragStart) return;
    const cell = (e.currentTarget as HTMLElement).closest('td');
    if (!cell) return;
    const rect = cell.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if (isDepart && x < 8) {
      e.stopPropagation();
      onEdgeDragStart('start', e);
    } else if (isReturn && x > rect.width - 8) {
      e.stopPropagation();
      onEdgeDragStart('end', e);
    }
  }

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'stretch',
        overflow: 'hidden',
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onMouseDown={handleMouseDown}
    >
      <div style={{
        width: '25%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-end',
        paddingRight: '3px',
      }}>
        {isDepart && (
          <span style={{ fontSize: '11px', color: locationColorText, opacity: 0.7 }}>→</span>
        )}
      </div>
      <div style={{
        width: '50%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: locationColorBg,
        borderRadius: 0,
        borderLeft: memberColorBg ? `3px solid ${memberColorBg}` : undefined,
      }}>
        <span style={{
          fontSize: '10px',
          fontWeight: 500,
          color: locationColorText,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          textOverflow: 'ellipsis',
        }}>
          {locationDisplay}{hasNotes && <sup style={{ fontSize: '8px', opacity: 0.5 }}>*</sup>}
        </span>
      </div>
      <div style={{
        width: '25%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-start',
        paddingLeft: '3px',
      }}>
        {isReturn && (
          <span style={{ fontSize: '11px', color: locationColorText, opacity: 0.7 }}>←</span>
        )}
      </div>
    </div>
  );
}
