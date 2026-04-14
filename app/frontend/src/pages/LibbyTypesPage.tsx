import { useState, useEffect } from 'react';
import { api } from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LibraryType {
  code: string;
  name: string;
  description: string | null;
  entry_count: number;
}

// ---------------------------------------------------------------------------
// LibbyTypesPage
// ---------------------------------------------------------------------------

export function LibbyTypesPage() {
  const [types, setTypes] = useState<LibraryType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Inline-edit state
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);

  // New type form
  const [newCode, setNewCode] = useState('');
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const loadTypes = () => {
    setLoading(true);
    api.get<{ types: LibraryType[] }>('/libby/types')
      .then(d => { setTypes(d.types); setLoading(false); })
      .catch(e => { setError(String(e)); setLoading(false); });
  };

  useEffect(loadTypes, []);

  // --- Inline edit ---
  const startEdit = (t: LibraryType) => {
    setEditingCode(t.code);
    setEditName(t.name);
    setEditDesc(t.description ?? '');
    setSaveError(null);
  };

  const cancelEdit = () => { setEditingCode(null); setSaveError(null); };

  const saveEdit = async (code: string) => {
    setSaveError(null);
    try {
      await api.put<unknown>(`/libby/types/${code}`, {
        name: editName.trim(),
        description: editDesc.trim() || null,
      });
      setEditingCode(null);
      loadTypes();
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    }
  };

  // --- Add new type ---
  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError(null);
    if (!newCode.trim() || !newName.trim()) {
      setAddError('Code and name are required');
      return;
    }
    setAdding(true);
    try {
      await api.post<unknown>('/libby/types', {
        code: newCode.trim().toLowerCase(),
        name: newName.trim(),
        description: newDesc.trim() || null,
      });
      setNewCode('');
      setNewName('');
      setNewDesc('');
      loadTypes();
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : String(e));
    } finally {
      setAdding(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="libby-admin-page">
      <h2 className="libby-page-name">Types</h2>
      <p className="libby-admin-desc">
        {types.length} type{types.length !== 1 ? 's' : ''} · Edit name and description inline · Types with entries cannot be deleted
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
              <th>description</th>
              <th style={{ textAlign: 'right' }}>entries</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {types.map(t => {
              if (editingCode === t.code) {
                return (
                  <tr key={t.code} className="libby-admin-row libby-admin-row--editing">
                    <td className="libby-admin-code">{t.code}</td>
                    <td>
                      <input
                        className="libby-admin-input"
                        value={editName}
                        onChange={e => setEditName(e.target.value)}
                        autoFocus
                      />
                    </td>
                    <td>
                      <input
                        className="libby-admin-input libby-admin-input--wide"
                        value={editDesc}
                        onChange={e => setEditDesc(e.target.value)}
                        placeholder="optional description"
                      />
                      {saveError && <div className="libby-admin-inline-error">{saveError}</div>}
                    </td>
                    <td style={{ textAlign: 'right', color: 'var(--color-text-light)' }}>{t.entry_count}</td>
                    <td className="libby-admin-actions">
                      <button className="libby-admin-btn libby-admin-btn--primary" onClick={() => saveEdit(t.code)}>save</button>
                      <button className="libby-admin-btn" onClick={cancelEdit}>cancel</button>
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={t.code} className="libby-admin-row">
                  <td className="libby-admin-code">{t.code}</td>
                  <td>{t.name}</td>
                  <td style={{ color: t.description ? 'inherit' : 'var(--color-text-light)' }}>
                    {t.description ?? '—'}
                  </td>
                  <td style={{ textAlign: 'right', color: 'var(--color-text-light)' }}>{t.entry_count}</td>
                  <td className="libby-admin-actions">
                    <button className="libby-admin-btn" onClick={() => startEdit(t)}>edit</button>
                    {t.entry_count > 0 && (
                      <span className="libby-admin-no-delete" title={`${t.entry_count} entries — cannot delete`}>
                        {t.entry_count} entries
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* Add new type */}
      <div className="libby-admin-add-section">
        <h3 className="libby-admin-add-title">Add new type</h3>
        <form className="libby-admin-add-form" onSubmit={handleAdd}>
          <input
            className="libby-admin-input libby-admin-input--code"
            value={newCode}
            onChange={e => setNewCode(e.target.value.slice(0, 1))}
            placeholder="code"
            maxLength={1}
            title="Single letter, not already in use"
          />
          <input
            className="libby-admin-input"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="name (e.g. Essay)"
          />
          <input
            className="libby-admin-input libby-admin-input--wide"
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            placeholder="description (optional)"
          />
          <button
            type="submit"
            className="libby-admin-btn libby-admin-btn--primary"
            disabled={adding}
          >
            {adding ? 'Adding…' : 'Add'}
          </button>
        </form>
        {addError && <div className="libby-admin-error">{addError}</div>}
      </div>
    </div>
  );
}
