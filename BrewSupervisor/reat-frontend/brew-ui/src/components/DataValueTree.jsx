import { useState } from 'react'
import { stringifyDataValue } from '../features/data/dataValueUtils'

function JsonTreeNode({ label = null, value, depth = 0, defaultExpanded = false }) {
  const isObject = value !== null && typeof value === 'object'
  const isArray = Array.isArray(value)
  const entries = isObject ? (isArray ? value.map((item, index) => [String(index), item]) : Object.entries(value)) : []
  const [expanded, setExpanded] = useState(defaultExpanded)

  if (!isObject) {
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    return (
      <div className="json-node" style={{ '--json-depth': depth }}>
        {label !== null && <span className="json-key">{label}</span>}
        {label !== null && <span className="json-sep">: </span>}
        <span className={`json-leaf ${value === null ? 'is-null' : typeof value === 'string' ? 'is-string' : ''}`}>{text}</span>
      </div>
    )
  }

  const summary = isArray ? `array(${entries.length})` : `object(${entries.length})`

  return (
    <div className="json-node" style={{ '--json-depth': depth }}>
      <button
        type="button"
        className={`json-node-toggle ${expanded ? 'is-open' : ''}`}
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="json-node-arrow">{expanded ? '▼' : '▶'}</span>
        {label !== null && <span className="json-key">{label}</span>}
        {label !== null && <span className="json-sep">: </span>}
        <span className="json-summary">{summary}</span>
      </button>
      {expanded && (
        <div className="json-children">
          {entries.length ? entries.map(([childKey, childValue]) => (
            <JsonTreeNode
              key={childKey}
              label={childKey}
              value={childValue}
              depth={depth + 1}
            />
          )) : <div className="json-node-empty">empty</div>}
        </div>
      )}
    </div>
  )
}

export function ExpandedDataValue({ value }) {
  if (value !== null && typeof value === 'object') {
    return (
      <div className="json-scroll json-tree">
        <JsonTreeNode value={value} defaultExpanded />
      </div>
    )
  }

  return <span className="data-value-text is-expanded">{stringifyDataValue(value)}</span>
}
