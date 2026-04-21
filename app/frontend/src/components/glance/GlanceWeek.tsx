import React from 'react';
import type { GlanceDayData } from '../../hooks/useGlanceData';
import { DateStrip } from './DateStrip';
import { LaneRow } from './LaneRow';
import { HiddenLaneRow } from './HiddenLaneRow';
import type { LaneId } from './LaneRow';
import type { DragState, CursorCell } from '../../pages/GlancePage';

const MONTH_COLORS: Record<number, string> = {
  1:  '#FDFCF8', 2:  '#FAF8FC', 3:  'rgba(210, 195, 160, 0.04)',
  4:  'rgba(180, 175, 220, 0.04)', 5:  'rgba(195, 200, 140, 0.04)', 6:  'rgba(160, 190, 220, 0.04)',
  7:  '#F5FAF3', 8:  '#FDF8F0', 9:  '#F5F8FC',
  10: '#FCF7F3', 11: '#F8F5FB', 12: '#F3FCF9',
};

const ALL_LANES: { id: LaneId; label: string }[] = [
  { id: 'gcal',        label: 'calendar' },
  { id: 'york',        label: 'york' },
  { id: 'fam_events',  label: 'family' },
  { id: 'fam_travel',  label: 'travel' },
  { id: 'steve_events',label: 'my events' },
  { id: 'steve_travel',label: 'my travel' },
];

interface GlanceWeekProps {
  week: Date[];
  dayData: Record<string, GlanceDayData>;
  visibleLanes: Set<LaneId>;
  visibleMembers: Set<string>;
  monthLabel: string | null;
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

export function GlanceWeek({
  week,
  dayData,
  visibleLanes,
  visibleMembers,
  monthLabel,
  onNoteHover,
  onNoteLeave,
  cursor,
  dragState,
  onCellMouseDown,
  onCellMouseEnter,
  onCellMouseUp,
  onCellClick,
  onEdgeDragStart,
}: GlanceWeekProps) {
  const firstDay = week[0] ?? new Date();
  const monthNum = firstDay.getMonth() + 1;
  const monthBg = MONTH_COLORS[monthNum] ?? '#FAFAF8';

  return (
    <>
      <DateStrip week={week} monthBg={monthBg} monthLabel={monthLabel} />
      <HiddenLaneRow week={week} dayData={dayData} visibleLanes={visibleLanes} visibleMembers={visibleMembers} monthBg={monthBg} />
      {ALL_LANES.filter((l) => visibleLanes.has(l.id)).map((lane) => (
        <LaneRow
          key={lane.id}
          laneId={lane.id}
          laneLabel={lane.label}
          week={week}
          dayData={dayData}
          monthBg={monthBg}
          visibleMembers={visibleMembers}
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
      ))}
    </>
  );
}
