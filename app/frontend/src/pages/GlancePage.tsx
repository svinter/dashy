import React, { useState, useRef, useCallback } from 'react';
import { useGlanceData } from '../hooks/useGlanceData';
import { GlanceGrid } from '../components/glance/GlanceGrid';
import { GlanceTooltip } from '../components/glance/GlanceTooltip';
import type { TooltipData } from '../components/glance/GlanceTooltip';
import type { LaneId } from '../components/glance/LaneRow';

// ---------------------------------------------------------------------------
// Lane config
// ---------------------------------------------------------------------------

const LANE_CONFIG: { id: LaneId; controlLabel: string }[] = [
  { id: 'gcal',        controlLabel: 'gcal overlay' },
  { id: 'york',        controlLabel: 'york house' },
  { id: 'fam_events',  controlLabel: 'family events' },
  { id: 'fam_travel',  controlLabel: 'family travel' },
  { id: 'steve_events',controlLabel: 'my events' },
  { id: 'steve_travel',controlLabel: 'my travel' },
];

const DEFAULT_VISIBLE_LANES: Set<LaneId> = new Set([
  'york', 'fam_events', 'fam_travel', 'steve_events', 'steve_travel',
]);

const DEFAULT_VISIBLE_MEMBERS: Set<string> = new Set(['pgv', 'kpv', 'ovinters']);

// ---------------------------------------------------------------------------
// Member swatch colors (hardcoded to avoid extra fetch dependency in state init)
// ---------------------------------------------------------------------------

const MEMBER_SWATCHES: Record<string, { label: string; color: string }> = {
  pgv:      { label: 'PGV',      color: '#F4C0D1' },
  kpv:      { label: 'KPV',      color: '#9FE1CB' },
  ovinters: { label: 'OVinters', color: '#FAC775' },
};

// ---------------------------------------------------------------------------
// GlancePage
// ---------------------------------------------------------------------------

export function GlancePage() {
  const { weeksData, isLoading, error } = useGlanceData(12);

  const [visibleLanes, setVisibleLanes] = useState<Set<LaneId>>(new Set(DEFAULT_VISIBLE_LANES));
  const [visibleMembers, setVisibleMembers] = useState<Set<string>>(new Set(DEFAULT_VISIBLE_MEMBERS));
  const [mode, setMode] = useState<'vertical' | 'horizontal'>('vertical');
  const [tooltip, setTooltip] = useState<TooltipData | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const toggleLane = (id: LaneId) => {
    setVisibleLanes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleMember = (id: string) => {
    setVisibleMembers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleNoteHover = useCallback(
    (e: React.MouseEvent, laneLabel: string, date: string, notes: string[]) => {
      const target = e.currentTarget as HTMLElement;
      const rect = target.getBoundingClientRect();
      setTooltip({ laneLabel, date, notes, anchorRect: rect });
    },
    [],
  );

  const handleNoteLeave = useCallback(() => {
    setTooltip(null);
  }, []);

  if (error) {
    return (
      <div style={{ padding: '24px', color: 'var(--color-text-secondary)' }}>
        Error loading Glance data.
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ position: 'relative', padding: '0 16px 40px' }}>
      {/* Page header */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '12px', paddingTop: '16px' }}>
        <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Glance</h1>
        {isLoading && (
          <span style={{ fontSize: '12px', color: 'var(--color-text-light)' }}>loading…</span>
        )}
      </div>

      {/* Control bar */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '8px 16px',
          alignItems: 'center',
          marginBottom: '10px',
          fontSize: '11px',
          color: 'var(--color-text-secondary)',
        }}
      >
        {/* Lane toggles */}
        <span style={{ opacity: 0.5, marginRight: '2px' }}>lanes:</span>
        {LANE_CONFIG.map(({ id, controlLabel }) => (
          <label key={id} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={visibleLanes.has(id)}
              onChange={() => toggleLane(id)}
              style={{ margin: 0 }}
            />
            {controlLabel}
          </label>
        ))}

        <span style={{ opacity: 0.3 }}>|</span>

        {/* Member toggles */}
        <span style={{ opacity: 0.5, marginRight: '2px' }}>show:</span>
        {Object.entries(MEMBER_SWATCHES).map(([id, { label, color }]) => (
          <label key={id} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={visibleMembers.has(id)}
              onChange={() => toggleMember(id)}
              style={{ margin: 0 }}
            />
            <span
              style={{
                display: 'inline-block',
                width: '8px',
                height: '8px',
                borderRadius: '2px',
                background: color,
                flexShrink: 0,
              }}
            />
            {label}
          </label>
        ))}

        <span style={{ opacity: 0.3 }}>|</span>

        {/* Mode toggle */}
        <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
          <input
            type="radio"
            name="glance-mode"
            checked={mode === 'vertical'}
            onChange={() => setMode('vertical')}
            style={{ margin: 0 }}
          />
          vertical
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
          <input
            type="radio"
            name="glance-mode"
            checked={mode === 'horizontal'}
            onChange={() => setMode('horizontal')}
            style={{ margin: 0 }}
          />
          horizontal
        </label>
      </div>

      {/* Grid or placeholder */}
      {mode === 'horizontal' ? (
        <div
          style={{
            padding: '24px',
            textAlign: 'center',
            color: 'var(--color-text-light)',
            fontSize: '13px',
            border: '1px dashed #ccc',
            borderRadius: '4px',
          }}
        >
          Horizontal mode — coming soon
        </div>
      ) : (
        <GlanceGrid
          weeksData={weeksData}
          visibleLanes={visibleLanes}
          visibleMembers={visibleMembers}
          onNoteHover={handleNoteHover}
          onNoteLeave={handleNoteLeave}
        />
      )}

      {/* Tooltip rendered at page level to avoid z-index issues */}
      <GlanceTooltip tooltip={tooltip} />
    </div>
  );
}
