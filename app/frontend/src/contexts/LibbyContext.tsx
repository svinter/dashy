import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import type { FilterItem } from '../components/shared/ClientFilterBar';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LibbyGroup {
  company_id: number | null;
  company_name: string;
  clients: { id: number; name: string; manifest_gdoc_url?: string | null }[];
}

// FilterItem-compatible selection model (company or individual client)
export interface LibbyFilterSelection extends FilterItem {
  type: 'company' | 'client';
  company_name?: string;
}

interface LibbyContextValue {
  // Raw groups data — used by LibbyClientFilter to build search index
  groups: LibbyGroup[];

  // Filter bar state (single-select enforced in onSelectionChange)
  selection: LibbyFilterSelection[];
  allChip: boolean;
  onSelectionChange: (sel: LibbyFilterSelection[], allChip: boolean) => void;

  // Derived active state — used by CatalogPage for search + record action
  activeClientId: number | null;      // non-null only when individual client selected
  activeClientName: string | null;    // person name when client selected
  activeCompanyId: number | null;     // non-null when company chip selected
  activeCompanyName: string | null;   // company name when company chip selected
  activeClientManifestUrl: string | null;  // manifest_gdoc_url for active individual client

  // Queue badge
  queueCount: number;
  refreshQueueCount: () => void;

  // Help popup
  isHelpOpen: boolean;
  setHelpOpen: (open: boolean) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const LibbyContext = createContext<LibbyContextValue>({
  groups: [],
  selection: [],
  allChip: false,
  onSelectionChange: () => {},
  activeClientId: null,
  activeClientName: null,
  activeCompanyId: null,
  activeCompanyName: null,
  activeClientManifestUrl: null,
  queueCount: 0,
  refreshQueueCount: () => {},
  isHelpOpen: false,
  setHelpOpen: () => {},
});

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function LibbyProvider({ children }: { children: ReactNode }) {
  const [groups, setGroups] = useState<LibbyGroup[]>([]);
  const [selection, setSelection] = useState<LibbyFilterSelection[]>([]);
  const [allChip, setAllChip] = useState(false);
  const [isHelpOpen, setHelpOpen] = useState(false);
  const [queueCount, setQueueCount] = useState(0);

  const refreshQueueCount = useCallback(() => {
    fetch('/api/libby/queue')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.count != null) setQueueCount(d.count); })
      .catch(() => {});
  }, []);

  // Poll queue count every 30s + on mount
  useEffect(() => {
    refreshQueueCount();
    const timer = setInterval(refreshQueueCount, 30_000);
    return () => clearInterval(timer);
  }, [refreshQueueCount]);

  // Fetch groups + active-client in parallel on mount
  useEffect(() => {
    Promise.all([
      fetch('/api/coaching/clients').then(r => r.ok ? r.json() : { groups: [] }),
      fetch('/api/libby/active-client').then(r => r.ok ? r.json() : null),
    ])
      .then(([groupsData, activeData]) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const rawGroups: LibbyGroup[] = (groupsData.groups ?? []).map((g: any) => ({
          company_id: g.company_id,
          company_name: g.company_name,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          clients: (g.clients ?? []).map((c: any) => ({ id: c.id, name: c.name, manifest_gdoc_url: c.manifest_gdoc_url ?? null })),
        }));
        setGroups(rawGroups);

        if (activeData?.id) {
          // Find which company this client belongs to
          let companyName: string | undefined;
          for (const g of rawGroups) {
            if (g.clients.some(c => c.id === activeData.id)) {
              companyName = g.company_name;
              break;
            }
          }
          setSelection([{
            type: 'client',
            id: activeData.id,
            label: activeData.name,
            company_name: companyName,
          }]);
        }
      })
      .catch(() => {});
  }, []);

  // Single-select enforcement: keep only the last item when adding
  const onSelectionChange = (newSel: LibbyFilterSelection[], newAllChip: boolean) => {
    const enforced = newSel.length > 1 ? [newSel[newSel.length - 1]] : newSel;
    setSelection(enforced);
    setAllChip(newAllChip);
  };

  // Derive active client / company from selection
  const sel = selection[0] ?? null;
  const activeClientId = sel?.type === 'client' ? sel.id : null;
  const activeClientName = sel?.type === 'client' ? sel.label : null;
  const activeCompanyId = sel?.type === 'company' ? sel.id : null;
  const activeCompanyName = sel?.type === 'company' ? sel.label : null;
  const activeClientManifestUrl = activeClientId != null
    ? (groups.flatMap(g => g.clients).find(c => c.id === activeClientId)?.manifest_gdoc_url ?? null)
    : null;

  return (
    <LibbyContext.Provider
      value={{
        groups,
        selection,
        allChip,
        onSelectionChange,
        activeClientId,
        activeClientName,
        activeCompanyId,
        activeCompanyName,
        activeClientManifestUrl,
        queueCount,
        refreshQueueCount,
        isHelpOpen,
        setHelpOpen,
      }}
    >
      {children}
    </LibbyContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useLibbyContext() {
  return useContext(LibbyContext);
}
