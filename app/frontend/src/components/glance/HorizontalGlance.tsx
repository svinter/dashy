/**
 * HorizontalGlance — alternate view mode.
 * Days flow left-to-right; lanes stack top-to-bottom.
 * Cell width: 28px. Lane-label column: 100px sticky left.
 * Month headers span their month's columns, sticky to top.
 * View-only: clicks open the ViewEditPopover, no creation drag.
 */
import React, { useState } from 'react';
import type { GlanceWeeksData, GlanceTripDay, GlanceEntry } from '../../hooks/useGlanceData';
import { useGlanceWeeks } from '../../hooks/useGlanceData';
import type { LaneId } from './LaneRow';
import { ViewEditPopover } from './ViewEditPopover';
import {
  useDeleteGlanceTrip,
  useDeleteGlanceEntry,
} from '../../hooks/useGlanceData';

const ALL_LANES: { id: LaneId; label: string }[] = [
  { id: 'gcal',        label: 'gcal' },
  { id: 'york',        label: 'york' },
  { id: 'fam_events',  label: 'family' },
  { id: 'fam_travel',  label: 'travel' },
  { id: 'steve_events',label: 'my events' },
  { id: 'steve_travel',label: 'my travel' },
];

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

const CELL_W = 28;
const LABEL_W = 100;
const LANE_ROW_HEIGHT = 24;

function localIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function isWeekend(d: Date) {
  const dow = d.getDay();
  return dow === 0 || dow === 6;
}

interface HorizontalGlanceProps {
  weeksData: GlanceWeeksData;
  visibleLanes: Set<LaneId>;
  visibleMembers: Set<string>;
}

interface PopoverState {
  date: string;
  laneId: LaneId;
  laneLabel: string;
  trips: GlanceTripDay[];
  entries: GlanceEntry[];
}

