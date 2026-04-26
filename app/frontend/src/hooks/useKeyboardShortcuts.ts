import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

export type ShortcutCategory = 'navigation' | 'actions' | 'focus' | 'issues' | 'discovery' | 'overlays';

export interface ShortcutDef {
  keys: string;
  description: string;
  category: ShortcutCategory;
}

export const SHORTCUT_DEFINITIONS: ShortcutDef[] = [
  // Navigation (g + key, optionally g + key + subpage key)
  { keys: 'g d', description: 'Go to Today', category: 'navigation' },
  { keys: 'g n', description: 'Go to Thoughts', category: 'navigation' },
  { keys: 'g i', description: 'Go to Issues', category: 'navigation' },
  { keys: 'g l [c/t/y/n/r]', description: 'Go to Library (Catalog/Topics/Types/New/Reading)', category: 'navigation' },
  { keys: 'g m', description: 'Go to Meetings', category: 'navigation' },
  { keys: 'g w', description: 'Go to Writing', category: 'navigation' },
  { keys: 'g p', description: 'Go to People', category: 'navigation' },
  { keys: 'g h', description: 'Go to GitHub', category: 'navigation' },
  { keys: 'g q', description: 'Go to Code Search', category: 'navigation' },
  { keys: 'g c', description: 'Go to Claude', category: 'navigation' },
  { keys: 'g e', description: 'Go to Email', category: 'navigation' },
  { keys: 'g k', description: 'Go to Slack', category: 'navigation' },
  { keys: 'g o [c/l/s/v/o]', description: 'Go to Coaching (Clients/Cloud/Setup/Vinny/Ops)', category: 'navigation' },
  { keys: 'g f', description: 'Go to Drive (files)', category: 'navigation' },
  { keys: 'g x', description: 'Go to Ramp (expenses)', category: 'navigation' },
  { keys: 'g b [q/s/i/p/o/d]', description: 'Go to Billing (Queue/Sessions/Invoices/…)', category: 'navigation' },
  { keys: 'g s', description: 'Go to Settings', category: 'navigation' },
  { keys: '⌘→ / ⌘←', description: 'Next / previous page in current module', category: 'navigation' },

  // Actions
  { keys: 'h', description: 'Help / intro', category: 'actions' },
  { keys: 'c', description: 'New thought', category: 'actions' },
  { keys: 'r', description: 'Refresh page data', category: 'actions' },
  { keys: 'u', description: 'Undo last action', category: 'actions' },
  { keys: 's', description: 'Sync all data', category: 'actions' },
  { keys: 'D', description: 'Discover issues (AI scan)', category: 'actions' },

  // Focus
  { keys: 'Tab / j / \u2193', description: 'Next item in list', category: 'focus' },
  { keys: 'Shift+Tab / k / \u2191', description: 'Previous item in list', category: 'focus' },
  { keys: 'Enter', description: 'Open focused item', category: 'focus' },
  { keys: 'd', description: 'Dismiss focused item', category: 'focus' },
  { keys: 'e', description: 'Expand / collapse item', category: 'focus' },
  { keys: 'i', description: 'Create issue from item', category: 'focus' },
  { keys: 'f', description: 'Toggle score filter (all / filtered)', category: 'focus' },

  // Issues (on Issues page)
  { keys: 'j / \u2193', description: 'Next issue', category: 'issues' },
  { keys: 'k / \u2191', description: 'Previous issue', category: 'issues' },
  { keys: 'Enter', description: 'Expand / collapse issue', category: 'issues' },
  { keys: 'x', description: 'Toggle done', category: 'issues' },
  { keys: '\u2190 / \u2192', description: 'Change priority', category: 'issues' },
  { keys: 'Shift+\u2190 / Shift+\u2192', description: 'Change size', category: 'issues' },
  { keys: 'Tab', description: 'Edit expanded issue', category: 'issues' },
  { keys: 'Delete', description: 'Delete issue', category: 'issues' },
  { keys: 'i', description: 'New issue', category: 'issues' },

  // Discovery (in review overlay)
  { keys: 'j / \u2193', description: 'Next proposal', category: 'discovery' },
  { keys: 'k / \u2191', description: 'Previous proposal', category: 'discovery' },
  { keys: 'Enter', description: 'Accept proposal', category: 'discovery' },
  { keys: 'x', description: 'Reject proposal', category: 'discovery' },
  { keys: 'e', description: 'Edit proposal', category: 'discovery' },
  { keys: 'Escape', description: 'Close review', category: 'discovery' },

  // Overlays
  { keys: 'Ctrl+Tab', description: 'Switch recent page', category: 'overlays' },
  { keys: '\u2318K', description: 'Search / command palette', category: 'overlays' },
  { keys: 'Tab (in \u2318K)', description: 'Quick create (issue/thought)', category: 'overlays' },
  { keys: '\u2318E (in \u2318K)', description: 'Toggle external search', category: 'overlays' },
  { keys: '\u2318/ (in \u2318K)', description: 'Toggle code search', category: 'overlays' },
  { keys: '?', description: 'Keyboard shortcuts help', category: 'overlays' },
  { keys: 'Escape', description: 'Close overlay', category: 'overlays' },
];

