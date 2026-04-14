import { useState, useEffect } from 'react';
import { useLibbyContext } from '../contexts/LibbyContext';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

const ALL_TYPES = [
  { code: 'b', name: 'Book' },
  { code: 'a', name: 'Article' },
  { code: 'e', name: 'Essay' },
  { code: 'p', name: 'Podcast' },
  { code: 'v', name: 'Video' },
  { code: 'm', name: 'Movie' },
  { code: 't', name: 'Tool' },
  { code: 'w', name: 'Webpage' },
  { code: 's', name: 'Worksheet' },
  { code: 'z', name: 'Assessment' },
  { code: 'n', name: 'Note' },
  { code: 'd', name: 'Document' },
  { code: 'f', name: 'Framework' },
  { code: 'c', name: 'Course' },
  { code: 'r', name: 'Research' },
  { code: 'q', name: 'Quote' },
];

interface QueueEntry {
  id: number;
  name: string;
  type_code: string;
  created_at: string;
  status: 'pending' | 'processing' | 'ready' | 'failed';
}

// ---------------------------------------------------------------------------
// LibbyNewPage
// ---------------------------------------------------------------------------

export function LibbyNewPage() {
  const { refreshQueueCount } = useLibbyContext();

  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(true);

  // Generic form state
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [comments, setComments] = useState('');
  const [priority, setPriority] = useState<'high' | 'medium' | 'low'>('medium');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const loadQueue = () => {
    fetch('/api/libby/queue')
      .then(r => r.ok ? r.json() : { entries: [], count: 0 })
      .then(d => { setQueue(d.entries ?? []); setLoadingQueue(false); })
      .catch(() => setLoadingQueue(false));
  };

  useEffect(loadQueue, []);

  const handleTypeSelect = (code: string) => {
    setSelectedType(prev => prev === code ? null : code);
    setSaveError(null);
    setSaveSuccess(null);
  };

  const resetForm = () => {
    setName(''); setUrl(''); setComments(''); setPriority('medium');
    setSaveError(null); setSaveSuccess(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !selectedType) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      const resp = await fetch('/api/libby/entries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          type_code: selectedType,
          url: url.trim() || null,
          comments: comments.trim() || null,
          priority,
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setSaveSuccess(`Added: "${data.name}"`);
        resetForm();
        loadQueue();
        refreshQueueCount();
      } else {
        setSaveError(data.detail ?? 'Save failed');
      }
    } catch {
      setSaveError('Save failed — server error');
    } finally {
      setSaving(false);
    }
  };

  const selectedTypeName = ALL_TYPES.find(t => t.code === selectedType)?.name;

  return (
    <div className="libby-new-page">

      {/* ── Type selector ── */}
      <div className="libby-type-selector">
        {ALL_TYPES.map(t => (
          <button
            key={t.code}
            className={`libby-type-btn${selectedType === t.code ? ' libby-type-btn--selected' : ''}`}
            onClick={() => handleTypeSelect(t.code)}
            type="button"
          >
            <span className="libby-type-btn-code">{t.code}</span>
            <span className="libby-type-btn-name">{t.name}</span>
          </button>
        ))}
      </div>

      {/* ── Creation form ── */}
      {selectedType ? (
        <form className="libby-new-form" onSubmit={handleSubmit}>
          <div className="libby-new-form-heading">
            New {selectedTypeName}
          </div>

          <div className="libby-form-row">
            <label className="libby-form-label">name *</label>
            <input
              className="libby-form-input"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Title or name"
              required
              autoFocus
              spellCheck={false}
            />
          </div>

          <div className="libby-form-row">
            <label className="libby-form-label">url</label>
            <input
              className="libby-form-input"
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://…"
              spellCheck={false}
            />
          </div>

          <div className="libby-form-row">
            <label className="libby-form-label">comments</label>
            <textarea
              className="libby-form-input libby-form-textarea"
              value={comments}
              onChange={e => setComments(e.target.value)}
              placeholder="Brief annotation (optional)"
              rows={3}
            />
          </div>

          <div className="libby-form-row">
            <label className="libby-form-label">priority</label>
            <select
              className="libby-form-input libby-form-select"
              value={priority}
              onChange={e => setPriority(e.target.value as 'high' | 'medium' | 'low')}
            >
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
          </div>

          {saveError && <div className="libby-admin-error">{saveError}</div>}
          {saveSuccess && <div className="libby-save-success">{saveSuccess}</div>}

          <div className="libby-form-actions">
            <button
              type="submit"
              className="libby-admin-btn libby-admin-btn--primary"
              disabled={saving || !name.trim()}
            >
              {saving ? 'Saving…' : 'Add to library'}
            </button>
            <button type="button" className="libby-admin-btn" onClick={resetForm}>
              clear
            </button>
          </div>
        </form>
      ) : (
        <div className="libby-new-prompt">Select a type above to add a new entry</div>
      )}

      {/* ── Review queue ── */}
      <div className="libby-queue-section">
        <h3 className="libby-queue-title">Review queue</h3>
        <p className="libby-admin-desc">
          Entries awaiting auto-tagging and auto-synopsis. Click a row to review once ready.
        </p>

        {loadingQueue ? (
          <div className="libby-admin-loading">Loading…</div>
        ) : queue.length === 0 ? (
          <div className="libby-queue-empty">No entries in queue</div>
        ) : (
          <table className="libby-admin-table libby-queue-table">
            <thead>
              <tr>
                <th>name</th>
                <th>type</th>
                <th>created</th>
                <th>pending</th>
                <th>status</th>
              </tr>
            </thead>
            <tbody>
              {queue.map(entry => (
                <tr key={entry.id} className="libby-admin-row libby-queue-row">
                  <td className="libby-queue-name">{entry.name}</td>
                  <td className="libby-admin-code">{entry.type_code}</td>
                  <td className="libby-queue-date">{entry.created_at.slice(0, 10)}</td>
                  <td className="libby-queue-pending">tags · synopsis</td>
                  <td>
                    <span className={`libby-queue-status libby-queue-status--${entry.status}`}>
                      {entry.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
