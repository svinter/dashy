import React from 'react';
import type { GlanceDayData } from '../../hooks/useGlanceData';
import { TripPill } from './TripPill';
import { EntryCell } from './EntryCell';

export type LaneId = 'gcal' | 'york' | 'fam_events' | 'fam_travel' | 'steve_events' | 'steve_travel';

interface LaneRowProps {
  laneId: LaneId;
  laneLabel: string;
  week: Date[];
  dayData: Record<string, GlanceDayData>;
  monthBg: string;
  visibleMembers: Set<string>;
  onNoteHover: (e: React.MouseEvent, laneLabel: string, date: string, notes: string[]) => void;
  onNoteLeave: () => void;
}

function localIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function isWeekend(d: Date): boolean {
  const dow = d.getDay();
  return dow === 0 || dow === 6;
}

function formatDate(d: Date): string {
  const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${MONTH_ABBR[d.getMonth()]} ${d.getDate()}`;
}

export function LaneRow({
  laneId,
  laneLabel,
  week,
  dayData,
  monthBg,
  visibleMembers,
  onNoteHover,
  onNoteLeave,
}: LaneRowProps) {
  const cellBorderBottom =
    laneId === 'york' || laneId === 'fam_travel'
      ? '0.5px solid rgba(0,0,0,0.22)'
      : undefined;
  const cellBorderTop =
    laneId === 'steve_events'
      ? 'var(--glance-line-hairline)'
      : undefined;

  return (
    <tr>
      {/* Month column — tinted, no horizontal border */}
      <td style={{ background: monthBg }} />

      {/* Lane label */}
      <td
        style={{
          background: monthBg,
          fontSize: '10px',
          fontWeight: 400,
          color: 'var(--color-text-tertiary, #999)',
          textAlign: 'right',
          paddingRight: '6px',
          whiteSpace: 'nowrap',
          verticalAlign: 'middle',
          borderBottom: cellBorderBottom,
          borderTop: cellBorderTop,
        }}
      >
        {laneLabel}
      </td>

      {/* Seven day cells */}
      {week.map((d) => {
        const ds = localIso(d);
        const weekend = isWeekend(d);
        const data = dayData[ds];
        const cellBg = weekend
          ? shadeColor(monthBg, -0.025)
          : monthBg;

        const trips = (data?.trips ?? []).filter((t) => t.lane === laneId);
        const entries = (data?.entries ?? []).filter((e) => {
          if (e.lane !== laneId) return false;
          // Filter by member visibility for fam lanes
          if (laneId === 'fam_events' || laneId === 'fam_travel') {
            if (e.member_id && !visibleMembers.has(e.member_id)) return false;
          }
          return true;
        });

        const filteredTrips = trips.filter((t) => {
          if (laneId === 'fam_travel') {
            return !t.member_id || visibleMembers.has(t.member_id);
          }
          return true;
        });

        const dateStr = formatDate(d);
        return (
          <td
            key={ds}
            style={{
              background: cellBg,
              verticalAlign: 'middle',
              padding: '2px 3px',
              minHeight: '20px',
              textAlign: 'center',
              borderBottom: cellBorderBottom,
              borderTop: cellBorderTop,
              borderLeft: d.getDate() === 1 ? '2px solid rgba(0,0,0,0.35)' : undefined,
            }}
          >
            {filteredTrips.map((trip, i) => (
              <div key={`trip-${trip.trip_id}-${i}`} style={{ marginBottom: filteredTrips.length > 1 ? '2px' : 0 }}>
                <TripPill
                  trip={trip}
                  onMouseEnter={trip.day_notes
                    ? (e) => onNoteHover(e, laneLabel, dateStr, [trip.day_notes!])
                    : undefined}
                  onMouseLeave={onNoteLeave}
                />
              </div>
            ))}
            {entries.map((entry, i) => (
              <div key={`entry-${entry.id}-${i}`} style={{ marginBottom: entries.length > 1 ? '2px' : 0 }}>
                <EntryCell
                  entry={entry}
                  onMouseEnter={entry.notes
                    ? (e) => onNoteHover(e, laneLabel, dateStr, [entry.notes!])
                    : undefined}
                  onMouseLeave={onNoteLeave}
                />
              </div>
            ))}
          </td>
        );
      })}
    </tr>
  );
}

/**
 * Lighten or darken a color by a factor (-1 to 1).
 * Handles both hex (#RRGGBB) and rgba(...) inputs.
 * factor < 0 = darker, factor > 0 = lighter.
 */
function shadeColor(color: string, factor: number): string {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  let r: number, g: number, b: number, a = 1;

  if (color.startsWith('rgba')) {
    const m = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
    if (!m) return color;
    r = parseInt(m[1]); g = parseInt(m[2]); b = parseInt(m[3]);
    a = m[4] !== undefined ? parseFloat(m[4]) : 1;
  } else {
    r = parseInt(color.slice(1, 3), 16);
    g = parseInt(color.slice(3, 5), 16);
    b = parseInt(color.slice(5, 7), 16);
  }

  let nr: number, ng: number, nb: number;
  if (factor < 0) {
    const f = 1 + factor;
    nr = clamp(r * f); ng = clamp(g * f); nb = clamp(b * f);
  } else {
    nr = clamp(r + (255 - r) * factor);
    ng = clamp(g + (255 - g) * factor);
    nb = clamp(b + (255 - b) * factor);
  }
  return a < 1 ? `rgba(${nr}, ${ng}, ${nb}, ${a})` : `rgb(${nr}, ${ng}, ${nb})`;
}