// ---------------------------------------------------------------------------
// g + letter navigation map
// Entries with 'path' navigate immediately.
// Entries with 'default' + 'sub' navigate to default, then await a third key.
// ---------------------------------------------------------------------------

type GNavSimple = { path: string };
type GNavModule = { default: string; sub: Record<string, string> };
type GNavEntry = GNavSimple | GNavModule;

const G_NAV: Record<string, GNavEntry> = {
  d: { path: '/' },
  n: { path: '/notes' },
  i: { path: '/issues' },
  l: {
    default: '/libby/catalog',
    sub: {
      c: '/libby/catalog',
      t: '/libby/topics',
      y: '/libby/types',
      n: '/libby/new',
      r: '/libby/reading',
    },
  },
  m: { path: '/meetings' },
  w: { path: '/docs' },
  p: { path: '/people' },
  h: { path: '/github' },
  q: { path: '/code-search' },
  c: { path: '/claude' },
  e: { path: '/email' },
  k: { path: '/slack' },
  o: {
    default: '/coaching/clients',
    sub: {
      c: '/coaching/clients',
      l: '/coaching/wordcloud',
      s: '/coaching/setup',
      v: '/coaching/vinny',
      o: '/coaching/operations',
    },
  },
  f: { path: '/drive' },
  x: { path: '/ramp' },
  b: {
    default: '/billing/queue',
    sub: {
      q: '/billing/queue',
      s: '/billing/sessions',
      i: '/billing/invoices',
      p: '/billing/payments',
      o: '/billing/overview',
      d: '/billing/draft',
    },
  },
  s: { path: '/settings' },
};

// ---------------------------------------------------------------------------
// ⌘→ / ⌘← module page cycling
// ---------------------------------------------------------------------------

const MODULE_PAGE_ORDER: Record<string, string[]> = {
  '/libby':    ['/libby/catalog', '/libby/topics', '/libby/types', '/libby/new', '/libby/reading'],
  '/billing':  ['/billing/queue', '/billing/sessions', '/billing/invoices',
                '/billing/payments', '/billing/overview', '/billing/draft'],
  '/coaching': ['/coaching/clients', '/coaching/wordcloud', '/coaching/setup',
                '/coaching/vinny', '/coaching/operations'],
};

type GNavState = 'idle' | 'waiting-module' | 'waiting-subpage';

interface UseKeyboardShortcutsOptions {
  navigate: (path: string) => void;
  onSearchOpen: () => void;
  onHelpOpen: () => void;
  onRefresh: () => void;
  onUndo: () => void;
  onSync: () => void;
  onDiscoverIssues?: () => void;
  suppressWhen?: boolean;
  // Recent pages (Ctrl+Tab)
  pageHistory?: string[];
  recentPagesOpen?: boolean;
  recentPagesIndex?: number;
  onRecentPagesOpen?: (index: number) => void;
  onRecentPagesNext?: () => void;
  onRecentPagesPrev?: () => void;
  onRecentPagesCommit?: () => void;
  onRecentPagesClose?: () => void;
}

