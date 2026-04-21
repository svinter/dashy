import React from 'react';
import type { GlanceWeeksData } from '../../hooks/useGlanceData';
import { useGlanceWeeks } from '../../hooks/useGlanceData';
import { GlanceWeek } from './GlanceWeek';
import type { LaneId } from './LaneRow';

const DAY_HEADERS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_FULL = ['January','February','March','April','May','June',
                    'July','August','September','October','November','December'];

interface GlanceGridProps {
  weeksData: GlanceWeeksData;
  visibleLanes: Set<LaneId>;
  visibleMembers: Set<string>;
  onNoteHover: (e: React.MouseEvent, laneLabel: string, date: string, notes: string[]) => void;
  onNoteLeave: () => void;
}

export function GlanceGrid({
  weeksData,
  visibleLanes,
  visibleMembers,
  onNoteHover,
  onNoteLeave,
}: GlanceGridProps) {
  const weeks = useGlanceWeeks(weeksData);

  // Track which months have already shown their label
  const seenMonths = new Set<string>();

  return (
    <table
      style={{
        tableLayout: 'fixed',
        width: '100%',
        borderCollapse: 'collapse',
        borderSpacing: 0,
      }}
    >
      <colgroup>
        {/* Month column */}
        <col style={{ width: '46px' }} />
        {/* Lane-label column */}
        <col style={{ width: '66px' }} />
        {/* Seven day columns */}
        {DAY_HEADERS.map((d) => (
          <col key={d} style={{ width: 'calc((100% - 112px) / 7)' }} />
        ))}
      </colgroup>

      <thead>
        <tr style={{ borderBottom: 'var(--glance-line-bold)' }}>
          <th style={{ fontWeight: 400, fontSize: '10px', color: 'var(--color-text-tertiary, #999)', textAlign: 'left', padding: '4px 4px' }}>
            month
          </th>
          <th style={{ fontWeight: 400, fontSize: '10px', color: 'var(--color-text-tertiary, #999)', textAlign: 'right', paddingRight: '6px' }}>
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
              }}
            >
              {d}
            </th>
          ))}
        </tr>
      </thead>

      <tbody>
        {weeks.map((week, wi) => {
          const firstDay = week[0];
          const monthKey = `${firstDay.getFullYear()}-${firstDay.getMonth()}`;
          let monthLabel: string | null = null;

          if (!seenMonths.has(monthKey)) {
            seenMonths.add(monthKey);
            monthLabel = `${MONTH_FULL[firstDay.getMonth()]} ${firstDay.getFullYear()}`;
          }

          return (
            <GlanceWeek
              key={wi}
              week={week}
              dayData={weeksData}
              visibleLanes={visibleLanes}
              visibleMembers={visibleMembers}
              monthLabel={monthLabel}
              onNoteHover={onNoteHover}
              onNoteLeave={onNoteLeave}
            />
          );
        })}
      </tbody>
    </table>
  );
}
