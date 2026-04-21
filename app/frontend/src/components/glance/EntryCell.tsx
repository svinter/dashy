import React from 'react';
import type { GlanceEntry } from '../../hooks/useGlanceData';

interface EntryCellProps {
  entry: GlanceEntry;
  onMouseEnter?: (e: React.MouseEvent, notes: string) => void;
  onMouseLeave?: () => void;
}

export function EntryCell({ entry, onMouseEnter, onMouseLeave }: EntryCellProps) {
  const hasNotes = Boolean(entry.notes);
  const noteMark = hasNotes ? (
    <sup style={{ fontSize: '8px', opacity: 0.5, marginLeft: '1px' }}>*</sup>
  ) : null;

  const handlers = hasNotes && onMouseEnter
    ? {
        onMouseEnter: (e: React.MouseEvent) => onMouseEnter(e, entry.notes!),
        onMouseLeave,
      }
    : {};

  if (entry.lane === 'steve_events') {
    // Plain text, centered
    return (
      <div
        style={{ fontSize: '10px', textAlign: 'center', lineHeight: '15px' }}
        {...handlers}
      >
        {entry.label}{noteMark}
      </div>
    );
  }

  if (entry.lane === 'fam_events') {
    const bg = entry.member_color_bg ?? '#e0e0e0';
    const fg = entry.member_color_text ?? '#000';
    const memberDisplay = entry.member_display ?? entry.member_id ?? '';
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
          whiteSpace: 'nowrap',
        }}
        {...handlers}
      >
        {entry.label} · {memberDisplay}{noteMark}
      </div>
    );
  }

  if (entry.lane === 'york') {
    return (
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          background: '#97C459',
          color: '#173404',
          borderRadius: '3px',
          padding: '1px 5px',
          fontSize: '10px',
          lineHeight: '15px',
          whiteSpace: 'nowrap',
        }}
        {...handlers}
      >
        {entry.label}{noteMark}
      </div>
    );
  }

  // Fallback — generic pill
  return (
    <div style={{ fontSize: '10px', lineHeight: '15px' }} {...handlers}>
      {entry.label}{noteMark}
    </div>
  );
}
