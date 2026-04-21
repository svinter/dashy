import React from 'react';
import type { GlanceDayData } from '../../hooks/useGlanceData';
import type { LaneId } from './LaneRow';

function isoWeekNumber(d: Date): number {
  const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = utc.getUTCDay() || 7;
  utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  return Math.ceil((((utc.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
}

function isWeekend(d: Date): boolean {
  const dow = d.getDay();
  return dow === 0 || dow === 6;
}

function localIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

const TODAY_STR = localIso(new Date());

const LANE_DOT_COLOR: Record<string, string> = {
  gcal:         '#888',
  york:         '#97C459',
  fam_events:   '#9FE1CB',
  fam_travel:   '#9FE1CB',
  steve_events: '#aaa',
  steve_travel: '#B5D4F4',
};

interface DateStripProps {
  week: Date[];
  monthBg: string;
  monthLabel: string | null;
  dayData?: Record<string, GlanceDayData>;
  visibleLanes?: Set<LaneId>;
}

const DATE_STRIP_WEEKDAY_BG = '#EFEEEA';
const DATE_STRIP_WEEKEND_BG = '#E8E6E0';
const DATE_STRIP_FONT: React.CSSProperties = {
  fontSize: '11px',
  fontWeight: 500,
  color: '#4a4944',
  height: '20px',
  lineHeight: '20px',
  textAlign: 'center',
  boxSizing: 'border-box',
};

export function DateStrip({ week, monthBg, monthLabel, dayData, visibleLanes }: DateStripProps) {
  const weekNum = week[0] ? isoWeekNumber(week[0]) : 0;

  const cellBorder: React.CSSProperties = {
    borderTop: 'var(--glance-line-bold)',
    borderBottom: 'var(--glance-line-hairline)',
  };

  const isMonthRgba = monthBg.startsWith('rgba');
  const weekdayStripBg: React.CSSProperties = isMonthRgba
    ? { backgroundColor: DATE_STRIP_WEEKDAY_BG, backgroundImage: `linear-gradient(${monthBg}, ${monthBg})` }
    : { backgroundColor: monthBg };
  const weekendStripBg: React.CSSProperties = isMonthRgba
    ? { backgroundColor: DATE_STRIP_WEEKEND_BG, backgroundImage: `linear-gradient(${monthBg}, ${monthBg})` }
    : { backgroundColor: DATE_STRIP_WEEKEND_BG };

  return (
    <tr>
      {/* Month column */}
      <td
        style={{
          ...cellBorder,
          ...weekdayStripBg,
          verticalAlign: 'middle',
          padding: '0 4px',
          fontSize: '9px',
          fontWeight: 500,
          lineHeight: 1.2,
          color: 'var(--color-text, #111)',
          boxSizing: 'border-box',
        }}
      >
        {monthLabel}
      </td>

      {/* Week-number cell */}
      <td
        style={{
          ...DATE_STRIP_FONT,
          ...cellBorder,
          ...weekdayStripBg,
          fontSize: '10px',
          color: '#7a7870',
          paddingRight: '4px',
          textAlign: 'right',
        }}
      >
        week {weekNum}
      </td>

      {/* Seven day cells */}
      {week.map((d) => {
        const ds = localIso(d);
        const weekend = isWeekend(d);
        const isToday = ds === TODAY_STR;
        const dayNum = d.getDate();

        // Collect hidden-lane dots for this day
        const dots: string[] = [];
        if (dayData && visibleLanes) {
          const data = dayData[ds];
          if (data) {
            for (const trip of data.trips) {
              if (!visibleLanes.has(trip.lane as LaneId) && !dots.includes(trip.lane)) {
                dots.push(trip.lane);
              }
            }
            for (const entry of data.entries) {
              if (!visibleLanes.has(entry.lane as LaneId) && !dots.includes(entry.lane)) {
                dots.push(entry.lane);
              }
            }
          }
        }

        return (
          <td
            key={ds}
            style={{
              ...DATE_STRIP_FONT,
              ...cellBorder,
              ...(weekend ? weekendStripBg : weekdayStripBg),
              outline: isToday ? '1.5px solid #D85A30' : undefined,
              outlineOffset: isToday ? '-1px' : undefined,
              borderLeft: dayNum === 1 ? '2px solid rgba(0,0,0,0.35)' : undefined,
              position: 'relative',
            }}
          >
            <span style={{ opacity: isToday ? 0.4 : 1, display: 'block', textAlign: 'center' }}>
              {dayNum}
            </span>
            {dots.length > 0 && (
              <div style={{
                position: 'absolute', top: 2, right: 2,
                display: 'flex', flexDirection: 'column', gap: '1px',
                pointerEvents: 'none',
              }}>
                {dots.slice(0, 3).map((lane) => (
                  <span
                    key={lane}
                    title={lane}
                    style={{
                      display: 'block',
                      width: 4, height: 4,
                      borderRadius: '50%',
                      background: LANE_DOT_COLOR[lane] ?? '#ccc',
                    }}
                  />
                ))}
              </div>
            )}
          </td>
        );
      })}

      {/* Comment column — empty in date strip */}
      <td
        style={{
          ...cellBorder,
          ...weekdayStripBg,
          boxSizing: 'border-box',
        }}
      />
    </tr>
  );
}
