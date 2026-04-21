import React from 'react';
import type { GlanceDayData } from '../../hooks/useGlanceData';
import { DateStrip } from './DateStrip';
import { LaneRow } from './LaneRow';
import type { LaneId } from './LaneRow';
import type { DragState, CursorCell } from '../../pages/GlancePage';

const MONTH_RGB: Record<number, [number, number, number]> = {
  1:  [220, 210, 185],
  2:  [200, 185, 220],
  3:  [210, 195, 160],
  4:  [180, 175, 220],
  5:  [195, 200, 140],
  6:  [160, 190, 220],
  7:  [185, 215, 170],
  8:  [220, 200, 160],
  9:  [170, 195, 220],
  10: [220, 185, 160],
  11: [190, 175, 215],
  12: [175, 210, 205],
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

export function GlanceWeek({
  week,
  dayData,
  visibleLanes,
  visibleMembers,
  monthLabel,
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
}: GlanceWeekProps) {
  const firstDay = week[0] ?? new Date();
  const monthNum = firstDay.getMonth() + 1;
  const rgb = MONTH_RGB[monthNum] ?? [250, 250, 248];
  const monthBg = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${monthOpacity / 100})`;

  return (
    <>
      <DateStrip week={week} monthBg={monthBg} monthLabel={monthLabel} dayData={dayData} visibleLanes={visibleLanes} />
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
