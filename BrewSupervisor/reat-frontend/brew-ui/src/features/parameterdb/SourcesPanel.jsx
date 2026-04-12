import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchSources, fetchSourceTypes, fetchSourceTypeUi,
  createSource, updateSource, deleteSource,
} from './loaders.js';
import { SchemaForm } from './SchemaForm.jsx';
import { buildFormData, buildSections, collectJsonFieldKeys, collectRequiredPaths, getByPath, setByPath } from './schemaUtils.js';
import { buildSourceInventory } from './graph/graphModel.js';

function SourceEditModal({ fermenterId, mode, record, sourceTypes, parameterNames, onSave, onClose }) {
  const isCreate = mode === 'create';
  const [sourceType, setSourceType] = useState(record?.source_type ?? Object.keys(sourceTypes ?? {})[0] ?? '');
  const [schemaUi, setSchemaUi] = useState(null);
  const sections = useMemo(() => buildSections(schemaUi, mode), [schemaUi, mode]);
  const [draft, setDraft] = useState({});
  const [jsonDrafts, setJsonDrafts] = useState({});
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadSchema() {
      if (!sourceType) return;
      try {
        const response = await fetchSourceTypeUi(fermenterId, sourceType, record?.name ?? null, mode);
        if (cancelled) return;
        const ui = response?.ui ?? null;
        setSchemaUi(ui);
        const nextDraft = buildFormData(ui, mode, record, 'source_type');
        setDraft(nextDraft);
        const nextJsonDrafts = {};
        collectJsonFieldKeys(buildSections(ui, mode)).forEach((key) => {
          nextJsonDrafts[key] = JSON.stringify(getByPath(nextDraft, key) ?? null, null, 2);
        });
        setJsonDrafts(nextJsonDrafts);
        setErrors({});
      } catch (err) {
        if (!cancelled) setErrors({ save: err?.message ?? String(err) });
      }
    }
    loadSchema();
    return () => { cancelled = true; };
  }, [fermenterId, sourceType, record, mode]);

  function handleFieldChange(field, rawValue) {
    setDraft((current) => {
      const next = JSON.parse(JSON.stringify(current));
      if (Array.isArray(rawValue)) setByPath(next, field.key, rawValue);
      else if (field.type === 'int') setByPath(next, field.key, rawValue === '' ? null : Number.parseInt(rawValue, 10));
      else if (field.type === 'float') setByPath(next, field.key, rawValue === '' ? null : Number.parseFloat(rawValue));
      else if (field.type === 'parameter_ref_list') setByPath(next, field.key, String(rawValue).split(',').map((item) => item.trim()).filter(Boolean));
      else setByPath(next, field.key, rawValue);
      return next;
    });
    setErrors((current) => {
      const next = { ...current };
      delete next[field.key];
      delete next.save;
      return next;
    });
  }

  async function handleSave() {
    const next = JSON.parse(JSON.stringify(draft));
    const nextErrors = {};
    collectJsonFieldKeys(sections).forEach((key) => {
      try {
        const raw = jsonDrafts[key];
        setByPath(next, key, raw == null || raw.trim() === '' ? null : JSON.parse(raw));
      } catch {
        nextErrors[key] = 'Invalid JSON';
      }
    });
    collectRequiredPaths(schemaUi, sections, next).forEach((key) => {
      const value = getByPath(next, key);
      if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) {
        nextErrors[key] = 'Required';
      }
    });
    if (Object.keys(nextErrors).length) {
      setErrors(nextErrors);
      return;
    }
    setSaving(true);
    try {
      await onSave({ name: next.name.trim(), source_type: sourceType, config: next.config ?? {} });
      onClose();
    } catch (err) {
      setErrors({ save: err?.message ?? 'Save failed' });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pdb-modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="pdb-modal pdb-modal-sm">
        <div className="pdb-modal-header">
          <h3>{isCreate ? 'Add Data Source' : `Edit — ${record?.name}`}</h3>
          <button className="pdb-close-btn" onClick={onClose}>✕</button>
        </div>
        <div className="pdb-modal-body">
          {isCreate && (
            <div className="pdb-field">
              <label className="pdb-label">Type</label>
              <select className="pdb-input" value={sourceType} onChange={e => setSourceType(e.target.value)}>
                {Object.entries(sourceTypes ?? {}).map(([k, spec]) => (
                  <option key={k} value={k}>{spec.display_name ?? k}</option>
                ))}
              </select>
            </div>
          )}
          {!isCreate && (
            <div className="pdb-field">
              <label className="pdb-label">Type</label>
              <div className="pdb-readonly">{record?.source_type}</div>
            </div>
          )}
          {schemaUi && (
            <SchemaForm
              fermenterId={fermenterId}
              sections={sections}
              data={draft}
              errors={errors}
              rawJson={jsonDrafts}
              parameterOptions={parameterNames}
              onFieldChange={handleFieldChange}
              onJsonChange={(key, value) => setJsonDrafts((current) => ({ ...current, [key]: value }))}
            />
          )}
          {errors.save && <div className="pdb-save-error">{errors.save}</div>}
        </div>
        <div className="pdb-modal-footer">
          <button className="pdb-btn-secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="pdb-btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function SourcesPanel({ fermenterId, parameterNames, params, graph }) {
  const [sources, setSources] = useState({});
  const [sourceTypes, setSourceTypes] = useState({});
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // null | {mode:'create'|'edit', record?:...}
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([fetchSources(fermenterId), fetchSourceTypes(fermenterId)]);
      setSources(s.sources ?? {});
      setSourceTypes(t.types ?? {});
      setError('');
    } catch (err) {
      setError(err?.message ?? 'Load failed');
    } finally {
      setLoading(false);
    }
  }, [fermenterId]);

  useEffect(() => { reload(); }, [reload]);

  async function handleSave({ name, source_type, config }) {
    if (modal?.mode === 'create') {
      await createSource(fermenterId, name, source_type, config);
    } else {
      await updateSource(fermenterId, modal.record.name, config);
    }
    await reload();
  }

  async function handleDelete(name, deleteOwnedParameters = false) {
    setDeleting(name);
    try {
      await deleteSource(fermenterId, name, { deleteOwnedParameters });
      setDeleteTarget(null);
      await reload();
    } catch (err) {
      setError(err?.message ?? 'Delete failed');
    } finally {
      setDeleting(null);
    }
  }

  const effectiveSources = useMemo(() => {
    const graphSources = graph?.sources;
    return graphSources && typeof graphSources === 'object' ? graphSources : sources;
  }, [graph?.sources, sources]);

  const sourceInventory = useMemo(() => buildSourceInventory(params, effectiveSources), [effectiveSources, params]);
  const rows = useMemo(() => Object.entries(sources), [sources]);

  return (
    <div className="pdb-sources-panel">
      <div className="pdb-toolbar">
        <button className="pdb-btn-primary" onClick={() => setModal({ mode: 'create' })}>+ Add Source</button>
        <button className="pdb-btn-ghost" onClick={reload}>↻ Refresh</button>
        {error && <span className="pdb-error-inline">{error}</span>}
      </div>
      {loading ? (
        <div className="pdb-loading">Loading sources…</div>
      ) : rows.length === 0 ? (
        <div className="pdb-empty">No data sources configured.</div>
      ) : (
        <table className="pdb-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Running</th>
              <th>Depends On</th>
              <th>Publishes</th>
              <th>Config</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, rec]) => (
              (() => {
                const sourceSummary = sourceInventory.get(name);
                const links = sourceSummary?.feedsFrom ?? [];
                const publishes = sourceSummary?.publishedParams ?? [];
                const sourceType = sourceSummary?.sourceType || rec.source_type;
                return (
                  <tr key={name}>
                    <td className="pdb-cell-name">{name}</td>
                    <td><span className="pdb-type-badge">{sourceType}</span></td>
                    <td>
                      <span className="pdb-status-indicator">
                        <span
                          className={`pdb-status-dot ${rec.running ? 'pdb-status-ok' : 'pdb-status-off'}`}
                          aria-hidden="true"
                        />
                        <span>{rec.running ? 'running' : 'stopped'}</span>
                      </span>
                    </td>
                    <td className="pdb-cell-deps">
                      {links.length
                        ? links.map((item) => <code key={item} className="pdb-dep-chip">{item}</code>)
                        : <span className="pdb-cell-nil">—</span>}
                    </td>
                    <td className="pdb-cell-deps">
                      {publishes.length
                        ? publishes.map((item) => <code key={item} className="pdb-dep-chip pdb-dep-chip-write">{item}</code>)
                        : <span className="pdb-cell-nil">—</span>}
                    </td>
                    <td className="pdb-cell-config" title={JSON.stringify(rec.config)}>
                      {JSON.stringify(rec.config).slice(0, 80)}
                    </td>
                    <td className="pdb-cell-actions">
                      <button className="pdb-btn-ghost pdb-btn-sm"
                        onClick={() => setModal({ mode: 'edit', record: { name, ...rec, source_type: sourceType } })}>Edit</button>
                      <button className="pdb-btn-danger pdb-btn-sm"
                        disabled={deleting === name}
                        onClick={() => { setDeleteTarget(name); setError(''); }}>
                        {deleting === name ? '…' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                );
              })()
            ))}
          </tbody>
        </table>
      )}
      {modal && (
        <SourceEditModal
          fermenterId={fermenterId}
          mode={modal.mode}
          record={modal.record}
          sourceTypes={sourceTypes}
          parameterNames={parameterNames}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {deleteTarget && (
        <div className="pdb-modal-overlay">
          <div className="pdb-modal pdb-modal-sm">
            <div className="pdb-modal-header">
              <span>Delete Source</span>
              <button className="pdb-close-btn" onClick={() => setDeleteTarget(null)}>✕</button>
            </div>
            <div className="pdb-modal-body">
              <p>Delete source <code className="pdb-param-name">{deleteTarget}</code>?</p>
              <p style={{ color: '#94a3b8', fontSize: 13 }}>
                Delete + Clean also removes parameters with metadata owner = {deleteTarget}.
              </p>
              {error && <div className="pdb-save-error">{error}</div>}
            </div>
            <div className="pdb-modal-footer">
              <button className="pdb-btn-danger" onClick={() => handleDelete(deleteTarget, false)} disabled={Boolean(deleting)}>
                {deleting === deleteTarget ? 'Deleting…' : 'Delete'}
              </button>
              <button className="pdb-btn-danger" onClick={() => handleDelete(deleteTarget, true)} disabled={Boolean(deleting)}>
                {deleting === deleteTarget ? 'Deleting…' : 'Delete + Clean'}
              </button>
              <button className="pdb-btn-secondary" onClick={() => setDeleteTarget(null)} disabled={Boolean(deleting)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
