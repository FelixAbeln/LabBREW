import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchSources, fetchSourceTypes, fetchSourceTypeUi,
  createSource, updateSource, deleteSource, invokeSourceTypeModuleAction,
} from './loaders.js';
import { SchemaForm } from './SchemaForm.jsx';
import { buildFormData, buildSections, collectJsonFieldKeys, collectRequiredPaths, getByPath, setByPath } from './schemaUtils.js';
import { buildSourceInventory } from './graph/graphModel.js';

function buildModuleState(moduleSpec, draft) {
  const fields = Array.isArray(moduleSpec?.menu?.fields) ? moduleSpec.menu.fields : [];
  const next = {};
  fields.forEach((field) => {
    const key = String(field?.key ?? '').trim();
    if (!key) return;
    const configKey = String(field?.config_key || key);
    const fromDraft = draft?.config?.[configKey];
    if (fromDraft !== undefined && fromDraft !== null && fromDraft !== '') {
      next[key] = fromDraft;
      return;
    }
    if (field?.default !== undefined) {
      next[key] = field.default;
      return;
    }
    next[key] = field?.type === 'string' ? '' : null;
  });
  return next;
}

function SourceModulePanel({ fermenterId, sourceType, sourceName, moduleSpec, draft, onApplyConfig }) {
  const [moduleState, setModuleState] = useState(() => buildModuleState(moduleSpec, draft));
  const [resultItems, setResultItems] = useState([]);
  const [lastScannedCount, setLastScannedCount] = useState(null);
  const [moduleWarnings, setModuleWarnings] = useState([]);
  const [moduleError, setModuleError] = useState('');
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setModuleState(buildModuleState(moduleSpec, draft));
  }, [moduleSpec, draft]);

  const fields = Array.isArray(moduleSpec?.menu?.fields) ? moduleSpec.menu.fields : [];
  const actionSpec = moduleSpec?.menu?.action ?? null;
  const resultSpec = useMemo(() => {
    if (moduleSpec?.menu?.result && typeof moduleSpec.menu.result === 'object') {
      return moduleSpec.menu.result;
    }
    return {};
  }, [moduleSpec]);
  const runSpec = moduleSpec?.menu?.run && typeof moduleSpec.menu.run === 'object' ? moduleSpec.menu.run : {};
  const runMode = String(runSpec?.mode || 'manual').trim().toLowerCase();
  const autoRun = runMode === 'auto';
  const suppressWarnings = Boolean(moduleSpec?.menu?.suppress_warnings);
  const preserveResults = Boolean(moduleSpec?.menu?.preserve_results);
  const pollIntervalSeconds = Number(runSpec?.poll_interval_s ?? 0);
  const pollIntervalMs = Number.isFinite(pollIntervalSeconds) && pollIntervalSeconds > 0
    ? pollIntervalSeconds * 1000
    : 0;
  const requestTimeoutSeconds = Number(runSpec?.request_timeout_s ?? 8);
  const requestTimeoutMs = Number.isFinite(requestTimeoutSeconds) && requestTimeoutSeconds > 0
    ? requestTimeoutSeconds * 1000
    : 8000;
  const cancelInflightOnCleanup = runSpec?.cancel_inflight_on_cleanup === undefined
    ? true
    : Boolean(runSpec.cancel_inflight_on_cleanup);
  const hasFermenterId = typeof fermenterId === 'string' && fermenterId.trim().length > 0;

  const runAction = useCallback(async (signal) => {
    const actionName = String(actionSpec?.action || actionSpec?.id || '').trim();
    if (!actionName || !hasFermenterId) return;
    const abortSignal = (typeof AbortSignal !== 'undefined' && signal instanceof AbortSignal)
      ? signal
      : null;
    const requestController = new AbortController();
    const timeoutId = setTimeout(() => requestController.abort(), requestTimeoutMs);
    let detachExternalAbort = null;
    if (abortSignal) {
      const onExternalAbort = () => requestController.abort();
      abortSignal.addEventListener('abort', onExternalAbort, { once: true });
      detachExternalAbort = () => abortSignal.removeEventListener('abort', onExternalAbort);
    }
    setRunning(true);
    setModuleError('');
    setModuleWarnings([]);
    try {
      const response = await invokeSourceTypeModuleAction(
        fermenterId,
        sourceType,
        actionName,
        moduleState,
        sourceName,
        requestController.signal,
      );
      const listKey = String(resultSpec.list_key || 'candidates');
      const items = Array.isArray(response?.result?.[listKey]) ? response.result[listKey] : [];
      if (preserveResults) {
        const keyFields = Array.isArray(resultSpec?.key_fields) ? resultSpec.key_fields : [];
        const titleKey = String(resultSpec?.title_key || 'host');
        const buildResultKey = (item) => {
          if (keyFields.length > 0) {
            return keyFields.map((field) => String(item?.[field] ?? '')).join('||');
          }
          return String(item?.[titleKey] ?? '');
        };
        setResultItems((previous) => {
          const merged = new Map();
          previous.forEach((item) => merged.set(buildResultKey(item), item));
          items.forEach((item) => merged.set(buildResultKey(item), item));
          return Array.from(merged.values());
        });
      } else {
        setResultItems(items);
      }
      setLastScannedCount(Number(response?.result?.scanned ?? 0));
      setModuleWarnings(Array.isArray(response?.result?.warnings) ? response.result.warnings : []);
    } catch (err) {
      const message = String(err?.message ?? '');
      const isAbortError = err?.name === 'AbortError' || /aborted/i.test(message);
      const isTransientFermenterLookup = /fermenter not found/i.test(message);
      if (isAbortError || isTransientFermenterLookup) return;
      setModuleError(err?.message ?? 'Module action failed');
      setResultItems([]);
      setLastScannedCount(null);
      setModuleWarnings([]);
    } finally {
      clearTimeout(timeoutId);
      if (detachExternalAbort) detachExternalAbort();
      setRunning(false);
    }
  }, [actionSpec?.action, actionSpec?.id, hasFermenterId, fermenterId, moduleState, preserveResults, requestTimeoutMs, resultSpec, sourceName, sourceType]);

  useEffect(() => {
    if (!autoRun || !actionSpec?.action || !hasFermenterId) return;
    const controller = new AbortController();
    let timerId = null;

    async function scanLoop() {
      if (controller.signal.aborted) return;
      await runAction(controller.signal);
      if (controller.signal.aborted || pollIntervalMs <= 0) return;
      timerId = setTimeout(scanLoop, pollIntervalMs);
    }

    scanLoop();
    return () => {
      if (cancelInflightOnCleanup) controller.abort();
      if (timerId) clearTimeout(timerId);
    };
  }, [autoRun, actionSpec?.action, cancelInflightOnCleanup, hasFermenterId, pollIntervalMs, runAction]);

  function applyResultItem(item) {
    const applyMap = resultSpec?.apply_map;
    if (!applyMap || typeof applyMap !== 'object') return;
    const patch = {};
    Object.entries(applyMap).forEach(([configKey, itemKey]) => {
      if (typeof itemKey !== 'string') return;
      if (item[itemKey] !== undefined) patch[configKey] = item[itemKey];
    });
    onApplyConfig(patch);
  }

  function valuesMatch(left, right) {
    if (left == null && right == null) return true;
    if (left == null || right == null) return false;
    return String(left) === String(right);
  }

  function isItemSelected(item) {
    const applyMap = resultSpec?.apply_map;
    if (!applyMap || typeof applyMap !== 'object') return false;
    const pairs = Object.entries(applyMap).filter(([, itemKey]) => typeof itemKey === 'string');
    if (!pairs.length) return false;
    const config = draft?.config ?? {};
    return pairs.every(([configKey, itemKey]) => valuesMatch(config?.[configKey], item?.[itemKey]));
  }

  if (!actionSpec?.action) {
    return null;
  }

  return (
    <div className="pdb-source-module">
      <div className="pdb-source-module-header">
        <h4>{moduleSpec?.display_name || 'Source Module'}</h4>
        <span>{moduleSpec?.description || ''}</span>
      </div>
      <div className="pdb-source-module-controls">
        {fields.map((field) => {
          const key = String(field?.key ?? '').trim();
          if (!key) return null;
          const type = String(field?.type || 'string');
          const configKey = String(field?.config_key || key);
          const value = moduleState[key] ?? '';
          const onFieldChange = (raw) => {
            const parsed = type === 'int'
              ? (raw === '' ? null : Number.parseInt(raw, 10))
              : type === 'float'
                ? (raw === '' ? null : Number.parseFloat(raw))
                : raw;
            setModuleState((current) => ({
              ...current,
              [key]: parsed,
            }));
            onApplyConfig({ [configKey]: parsed });
          };

          if (type === 'enum') {
            const choices = Array.isArray(field?.choices) ? field.choices : [];
            return (
              <select
                key={key}
                className="pdb-input"
                value={String(value ?? '')}
                onChange={(e) => onFieldChange(e.target.value)}
              >
                {choices.map((choice) => {
                  const text = String(choice);
                  return <option key={text} value={text}>{text}</option>;
                })}
              </select>
            );
          }

          return (
            <input
              key={key}
              className="pdb-input"
              type={type === 'int' || type === 'float' ? 'number' : 'text'}
              step={type === 'float' ? 'any' : undefined}
              min={field?.min ?? undefined}
              placeholder={field?.label || key}
              value={value}
              onChange={(e) => onFieldChange(e.target.value)}
            />
          );
        })}
        {!autoRun && (
          <button className="pdb-btn-primary" onClick={() => runAction(null)} disabled={running || !hasFermenterId}>
            {running ? 'Running…' : String(actionSpec.label || 'Run')}
          </button>
        )}
      </div>
      {!suppressWarnings && moduleWarnings.length > 0 && (
        <div className="pdb-field-help">{moduleWarnings.join(' | ')}</div>
      )}
      {moduleError && <div className="pdb-save-error">{moduleError}</div>}
      {!moduleError && lastScannedCount !== null && resultItems.length === 0 && (
        <div className="pdb-field-help">{String(resultSpec?.empty_message || `Scanned ${lastScannedCount} targets, no devices discovered.`)}</div>
      )}
      {resultItems.length > 0 && (
        <div className="pdb-source-module-results">
          {resultItems.map((item, index) => {
            const titleKey = String(resultSpec?.title_key || 'host');
            const subtitleKeys = Array.isArray(resultSpec?.subtitle_keys) ? resultSpec.subtitle_keys : [];
            const statusKey = String(resultSpec?.status_key || 'reachable');
            const errorKey = String(resultSpec?.error_key || 'error');
            const title = String(item?.[titleKey] ?? `item-${index + 1}`);
            const subtitle = subtitleKeys
              .map((k) => String(item?.[k] ?? '').trim())
              .filter(Boolean)
              .join(' · ');
            const status = Boolean(item?.[statusKey]);
            const selected = isItemSelected(item);
            return (
              <div key={`${title}-${index}`} className={`pdb-source-module-card${selected ? ' is-selected' : ''}`}>
                <div>
                  <strong>{title}</strong>
                  {subtitle && <span>{subtitle}</span>}
                </div>
                <div>
                  {selected ? (
                    <span className="pdb-type-badge pdb-type-badge-selected">selected</span>
                  ) : status ? (
                    <span className="pdb-type-badge">ready</span>
                  ) : (
                    <span className="pdb-error-inline">{String(item?.[errorKey] || 'unavailable')}</span>
                  )}
                </div>
                <button
                  className={`pdb-btn-ghost pdb-btn-sm${selected ? ' pdb-btn-ghost-selected' : ''}`}
                  disabled={!status || selected}
                  onClick={() => applyResultItem(item)}
                >
                  {selected ? 'Selected' : String(resultSpec?.apply_label || 'Apply')}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

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

  function handleApplyConfigPatch(configPatch) {
    setDraft((current) => {
      const next = JSON.parse(JSON.stringify(current));
      next.config = { ...(next.config ?? {}), ...(configPatch ?? {}) };
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
            <>
              {schemaUi?.module && (
                <SourceModulePanel
                  fermenterId={fermenterId}
                  sourceType={sourceType}
                  sourceName={record?.name ?? null}
                  moduleSpec={schemaUi.module}
                  draft={draft}
                  onApplyConfig={handleApplyConfigPatch}
                />
              )}
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
            </>
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
  const [toggleBusy, setToggleBusy] = useState('');
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

  async function handleToggleEnabled(name, record) {
    if (!name || !record || toggleBusy) {
      return;
    }
    const nextEnabled = !(record.enabled !== false);
    setToggleBusy(name);
    try {
      await updateSource(fermenterId, name, {
        ...(record.config ?? {}),
        enabled: nextEnabled,
      });
      await reload();
    } catch (err) {
      setError(err?.message ?? 'Toggle failed');
    } finally {
      setToggleBusy('');
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
                const enabled = rec.enabled !== false;
                const running = Boolean(rec.running);
                const statusLabel = running ? 'running' : 'stopped';
                return (
                  <tr key={name}>
                    <td className="pdb-cell-name">{name}</td>
                    <td><span className="pdb-type-badge">{sourceType}</span></td>
                    <td>
                      <span className="pdb-status-indicator">
                        <span
                          className={`pdb-status-dot ${running ? 'pdb-status-ok' : 'pdb-status-off'}`}
                          aria-hidden="true"
                        />
                        <span>{statusLabel}</span>
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
                      <button
                        className="pdb-btn-ghost pdb-btn-sm"
                        disabled={toggleBusy === name || deleting === name}
                        onClick={() => handleToggleEnabled(name, rec)}
                      >
                        {toggleBusy === name ? '…' : (enabled ? 'Disable' : 'Enable')}
                      </button>
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
                Delete + Clean also removes parameters created by this data source (for example, matching owner = {deleteTarget} and created_by = "data_source"; source type may also apply). Manually created parameters are not removed just because the owner matches.
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
