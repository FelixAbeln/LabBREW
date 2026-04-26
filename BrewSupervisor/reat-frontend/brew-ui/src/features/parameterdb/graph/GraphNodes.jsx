import { Handle, Position } from '@xyflow/react';
import { NODE_W, PARAM_NODE_H, SOURCE_NODE_H, sourceColor, typeColor } from './graphModel.js';
import { isInvalidState, isStaleOnlyState } from '../stateFlags.js';

export function ParameterNode({ data, selected }) {
  const { name, paramType, value, signalValue, signal_value, scanIndex, hasWarning, invalidConfig } = data;
  const rawSignal = signalValue ?? signal_value;
  const hasInvalidOverride = Boolean(data?.state?.parameter_force_invalid);
  const isStaleOnly = isStaleOnlyState(data?.state, { hasInvalidOverride });
  const invalidState = isInvalidState(data?.state, { invalidConfig, hasInvalidOverride });
  const color = typeColor(paramType);
  const accent = invalidState ? '#ef4444' : (isStaleOnly ? '#f59e0b' : color);
  const shortName = name.length > 26 ? '…' + name.slice(-24) : name;
  const valStr = invalidState ? '—' : (value === null || value === undefined ? '—' : String(value).slice(0, 18));
  // Show raw signal: highlighted when pipeline has changed the value, dimmed when passthrough
  const hasSignal = !invalidState && rawSignal !== undefined && rawSignal !== null;
  const isPrimitive = (v) => v === null || typeof v !== 'object';
  const pipelineActive = hasSignal && isPrimitive(rawSignal) && isPrimitive(value) && rawSignal !== value;
  const sigStr = hasSignal ? String(rawSignal).slice(0, 18) : null;
  const isActive = selected || data.isSelected;
  const isRelated = data.isRelated;
  const isDimmed = data.isDimmed;
  const nodeClassName = [
    'pdb-graph-param-node',
    isActive ? 'is-active' : '',
    isRelated ? 'is-related' : '',
    isDimmed ? 'is-dimmed' : '',
    invalidState ? 'is-invalid' : '',
    isStaleOnly ? 'is-stale' : '',
    hasWarning ? 'has-warning' : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={nodeClassName}
      style={{ '--pdb-accent': accent, '--pdb-node-w': `${NODE_W}px`, '--pdb-node-h': `${PARAM_NODE_H}px` }}
    >
      <Handle type="target" position={Position.Top} style={{ background: accent, width: 8, height: 8 }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', wordBreak: 'break-all' }} title={name}>
          {shortName}
        </span>
        {scanIndex !== null && (
          <span style={{ fontSize: 10, color: accent, marginLeft: 4, flex: '0 0 auto' }}>#{scanIndex}</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
        <span
          style={{
            fontSize: 10,
            background: accent + '33',
            color: accent,
            borderRadius: 4,
            padding: '1px 5px',
            flex: '0 0 auto',
          }}
        >
          {paramType}
        </span>
        <span style={{ fontSize: 11, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {valStr}
        </span>
        {invalidState && <span title="Parameter invalid" style={{ fontSize: 12, flex: '0 0 auto' }}>⛔</span>}
        {isStaleOnly && <span title="Parameter stale" style={{ fontSize: 12, flex: '0 0 auto' }}>⏸</span>}
        {hasWarning && <span title="Graph warning" style={{ fontSize: 12, flex: '0 0 auto' }}>⚠️</span>}
      </div>
      {sigStr && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
          <span style={{ fontSize: 9, color: '#64748b', flex: '0 0 auto' }}>raw</span>
          <span style={{ fontSize: 10, color: pipelineActive ? '#f59e0b' : '#475569', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {sigStr}
          </span>
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: accent, width: 8, height: 8 }} />
    </div>
  );
}

export function SourceNode({ data, selected }) {
  const color = sourceColor(data.sourceType);
  const title = data.name.length > 26 ? '…' + data.name.slice(-24) : data.name;
  const isActive = selected || data.isSelected;
  const isRelated = data.isRelated;
  const isDimmed = data.isDimmed;
  return (
    <div
      style={{
        width: NODE_W,
        minHeight: SOURCE_NODE_H,
        border: `2px dashed ${isActive ? '#fff' : color}`,
        borderRadius: 8,
        background: isActive ? '#221b11' : isRelated ? '#1c160d' : '#16110b',
        padding: '8px 10px',
        boxShadow: isActive ? `0 0 0 2px ${color}` : isRelated ? `0 0 0 1px ${color}66` : 'none',
        opacity: isDimmed ? 0.28 : 1,
        transition: 'opacity 0.15s ease, box-shadow 0.15s ease, background 0.15s ease',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color, width: 8, height: 8 }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontSize: 11, color: '#f8fafc', fontFamily: 'monospace', wordBreak: 'break-all' }} title={data.name}>
          {title}
        </span>
        <span style={{ fontSize: 10, color }}>{data.publishedCount} pub</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
        <span
          style={{
            fontSize: 10,
            background: `${color}33`,
            color,
            borderRadius: 4,
            padding: '1px 5px',
            flex: '0 0 auto',
          }}
        >
          {data.sourceType}
        </span>
        {data.device && (
          <span style={{ fontSize: 11, color: '#cbd5e1', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {data.device}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: color, width: 8, height: 8 }} />
    </div>
  );
}

