import React from 'react';
import type { GlanceTripDay } from '../../hooks/useGlanceData';

interface TripPillProps {
  trip: GlanceTripDay;
  onMouseEnter?: (e: React.MouseEvent, notes: string) => void;
  onMouseLeave?: () => void;
}

function buildLabel(trip: GlanceTripDay): React.ReactNode {
  const loc = trip.location_display ?? trip.location_id;
  const { depart, sleep } = trip;
  const ret = trip['return'];

  // Build marks: → prefix if depart, ← suffix if return, · suffix if sleep (non-return)
  let prefix = '';
  let suffix = '';

  if (depart) prefix = '→ ';
  if (ret) suffix = ' ←';
  else if (sleep) suffix = ' ·';

  const hasNotes = Boolean(trip.day_notes);

  return (
    <>
      {prefix}{loc}{suffix}
      {hasNotes && (
        <sup style={{ fontSize: '8px', opacity: 0.5, marginLeft: '1px' }}>*</sup>
      )}
    </>
  );
}

export function TripPill({ trip, onMouseEnter, onMouseLeave }: TripPillProps) {
  const isFam = trip.lane === 'fam_travel';
  const bg = trip.location_color_bg ?? '#ccc';
  const fg = trip.location_color_text ?? '#000';

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        background: bg,
        color: fg,
        borderRadius: '3px',
        padding: '1px 5px',
        fontSize: '10px',
        lineHeight: '15px',
        borderLeft: isFam ? `3px solid ${trip.member_color_bg ?? '#ccc'}` : undefined,
        cursor: trip.day_notes ? 'default' : undefined,
        whiteSpace: 'nowrap',
      }}
      onMouseEnter={trip.day_notes && onMouseEnter ? (e) => onMouseEnter(e, trip.day_notes!) : undefined}
      onMouseLeave={trip.day_notes ? onMouseLeave : undefined}
    >
      {buildLabel(trip)}
    </div>
  );
}
