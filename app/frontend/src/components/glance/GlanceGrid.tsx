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

  // Year shown in column-1 header: year of the first week's Thursday
  const headerYear = weeks.length > 0
    ? (weeks[0][3] ?? weeks[0][0]).getFullYear()
    : new Date().getFullYear();

  // Track which months have already shown their label
  const seenMonths = new Set<string>();

  return (
    <table
      className="glance-table"
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
        <tr>
          {/* Month column header — no border */}
          <th style={{ fontWeight: 400, fontSize: '10px', color: 'var(--color-text-tertiary, #999)', textAlign: 'left', padding: '4px 4px' }}>
            {headerYear}
          </th>
          <th style={{ fontWeight: 400, fontSize: '10px', color: 'var(--color-text-tertiary, #999)', textAlign: 'right', paddingRight: '6px', borderBottom: 'var(--glance-line-bold)' }}>
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
                borderBottom: 'var(--glance-line-bold)',
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
            monthLabel = MONTH_FULL[firstDay.getMonth()];
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
