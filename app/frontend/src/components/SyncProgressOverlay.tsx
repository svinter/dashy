import { useEffect } from 'react';
import { useCancelSync } from '../api/hooks';
import { useSyncProgress } from '../hooks/useSyncProgress';

type StepStatus = 'pending' | 'running' | 'done' | 'error';

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'running') {
    return (
      <svg className="sync-step-spinner" width="14" height="14" viewBox="0 0 14 14">
        <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="20 14" />
      </svg>
    );
  }
  if (status === 'done') {
    return <span className="sync-step-check">&#x2713;</span>;
  }
  if (status === 'error') {
    return <span className="sync-step-error-icon">&#x2717;</span>;
  }
  return <span className="sync-step-pending-icon">&#x25CB;</span>;
}

/** Extract a short, human-readable message from a Python traceback or error string. */
function shortError(raw: string | null | undefined): string {
  if (!raw) return '';
  const lines = raw.trim().split('\n');
  const last = lines[lines.length - 1].trim();
  const cleaned = last
    .replace(/^[\w.]+Error:\s*/, '')
    .replace(/^[\w.]+Exception:\s*/, '');
  return cleaned.length > 120 ? cleaned.slice(0, 117) + '...' : cleaned;
}

export function SyncDetailModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const cancelSync = useCancelSync();
  const { isRunning, dataSources, sources, completedCount, totalCount, getSourceStatus } = useSyncProgress();

  // Escape closes the modal
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const allDone = !isRunning && completedCount > 0;

  return (
    <div className="sync-detail-modal">
      <div className="sync-progress-panel">
        <div className="sync-progress-header">
          <div className="sync-progress-title">
            {allDone ? (
              <span className="sync-progress-done">Sync complete &#x2713;</span>
            ) : isRunning ? (
              `Syncing ${completedCount}/${totalCount}`
            ) : (
              'Sync status'
            )}
          </div>
          <button className="sync-detail-close" onClick={onClose} title="Close">&times;</button>
        </div>

        <div className="sync-progress-section">
          <div className="sync-progress-section-label">Data sources</div>
          {dataSources.map(({ key, label }) => {
            const status = getSourceStatus(key);
            const src = sources[key];
            const showCount = status === 'done' && src?.items_synced != null;
            const duration = src?.duration_seconds;
            const errorMsg = status === 'error' ? shortError(src?.last_error) : '';
            return (
              <div key={key}>
                <div className={`sync-step sync-step-${status}`}>
                  <StepIcon status={status} />
                  <span className="sync-step-label">{label}</span>
                  {showCount && (
                    <span className="sync-step-count">
                      {src.items_synced} items
                      {duration != null && <span className="sync-step-duration"> &middot; {duration}s</span>}
                    </span>
                  )}
                  {status === 'running' && (
                    <span className="sync-step-hint">syncing&hellip;</span>
                  )}
                </div>
                {errorMsg && (
                  <div className="sync-step-error-msg" title={src?.last_error ?? ''}>{errorMsg}</div>
                )}
              </div>
            );
          })}
        </div>

        <div className="sync-progress-footer">
          {isRunning ? (
            <button className="btn-link" onClick={() => cancelSync.mutate()} style={{ fontSize: 'inherit' }}>
              Cancel sync
            </button>
          ) : (
            <span>Press Esc to close</span>
          )}
        </div>
      </div>
    </div>
  );
}
