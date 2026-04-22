import React, { useState } from 'react';
import type { GlanceTripDay } from '../../hooks/useGlanceData';
import { computeColor } from './ColorPicker';

const LANE_ROW_HEIGHT = 24;

export type RibbonPos = 'solo' | 'start' | 'middle' | 'end';

interface TripBarProps {
  trip: GlanceTripDay;
  ribbonPos: RibbonPos;
  showLabel: boolean;
  prevTripId: number | null;
  nextTripId: number | null;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: () => void;
  onEdgeDragStart?: (edge: 'start' | 'end', e: React.MouseEvent) => void;
}

export function TripBar({
  trip,
  ribbonPos,
  showLabel,
  prevTripId,
  nextTripId,
  onMouseEnter,
  onMouseLeave,
  onEdgeDragStart,
}: TripBarProps) {
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

  const locationDisplay = trip.location_display ?? trip.location_id;
  const memberColorBg   = trip.lane === 'fam_travel' ? (trip.member_color_bg ?? null) : null;
  const isDepart  = trip.depart;
  const isReturn  = trip.return;
  const hasNotes  = Boolean(trip.day_notes || trip.trip_notes);

  // Arrow suppression: only show → if prev day has a different (non-null) trip
  // Only show ← if next day has a different (non-null) trip
  const showDepartArrow = isDepart && prevTripId !== null && prevTripId !== trip.trip_id;
  const showReturnArrow = isReturn && nextTripId !== null && nextTripId !== trip.trip_id;

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

  // ── Solo (single day) ── original pill style ──────────────────────────────
  if (ribbonPos === 'solo') {
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
          <span style={{ fontSize: '11px', color: locationColorText, opacity: 0.7, marginRight: '3px' }}>→</span>
        )}
        <span style={{
          display: 'inline-block',
          padding: '1px 6px',
          borderRadius: '3px',
          fontSize: '10px',
          fontWeight: 500,
          background: locationColorBg,
          color: locationColorText,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          borderLeft: memberColorBg ? `3px solid ${memberColorBg}` : undefined,
        }}>
          {locationDisplay}{hasNotes && <sup style={{ fontSize: '8px', opacity: 0.5 }}>*</sup>}
        </span>
        {isReturn && (
          <span style={{ fontSize: '11px', color: locationColorText, opacity: 0.7, marginLeft: '3px' }}>←</span>
        )}
      </div>
    );
  }

  // ── Ribbon (start / middle / end) ─────────────────────────────────────────
  const borderRadius = (() => {
    const leftR  = ribbonPos === 'start' && isDepart  ? '3px' : '0';
    const rightR = ribbonPos === 'end'   && isReturn  ? '3px' : '0';
    return `${leftR} ${rightR} ${rightR} ${leftR}`;
  })();

  return (
    <div
      className="glance-trip-bar"
      style={{
        position: 'relative',
        width: '100%',
        height: LANE_ROW_HEIGHT,
        background: locationColorBg,
        borderRadius,
        borderLeft: memberColorBg && ribbonPos === 'start' ? `3px solid ${memberColorBg}` : undefined,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: edgeCursor,
        overflow: 'hidden',
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
    >
      {/* Departure arrow — inside ribbon at left edge */}
      {showDepartArrow && (
        <span style={{
          position: 'absolute', left: 3,
          fontSize: '11px', color: locationColorText, opacity: 0.8,
          pointerEvents: 'none',
        }}>→</span>
      )}

      {/* Location label — only in middle cell */}
      {showLabel && (
        <span style={{
          fontSize: '10px',
          fontWeight: 500,
          color: locationColorText,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          padding: '0 16px',  // leave room for arrows
          maxWidth: '100%',
        }}>
          {locationDisplay}{hasNotes && <sup style={{ fontSize: '8px', opacity: 0.5 }}>*</sup>}
        </span>
      )}

      {/* Return arrow — inside ribbon at right edge */}
      {showReturnArrow && (
        <span style={{
          position: 'absolute', right: 3,
          fontSize: '11px', color: locationColorText, opacity: 0.8,
          pointerEvents: 'none',
        }}>←</span>
      )}
    </div>
  );
}
