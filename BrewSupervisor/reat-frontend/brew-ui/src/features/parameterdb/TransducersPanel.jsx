import { useEffect, useMemo, useState } from 'react';
import {
  createTransducer,
  deleteTransducer,
  fetchParams,
  fetchTransducers,
  updateParamConfig,
  updateTransducer,
} from './loaders.js';

function emptyDraft() {
  return {
    name: '',
    equation: 'x',
    min_limit: '',
    max_limit: '',
    input_unit: 'V',
    output_unit: '',
    description: '',
  };
}

function normalizeDraft(initial) {
  return {
    ...emptyDraft(),
    ...(initial || {}),
    equation: String(initial?.equation || 'x'),
  };
}

function TransducerModal({ mode, initial, onClose, onSave }) {
  const isCreate = mode === 'create';
  const [draft, setDraft] = useState(normalizeDraft(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  function setField(key, value) {
    setDraft((current) => ({ ...current, [key]: value }));
    setError('');
  }

  async function handleSave() {
    const hadMinLimit = !isCreate && Object.prototype.hasOwnProperty.call(initial || {}, 'min_limit');
    const hadMaxLimit = !isCreate && Object.prototype.hasOwnProperty.call(initial || {}, 'max_limit');
    const next = {
      ...draft,
      name: String(draft.name || '').trim(),
      equation: String(draft.equation || '').trim(),
      min_limit: String(draft.min_limit ?? '').trim(),
      max_limit: String(draft.max_limit ?? '').trim(),
      input_unit: String(draft.input_unit || '').trim(),
      output_unit: String(draft.output_unit || '').trim(),
      description: String(draft.description || '').trim(),
    }

    if (next.min_limit === '') {
      if (hadMinLimit) next.min_limit = null;
      else delete next.min_limit;
    }
    if (next.max_limit === '') {
      if (hadMaxLimit) next.max_limit = null;
      else delete next.max_limit;
    }

    if (!next.name) {
      setError('Name is required');
      return;
    }
    if (!next.equation) {
      setError('Equation is required');
      return;
    }
    if (next.min_limit !== undefined && Number.isNaN(Number(next.min_limit))) {
      setError('Min Limit must be numeric');
      return;
    }
    if (next.max_limit !== undefined && Number.isNaN(Number(next.max_limit))) {
      setError('Max Limit must be numeric');
      return;
    }

    setSaving(true);
    try {
      await onSave(next);
      onClose();
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pdb-modal-overlay" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <div className="pdb-modal pdb-modal-sm">
        <div className="pdb-modal-header">
          <h3>{isCreate ? 'Add Transducer' : `Edit — ${initial?.name || ''}`}</h3>
          <button className="pdb-close-btn" onClick={onClose}>✕</button>
        </div>
        <div className="pdb-modal-body">
          <div className="pdb-field">
            <label className="pdb-label">Name</label>
            <input className="pdb-input" value={draft.name} disabled={!isCreate} onChange={(e) => setField('name', e.target.value)} />
          </div>

          <div className="pdb-field">
            <label className="pdb-label">Equation</label>
            <input
              className="pdb-input"
              value={draft.equation || ''}
              onChange={(e) => setField('equation', e.target.value)}
              placeholder="x"
            />
            <div className="pdb-field-help">Use x (or value) as the calibrated input value.</div>
          </div>

          <div className="pdb-field">
            <label className="pdb-label">Min Limit</label>
            <input
              className="pdb-input"
              type="number"
              step="any"
              value={draft.min_limit ?? ''}
              onChange={(e) => setField('min_limit', e.target.value)}
              placeholder="optional"
            />
          </div>

          <div className="pdb-field">
            <label className="pdb-label">Max Limit</label>
            <input
              className="pdb-input"
              type="number"
              step="any"
              value={draft.max_limit ?? ''}
              onChange={(e) => setField('max_limit', e.target.value)}
              placeholder="optional"
            />
          </div>

          <div className="pdb-field">
            <label className="pdb-label">Input Unit</label>
            <input className="pdb-input" value={draft.input_unit} onChange={(e) => setField('input_unit', e.target.value)} />
          </div>

          <div className="pdb-field">
            <label className="pdb-label">Output Unit</label>
            <input className="pdb-input" value={draft.output_unit} onChange={(e) => setField('output_unit', e.target.value)} />
          </div>

          <div className="pdb-field">
            <label className="pdb-label">Description</label>
            <textarea className="pdb-textarea" rows={3} value={draft.description} onChange={(e) => setField('description', e.target.value)} />
          </div>

          {error && <div className="pdb-save-error">{error}</div>}
        </div>
        <div className="pdb-modal-footer">
          <button className="pdb-btn-secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="pdb-btn-primary" onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </div>
    </div>
  );
}

function TransducerDeleteModal({ state, onClose, onConfirmClearAndDelete }) {
  const { name, impacted, busy, error } = state;
  return (
    <div className="pdb-modal-overlay" onClick={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <div className="pdb-modal pdb-modal-sm">
        <div className="pdb-modal-header">
          <h3>Delete Transducer</h3>
          <button className="pdb-close-btn" onClick={onClose} disabled={busy}>✕</button>
        </div>
        <div className="pdb-modal-body">
          <p>Delete <code className="pdb-param-name">{name}</code>?</p>
          {impacted.length > 0 ? (
            <>
              <p style={{ color: '#475569' }}>
                This transducer is currently selected by {impacted.length} parameter{impacted.length === 1 ? '' : 's'}.
                Choose <strong>Clear &amp; Delete</strong> to remove these references first.
              </p>
              <div className="pdb-picker-list">
                {impacted.map((paramName) => (
                  <div key={paramName} className="pdb-picker-item pdb-picker-row">
                    <code className="pdb-param-name">{paramName}</code>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p style={{ color: '#475569' }}>
              No parameters currently reference this transducer.
            </p>
          )}
          {error && <div className="pdb-save-error">{error}</div>}
        </div>
        <div className="pdb-modal-footer">
          <button className="pdb-btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button
            className="pdb-btn-danger"
            onClick={onConfirmClearAndDelete}
            disabled={busy}
            title="Clear transducer_id from impacted parameters, then delete transducer"
          >
            {busy ? 'Working…' : impacted.length > 0 ? 'Clear & Delete' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function TransducersPanel({ fermenterId }) {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(Boolean(fermenterId));
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null);
  const [deleteState, setDeleteState] = useState(null);

  async function refresh() {
    if (!fermenterId) {
      setItems([]);
      setError('');
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const response = await fetchTransducers(fermenterId);
      setItems(Array.isArray(response?.transducers) ? response.transducers : []);
      setError('');
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [fermenterId]);

  const visible = useMemo(() => {
    const needle = String(filter || '').trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) => String(item?.name || '').toLowerCase().includes(needle));
  }, [items, filter]);

  async function _referencingParameters(name) {
    const transducerName = String(name || '').trim();
    if (!transducerName) return [];
    const response = await fetchParams(fermenterId);
    const params = response?.params ?? {};
    return Object.entries(params)
      .filter(([, record]) => String(record?.config?.transducer_id || '').trim() === transducerName)
      .map(([paramName]) => paramName)
      .sort((a, b) => a.localeCompare(b));
  }

  async function handleDelete(name) {
    if (!name) return;
    try {
      const impacted = await _referencingParameters(name);
      setDeleteState({
        name,
        impacted,
        busy: false,
        error: '',
      });
    } catch (err) {
      setError(String(err?.message || err));
    }
  }

  async function handleConfirmClearAndDelete() {
    if (!deleteState?.name) return;
    const transducerName = deleteState.name;
    setDeleteState((current) => ({ ...(current || {}), busy: true, error: '' }));
    try {
      if (deleteState.impacted.length > 0) {
        const response = await fetchParams(fermenterId);
        const params = response?.params ?? {};
        await Promise.all(
          deleteState.impacted.map((paramName) => {
            const currentConfig = { ...(params[paramName]?.config ?? {}) };
            currentConfig.transducer_id = '';
            return updateParamConfig(fermenterId, paramName, currentConfig);
          }),
        );
      }
      await deleteTransducer(fermenterId, transducerName);
      setDeleteState(null);
      await refresh();
    } catch (err) {
      setDeleteState((current) => ({
        ...(current || { name: transducerName, impacted: [] }),
        busy: false,
        error: String(err?.message || err),
      }));
    }
  }

  return (
    <div className="pdb-list-container">
      <div className="pdb-toolbar">
        <input
          className="pdb-input pdb-toolbar-filter"
          placeholder="Filter transducers…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <span style={{ fontSize: 12, color: '#64748b', flex: '0 0 auto' }}>{visible.length} / {items.length}</span>
        <div style={{ flex: 1 }} />
        <button className="pdb-btn-primary pdb-btn-sm" onClick={() => setModal({ mode: 'create', item: emptyDraft() })}>+ Add Transducer</button>
      </div>

      {error && <div className="pdb-page-error">{error}</div>}

      <div className="pdb-table-wrap">
        {loading ? (
          <div className="pdb-loading">Loading…</div>
        ) : (
          <table className="pdb-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Equation</th>
                <th>Limits</th>
                <th>Units</th>
                <th>Description</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.length === 0 && (
                <tr>
                  <td colSpan={6} className="pdb-empty">No transducers configured</td>
                </tr>
              )}
              {visible.map((item) => (
                <tr key={item.name}>
                  <td><code className="pdb-param-name">{item.name}</code></td>
                  <td>{item.equation || '—'}</td>
                  <td>{`${item.min_limit ?? '-'} → ${item.max_limit ?? '-'}`}</td>
                  <td>{`${item.input_unit || '-'} → ${item.output_unit || '-'}`}</td>
                  <td>{item.description || '—'}</td>
                  <td>
                    <div className="pdb-row-actions">
                      <button className="pdb-btn-ghost pdb-btn-sm" onClick={() => setModal({ mode: 'edit', item })}>Edit</button>
                      <button className="pdb-btn-danger pdb-btn-sm" onClick={() => handleDelete(item.name)}>Del</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {modal && (
        <TransducerModal
          mode={modal.mode}
          initial={modal.item}
          onClose={() => setModal(null)}
          onSave={async (item) => {
            if (modal.mode === 'create') {
              await createTransducer(fermenterId, item);
            } else {
              await updateTransducer(fermenterId, modal.item.name, item);
            }
            await refresh();
          }}
        />
      )}

      {deleteState && (
        <TransducerDeleteModal
          state={deleteState}
          onClose={() => {
            if (!deleteState.busy) setDeleteState(null);
          }}
          onConfirmClearAndDelete={handleConfirmClearAndDelete}
        />
      )}
    </div>
  );
}
