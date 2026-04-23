import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

export interface ModulePref {
  module_id: string;
  label: string;
  route: string;
  connector?: string | null;
  section_id: string;
  section_label: string;
  visible: boolean;
}

async function fetchModulePrefs(): Promise<ModulePref[]> {
  const res = await fetch('/api/settings/modules');
  if (!res.ok) throw new Error('Failed to load module prefs');
  return res.json();
}

async function updateModuleVisibility(moduleId: string, visible: boolean): Promise<void> {
  const res = await fetch(`/api/settings/modules/${encodeURIComponent(moduleId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ visible }),
  });
  if (!res.ok) throw new Error('Failed to update module visibility');
}

export function useModulePrefs() {
  const queryClient = useQueryClient();
  const query = useQuery<ModulePref[]>({
    queryKey: ['module-prefs'],
    queryFn: fetchModulePrefs,
    staleTime: 30_000,
  });

  const hiddenIds = new Set(
    (query.data ?? []).filter((p) => !p.visible).map((p) => p.module_id)
  );

  const mutation = useMutation({
    mutationFn: ({ moduleId, visible }: { moduleId: string; visible: boolean }) =>
      updateModuleVisibility(moduleId, visible),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['module-prefs'] });
    },
  });

  return {
    data: query.data,
    isLoading: query.isLoading,
    hiddenIds,
    updatePref: (moduleId: string, visible: boolean) =>
      mutation.mutate({ moduleId, visible }),
    isPending: mutation.isPending,
  };
}
