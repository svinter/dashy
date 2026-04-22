import React from 'react';
import type { GlanceDayData } from '../../hooks/useGlanceData';
import { DateStrip } from './DateStrip';
import { LaneRow } from './LaneRow';
import type { LaneId } from './LaneRow';
import type { DragState, CursorCell } from '../../pages/GlancePage';

// Exported so LaneRow can use the same palette for per-cell coloring
export const MONTH_RGB: Record<number, [number, number, number]> = {
  1:  [220, 200, 180],  // Jan — warm beige
  2:  [200, 180, 220],  // Feb — soft purple
  3:  [220, 195, 150],  // Mar — warm sand (more yellow than May)
  4:  [170, 180, 230],  // Apr — periwinkle blue
  5:  [160, 210, 170],  // May — sage green (clearly green)
  6:  [150, 200, 230],  // Jun — sky blue
  7:  [230, 190, 150],  // Jul — peach
  8:  [230, 210, 150],  // Aug — golden
  9:  [180, 220, 210],  // Sep — seafoam
  10: [230, 170, 150],  // Oct — terracotta
  11: [190, 170, 220],  // Nov — lavender
  12: [160, 210, 200],  // Dec — teal
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
  return (
    <>
      {/* DateStrip no longer takes monthBg — always renders gray */}
      <DateStrip week={week} monthLabel={monthLabel} dayData={dayData} visibleLanes={visibleLanes} />
      {ALL_LANES.filter((l) => visibleLanes.has(l.id)).map((lane) => (
        <LaneRow
          key={lane.id}
          laneId={lane.id}
          laneLabel={lane.label}
          week={week}
          dayData={dayData}
          monthOpacity={monthOpacity}
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
