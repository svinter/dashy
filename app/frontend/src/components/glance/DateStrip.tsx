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

  // Borders applied per-cell (not on <tr>) so the month column stays border-free.
  const cellBorder: React.CSSProperties = {
    borderTop: 'var(--glance-line-bold)',
    borderBottom: 'var(--glance-line-hairline)',
  };

  // Month tinting: for rgba months, overlay the tint on top of the gray band.
  // For hex months, the hex IS the tinted color — use it directly.
  const isMonthRgba = monthBg.startsWith('rgba');
  const weekdayStripBg: React.CSSProperties = isMonthRgba
    ? { backgroundColor: DATE_STRIP_WEEKDAY_BG, backgroundImage: `linear-gradient(${monthBg}, ${monthBg})` }
    : { backgroundColor: monthBg };
  const weekendStripBg: React.CSSProperties = isMonthRgba
    ? { backgroundColor: DATE_STRIP_WEEKEND_BG, backgroundImage: `linear-gradient(${monthBg}, ${monthBg})` }
    : { backgroundColor: DATE_STRIP_WEEKEND_BG };

  return (
    <tr>
      {/* Month column — gray band + month tint, bold black label */}
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
