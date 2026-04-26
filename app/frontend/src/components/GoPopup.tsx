import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

interface PageEntry { label: string; path: string; }
interface ModuleEntry { label: string; defaultPath: string; pages: Record<string, PageEntry>; }

const MODULES: Record<string, ModuleEntry> = {
  b: { label: 'Billing', defaultPath: '/billing', pages: {
    s: { label: 'Sessions',  path: '/billing' },
    c: { label: 'Confirmed', path: '/billing/sessions' },
    i: { label: 'Invoices',  path: '/billing/invoices' },
    p: { label: 'Payments',  path: '/billing/payments' },
    a: { label: 'Payables',  path: '/billing/payables' },
    u: { label: 'Summary',   path: '/billing/summary' },
    r: { label: 'Prepare',   path: '/billing/prepare' },
  }},
  c: { label: 'Coaching', defaultPath: '/coaching/clients', pages: {
    cl: { label: 'Clients',    path: '/coaching/clients' },
    co: { label: 'Cloud',      path: '/coaching/wordcloud' },
    s:  { label: 'Setup',      path: '/coaching/setup' },
    v:  { label: 'Vinny',      path: '/coaching/vinny' },
    o:  { label: 'Operations', path: '/coaching/operations' },
  }},
  l: { label: 'Library', defaultPath: '/libby/catalog', pages: {
    c: { label: 'Catalog', path: '/libby/catalog' },
    t: { label: 'Tags',    path: '/libby/topics' },
    y: { label: 'Types',   path: '/libby/types' },
    n: { label: 'New',     path: '/libby/new' },
    r: { label: 'Reading', path: '/libby/reading' },
  }},
  m: { label: 'Meetings', defaultPath: '/meetings', pages: {} },
  s: { label: 'Scripty',  defaultPath: '/scripty',  pages: {} },
  h: { label: 'Home',     defaultPath: '/',         pages: {} },
};

// ---------------------------------------------------------------------------
// Matching
// ---------------------------------------------------------------------------

interface GoMatch {
  moduleName: string;
  pageName: string | null;
  path: string;
  ambiguous: boolean;
  hasSpace: boolean;
}

function resolveMatch(input: string): GoMatch | null {
  const raw = input.toLowerCase();
  const spaceIdx = raw.indexOf(' ');
  const moduleTok = spaceIdx === -1 ? raw : raw.slice(0, spaceIdx);
  const pageTok   = spaceIdx === -1 ? null : raw.slice(spaceIdx + 1);

  if (!moduleTok) return null;

  const moduleMatches = Object.entries(MODULES).filter(([k]) => k.startsWith(moduleTok));
  if (moduleMatches.length === 0) return null;

  const [, mod] = moduleMatches[0];
  const hasSpace = spaceIdx !== -1;

  if (pageTok === null || pageTok === '') {
    return { moduleName: mod.label, pageName: null, path: mod.defaultPath, ambiguous: moduleMatches.length > 1, hasSpace };
  }

  const pageMatches = Object.entries(mod.pages).filter(([k]) => k.startsWith(pageTok));
  if (pageMatches.length === 0) return null;

  const [, page] = pageMatches[0];
  return { moduleName: mod.label, pageName: page.label, path: page.path, ambiguous: pageMatches.length > 1, hasSpace: true };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface GoPopupProps {
  isOpen: boolean;
  onClose: () => void;
}

export function GoPopup({ isOpen, onClose }: GoPopupProps) {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (isOpen) {
      setInput('');
      // rAF ensures the element is mounted before focus
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const match = resolveMatch(input);

  const displayLabel = match
    ? match.pageName
      ? `${match.moduleName} → ${match.pageName}`
      : match.hasSpace
        ? `${match.moduleName} →`
        : match.moduleName
    : null;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape' || (e.altKey && !e.metaKey && e.code === 'KeyG')) {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (match) { navigate(match.path); onClose(); }
      return;
    }
  };

  return (
    <>
      <div className="go-backdrop" onClick={onClose} />
      <div className="go-popup">
        <input
          ref={inputRef}
          className="go-input"
          type="text"
          placeholder="go…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          spellCheck={false}
          autoComplete="off"
        />
        {displayLabel && (
          <div className={`go-match${match?.ambiguous ? ' go-match--ambiguous' : ''}`}>
            {displayLabel}
          </div>
        )}
      </div>
    </>
  );
}
