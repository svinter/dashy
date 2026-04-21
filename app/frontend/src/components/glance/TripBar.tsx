import React, { useState } from 'react';
import type { GlanceTripDay } from '../../hooks/useGlanceData';
import { computeColor } from './ColorPicker';

interface TripBarProps {
  trip: GlanceTripDay;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: () => void;
  onEdgeDragStart?: (edge: 'start' | 'end', e: React.MouseEvent) => void;
}

export function TripBar({ trip, onMouseEnter, onMouseLeave, onEdgeDragStart }: TripBarProps) {
  let locationColorBg   = trip.location_color_bg  ?? '#ccc';
  let locationColorText = trip.location_color_text ?? '#000';

  // Override colors from color_data if present
  if (trip.color_data) {
    try {
      const cd = JSON.parse(trip.color_data);
      const computed = computeColor(cd.h, cd.s, cd.tint, cd.opacity);
      locationColorBg   = computed.bg;
      locationColorText = computed.text;
    } catch { /* ignore parse errors */ }
  }

  const locationDisplay   = trip.location_display   ?? trip.location_id;
  const memberColorBg     = trip.lane === 'fam_travel' ? (trip.member_color_bg ?? null) : null;
  const isDepart  = trip.depart;
  const isReturn  = trip.return;
  const hasNotes  = Boolean(trip.day_notes || trip.trip_notes);

  const [cursor, setCursor] = useState<'default' | 'ew-resize'>('default');

  function handleMouseMove(e: React.MouseEvent) {
    const el = e.currentTarget as HTMLElement;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if ((isDepart && x < 8) || (isReturn && x > rect.width - 8)) {
      setCursor('ew-resize');
    } else {
      setCursor('default');
    }
  }

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
    <div style={{
      position: 'absolute', inset: 0,
      display: 'flex', flexDirection: 'row', alignItems: 'stretch',
      overflow: 'hidden',
      cursor,
    }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
    >
      <div style={{
        width: '25%', display: 'flex',
        alignItems: 'center', justifyContent: 'flex-end', paddingRight: '3px',
      }}>
        {isDepart && <span style={{ fontSize: '11px', color: locationColorText, opacity: 0.7 }}>→</span>}
      </div>
      <div style={{
        width: '50%', display: 'flex',
        alignItems: 'center', justifyContent: 'center',
        background: locationColorBg, borderRadius: 0,
        borderLeft: memberColorBg ? `3px solid ${memberColorBg}` : undefined,
      }}>
        <span style={{ fontSize: '10px', fontWeight: 500, color: locationColorText, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
          {locationDisplay}{hasNotes && <sup style={{ fontSize: '8px', opacity: 0.5 }}>*</sup>}
        </span>
      </div>
      <div style={{
        width: '25%', display: 'flex',
        alignItems: 'center', justifyContent: 'flex-start', paddingLeft: '3px',
      }}>
        {isReturn && <span style={{ fontSize: '11px', color: locationColorText, opacity: 0.7 }}>←</span>}
      </div>
    </div>
  );
}
