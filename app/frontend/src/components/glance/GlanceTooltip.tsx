
export interface TooltipData {
  laneLabel: string;
  date: string;          // e.g. "Apr 4"
  notes: string[];
  anchorRect: DOMRect;
}

interface GlanceTooltipProps {
  tooltip: TooltipData | null;
}

export function GlanceTooltip({ tooltip }: GlanceTooltipProps) {
  if (!tooltip) return null;

  // Position above the anchor cell, centered horizontally
  const left = tooltip.anchorRect.left + tooltip.anchorRect.width / 2;
  const top = tooltip.anchorRect.top + window.scrollY - 8;

  return (
    <div
      style={{
        position: 'absolute',
        top,
        left,
        transform: 'translate(-50%, -100%)',
        background: '#2C2C2A',
        color: '#F1EFE8',
        borderRadius: '4px',
        padding: '6px 9px',
        pointerEvents: 'none',
        zIndex: 200,
        maxWidth: '240px',
        whiteSpace: 'pre-wrap',
        boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
      }}
    >
      <div style={{ fontSize: '11px', fontWeight: 500, marginBottom: '3px' }}>
        {tooltip.laneLabel} · {tooltip.date}
      </div>
      {tooltip.notes.map((n, i) => (
        <div key={i} style={{ fontSize: '11px', opacity: 0.85 }}>
          {n}
        </div>
      ))}
    </div>
  );
}