export function useKeyboardShortcuts(opts: UseKeyboardShortcutsOptions) {
  const location = useLocation();
  const gNavState = useRef<GNavState>('idle');
  const gNavModule = useRef<string | null>(null);
  const gNavTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const o = optsRef.current;

      // Cmd+K: search — works everywhere including Claude page
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        o.onSearchOpen();
        return;
      }

      // Ctrl+Tab / Ctrl+Shift+Tab: recent pages — works everywhere
      if (e.ctrlKey && e.key === 'Tab' && !e.metaKey && !e.altKey) {
        e.preventDefault();
        if (o.recentPagesOpen) {
          if (e.shiftKey) {
            o.onRecentPagesPrev?.();
          } else {
            o.onRecentPagesNext?.();
          }
        } else if (o.pageHistory && o.pageHistory.length >= 2) {
          o.onRecentPagesOpen?.(1);
        }
        return;
      }

      // Guard: skip in inputs/textareas/contentEditable
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if ((e.target as HTMLElement)?.isContentEditable) return;

      // Guard: skip when the Libby catalog container (or a child) has focus.
      // The catalog handles its own letter-key shortcuts (result picking, actions)
      // and must not share the g-navigation state machine.
      if ((e.target as HTMLElement)?.closest?.('[data-libby-catalog]')) return;

      // Guard: skip on Claude page (terminal captures keys)
      if (location.pathname === '/claude') return;

      // Guard: skip when overlays are open
      if (o.suppressWhen) return;

      // Shift+D: discover issues (before meta guard since shift is held)
      if (e.key === 'D' && e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        o.onDiscoverIssues?.();
        return;
      }

      // ⌘→ / ⌘← — next/previous page within current module
      if (e.metaKey && !e.ctrlKey && !e.altKey &&
          (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
        e.preventDefault();
        const pathname = location.pathname;
        const moduleKey = Object.keys(MODULE_PAGE_ORDER).find(k => pathname.startsWith(k));
        if (moduleKey) {
          const pages = MODULE_PAGE_ORDER[moduleKey];
          const idx = pages.findIndex(p => pathname === p || pathname.startsWith(p + '/'));
          if (e.key === 'ArrowRight') {
            o.navigate(idx >= 0 ? pages[(idx + 1) % pages.length] : pages[0]);
          } else {
            o.navigate(idx >= 0 ? pages[(idx - 1 + pages.length) % pages.length] : pages[pages.length - 1]);
          }
        }
        return;
      }

      // Don't process other shortcuts if meta/ctrl/alt held
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // ? key: help overlay
      if (e.key === '?') {
        e.preventDefault();
        o.onHelpOpen();
        return;
      }

      // ---------------------------------------------------------------------------
      // g navigation — three-state machine
      // ---------------------------------------------------------------------------

      if (gNavState.current === 'waiting-subpage') {
        if (gNavTimer.current) clearTimeout(gNavTimer.current);
        const modKey = gNavModule.current!;
        const entry = G_NAV[modKey];
        if ('sub' in entry) {
          const subPath = entry.sub[e.key.toLowerCase()];
          if (subPath) {
            e.preventDefault();
            o.navigate(subPath);
          }
        }
        gNavState.current = 'idle';
        gNavModule.current = null;
        return;
      }

      if (gNavState.current === 'waiting-module') {
        if (gNavTimer.current) clearTimeout(gNavTimer.current);
        gNavState.current = 'idle';

        const entry = G_NAV[e.key.toLowerCase()];
        if (!entry) return;

        e.preventDefault();
        if ('path' in entry) {
          o.navigate(entry.path);
        } else {
          o.navigate(entry.default);
          gNavModule.current = e.key.toLowerCase();
          gNavState.current = 'waiting-subpage';
          gNavTimer.current = setTimeout(() => {
            gNavState.current = 'idle';
            gNavModule.current = null;
          }, 800);
        }
        return;
      }

      // 'g' starts the sequence
      if (e.key === 'g') {
        gNavState.current = 'waiting-module';
        gNavTimer.current = window.setTimeout(() => {
          gNavState.current = 'idle';
        }, 1500);
        return;
      }

      // ---------------------------------------------------------------------------
      // Single-key shortcuts
      // ---------------------------------------------------------------------------
      if (e.key === 'c') {
        o.navigate('/notes?focus=1');
        return;
      }
      if (e.key === 'h') {
        o.navigate('/help');
        return;
      }
      if (e.key === 'r') {
        e.preventDefault();
        o.onRefresh();
        return;
      }
      if (e.key === 'u') {
        e.preventDefault();
        o.onUndo();
        return;
      }
      if (e.key === 's') {
        e.preventDefault();
        o.onSync();
        return;
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [location.pathname]);

  // Ctrl keyup commits recent-page selection
  useEffect(() => {
    if (!opts.recentPagesOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Control') {
        optsRef.current.onRecentPagesCommit?.();
      }
      if (e.key === 'Escape') {
        optsRef.current.onRecentPagesClose?.();
      }
    };
    document.addEventListener('keyup', handler);
    return () => document.removeEventListener('keyup', handler);
  }, [opts.recentPagesOpen]);
}