export function HorizontalGlance({ weeksData, visibleLanes, visibleMembers }: HorizontalGlanceProps) {
  const weeks = useGlanceWeeks(weeksData);
  const allDays = weeks.flat();

  const [popover, setPopover] = useState<PopoverState | null>(null);
  const deleteTrip = useDeleteGlanceTrip();
  const deleteEntry = useDeleteGlanceEntry();

  function TODAY_STR() {
    const n = new Date();
    return localIso(n);
  }
  const todayStr = TODAY_STR();

  // Build month spans for header
  const monthSpans: Array<{ label: string; count: number }> = [];
  for (const d of allDays) {
    const label = `${MONTH_ABBR[d.getMonth()]} ${d.getFullYear()}`;
    if (monthSpans.length === 0 || monthSpans[monthSpans.length - 1].label !== label) {
      monthSpans.push({ label, count: 1 });
    } else {
      monthSpans[monthSpans.length - 1].count++;
    }
  }

  function handleCellClick(date: string, laneId: LaneId, laneLabel: string) {
    const data = weeksData[date];
    if (!data) return;
    const trips = data.trips.filter((t) => t.lane === laneId);
    const entries = data.entries.filter((e) => e.lane === laneId);
    if (trips.length === 0 && entries.length === 0) return;
    setPopover({ date, laneId, laneLabel, trips, entries });
  }

  return (
    <div style={{ overflowX: 'auto', position: 'relative' }}>
      <div style={{ minWidth: `${LABEL_W + allDays.length * CELL_W}px` }}>
        {/* Month header row */}
        <div style={{ display: 'flex', position: 'sticky', top: 0, zIndex: 10, background: '#fff' }}>
          <div style={{ width: LABEL_W, flexShrink: 0, fontSize: '10px', fontWeight: 500, padding: '2px 6px', borderBottom: '2px solid rgba(0,0,0,0.25)' }} />
          {monthSpans.map((span, i) => (
            <div
              key={i}
              style={{
                width: span.count * CELL_W,
                flexShrink: 0,
                fontSize: '10px',
                fontWeight: 500,
                padding: '2px 4px',
                borderBottom: '2px solid rgba(0,0,0,0.25)',
                borderLeft: i > 0 ? '1px solid rgba(0,0,0,0.15)' : undefined,
                overflow: 'hidden',
                whiteSpace: 'nowrap',
                color: 'var(--color-text-muted)',
              }}
            >
              {span.label}
            </div>
          ))}
        </div>

        {/* Date number row */}
        <div style={{ display: 'flex', position: 'sticky', top: '22px', zIndex: 9, background: '#EFEEEA' }}>
          <div style={{ width: LABEL_W, flexShrink: 0 }} />
          {allDays.map((d) => {
            const ds = localIso(d);
            const isToday = ds === todayStr;
            return (
              <div
                key={ds}
                style={{
                  width: CELL_W,
                  flexShrink: 0,
                  fontSize: '9px',
                  textAlign: 'center',
                  lineHeight: '18px',
                  height: '18px',
                  color: isToday ? 'var(--color-text-muted)' : '#4a4944',
                  fontWeight: isToday ? 400 : 500,
                  background: isToday ? 'rgba(216,90,48,0.08)' : isWeekend(d) ? '#E8E6E0' : undefined,
                  outline: isToday ? '1.5px solid #D85A30' : undefined,
                  outlineOffset: isToday ? '-1px' : undefined,
                  borderLeft: d.getDate() === 1 ? '2px solid rgba(0,0,0,0.35)' : undefined,
                  boxSizing: 'border-box',
                }}
              >
                {d.getDate()}
              </div>
            );
          })}
        </div>

        {/* Lane rows */}
        {ALL_LANES.filter((l) => visibleLanes.has(l.id)).map((lane) => (
          <div key={lane.id} style={{ display: 'flex', borderTop: '0.5px solid rgba(0,0,0,0.1)' }}>
            {/* Lane label — sticky left */}
            <div
              style={{
                width: LABEL_W,
                flexShrink: 0,
                fontSize: '10px',
                color: 'var(--color-text-tertiary, #999)',
                textAlign: 'right',
                paddingRight: '8px',
                lineHeight: LANE_ROW_HEIGHT + 'px',
                height: LANE_ROW_HEIGHT,
                position: 'sticky',
                left: 0,
                background: '#fff',
                zIndex: 2,
              }}
            >
              {lane.label}
            </div>
            {/* Day cells */}
            {allDays.map((d) => {
              const ds = localIso(d);
              const data = weeksData[ds];
              const trips = (data?.trips ?? []).filter((t) => t.lane === lane.id);
              const entries = (data?.entries ?? []).filter((e) => {
                if (e.lane !== lane.id) return false;
                if (lane.id === 'fam_events' || lane.id === 'fam_travel') {
                  if (e.member_id && !visibleMembers.has(e.member_id)) return false;
                }
                return true;
              });

              const hasContent = trips.length > 0 || entries.length > 0;
              const firstTrip = trips[0];

              let cellContent: React.ReactNode = null;
              if (firstTrip) {
                const bg = firstTrip.location_color_bg ?? '#ccc';
                const fg = firstTrip.location_color_text ?? '#000';
                const glyph = firstTrip.depart ? '→' : firstTrip.return ? '←' : '·';
                cellContent = (
                  <span style={{ fontSize: '9px', color: fg, display: 'block', background: bg, textAlign: 'center', lineHeight: '18px', height: '18px' }} title={`${firstTrip.location_display} ${firstTrip.trip_start}–${firstTrip.trip_end}`}>
                    {glyph}
                  </span>
                );
              } else if (entries.length > 0) {
                const e = entries[0];
                const bg = e.member_color_bg ?? (lane.id === 'york' ? '#97C35B' : undefined);
                cellContent = (
                  <span style={{ display: 'block', background: bg, textAlign: 'center', lineHeight: '18px', height: '18px', fontSize: '8px' }} title={e.label + (e.notes ? '\n' + e.notes : '')}>
                    •
                  </span>
                );
              }

              return (
                <div
                  key={ds}
                  style={{
                    width: CELL_W,
                    height: LANE_ROW_HEIGHT,
                    flexShrink: 0,
                    background: isWeekend(d) ? 'rgba(0,0,0,0.025)' : undefined,
                    borderLeft: d.getDate() === 1 ? '2px solid rgba(0,0,0,0.35)' : undefined,
                    cursor: hasContent ? 'pointer' : 'default',
                    boxSizing: 'border-box',
                  }}
                  onClick={() => handleCellClick(ds, lane.id, lane.label)}
                  title={ds}
                >
                  {cellContent}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {popover && (
        <ViewEditPopover
          date={popover.date}
          laneId={popover.laneId}
          laneLabel={popover.laneLabel}
          trips={popover.trips}
          entries={popover.entries}
          onEditTrip={() => { /* edit not supported in horizontal mode */ setPopover(null); }}
          onEditEntry={() => { setPopover(null); }}
          onDeleteTrip={(id) => { deleteTrip.mutate(id); setPopover(null); }}
          onDeleteEntry={(id) => { deleteEntry.mutate(id); setPopover(null); }}
          onClose={() => setPopover(null)}
        />
      )}
    </div>
  );
}
