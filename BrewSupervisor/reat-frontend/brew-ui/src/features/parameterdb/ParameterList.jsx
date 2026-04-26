import { useState } from 'react';
import { deleteParam } from './loaders.js';
import { ParameterEditModal } from './ParameterEditModal.jsx';

export function ParameterList({
  fermenterId,
  params,
  graph,
  paramTypes,
  pinnedTargets,
  pinBusyTarget,
  pinError,
  onTogglePin,
  onRefresh,
}) {
  const [filter, setFilter] = useState('');
  const [editTarget, setEditTarget] = useState(null);   // null | {name, rec} | 'create'
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const entries = Object.entries(params ?? {});
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? entries.filter(([n]) => n.toLowerCase().includes(needle))
    : entries;

  const deps = graph?.dependencies ?? {};
  const writes = graph?.write_targets ?? {};
  const scanOrder = graph?.scan_order ?? [];

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await deleteParam(fermenterId, deleteTarget);
      setDeleteTarget(null);
      onRefresh();
    } catch (e) {
      setDeleteError(String(e));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="pdb-list-container">
      {/* Toolbar */}
      <div className="pdb-toolbar">
        <input
          className="pdb-input pdb-toolbar-filter"
          placeholder="Filter parameters…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        <span style={{ fontSize: 12, color: '#64748b', flex: '0 0 auto' }}>
          {visible.length} / {entries.length}
        </span>
        <div style={{ flex: 1 }} />
        <button className="pdb-btn-primary pdb-btn-sm" onClick={() => setEditTarget('create')}>
          + Add Parameter
        </button>
      </div>
      {pinError && <div className="pdb-pin-error">Pin update failed: {pinError}</div>}

      {/* Table */}
      <div className="pdb-table-wrap">
        <table className="pdb-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Scan #</th>
              <th>Signal</th>
              <th>Value</th>
              <th>Depends on</th>
              <th>Used by</th>
              <th>Writes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr><td colSpan={8} className="pdb-empty">No parameters found</td></tr>
            )}
            {visible.map(([name, rec]) => {
              const scanIdx = scanOrder.indexOf(name);
              const paramDeps = deps[name] ?? [];
              const usedBy = entries.filter(([n]) => (deps[n] ?? []).includes(name)).map(([n]) => n);
              const writesTo = writes[name] ?? [];
              const reasons = rec?.state?.parameter_invalid_reasons ?? [];
              const isStaleOnly = rec?.state?.parameter_valid === false
                && reasons.length > 0
                && reasons.every(r => r === 'mirror_source_invalid' || r === 'datasource_silent' || r === 'dependency_stale');
              const isInvalid = !isStaleOnly && (Boolean(rec?.state?.invalid_config) || rec?.state?.parameter_valid === false || Boolean(rec?.state?.parameter_force_invalid));
              const displayValue = isInvalid
                ? '—'
                : (rec.value === null || rec.value === undefined ? '—' : String(rec.value));
              const hasSignal = !isInvalid && !isStaleOnly && rec.signal_value !== undefined && rec.signal_value !== null;
              const isPrimitive = (v) => v === null || typeof v !== 'object';
              const pipelineActive = hasSignal && isPrimitive(rec.signal_value) && isPrimitive(rec.value) && rec.signal_value !== rec.value;
              const displaySignal = hasSignal ? String(rec.signal_value) : '—';
              const isPinned = pinnedTargets instanceof Set ? pinnedTargets.has(name) : false;
              const pinBusy = pinBusyTarget === name;

              return (
                <tr key={name} className={`pdb-tr ${isInvalid ? 'pdb-tr-invalid' : ''} ${isStaleOnly ? 'pdb-tr-stale' : ''}`}>
                  <td className="pdb-cell-name">
                    <code className={`pdb-param-name ${isInvalid ? 'pdb-param-name-invalid' : ''}`}>{name}</code>
                  </td>
                  <td>
                    <span className="pdb-type-badge">{rec.parameter_type}</span>
                    {isInvalid && <span className="pdb-invalid-tag">invalid</span>}
                    {isStaleOnly && <span className="pdb-stale-tag" title={
                      reasons.includes('dependency_stale')
                        ? `Upstream stale: ${(rec?.state?.dependency_stale_parameters ?? []).join(', ') || '?'}`
                        : reasons.includes('datasource_silent')
                          ? 'Datasource stopped sending'
                          : `Mirror source invalid: ${rec?.state?.mirror_source ?? '?'}`
                    }>stale</span>}
                  </td>
                  <td className="pdb-cell-num">
                    {scanIdx >= 0 ? <span className="pdb-scan-idx">#{scanIdx}</span> : '—'}
                  </td>
                  <td className="pdb-cell-value">
                    {hasSignal ? (
                      <span
                        className={pipelineActive ? 'pdb-signal-str' : 'pdb-signal-str pdb-signal-passthrough'}
                        title={pipelineActive ? 'Raw signal before pipeline' : 'Signal (no pipeline active)'}
                      >{displaySignal}</span>
                    ) : (
                      <span className="pdb-cell-nil">—</span>
                    )}
                  </td>
                  <td className="pdb-cell-value">
                    <span className="pdb-value-str">
                      {displayValue}
                    </span>
                  </td>
                  <td className="pdb-cell-deps">
                    {paramDeps.length > 0
                      ? paramDeps.map(d => <code key={d} className="pdb-dep-chip">{d}</code>)
                      : <span className="pdb-cell-nil">—</span>}
                  </td>
                  <td className="pdb-cell-deps">
                    {usedBy.length > 0
                      ? usedBy.map(d => <code key={d} className="pdb-dep-chip">{d}</code>)
                      : <span className="pdb-cell-nil">—</span>}
                  </td>
                  <td className="pdb-cell-deps">
                    {writesTo.length > 0
                      ? writesTo.map(d => <code key={d} className="pdb-dep-chip pdb-dep-chip-write">{d}</code>)
                      : <span className="pdb-cell-nil">—</span>}
                  </td>
                  <td className="pdb-cell-actions">
                    <div className="pdb-action-group">
                      <button
                        className={`pdb-btn-ghost pdb-btn-sm ${isPinned ? 'pdb-btn-pin-active' : ''}`}
                        onClick={() => onTogglePin?.(name, isPinned)}
                        disabled={Boolean(pinBusyTarget)}
                        title={isPinned ? 'Remove from custom manual controls' : 'Add to custom manual controls'}
                      >
                        {pinBusy ? '…' : isPinned ? 'Unpin' : 'Pin'}
                      </button>
                      <button
                        className="pdb-btn-ghost pdb-btn-sm"
                        onClick={() => setEditTarget({ name, rec })}
                        title="Edit parameter"
                      >Edit</button>
                      <button
                        className="pdb-btn-danger pdb-btn-sm"
                        onClick={() => { setDeleteTarget(name); setDeleteError(''); }}
                        title="Delete parameter"
                      >Del</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Edit / Create modal */}
      {editTarget && (
        <ParameterEditModal
          key={editTarget === 'create' ? `create:${fermenterId}` : `edit:${fermenterId}:${editTarget.name}`}
          fermenterId={fermenterId}
          mode={editTarget === 'create' ? 'create' : 'edit'}
          record={editTarget === 'create' ? null : { name: editTarget.name, ...editTarget.rec }}
          paramTypes={paramTypes}
          parameterNames={entries.map(([name]) => name)}
          onClose={() => setEditTarget(null)}
          onSaved={() => { setEditTarget(null); onRefresh(); }}
        />
      )}

      {/* Delete confirmation */}
      {deleteTarget && (
        <div className="pdb-modal-overlay">
          <div className="pdb-modal pdb-modal-sm">
            <div className="pdb-modal-header">
              <span>Delete Parameter</span>
              <button className="pdb-close-btn" onClick={() => setDeleteTarget(null)}>✕</button>
            </div>
            <div className="pdb-modal-body">
              <p>Delete <code className="pdb-param-name">{deleteTarget}</code>?</p>
              <p style={{ color: '#94a3b8', fontSize: 13 }}>
                Any parameters that depend on it will produce graph warnings.
              </p>
              {deleteError && <div className="pdb-save-error">{deleteError}</div>}
            </div>
            <div className="pdb-modal-footer">
              <button className="pdb-btn-secondary" onClick={() => setDeleteTarget(null)}>Cancel</button>
              <button className="pdb-btn-danger" onClick={handleDelete} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
