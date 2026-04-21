import React from 'react';
import type { GlanceDayData } from '../../hooks/useGlanceData';
import { TripBar } from './TripBar';
import { EntryCell } from './EntryCell';
import { CommentCell } from './CommentCell';
import type { DragState, CursorCell } from '../../pages/GlancePage';

export type LaneId = 'gcal' | 'york' | 'fam_events' | 'fam_travel' | 'steve_events' | 'steve_travel';

const LANE_ROW_HEIGHT = 24;

interface LaneRowProps {
  laneId: LaneId;
  laneLabel: string;
  week: Date[];
  dayData: Record<string, GlanceDayData>;
  monthBg: string;
  visibleMembers: Set<string>;
  onNoteHover: (e: React.MouseEvent, laneLabel: string, date: string, notes: string[]) => void;
  onNoteLeave: () => void;
  cursor: CursorCell | null;
  dragState: DragState | null;
  onCellMouseDown: (date: string, laneId: LaneId, e: React.MouseEvent) => void;
  onCellMouseEnter: (date: string) => void;
  onCellMouseUp: (date: string, laneId: LaneId) => void;
  onCellClick: (date: string, laneId: LaneId, e: React.MouseEvent) => void;
  onEdgeDragStart: (tripId: number, edge: 'start' | 'end', e: React.MouseEvent) => void;
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

/** Returns selected dates for the current drag (creation type only). */
function dragSelectedDates(drag: DragState | null): Set<string> {
  if (!drag || drag.type !== 'create') return new Set();
  const a = drag.startDate < drag.currentDate ? drag.startDate : drag.currentDate;
  const b = drag.startDate > drag.currentDate ? drag.startDate : drag.currentDate;
  const set = new Set<string>();
  const start = new Date(a + 'T00:00:00');
  const end = new Date(b + 'T00:00:00');
  const d = new Date(start);
  while (d <= end) {
    set.add(localIso(d));
    d.setDate(d.getDate() + 1);
  }
  return set;
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
  cursor,
  dragState,
  onCellMouseDown,
  onCellMouseEnter,
  onCellMouseUp,
  onCellClick,
  onEdgeDragStart,
}: LaneRowProps) {
  const cellBorderBottom =
    laneId === 'york' || laneId === 'fam_travel'
      ? '0.5px solid rgba(0,0,0,0.22)'
      : undefined;
  const cellBorderTop =
    laneId === 'steve_events'
      ? 'var(--glance-line-hairline)'
      : undefined;

  const weekStartIso = localIso(week[0]);
  const comment = dayData[weekStartIso]?.week_comment?.[laneId] ?? '';

  const selected = dragSelectedDates(dragState);

  return (
    <tr>
      {/* Month column — sticky left */}
      <td style={{ background: monthBg, position: 'sticky', left: 0, zIndex: 5 }} />

      {/* Lane label — sticky left */}
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
          position: 'sticky',
          left: 46,
          zIndex: 4,
        }}
      >
        {laneLabel}
      </td>

      {/* Seven day cells */}
      {week.map((d) => {
        const ds = localIso(d);
        const weekend = isWeekend(d);
        const data = dayData[ds];

        const trips = (data?.trips ?? []).filter((t) => t.lane === laneId);
        const entries = (data?.entries ?? []).filter((e) => {
          if (e.lane !== laneId) return false;
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

        const isCursor = cursor?.date === ds && cursor?.laneId === laneId;
        const isDragSelected = selected.has(ds) && (dragState?.type === 'create' ? dragState.laneId === laneId : false);

        const dateStr = formatDate(d);

        type CellStyle = React.CSSProperties & { '--glance-cell-bg'?: string };
        let outlineStyle: CellStyle = {};
        if (isCursor && isDragSelected) {
          outlineStyle = { outline: '1.5px solid #378ADD', '--glance-cell-bg': `rgba(55, 138, 221, 0.06)` };
        } else if (isCursor) {
          outlineStyle = { outline: '1.5px solid #378ADD', outlineOffset: '-1px' };
        } else if (isDragSelected) {
          outlineStyle = { outline: '1.5px solid rgba(55, 138, 221, 0.5)', '--glance-cell-bg': `rgba(55, 138, 221, 0.06)` };
        }

        return (
          <td
            key={ds}
            data-date={ds}
            data-lane={laneId}
            style={{
              '--glance-cell-bg': monthBg,
              filter: weekend ? 'brightness(0.975)' : undefined,
              padding: 0,
              height: LANE_ROW_HEIGHT,
              overflow: 'hidden',
              verticalAlign: 'middle',
              position: 'relative',
              borderBottom: cellBorderBottom,
              borderTop: cellBorderTop,
              borderLeft: d.getDate() === 1 ? '2px solid rgba(0,0,0,0.35)' : undefined,
              cursor: laneId === 'gcal' ? 'default' : 'pointer',
              userSelect: 'none',
              ...outlineStyle,
            } as React.CSSProperties}
            onMouseDown={(e) => onCellMouseDown(ds, laneId, e)}
            onMouseEnter={() => onCellMouseEnter(ds)}
            onMouseUp={(e) => onCellMouseUp(ds, laneId)}
            onClick={(e) => onCellClick(ds, laneId, e)}
          >
            {filteredTrips.length > 0 && (
              <TripBar
                trip={filteredTrips[0]}
                onMouseEnter={filteredTrips[0].day_notes || filteredTrips[0].trip_notes
                  ? (e) => onNoteHover(e, laneLabel, dateStr, [filteredTrips[0].day_notes || filteredTrips[0].trip_notes || ''].filter(Boolean))
                  : undefined}
                onMouseLeave={onNoteLeave}
                onEdgeDragStart={(edge, e) => onEdgeDragStart(filteredTrips[0].trip_id, edge, e)}
              />
            )}
            {entries.map((entry, i) => (
              <div key={`entry-${entry.id}-${i}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: LANE_ROW_HEIGHT, marginBottom: entries.length > 1 ? '2px' : 0 }}>
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

      {/* Comment column */}
      <CommentCell
        weekStart={weekStartIso}
        laneId={laneId}
        comment={comment}
        cellBg={monthBg}
        borderBottom={cellBorderBottom}
        borderTop={cellBorderTop}
      />
    </tr>
  );
}

