import { useQuery } from '@tanstack/react-query';

export interface SidebarItem {
  id: string;
  label: string;
  route: string;
  connector?: string;
}

export interface SidebarSection {
  id: string;
  label: string | null;
  items: SidebarItem[];
}

export interface SidebarConfig {
  sections: SidebarSection[];
}

async function fetchSidebarConfig(): Promise<SidebarConfig> {
  console.log('[useSidebarConfig] fetchSidebarConfig fired');
  const res = await fetch('/api/config/sidebar');
  if (!res.ok) throw new Error('Failed to load sidebar config');
  return res.json();
}

export function useSidebarConfig() {
  return useQuery<SidebarConfig>({
    queryKey: ['sidebar-config'],
    queryFn: fetchSidebarConfig,
  });
}
