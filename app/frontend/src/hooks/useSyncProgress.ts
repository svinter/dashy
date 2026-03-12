import { useEffect, useRef, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSyncStatus, useConnectors } from '../api/hooks';

type StepStatus = 'pending' | 'running' | 'done' | 'error';

const ALL_DATA_SOURCES: { key: string; label: string; connector: string | null }[] = [
  { key: 'granola', label: 'Meetings', connector: 'granola' },
  { key: 'gmail', label: 'Gmail', connector: 'google' },
  { key: 'calendar', label: 'Calendar', connector: 'google' },
  { key: 'drive', label: 'Drive', connector: 'google_drive' },
  { key: 'sheets', label: 'Sheets', connector: 'google_drive' },
  { key: 'docs', label: 'Docs', connector: 'google_drive' },
  { key: 'slack', label: 'Slack', connector: 'slack' },
  { key: 'notion', label: 'Notion', connector: 'notion' },
  { key: 'github', label: 'GitHub', connector: 'github' },
  { key: 'ramp', label: 'Ramp transactions', connector: 'ramp' },
  { key: 'ramp_vendors', label: 'Ramp vendors', connector: 'ramp' },
  { key: 'ramp_bills', label: 'Ramp bills', connector: 'ramp' },
  { key: 'news', label: 'News', connector: 'news' },
];

// Source key → query keys to invalidate when that source completes
const SOURCE_QUERY_MAP: Record<string, string[]> = {
  gmail: ['email-prioritized', 'all-emails', 'briefing'],
  calendar: ['meetings', 'briefing'],
  slack: ['slack-prioritized', 'all-slack', 'briefing'],
  notion: ['notion-prioritized', 'all-notion'],
  github: ['github-pulls', 'all-github'],
  drive: ['drive-prioritized', 'all-drive'],
  ramp: ['ramp-prioritized'],
  ramp_vendors: ['ramp-prioritized'],
  ramp_bills: ['ramp-bills'],
  news: ['news-prioritized', 'news'],
  granola: ['meetings'],
  markdown: ['people', 'groups'],
  sheets: ['sheets'],
  docs: ['docs'],
};

export function useSyncProgress() {
  const qc = useQueryClient();
  const syncStatus = useSyncStatus();
  const { data: connectors } = useConnectors();

  const syncStartedAtRef = useRef<string | null>(null);
  const prevRunningRef = useRef(false);
  const completedSourcesRef = useRef<Set<string>>(new Set());

  const enabledSet = useMemo(
    () => new Set(connectors?.filter(c => c.enabled).map(c => c.id)),
    [connectors],
  );

  const dataSources = useMemo(
    () => ALL_DATA_SOURCES.filter(s => s.connector === null || enabledSet.has(s.connector)),
    [enabledSet],
  );

  const isRunning = syncStatus.data?.running ?? false;
  const sources = syncStatus.data?.sources ?? {};
  const activeSources = new Set(syncStatus.data?.active_sources ?? []);

  // Detect sync start/end
  useEffect(() => {
    if (!prevRunningRef.current && isRunning) {
      // Sync just started — record start time with 5s buffer for fast sources
      const now = new Date();
      const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000 - 5000);
      syncStartedAtRef.current = local.toISOString().replace('Z', '');
      completedSourcesRef.current = new Set();
    } else if (prevRunningRef.current && !isRunning) {
      // Sync finished — final invalidation catches reranked priorities etc.
      setTimeout(() => qc.invalidateQueries(), 500);
      syncStartedAtRef.current = null;
    }
    prevRunningRef.current = isRunning;
  }, [isRunning, qc]);

  // Incremental invalidation: when a source newly completes, invalidate its queries
  const syncData = syncStatus.data;
  useEffect(() => {
    const startedAt = syncStartedAtRef.current;
    const currentSources = syncData?.sources ?? {};
    if (!startedAt || !isRunning) return;

    for (const [key, src] of Object.entries(currentSources)) {
      if (completedSourcesRef.current.has(key)) continue;
      if (src.last_sync_at > startedAt && src.last_sync_status) {
        completedSourcesRef.current.add(key);
        const queryKeys = SOURCE_QUERY_MAP[key] ?? [];
        for (const qk of queryKeys) {
          qc.invalidateQueries({ queryKey: [qk] });
        }
      }
    }
  }, [syncData, isRunning, qc]);

  function getSourceStatus(key: string): StepStatus {
    if (activeSources.has(key)) return 'running';
    const src = sources[key];
    const startedAt = syncStartedAtRef.current;
    if (!src || !startedAt) return 'pending';
    if (src.last_sync_at > startedAt) {
      return src.last_sync_status === 'success' ? 'done' : 'error';
    }
    return 'pending';
  }

  const completedCount = dataSources.filter(s => {
    const status = getSourceStatus(s.key);
    return status === 'done' || status === 'error';
  }).length;

  return {
    isRunning,
    dataSources,
    sources,
    activeSources,
    completedCount,
    totalCount: dataSources.length,
    getSourceStatus,
    autoSync: syncStatus.data?.auto_sync,
  };
}
