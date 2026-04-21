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
  // Border rules
  const rowStyle: React.CSSProperties = {};
  if (laneId === 'york') {
    rowStyle.borderBottom = 'var(--glance-line-hairline)';
  }
  if (laneId === 'steve_events') {
    rowStyle.borderTop = 'var(--glance-line-hairline)';
  }

  return (
    <tr style={rowStyle}>
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
        }}
      >
        {laneLabel}
      </td>

      {/* Seven day cells */}
      {week.map((d) => {
        const ds = d.toISOString().slice(0, 10);
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
 * Lighten or darken a hex color by a factor (-1 to 1).
 * factor < 0 = darker, factor > 0 = lighter.
 */
function shadeColor(hex: string, factor: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  if (factor < 0) {
    const f = 1 + factor;
    return `rgb(${clamp(r * f)}, ${clamp(g * f)}, ${clamp(b * f)})`;
  }
  const f = factor;
  return `rgb(${clamp(r + (255 - r) * f)}, ${clamp(g + (255 - g) * f)}, ${clamp(b + (255 - b) * f)})`;
}
