import React, { useState, useEffect } from 'react';
import type { GlanceWeeksData } from '../../hooks/useGlanceData';
import { useGlanceWeeks } from '../../hooks/useGlanceData';
import { GlanceWeek } from './GlanceWeek';
import type { LaneId } from './LaneRow';
import type { DragState, CursorCell } from '../../pages/GlancePage';

const DAY_HEADERS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// 9 columns: lane(66) + 7 day cols + 1 comment col (2× day width)
// 9 units share (100% - 66px): each day col = 1 unit, comment col = 2 units → total 9 units = 100%
const DAY_COL_W = 'calc((100% - 66px) / 9)';
const COMMENT_COL_W = 'calc((100% - 66px) / 9 * 2)';

const TH_BG = 'var(--color-bg, #fffff8)';
const TH_BORDER_BOTTOM = '2px solid rgba(0,0,0,0.35)';

// Shared colgroup for both the header table and the body table.
// Both tables have identical colgroup so their columns align pixel-perfectly.
function Colgroup() {
  return (
    <colgroup>
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
  scrollRef: React.RefObject<HTMLDivElement | null>;
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

  const [headerYear, setHeaderYear] = useState(() =>
    weeks.length > 0 ? (weeks[0][3] ?? weeks[0][0]).getFullYear() : new Date().getFullYear()
  );

  // Reset year to top of page when data changes (page navigation)
  useEffect(() => {
    if (weeks.length > 0) {
      setHeaderYear((weeks[0][3] ?? weeks[0][0]).getFullYear());
    }
  }, [weeks]);

  // Dynamic height: fill from scroll container top to viewport bottom.
  // Use getBoundingClientRect().top + window.scrollY for the absolute document
  // offset so the value is stable regardless of scroll position.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const updateHeight = () => {
      let offsetTop = 0;
      let node: HTMLElement | null = el;
      while (node) { offsetTop += node.offsetTop; node = node.offsetParent as HTMLElement | null; }
      el.style.height = `${window.innerHeight - offsetTop}px`;
    };
    updateHeight();
    window.addEventListener('resize', updateHeight);
    return () => window.removeEventListener('resize', updateHeight);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Year in header tracks the midpoint of the visible scroll area
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || weeks.length === 0) return;
    const handleScroll = () => {
      const midScrollTop = el.scrollTop + el.clientHeight / 2;
      const weekHeight = el.scrollHeight / weeks.length;
      const midWeekIndex = Math.min(Math.floor(midScrollTop / weekHeight), weeks.length - 1);
      const midWeek = weeks[midWeekIndex];
      if (midWeek) setHeaderYear((midWeek[3] ?? midWeek[0]).getFullYear());
    };
    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [weeks, scrollRef]);

  return (
    // Flex column: fixed header + scrollable body below it.
    // overflowY: 'scroll' (not 'auto') ensures the scrollbar is always reserved,
    // keeping the body table the same width as the header table.
    <div style={{ display: 'flex', flexDirection: 'column' }}>

      {/* ── Fixed header table — never scrolls ── */}
      {/* display:block + fontSize:0 collapses inline whitespace without affecting the table's own line heights */}
      <div style={{ overflow: 'hidden', flexShrink: 0, marginBottom: 0, paddingBottom: 0, display: 'block', fontSize: 0 }}>
        <table className="glance-table" style={{ ...TABLE_STYLE, borderSpacing: 0, borderCollapse: 'separate', marginBottom: 0 }}>
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
                borderBottom: TH_BORDER_BOTTOM,
              }}>
                {headerYear}
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
                    borderBottom: TH_BORDER_BOTTOM,
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
                borderBottom: TH_BORDER_BOTTOM,
              }}>
                notes
              </th>
            </tr>
          </thead>
        </table>
      </div>

      {/* ── Scrollable body ── */}
      <div ref={scrollRef} style={{ overflowY: 'scroll', marginTop: 0, paddingTop: 0 }}>
        <table className="glance-table" style={TABLE_STYLE}>
          <Colgroup />
          <tbody>
            {weeks.map((week, wi) => {
              return (
                <GlanceWeek
                  key={wi}
                  week={week}
                  dayData={weeksData}
                  visibleLanes={visibleLanes}
                  visibleMembers={visibleMembers}
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
