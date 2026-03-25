import { Handle, Position } from '@xyflow/react';
import { sourceColor, typeColor } from './graphModel.js';

const NODE_W = 220;
const NODE_H = 72;

function ParameterNode({ data, selected }) {
  const { name, paramType, value, scanIndex, hasWarning } = data;
  const color = typeColor(paramType);
  const shortName = name.length > 26 ? '…' + name.slice(-24) : name;
  const valStr = value === null || value === undefined ? '—' : String(value).slice(0, 18);
  const isActive = selected || data.isSelected;
  const isRelated = data.isRelated;
  const isDimmed = data.isDimmed;

  return (
    <div
      style={{
        width: NODE_W,
        height: NODE_H,
        border: `2px solid ${hasWarning ? '#f59e0b' : isActive ? '#fff' : color}`,
        borderRadius: 8,
        background: isActive ? '#1e293b' : isRelated ? '#142033' : '#0f172a',
        padding: '6px 10px',
        cursor: 'pointer',
        boxShadow: isActive ? `0 0 0 2px ${color}` : isRelated ? `0 0 0 1px ${color}66` : 'none',
        position: 'relative',
        opacity: isDimmed ? 0.28 : 1,
        transition: 'opacity 0.15s ease, box-shadow 0.15s ease, background 0.15s ease',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color, width: 8, height: 8 }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', wordBreak: 'break-all' }} title={name}>
          {shortName}
        </span>
        {scanIndex !== null && (
          <span style={{ fontSize: 10, color, marginLeft: 4, flex: '0 0 auto' }}>#{scanIndex}</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
        <span
          style={{
            fontSize: 10,
            background: color + '33',
            color,
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
        {hasWarning && <span title="Graph warning" style={{ fontSize: 12, flex: '0 0 auto' }}>⚠️</span>}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: color, width: 8, height: 8 }} />
    </div>
  );
}

function SourceNode({ data, selected }) {
  const color = sourceColor(data.sourceType);
  const title = data.name.length > 26 ? '…' + data.name.slice(-24) : data.name;
  const isActive = selected || data.isSelected;
  const isRelated = data.isRelated;
  const isDimmed = data.isDimmed;
  return (
    <div
      style={{
        width: NODE_W,
        minHeight: NODE_H,
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

export const nodeTypes = { parameter: ParameterNode, source: SourceNode };
