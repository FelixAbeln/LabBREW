import { sourceColor, typeColor } from './graphModel.js';

export function GraphDetailPanel({ selected, graph, onClear }) {
  if (!selected) return null;
  const rawSignal = selected.signal_value ?? selected.signalValue;

  const isSourceNode = selected.kind === 'source';
  const deps = graph?.dependencies?.[selected.name] ?? [];
  const dependents = selected.name
    ? Object.entries(graph?.dependencies ?? {})
        .filter(([, ds]) => ds.includes(selected.name))
        .map(([n]) => n)
    : [];
  const writes = graph?.write_targets?.[selected.name] ?? [];
  const warnings = (graph?.warnings ?? []).filter((w) => String(w).includes(selected.name ?? '~~'));

  return (
    <div className="pdb-graph-detail">
      <div className="pdb-graph-detail-header">
        <span className="pdb-graph-detail-name" title={selected.name}>{selected.name}</span>
        <button className="pdb-close-btn pdb-close-btn-sm" onClick={onClear}>✕</button>
      </div>
      <div className="pdb-graph-detail-body">
        {isSourceNode ? (
          <>
            <div className="pdb-detail-row">
              <span className="pdb-detail-key">Type</span>
              <span className="pdb-type-badge" style={{ '--tc': sourceColor(selected.sourceType) }}>
                {selected.sourceType}
              </span>
            </div>
            {selected.device && (
              <div className="pdb-detail-row">
                <span className="pdb-detail-key">Device</span>
                <span className="pdb-detail-val">{selected.device}</span>
              </div>
            )}
            <div className="pdb-detail-row">
              <span className="pdb-detail-key">Publishes</span>
              <span className="pdb-detail-val">{selected.publishedCount}</span>
            </div>
            {selected.feedsFrom?.length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title">Depends On</div>
                {selected.feedsFrom.map((param) => <div key={param} className="pdb-detail-tag">{param}</div>)}
              </div>
            )}
            {selected.publishedParams?.length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title">Published Parameters</div>
                {selected.publishedParams.map((param) => <div key={param} className="pdb-detail-tag pdb-detail-tag-write">{param}</div>)}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="pdb-detail-row">
              <span className="pdb-detail-key">Type</span>
              <span className="pdb-type-badge" style={{ '--tc': typeColor(selected.paramType) }}>
                {selected.paramType}
              </span>
            </div>
            <div className="pdb-detail-row">
              <span className="pdb-detail-key">Value</span>
              <span className="pdb-detail-val">{String(selected.value)}</span>
            </div>
            {rawSignal !== undefined && rawSignal !== null && (() => {
              const isPrimitive = (v) => v === null || typeof v !== 'object';
              const pipelineActive = isPrimitive(rawSignal) && isPrimitive(selected.value) && rawSignal !== selected.value;
              return (
                <div className="pdb-detail-row">
                  <span className="pdb-detail-key" style={{ color: '#64748b' }}>Signal (raw)</span>
                  <span className="pdb-detail-val" style={{ color: pipelineActive ? '#f59e0b' : '#475569' }}>{String(rawSignal)}</span>
                </div>
              );
            })()}
            {selected.scanIndex !== null && (
              <div className="pdb-detail-row">
                <span className="pdb-detail-key">Scan #</span>
                <span className="pdb-detail-val">{selected.scanIndex}</span>
              </div>
            )}
            {deps.length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title">↑ Depends on</div>
                {deps.map((d) => <div key={d} className="pdb-detail-tag">{d}</div>)}
              </div>
            )}
            {dependents.length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title">↓ Used by</div>
                {dependents.map((d) => <div key={d} className="pdb-detail-tag">{d}</div>)}
              </div>
            )}
            {writes.length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title" style={{ color: '#f59e0b' }}>→ Writes to</div>
                {writes.map((d) => <div key={d} className="pdb-detail-tag pdb-detail-tag-write">{d}</div>)}
              </div>
            )}
            {warnings.length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title" style={{ color: '#ef4444' }}>Warnings</div>
                {warnings.map((w, i) => <div key={i} className="pdb-detail-warning">{w}</div>)}
              </div>
            )}
            {selected.config && Object.keys(selected.config).length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title">Config</div>
                <pre className="pdb-detail-pre">{JSON.stringify(selected.config, null, 2)}</pre>
              </div>
            )}
            {selected.state && Object.keys(selected.state).length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title">State</div>
                <pre className="pdb-detail-pre">{JSON.stringify(selected.state, null, 2)}</pre>
              </div>
            )}
            {selected.metadata && Object.keys(selected.metadata).length > 0 && (
              <div className="pdb-detail-section">
                <div className="pdb-detail-section-title">Metadata</div>
                <pre className="pdb-detail-pre">{JSON.stringify(selected.metadata, null, 2)}</pre>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
