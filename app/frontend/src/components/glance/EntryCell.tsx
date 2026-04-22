import React from 'react';
import type { GlanceEntry } from '../../hooks/useGlanceData';
import { computeColor } from './ColorPicker';

interface EntryCellProps {
  entry: GlanceEntry;
  onMouseEnter?: (e: React.MouseEvent, notes: string) => void;
  onMouseLeave?: () => void;
}

export function EntryCell({ entry, onMouseEnter, onMouseLeave }: EntryCellProps) {
  const hasNotes = Boolean(entry.notes);

  // Parse color_data override if present
  let colorBgOverride: string | null = null;
  let colorTextOverride: string | null = null;
  if (entry.color_data) {
    try {
      const cd = JSON.parse(entry.color_data);
      const computed = computeColor(cd.h, cd.s, cd.tint, cd.opacity);
      colorBgOverride   = computed.bg;
      colorTextOverride = computed.text;
    } catch { /* ignore */ }
  }
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
    return (
      <div
        style={{
          fontSize: '10px', textAlign: 'center', lineHeight: '15px',
          ...(colorBgOverride ? {
            display: 'inline-flex', alignItems: 'center',
            background: colorBgOverride, color: colorTextOverride ?? undefined,
            borderRadius: '3px', padding: '1px 5px', whiteSpace: 'nowrap',
          } : {}),
        }}
        {...handlers}
      >
        {entry.label}{noteMark}
      </div>
    );
  }

  if (entry.lane === 'fam_events') {
    const bg   = colorBgOverride   ?? entry.member_color_bg  ?? '#e0e0e0';
    const fg   = colorTextOverride ?? entry.member_color_text ?? '#000';
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
    const bg = colorBgOverride   ?? '#97C35B';
    const fg = colorTextOverride ?? '#173404';
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
        {entry.label}{noteMark}
      </div>
    );
  }

  // Fallback — generic pill
  return (
    <div
      style={{
        fontSize: '10px', lineHeight: '15px',
        ...(colorBgOverride ? {
          display: 'inline-flex', alignItems: 'center',
          background: colorBgOverride, color: colorTextOverride ?? undefined,
          borderRadius: '3px', padding: '1px 5px', whiteSpace: 'nowrap',
        } : {}),
      }}
      {...handlers}
    >
      {entry.label}{noteMark}
    </div>
  );
}
