import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LibbyClient {
  id: number;
  name: string;
}

interface LibbyContextValue {
  activeClientId: number | null;
  activeClientName: string | null;
  allClients: LibbyClient[];
  setActiveClient: (id: number | null, name: string | null) => void;
  isHelpOpen: boolean;
  setHelpOpen: (open: boolean) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const LibbyContext = createContext<LibbyContextValue>({
  activeClientId: null,
  activeClientName: null,
  allClients: [],
  setActiveClient: () => {},
  isHelpOpen: false,
  setHelpOpen: () => {},
});

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function LibbyProvider({ children }: { children: ReactNode }) {
  const [activeClientId, setActiveClientId] = useState<number | null>(null);
  const [activeClientName, setActiveClientName] = useState<string | null>(null);
  const [allClients, setAllClients] = useState<LibbyClient[]>([]);
  const [isHelpOpen, setHelpOpen] = useState(false);

  // Load active client + full client list once on mount
  useEffect(() => {
    fetch('/api/libby/active-client')
      .then(r => (r.ok ? r.json() : null))
      .then((data: { id: number; name: string } | null) => {
        if (data) {
          setActiveClientId(data.id);
          setActiveClientName(data.name);
        }
      })
      .catch(() => {});

    fetch('/api/coaching/clients')
      .then(r => (r.ok ? r.json() : { groups: [] }))
      .then((data: { groups: { clients: LibbyClient[] }[] }) => {
        const flat: LibbyClient[] = [];
        for (const group of data.groups ?? []) {
          for (const c of group.clients ?? []) {
            flat.push({ id: c.id, name: c.name });
          }
        }
        flat.sort((a, b) => a.name.localeCompare(b.name));
        setAllClients(flat);
      })
      .catch(() => {});
  }, []);

  const setActiveClient = (id: number | null, name: string | null) => {
    setActiveClientId(id);
    setActiveClientName(name);
  };

  return (
    <LibbyContext.Provider
      value={{ activeClientId, activeClientName, allClients, setActiveClient, isHelpOpen, setHelpOpen }}
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
