import { useState } from 'react';
import { usePrioritizedNews, useRefreshPrioritizedNews } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { PrioritizedSourceList, ScoreBadge } from '../components/shared/PrioritizedSourceList';

function sourceLabel(source: string, sourceDetail: string | null): string {
  if (source === 'slack') return 'via Slack';
  if (source === 'email') return 'via Email';
  return sourceDetail || 'Web';
}

export function NewsPage() {
  const [days, setDays] = useState(14);
  const { data, isLoading } = usePrioritizedNews(days);
  const refresh = useRefreshPrioritizedNews(days);

  return (
    <PrioritizedSourceList
      title="News"
      source="news"
      items={data?.items ?? []}
      isLoading={isLoading}
      error={data?.error}
      stale={data?.stale}
      refresh={refresh}
      days={days}
      onDaysChange={setDays}
      dayOptions={[1, 14, 30]}
      defaultMinScore={5}
      itemNoun="article"
      getIssueTitle={(item) => item.title}
      renderItem={(item, expanded) => (
        <a
          className="dashboard-item dashboard-item-link"
          href={item.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
        >
          <div style={{ flexShrink: 0, paddingTop: '2px' }}><ScoreBadge score={item.priority_score} /></div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="dashboard-item-title">
              {item.title}
              {item.domain && <span className="news-item-domain" style={{ marginLeft: 'var(--space-xs)' }}>{item.domain}</span>}
            </div>
            <div className="dashboard-item-meta">
              <span className={`news-source-badge news-source-${item.source}`}>
                {sourceLabel(item.source, item.source_detail)}
              </span>
              {item.source_detail && item.source !== 'web' && <span> &middot; {item.source_detail}</span>}
              {item.published_at && <span> &middot; <TimeAgo date={item.published_at} /></span>}
            </div>
            {expanded && item.snippet && <div className="dashboard-item-expanded">{item.snippet}</div>}
            {item.priority_reason && <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{item.priority_reason}</div>}
          </div>
        </a>
      )}
    />
  );
}
