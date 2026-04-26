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

const LANE_DOT_COLOR: Record<string, string> = {
  gcal:         '#888',
  york:         '#97C35B',
  fam_events:   '#9FE1CB',
  fam_travel:   '#9FE1CB',
  steve_events: '#aaa',
  steve_travel: '#B5D4F4',
};

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function isLastDayOfMonth(d: Date): boolean {
  const next = new Date(d);
  next.setDate(next.getDate() + 1);
  return next.getDate() === 1;
}

interface DateStripProps {
  week: Date[];
  dayData?: Record<string, GlanceDayData>;
  visibleLanes?: Set<LaneId>;
}

// Date strip always uses fixed grays — never month tint
const DATE_STRIP_WEEKDAY_BG = '#EFEEEA';
const DATE_STRIP_WEEKEND_BG = '#E8E6E0';
export const DATE_STRIP_HEIGHT = 20;
const DATE_STRIP_FONT: React.CSSProperties = {
  fontSize: '11px',
  fontWeight: 500,
  color: '#4a4944',
  height: DATE_STRIP_HEIGHT,
  lineHeight: `${DATE_STRIP_HEIGHT}px`,
  textAlign: 'center',
  boxSizing: 'border-box',
};

const cellBorder: React.CSSProperties = {
  borderTop: 'var(--glance-line-bold)',
  borderBottom: 'var(--glance-line-hairline)',
};

export function DateStrip({ week, dayData, visibleLanes }: DateStripProps) {
  const weekNum = week[0] ? isoWeekNumber(week[0]) : 0;

  return (
    <tr>
      {/* Lane-label column — sticky left; shows ISO week number */}
      <td
        style={{
          ...DATE_STRIP_FONT,
          ...cellBorder,
          backgroundColor: DATE_STRIP_WEEKDAY_BG,
          fontSize: '10px',
          color: '#7a7870',
          paddingRight: '4px',
          textAlign: 'right',
          position: 'sticky',
          left: 0,
          zIndex: 4,
          verticalAlign: 'middle',
        }}
      >
        week {weekNum}
      </td>

      {/* Seven day cells */}
      {week.map((d) => {
        const ds = localIso(d);
        const weekend = isWeekend(d);
        const today = new Date();
        const isToday = d.getFullYear() === today.getFullYear() &&
                        d.getMonth()    === today.getMonth()    &&
                        d.getDate()     === today.getDate();
        const dayNum = d.getDate();
        const isMonday = d.getDay() === 1;
        const isFirstOfMonth = dayNum === 1;
        const isLastOfMonth = isLastDayOfMonth(d);

        // Priority: today (unchanged) > first of month > last of month > Monday > plain number
        let dateLabel: string;
        let dateColor: string | undefined;
        if (isToday) {
          dateLabel = (isFirstOfMonth || isLastOfMonth || isMonday)
            ? `${MONTH_ABBR[d.getMonth()]} ${dayNum}`
            : `${dayNum}`;
          dateColor = '#D85A30';
        } else if (isFirstOfMonth) {
          dateLabel = `${MONTH_ABBR[d.getMonth()]} ${dayNum}`;
          dateColor = '#D85A30';
        } else if (isLastOfMonth) {
          dateLabel = `${MONTH_ABBR[d.getMonth()]} ${dayNum}`;
          dateColor = '#D85A30';
        } else if (isMonday) {
          dateLabel = `${MONTH_ABBR[d.getMonth()]} ${dayNum}`;
          dateColor = undefined;
        } else {
          dateLabel = `${dayNum}`;
          dateColor = undefined;
        }

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
              backgroundColor: weekend ? DATE_STRIP_WEEKEND_BG : DATE_STRIP_WEEKDAY_BG,
              outline: isToday ? '1.5px solid #D85A30' : undefined,
              outlineOffset: isToday ? '-1px' : undefined,
              borderLeft: dayNum === 1 ? '2px solid rgba(0,0,0,0.35)' : undefined,
              position: 'relative',
            }}
          >
            <span style={{
              display: 'block',
              textAlign: 'center',
              fontSize: (isMonday || isFirstOfMonth || isLastOfMonth) ? '10px' : undefined,
              color: dateColor,
            }}>
              {dateLabel}
            </span>
            {dots.length > 0 && (
              <div style={{
                position: 'absolute', bottom: 2, left: '50%',
                transform: 'translateX(-50%)',
                display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '3px',
                justifyContent: 'center',
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
          backgroundColor: DATE_STRIP_WEEKDAY_BG,
          boxSizing: 'border-box',
        }}
      />
    </tr>
  );
}
