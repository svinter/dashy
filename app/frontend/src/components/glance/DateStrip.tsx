import React from 'react';

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

interface DateStripProps {
  week: Date[];
  monthBg: string;
  monthLabel: string | null; // e.g. "April 2026" — only on first week of month
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

export function DateStrip({ week, monthBg, monthLabel }: DateStripProps) {
  const weekNum = week[0] ? isoWeekNumber(week[0]) : 0;

  return (
    <tr style={{ borderTop: 'var(--glance-line-bold)', borderBottom: 'var(--glance-line-hairline)' }}>
      {/* Month column */}
      <td
        style={{
          background: monthBg,
          verticalAlign: 'middle',
          padding: '0 4px',
          fontSize: '9px',
          lineHeight: 1.2,
          color: 'var(--color-text-tertiary, #999)',
        }}
      >
        {monthLabel}
      </td>

      {/* Week-number / lane-label column — same styling as date strip */}
      <td
        style={{
          ...DATE_STRIP_FONT,
          background: DATE_STRIP_WEEKDAY_BG,
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
        return (
          <td
            key={ds}
            style={{
              ...DATE_STRIP_FONT,
              background: weekend ? DATE_STRIP_WEEKEND_BG : DATE_STRIP_WEEKDAY_BG,
              outline: isToday ? '1.5px solid #D85A30' : undefined,
              outlineOffset: isToday ? '-1px' : undefined,
            }}
          >
            <span style={{ opacity: isToday ? 0.4 : 1, display: 'block', textAlign: 'center' }}>
              {dayNum}
            </span>
          </td>
        );
      })}
    </tr>
  );
}
