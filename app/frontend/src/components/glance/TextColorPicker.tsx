import React from 'react';

const LABEL_W = 52;
const SWATCH_SIZE = 20;

const TEXT_COLORS: Array<{ value: string; label: string }> = [
  { value: '#000000', label: 'black' },
  { value: '#FF0000', label: 'red' },
  { value: '#0000FF', label: 'blue' },
  { value: '#FFFFFF', label: 'white' },
];

interface TextColorPickerProps {
  value: string | null;
  onChange: (color: string | null) => void;
}

export function TextColorPicker({ value, onChange }: TextColorPickerProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
      <span style={{ width: LABEL_W, fontSize: '12px', fontWeight: 500, flexShrink: 0 }}>text</span>
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
        {/* No-color / default (slash) swatch */}
        <button
          type="button"
          title="default"
          onClick={() => onChange(null)}
          style={{
            width: SWATCH_SIZE, height: SWATCH_SIZE, borderRadius: '50%',
            border: value === null
              ? '2px solid var(--color-text-primary, #111)'
              : '1.5px solid rgba(0,0,0,0.25)',
            background: 'none', cursor: 'pointer', padding: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <svg width={SWATCH_SIZE - 4} height={SWATCH_SIZE - 4} viewBox="0 0 16 16">
            <line x1="2" y1="2" x2="14" y2="14" stroke="rgba(0,0,0,0.35)" strokeWidth="1.5" />
          </svg>
        </button>

        {/* Color swatches */}
        {TEXT_COLORS.map(({ value: colorVal, label }) => {
          const isActive = value === colorVal;
          const isWhite = colorVal === '#FFFFFF';
          return (
            <button
              key={colorVal}
              type="button"
              title={label}
              onClick={() => onChange(colorVal)}
              style={{
                width: SWATCH_SIZE, height: SWATCH_SIZE, borderRadius: '50%',
                background: colorVal,
                border: isActive
                  ? '2px solid var(--color-text-primary, #111)'
                  : isWhite
                  ? '1.5px solid rgba(0,0,0,0.25)'
                  : '1.5px solid rgba(0,0,0,0.1)',
                cursor: 'pointer', padding: 0, flexShrink: 0,
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
