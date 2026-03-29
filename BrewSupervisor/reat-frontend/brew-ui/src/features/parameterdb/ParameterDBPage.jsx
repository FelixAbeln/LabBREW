import { useEffect, useRef, useState, useCallback } from 'react';
import { exportSnapshotFile, fetchParams, fetchGraph, fetchStats, fetchParamTypes, importSnapshotFile } from './loaders.js';
import { ParameterList } from './ParameterList.jsx';
import { ParameterGraph } from './ParameterGraph.jsx';
import { SourcesPanel } from './SourcesPanel.jsx';

const POLL_MS = 2500;

export function ParameterDBPage({ fermenterId, fermenterName, onClose }) {
  const [view, setView] = useState('params');   // 'params' | 'graph' | 'sources'
  const [params, setParams] = useState({});
  const [graph, setGraph] = useState(null);
  const [stats, setStats] = useState(null);
  const [paramTypes, setParamTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef(null);
  const snapshotFileInputRef = useRef(null);

  // Initial load of static data (types)
  useEffect(() => {
    if (!fermenterId) return;
    fetchParamTypes(fermenterId)
      .then(r => setParamTypes(r?.types ?? []))
      .catch(() => {});
  }, [fermenterId]);

  const refresh = useCallback(async () => {
    if (!fermenterId) return;
    try {
      const [pRes, gRes, sRes] = await Promise.all([
        fetchParams(fermenterId),
        fetchGraph(fermenterId),
        fetchStats(fermenterId),
      ]);
      setParams(pRes?.params ?? {});
      setGraph(gRes?.graph ?? null);
      setStats(sRes?.stats ?? null);
      setError('');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [fermenterId]);

  // Polling
  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [refresh]);

  const modeLabel = stats
    ? `${stats.scan_mode ?? '–'}  ${stats.hz != null ? `${stats.hz.toFixed(1)} Hz` : ''}`
    : null;

  const utilPct = stats?.utilization != null ? Math.round(stats.utilization * 100) : null;
  const overruns = stats?.overruns ?? 0;

  async function handleExportSnapshot() {
    if (!fermenterId || snapshotBusy) return;
    setSnapshotBusy(true);
    try {
      const response = await exportSnapshotFile(fermenterId);
      const snapshot = response?.snapshot;
      if (!snapshot || typeof snapshot !== 'object') {
        throw new Error('Snapshot export returned no snapshot payload');
      }
      const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${fermenterId || 'parameterdb'}-snapshot.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setError('');
    } catch (e) {
      setError(String(e));
    } finally {
      setSnapshotBusy(false);
    }
  }

  async function handleImportSnapshot(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !fermenterId || snapshotBusy) return;

    setSnapshotBusy(true);
    try {
      const text = await file.text();
      const snapshot = JSON.parse(text);
      await importSnapshotFile(fermenterId, snapshot, { replaceExisting: true, saveToDisk: true });
      await refresh();
      setError('');
    } catch (e) {
      setError(`Snapshot import failed: ${String(e)}`);
    } finally {
      setSnapshotBusy(false);
    }
  }

  return (
    <div className="pdb-page">
      {/* Page Header */}
      <div className="pdb-page-header">
        <div className="pdb-page-title">
          <span className="pdb-page-icon">⬡</span>
          <span>ParameterDB</span>
          {fermenterName && <span className="pdb-page-mode">{fermenterName}</span>}
          {modeLabel && <span className="pdb-page-mode">{modeLabel}</span>}
          {utilPct !== null && (
            <span className={`pdb-page-util ${utilPct > 80 ? 'pdb-util-warn' : ''}`}>
              {utilPct}% util
            </span>
          )}
          {overruns > 0 && (
            <span className="pdb-util-warn pdb-page-util">⚠ {overruns} overruns</span>
          )}
        </div>
        <div className="pdb-page-actions">
          <input
            ref={snapshotFileInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden-file-input"
            onChange={handleImportSnapshot}
          />
          <button className="pdb-btn-ghost pdb-btn-sm" onClick={handleExportSnapshot} disabled={snapshotBusy} title="Download current snapshot">
            {snapshotBusy ? '…' : 'Export Snapshot'}
          </button>
          <button
            className="pdb-btn-ghost pdb-btn-sm"
            onClick={() => snapshotFileInputRef.current?.click()}
            disabled={snapshotBusy}
            title="Replace database from snapshot file"
          >
            {snapshotBusy ? '…' : 'Import Snapshot'}
          </button>
          <button className="pdb-btn-ghost pdb-btn-sm" onClick={refresh} title="Refresh">
            ↺ Refresh
          </button>
          <button className="pdb-close-btn" onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      {/* View tabs */}
      <div className="pdb-view-tabs">
        {['params', 'graph', 'sources'].map(v => (
          <button
            key={v}
            className={`pdb-view-tab ${view === v ? 'pdb-view-tab-active' : ''}`}
            onClick={() => setView(v)}
          >
            {v === 'params' ? 'Parameters' : v === 'graph' ? 'Graph' : 'Sources'}
          </button>
        ))}
        <span style={{ marginLeft: 12, fontSize: 12, color: '#475569', alignSelf: 'center' }}>
          {Object.keys(params).length} params
        </span>
      </div>

      {/* Error */}
      {error && (
        <div className="pdb-page-error">
          ParameterDB unavailable: {error}
        </div>
      )}

      {/* Content */}
      <div className="pdb-page-body">
        {loading ? (
          <div className="pdb-loading">Loading…</div>
        ) : view === 'params' ? (
          <ParameterList
            fermenterId={fermenterId}
            params={params}
            graph={graph}
            paramTypes={paramTypes}
            onRefresh={refresh}
          />
        ) : view === 'graph' ? (
          <ParameterGraph fermenterId={fermenterId} params={params} graph={graph} />
        ) : (
          <SourcesPanel fermenterId={fermenterId} parameterNames={Object.keys(params)} params={params} />
        )}
      </div>
    </div>
  );
}
