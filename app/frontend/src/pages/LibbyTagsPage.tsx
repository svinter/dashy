import { useState, useEffect } from 'react';
import { api } from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LibraryTopic {
  id: number;
  code: string;
  name: string;
  entry_count: number;
}

// ---------------------------------------------------------------------------
// LibbyTagsPage
// ---------------------------------------------------------------------------

export function LibbyTagsPage() {
  const [topics, setTopics] = useState<LibraryTopic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Inline-edit state
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editCode, setEditCode] = useState('');
  const [editName, setEditName] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);

  // Merge modal state
  const [mergeSourceId, setMergeSourceId] = useState<number | null>(null);
  const [mergeTargetId, setMergeTargetId] = useState<string>('');
  const [mergeError, setMergeError] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);

  // Delete confirmation
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);

  const loadTopics = () => {
    setLoading(true);
    api.get<{ topics: LibraryTopic[] }>('/libby/topics')
      .then(d => { setTopics(d.topics); setLoading(false); })
      .catch(e => { setError(String(e)); setLoading(false); });
  };

  useEffect(loadTopics, []);

  // --- Inline edit ---
  const startEdit = (t: LibraryTopic) => {
    setEditingId(t.id);
    setEditCode(t.code);
    setEditName(t.name);
    setSaveError(null);
    setDeleteConfirmId(null);
    setMergeSourceId(null);
  };

  const cancelEdit = () => { setEditingId(null); setSaveError(null); };

  const saveEdit = async (id: number) => {
    setSaveError(null);
    try {
      await api.put<unknown>(`/libby/topics/${id}`, { code: editCode.trim(), name: editName.trim() });
      setEditingId(null);
      loadTopics();
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    }
  };

  // --- Delete ---
  const deleteTopic = async (id: number) => {
    try {
      await api.delete<unknown>(`/libby/topics/${id}`);
      setDeleteConfirmId(null);
      loadTopics();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // --- Merge ---
  const openMerge = (t: LibraryTopic) => {
    setMergeSourceId(t.id);
    setMergeTargetId('');
    setMergeError(null);
    setEditingId(null);
    setDeleteConfirmId(null);
  };

  const executeMerge = async () => {
    if (!mergeSourceId || !mergeTargetId) return;
    setMerging(true);
    setMergeError(null);
    try {
      await api.post('/libby/topics/merge', {
        source_id: mergeSourceId,
        target_id: parseInt(mergeTargetId, 10),
      });
      setMergeSourceId(null);
      loadTopics();
    } catch (e: unknown) {
      setMergeError(e instanceof Error ? e.message : String(e));
    } finally {
      setMerging(false);
    }
  };

  const mergeSource = topics.find(t => t.id === mergeSourceId);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="libby-admin-page">
      <h2 className="libby-page-name">Tags</h2>
      <p className="libby-admin-desc">
        {topics.length} topic{topics.length !== 1 ? 's' : ''} · Edit code or name inline · Merge to reassign all entries
      </p>

      {error && <div className="libby-admin-error">{error}</div>}

      {loading ? (
        <div className="libby-admin-loading">Loading…</div>
      ) : (
        <table className="libby-admin-table">
          <thead>
            <tr>
              <th>code</th>
              <th>name</th>
              <th style={{ textAlign: 'right' }}>entries</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {topics.map(t => {
              if (editingId === t.id) {
                return (
                  <tr key={t.id} className="libby-admin-row libby-admin-row--editing">
                    <td>
                      <input
                        className="libby-admin-input libby-admin-input--code"
                        value={editCode}
                        onChange={e => setEditCode(e.target.value)}
                        autoFocus
                      />
                    </td>
                    <td>
                      <input
                        className="libby-admin-input"
                        value={editName}
                        onChange={e => setEditName(e.target.value)}
                      />
                      {saveError && <div className="libby-admin-inline-error">{saveError}</div>}
                    </td>
                    <td style={{ textAlign: 'right', color: 'var(--color-text-light)' }}>{t.entry_count}</td>
                    <td className="libby-admin-actions">
                      <button className="libby-admin-btn libby-admin-btn--primary" onClick={() => saveEdit(t.id)}>save</button>
                      <button className="libby-admin-btn" onClick={cancelEdit}>cancel</button>
                    </td>
                  </tr>
                );
              }

              return (
                <tr key={t.id} className="libby-admin-row">
                  <td className="libby-admin-code">{t.code}</td>
                  <td>{t.name}</td>
                  <td style={{ textAlign: 'right', color: 'var(--color-text-light)' }}>{t.entry_count}</td>
                  <td className="libby-admin-actions">
                    <button className="libby-admin-btn" onClick={() => startEdit(t)}>edit</button>
                    <button className="libby-admin-btn" onClick={() => openMerge(t)}>merge</button>
                    {t.entry_count === 0 && (
                      deleteConfirmId === t.id ? (
                        <>
                          <button className="libby-admin-btn libby-admin-btn--danger" onClick={() => deleteTopic(t.id)}>confirm</button>
                          <button className="libby-admin-btn" onClick={() => setDeleteConfirmId(null)}>cancel</button>
                        </>
                      ) : (
                        <button className="libby-admin-btn libby-admin-btn--danger-outline" onClick={() => setDeleteConfirmId(t.id)}>delete</button>
                      )
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Merge modal */}
      {mergeSourceId !== null && mergeSource && (
        <div className="libby-modal-backdrop" onClick={() => setMergeSourceId(null)}>
          <div className="libby-modal" onClick={e => e.stopPropagation()}>
            <div className="libby-modal-title">Merge <strong>{mergeSource.code}</strong></div>
            <p className="libby-modal-desc">
              All {mergeSource.entry_count} entr{mergeSource.entry_count === 1 ? 'y' : 'ies'} assigned to <strong>{mergeSource.code}</strong> will be moved to the selected topic. The source topic will then be deleted.
            </p>
            <label className="libby-modal-label">Merge into:</label>
            <select
              className="libby-admin-select"
              value={mergeTargetId}
              onChange={e => setMergeTargetId(e.target.value)}
            >
              <option value="">— select —</option>
              {topics
                .filter(t => t.id !== mergeSourceId)
                .map(t => (
                  <option key={t.id} value={t.id}>{t.code} — {t.name}</option>
                ))}
            </select>
            {mergeError && <div className="libby-admin-error">{mergeError}</div>}
            <div className="libby-modal-footer">
              <button
                className="libby-admin-btn libby-admin-btn--primary"
                onClick={executeMerge}
                disabled={!mergeTargetId || merging}
              >
                {merging ? 'Merging…' : 'Merge'}
              </button>
              <button className="libby-admin-btn" onClick={() => setMergeSourceId(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
