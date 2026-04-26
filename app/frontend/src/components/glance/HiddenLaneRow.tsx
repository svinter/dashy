import type { GlanceDayData } from '../../hooks/useGlanceData';
import type { LaneId } from './LaneRow';

// Per-lane canonical dot colors
const LANE_DOT_COLOR: Record<string, string> = {
  gcal:        '#888',
  york:        '#97C35B',
  fam_events:  '#F4C0D1',
  fam_travel:  '#B5D4F4',
  steve_events:'#aaa',
  steve_travel:'#B5D4F4',
};

function localIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

interface HiddenLaneRowProps {
  week: Date[];
  dayData: Record<string, GlanceDayData>;
  visibleLanes: Set<LaneId>;
  visibleMembers: Set<string>;
  monthBg: string;
}

export function HiddenLaneRow({ week, dayData, visibleLanes, visibleMembers: _visibleMembers, monthBg }: HiddenLaneRowProps) {
  // Find hidden lanes that have any content this week
  const hiddenLanesWithContent = new Set<string>();

  for (const d of week) {
    const ds = localIso(d);
    const data = dayData[ds];
    if (!data) continue;

    for (const trip of data.trips) {
      if (!visibleLanes.has(trip.lane as LaneId)) {
        hiddenLanesWithContent.add(trip.lane);
      }
    }
    for (const entry of data.entries) {
      if (!visibleLanes.has(entry.lane as LaneId)) {
        hiddenLanesWithContent.add(entry.lane);
      }
    }
  }

  if (hiddenLanesWithContent.size === 0) return null;

  return (
    <tr style={{ height: '6px' }}>
      {/* lane-label col */}
      <td style={{ background: monthBg, padding: 0 }} />
      {/* day cols */}
      {week.map((d) => {
        const ds = localIso(d);
        const data = dayData[ds];

        // Collect hidden lane dots for this day
        const dots: string[] = [];
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

        return (
          <td key={ds} style={{ background: monthBg, padding: '0 2px', textAlign: 'center', verticalAlign: 'middle' }}>
            {dots.map((lane) => (
              <span
                key={lane}
                title={lane}
                style={{
                  display: 'inline-block',
                  width: '4px',
                  height: '4px',
                  borderRadius: '50%',
                  background: LANE_DOT_COLOR[lane] ?? '#ccc',
                  margin: '0 1px',
                  verticalAlign: 'middle',
                }}
              />
            ))}
          </td>
        );
      })}
      {/* comment col */}
      <td style={{ background: monthBg, padding: 0 }} />
    </tr>
  );
}
