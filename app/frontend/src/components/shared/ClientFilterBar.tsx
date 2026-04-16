import { useState, useRef, useEffect, useCallback } from 'react';

// ---------------------------------------------------------------------------
// HelpShortcut + HelpPopover — shared across Coaching and Billing filter bars
// ---------------------------------------------------------------------------

export interface HelpShortcut {
  keys: string;
  description: string;
}

interface HelpPopoverProps {
  title: string;
  shortcuts: HelpShortcut[];
  isOpen: boolean;
  onClose: () => void;
}

export function HelpPopover({ title, shortcuts, isOpen, onClose }: HelpPopoverProps) {
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="help-popover-backdrop" onClick={onClose}>
      <div className="help-popover" onClick={e => e.stopPropagation()}>
        <div className="help-popover-header">
          <span className="help-popover-title">{title}</span>
          <button className="help-popover-close" onClick={onClose}>×</button>
        </div>
        <table className="help-popover-table">
          <tbody>
            {shortcuts.map((s, i) => (
              <tr key={i}>
                <td className="help-popover-keys"><kbd>{s.keys}</kbd></td>
                <td className="help-popover-desc">{s.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FilterItem — base interface for items in any filter bar
// ---------------------------------------------------------------------------

export interface FilterItem {
  type: string;
  id: number | null;
  label: string;
}

// ---------------------------------------------------------------------------
// ClientFilterBar — generic keyboard+chip+autocomplete filter component.
//
// Usage: wrap with a thin module-specific component that provides matchFn.
// The matchFn receives the query text (AFTER the leading '-' is stripped if
// the user is in remove-mode) and returns matching FilterItem[].
// ---------------------------------------------------------------------------

interface ClientFilterBarProps<T extends FilterItem> {
  selection: T[];
  allChip: boolean;
  onSelectionChange: (sel: T[], allChip: boolean) => void;
  /** Called with query text (minus any leading '-' prefix). Returns matching items. */
  matchFn: (text: string) => T[];
  placeholder?: string;
  helpTitle?: string;
  shortcuts?: HelpShortcut[];
  /** CSS class for each selection chip. Defaults to coaching chip classes. */
  chipClassName?: (item: T) => string;
  /** Extra inline style for each chip (e.g. project purple). */
  chipStyle?: (item: T) => React.CSSProperties | undefined;
  /** Content to render inside the autocomplete hint for a match. */
  autocompleteLabel?: (item: T) => React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  /** When true, chips are not rendered inside this component (render them externally). */
  hideChips?: boolean;
  /** When true, focus the input on mount. */
  autoFocus?: boolean;
}

export function ClientFilterBar<T extends FilterItem,>({
  selection,
  allChip,
  onSelectionChange,
  matchFn,
  placeholder = 'filter… (⌘F · ⌘? help)',
  helpTitle = 'Keyboard shortcuts',
  shortcuts = [],
  chipClassName = (item) =>
    `coaching-filter-chip${item.type === 'company' ? ' coaching-filter-chip--company' : ''}`,
  chipStyle = (item) =>
    item.type === 'project' ? { color: '#7B52AB', borderColor: '#7B52AB' } : undefined,
  autocompleteLabel = (item) => {
    if (item.type === 'project') return <span style={{ color: '#7B52AB' }}>{item.label}</span>;
    if (item.type === 'company') return <span className="coaching-filter-ac-company">{item.label}</span>;
    return <span>{item.label}</span>;
  },
  className,
  style,
  hideChips = false,
  autoFocus = false,
}: ClientFilterBarProps<T>) {
  const [text, setText] = useState('');
  const [matchIndex, setMatchIndex] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const removing = text.startsWith('-');
  const queryText = removing ? text.slice(1) : text;
  const matches = matchFn(queryText);
  const currentMatch = matches[matchIndex] ?? null;
  const multipleMatches = matches.length > 1;

  useEffect(() => { setMatchIndex(0); }, [text]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey && e.key === 'f') { e.preventDefault(); inputRef.current?.focus(); return; }
      if (e.metaKey && (e.key === '/' || e.key === '?')) { e.preventDefault(); setHelpOpen(h => !h); return; }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  const addToSelection = useCallback((item: T) => {
    if (!selection.find(s => s.type === item.type && s.id === item.id)) {
      onSelectionChange([...selection, item], false);
    }
  }, [selection, onSelectionChange]);

  const removeFromSelection = useCallback((item: T) => {
    const next = selection.filter(s => !(s.type === item.type && s.id === item.id));
    onSelectionChange(next, allChip && next.length === 0);
  }, [selection, allChip, onSelectionChange]);

  const clearToAll = useCallback(() => {
    onSelectionChange([], true);
    setText('');
  }, [onSelectionChange]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') { e.preventDefault(); setText(''); return; }
    if ((e.metaKey || e.ctrlKey) && e.key === 'a') { e.preventDefault(); clearToAll(); return; }
    if ((e.metaKey || e.ctrlKey) && e.key === '.') { e.preventDefault(); inputRef.current?.blur(); setText(''); return; }
    if (e.key === 'ArrowLeft') { e.preventDefault(); if (multipleMatches) setMatchIndex(i => (i - 1 + matches.length) % matches.length); return; }
    if (e.key === 'ArrowRight') { e.preventDefault(); if (multipleMatches) setMatchIndex(i => (i + 1) % matches.length); return; }
    if (e.key === 'Enter' && currentMatch) {
      e.preventDefault();
      if (removing) removeFromSelection(currentMatch);
      else addToSelection(currentMatch);
      setText('');
    }
  };

  const showingAll = selection.length === 0;

  return (
    <div className={`coaching-filter${className ? ` ${className}` : ''}`} style={style}>
      {shortcuts.length > 0 && (
        <HelpPopover title={helpTitle} shortcuts={shortcuts} isOpen={helpOpen} onClose={() => setHelpOpen(false)} />
      )}

      {!hideChips && (allChip || selection.length > 0) && (
        <div className="coaching-filter-chips">
          {allChip && showingAll ? (
            <span className="coaching-filter-chip coaching-filter-chip--all">
              All
              <button className="coaching-filter-chip-remove" onClick={() => onSelectionChange([], false)}>×</button>
            </span>
          ) : (
            selection.map((item, i) => (
              <span key={i} className={chipClassName(item)} style={chipStyle(item)}>
                {item.label}
                <button className="coaching-filter-chip-remove" onClick={() => removeFromSelection(item)}>×</button>
              </span>
            ))
          )}
          {selection.length > 0 && (
            <button className="coaching-filter-clear" onClick={clearToAll}>clear</button>
          )}
        </div>
      )}

      {text && (
        <div className="coaching-filter-autocomplete">
          {currentMatch ? (
            <span style={{ color: multipleMatches ? 'var(--color-text-light)' : 'var(--color-text)' }}>
              {removing && <span style={{ opacity: 0.5 }}>−</span>}
              {autocompleteLabel(currentMatch)}
              {multipleMatches && <span className="coaching-filter-ac-hint"> ← → to cycle</span>}
            </span>
          ) : (
            <span style={{ color: 'var(--color-text-light)', fontStyle: 'italic' }}>no match</span>
          )}
        </div>
      )}

      <input
        ref={inputRef}
        className="coaching-filter-input"
        type="text"
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        spellCheck={false}
      />
    </div>
  );
}
