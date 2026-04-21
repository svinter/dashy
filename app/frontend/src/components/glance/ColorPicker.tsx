import React, { useState } from 'react';

export interface ColorData {
  h: number;
  s: number;
  tint: number;
  opacity: number;
}

export function computeColor(h: number, s: number, tint: number, opacity: number) {
  const l = 95 - (tint / 100) * 45;
  const bg = `hsla(${h}, ${s}%, ${l}%, ${opacity / 100})`;
  const text = `hsla(${h}, ${s}%, 25%, 1)`;
  return { bg, text };
}

const SWATCHES: Array<{ h: number; s: number; label: string }> = [
  { h: 16,  s: 70, label: 'coral'  },
  { h: 38,  s: 75, label: 'amber'  },
  { h: 100, s: 55, label: 'green'  },
  { h: 168, s: 60, label: 'teal'   },
  { h: 210, s: 65, label: 'blue'   },
  { h: 258, s: 60, label: 'purple' },
  { h: 330, s: 60, label: 'pink'   },
  { h: 30,  s: 8,  label: 'gray'   },
];

const SWATCH_SIZE = 26;
const LABEL_W = 52;

interface ColorPickerProps {
  value: ColorData | null;
  onChange: (color: ColorData | null) => void;
}

export function ColorPicker({ value, onChange }: ColorPickerProps) {
  const [tint, setTint]       = useState(value?.tint    ?? 60);
  const [opacity, setOpacity] = useState(value?.opacity ?? 85);
  const activeH = value?.h ?? null;
  const activeS = value?.s ?? null;
  const disabled = value === null;

  function selectSwatch(h: number, s: number) {
    onChange({ h, s, tint, opacity });
  }

  function clearColor() {
    onChange(null);
  }

  function handleTint(v: number) {
    setTint(v);
    if (value) onChange({ ...value, tint: v });
  }

  function handleOpacity(v: number) {
    setOpacity(v);
    if (value) onChange({ ...value, opacity: v });
  }

  const previewBg   = value ? computeColor(value.h, value.s, tint, opacity).bg   : 'transparent';
  const previewText = value ? computeColor(value.h, value.s, tint, opacity).text : '#999';
  const previewBorder = value ? 'none' : '1px solid rgba(0,0,0,0.15)';

  return (
    <div style={{ marginBottom: '12px' }}>
      {/* Row 1: swatch row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
        <span style={{ width: LABEL_W, fontSize: '12px', fontWeight: 500, flexShrink: 0 }}>color</span>
        <div style={{ display: 'flex', gap: '7px', alignItems: 'center', flexWrap: 'wrap' }}>
          {/* No-color swatch */}
          <button
            type="button"
            title="no color"
            onClick={clearColor}
            style={{
              width: SWATCH_SIZE, height: SWATCH_SIZE, borderRadius: '50%',
              border: disabled ? '2px solid var(--color-text-primary, #111)' : '1.5px solid rgba(0,0,0,0.25)',
              background: 'none', cursor: 'pointer', padding: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <svg width={SWATCH_SIZE - 4} height={SWATCH_SIZE - 4} viewBox="0 0 22 22">
              <line x1="3" y1="3" x2="19" y2="19" stroke="rgba(0,0,0,0.35)" strokeWidth="1.5" />
            </svg>
          </button>

          {/* Color swatches */}
          {SWATCHES.map(({ h, s, label }) => {
            const { bg } = computeColor(h, s, 60, 1);
            const isActive = activeH === h && activeS === s;
            return (
              <button
                key={label}
                type="button"
                title={label}
                onClick={() => selectSwatch(h, s)}
                style={{
                  width: SWATCH_SIZE, height: SWATCH_SIZE, borderRadius: '50%',
                  background: bg,
                  border: isActive ? '2px solid var(--color-text-primary, #111)' : '1.5px solid rgba(0,0,0,0.1)',
                  cursor: 'pointer', padding: 0, flexShrink: 0,
                }}
              />
            );
          })}
        </div>
      </div>

      {/* Rows 2-3: sliders */}
      <div style={{ opacity: disabled ? 0.3 : 1, pointerEvents: disabled ? 'none' : 'auto' }}>
        {/* Tint */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
          <span style={{ width: LABEL_W, fontSize: '12px', fontWeight: 500, flexShrink: 0 }}>tint</span>
          <input
            type="range" min={0} max={100} value={tint}
            onChange={(e) => handleTint(Number(e.target.value))}
            style={{ flex: 1 }}
          />
          <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', width: '28px', textAlign: 'right' }}>{tint}</span>
        </div>

        {/* Opacity */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
          <span style={{ width: LABEL_W, fontSize: '12px', fontWeight: 500, flexShrink: 0 }}>opacity</span>
          <input
            type="range" min={20} max={100} value={opacity}
            onChange={(e) => handleOpacity(Number(e.target.value))}
            style={{ flex: 1 }}
          />
          <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', width: '28px', textAlign: 'right' }}>{opacity}</span>
        </div>
      </div>

      {/* Preview */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Pill preview */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ width: LABEL_W, fontSize: '11px', color: 'var(--color-text-muted)', flexShrink: 0 }}>event</span>
          <div style={{
            height: '24px', borderRadius: '3px', padding: '0 8px',
            background: previewBg, color: previewText,
            border: previewBorder,
            display: 'flex', alignItems: 'center',
            fontSize: '10px', fontWeight: 500, whiteSpace: 'nowrap',
          }}>
            event
          </div>
        </div>
        {/* Trip bar preview */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', flexShrink: 0 }}>trip</span>
          <div style={{ height: '24px', width: '72px', display: 'flex', flexDirection: 'row' }}>
            <div style={{ width: '25%', background: 'rgba(0,0,0,0.04)' }} />
            <div style={{ width: '50%', background: previewBg, border: previewBorder, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ fontSize: '9px', color: previewText }}>·</span>
            </div>
            <div style={{ width: '25%', background: 'rgba(0,0,0,0.04)' }} />
          </div>
        </div>
      </div>
    </div>
  );
}
