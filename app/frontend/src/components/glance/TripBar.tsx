import React, { useState } from 'react';
import type { GlanceTripDay } from '../../hooks/useGlanceData';
import { computeColor } from './ColorPicker';

const LANE_ROW_HEIGHT = 24;

interface TripBarProps {
  trip: GlanceTripDay;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: () => void;
  onEdgeDragStart?: (edge: 'start' | 'end', e: React.MouseEvent) => void;
}

export function TripBar({
  trip,
  onMouseEnter,
  onMouseLeave,
  onEdgeDragStart,
}: TripBarProps) {
  const isSteve = trip.member_id === 'steve';

  let locationColorBg   = trip.location_color_bg  ?? '#ccc';
  let locationColorText = trip.location_color_text ?? '#000';

  if (trip.color_data) {
    try {
      const cd = JSON.parse(trip.color_data);
      const computed = computeColor(cd.h, cd.s, cd.tint, cd.opacity);
      locationColorBg   = computed.bg;
      locationColorText = computed.text;
    } catch { /* ignore parse errors */ }
  }

  const pillBg   = isSteve
    ? locationColorBg
    : (trip.member_travel_color_bg ?? trip.member_color_bg ?? locationColorBg);
  const pillText = isSteve
    ? locationColorText
    : (trip.member_travel_color_text ?? trip.member_color_text ?? locationColorText);

  const locationDisplay = trip.location_display ?? trip.location_id;
  const isDepart  = trip.depart;
  const isReturn  = trip.return;
  const hasNotes  = Boolean(trip.day_notes || trip.trip_notes);

  const [edgeCursor, setEdgeCursor] = useState<'default' | 'ew-resize'>('default');

  function handleMouseMove(e: React.MouseEvent) {
    const el = e.currentTarget as HTMLElement;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if ((isDepart && x < 8) || (isReturn && x > rect.width - 8)) {
      setEdgeCursor('ew-resize');
    } else {
      setEdgeCursor('default');
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
    <div
      className="glance-trip-bar"
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        width: '100%', height: LANE_ROW_HEIGHT,
        cursor: edgeCursor,
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
    >
      {isDepart && (
        <span style={{ fontSize: '11px', color: pillText, opacity: 0.7, marginRight: '3px' }}>→</span>
      )}
      <span style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: '3px',
        fontSize: '10px',
        fontWeight: 500,
        background: pillBg,
        color: pillText,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}>
        {locationDisplay}{hasNotes && <sup style={{ fontSize: '8px', opacity: 0.5 }}>*</sup>}
      </span>
      {isReturn && (
        <span style={{ fontSize: '11px', color: pillText, opacity: 0.7, marginLeft: '3px' }}>←</span>
      )}
    </div>
  );
}
