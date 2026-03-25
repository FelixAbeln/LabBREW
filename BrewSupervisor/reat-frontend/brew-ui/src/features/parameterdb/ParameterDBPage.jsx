import { useEffect, useRef, useState, useCallback } from 'react';
import { fetchParams, fetchGraph, fetchStats, fetchParamTypes } from './loaders.js';
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
  const [error, setError] = useState('');
  const pollRef = useRef(null);

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
