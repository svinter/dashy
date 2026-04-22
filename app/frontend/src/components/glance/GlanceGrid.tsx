import React from 'react';
import type { GlanceWeeksData } from '../../hooks/useGlanceData';
import { useGlanceWeeks } from '../../hooks/useGlanceData';
import { GlanceWeek } from './GlanceWeek';
import type { LaneId } from './LaneRow';
import type { DragState, CursorCell } from '../../pages/GlancePage';

const DAY_HEADERS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun',
                    'Jul','Aug','Sep','Oct','Nov','Dec'];

// 10 columns: month(46) + lane(66) + 7 day cols + 1 comment col (2× day width)
// 9 units share (100% - 112px): each day col = 1 unit, comment col = 2 units → total 9 units = 100%
const DAY_COL_W = 'calc((100% - 112px) / 9)';
const COMMENT_COL_W = 'calc((100% - 112px) / 9 * 2)';

const TH_BG = 'var(--color-bg, #fffff8)';

// Shared colgroup for both the header table and the body table.
// Both tables have identical colgroup so their columns align pixel-perfectly.
function Colgroup() {
  return (
    <colgroup>
      <col style={{ width: '46px' }} />
      <col style={{ width: '66px' }} />
      {DAY_HEADERS.map((d) => (
        <col key={d} style={{ width: DAY_COL_W }} />
      ))}
      <col style={{ width: COMMENT_COL_W }} />
    </colgroup>
  );
}

const TABLE_STYLE: React.CSSProperties = {
  tableLayout: 'fixed',
  width: '100%',
  borderCollapse: 'separate',
  borderSpacing: 0,
};

interface GlanceGridProps {
  scrollRef: React.RefObject<HTMLDivElement>;
  weeksData: GlanceWeeksData;
  visibleLanes: Set<LaneId>;
  visibleMembers: Set<string>;
  monthOpacity: number;
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

export function GlanceGrid({
  scrollRef,
  weeksData,
  visibleLanes,
  visibleMembers,
  monthOpacity,
  onNoteHover,
  onNoteLeave,
  cursor,
  dragState,
  onCellMouseDown,
  onCellMouseEnter,
  onCellMouseUp,
  onCellClick,
  onEdgeDragStart,
}: GlanceGridProps) {
  const weeks = useGlanceWeeks(weeksData);

  const headerYear = weeks.length > 0
    ? (weeks[0][3] ?? weeks[0][0]).getFullYear()
    : new Date().getFullYear();

  const seenMonths = new Set<string>();

  const thBorder: React.CSSProperties = { borderBottom: 'var(--glance-line-bold)' };

  return (
    // Flex column: fixed header + scrollable body below it.
    // overflowY: 'scroll' (not 'auto') ensures the scrollbar is always reserved,
    // keeping the body table the same width as the header table.
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 152px)' }}>

      {/* ── Fixed header table — never scrolls ── */}
      <table className="glance-table" style={TABLE_STYLE}>
        <Colgroup />
        <thead>
          <tr>
            <th style={{
              fontWeight: 500,
              fontSize: '10px',
              color: 'var(--color-text-primary, #111)',
              textAlign: 'left',
              padding: '4px 4px',
              position: 'sticky',
              left: 0,
              zIndex: 5,
              background: TH_BG,
            }}>
              {headerYear}
            </th>
            <th style={{
              fontWeight: 400,
              fontSize: '10px',
              color: 'var(--color-text-tertiary, #999)',
              textAlign: 'right',
              paddingRight: '6px',
              ...thBorder,
              position: 'sticky',
              left: 46,
              zIndex: 5,
              background: TH_BG,
            }}>
              lane
            </th>
            {DAY_HEADERS.map((d) => (
              <th
                key={d}
                style={{
                  fontWeight: 500,
                  fontSize: '11px',
                  color: '#4a4944',
                  textAlign: 'center',
                  padding: '4px 0',
                  background: TH_BG,
                  ...thBorder,
                }}
              >
                {d}
              </th>
            ))}
            <th style={{
              fontWeight: 400,
              fontSize: '10px',
              color: 'var(--color-text-tertiary, #999)',
              textAlign: 'left',
              paddingLeft: '6px',
              background: TH_BG,
              ...thBorder,
            }}>
              notes
            </th>
          </tr>
        </thead>
      </table>

      {/* ── Scrollable body ── */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'scroll' }}>
        <table className="glance-table" style={TABLE_STYLE}>
          <Colgroup />
          <tbody>
            {weeks.map((week, wi) => {
              const firstDay = week[0];
              const monthKey = `${firstDay.getFullYear()}-${firstDay.getMonth()}`;
              let monthLabel: string | null = null;
              if (!seenMonths.has(monthKey)) {
                seenMonths.add(monthKey);
                monthLabel = MONTH_ABBR[firstDay.getMonth()];
              }

              return (
                <GlanceWeek
                  key={wi}
                  week={week}
                  dayData={weeksData}
                  visibleLanes={visibleLanes}
                  visibleMembers={visibleMembers}
                  monthLabel={monthLabel}
                  monthOpacity={monthOpacity}
                  onNoteHover={onNoteHover}
                  onNoteLeave={onNoteLeave}
                  cursor={cursor}
                  dragState={dragState}
                  onCellMouseDown={onCellMouseDown}
                  onCellMouseEnter={onCellMouseEnter}
                  onCellMouseUp={onCellMouseUp}
                  onCellClick={onCellClick}
                  onEdgeDragStart={onEdgeDragStart}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
