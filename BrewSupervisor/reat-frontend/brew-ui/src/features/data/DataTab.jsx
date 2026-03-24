import { useMemo, useState } from 'react'
import { ExpandedDataValue } from '../../components/DataValueTree'
import {
  formatCollapsedDataValue,
  shouldCollapseDataValue,
  stringifyDataValue,
} from './dataValueUtils'

export function DataTab({
  dataServiceHealthy,
  isRecording,
  dataServiceStatus,
  dataHz,
  setDataHz,
  dataActionLoading,
  selectedStarredParams,
  loadstepSeconds,
  setLoadstepSeconds,
  isTakingLoadstep,
  isLoadstepDurationValid,
  loadstepRemainingSeconds,
  toggleMeasurementRecording,
  takeDataLoadstep,
  latestCompletedLoadstep,
  latestLoadstepEntries,
  rulesSnapshot,
  starredParams,
  toggleStarredParam,
}) {
  const [dataSearch, setDataSearch] = useState('')
  const [expandedDataKeys, setExpandedDataKeys] = useState(() => new Set())

  function toggleExpandedDataKey(name) {
    setExpandedDataKeys((current) => {
      const next = new Set(current)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const dataRows = useMemo(() => {
    const values = rulesSnapshot?.values && typeof rulesSnapshot.values === 'object' ? rulesSnapshot.values : {}
    const ownership = rulesSnapshot?.ownership && typeof rulesSnapshot.ownership === 'object' ? rulesSnapshot.ownership : {}
    const query = dataSearch.trim().toLowerCase()
    const starredSet = new Set(starredParams)

    const rows = Object.entries(values).map(([key, value]) => ({
      key,
      value,
      owner: ownership[key]?.owner || '',
      isStarred: starredSet.has(key),
    }))

    const filtered = query
      ? rows.filter((row) => row.key.toLowerCase().includes(query) || stringifyDataValue(row.value).toLowerCase().includes(query) || row.owner.toLowerCase().includes(query))
      : rows

    filtered.sort((a, b) => {
      if (a.isStarred !== b.isStarred) return a.isStarred ? -1 : 1
      return a.key.localeCompare(b.key)
    })

    return filtered
  }, [rulesSnapshot, dataSearch, starredParams])

  return (
    <div className="tab-content-grid data-tab-layout">
      <div className="info-card data-card">
        <div className="control-bar">
          <div className="control-bar-copy">
            <strong>Data recording</strong>
            <span>
              {dataServiceHealthy
                ? isRecording
                  ? `Recording ${dataServiceStatus?.config?.parameters?.length || 0} parameter(s) at ${dataServiceStatus?.config?.hz || dataHz} Hz`
                  : `Ready to record ${selectedStarredParams.length} favorite parameter(s)`
                : 'Data service unavailable for this fermenter'}
            </span>
          </div>
          <div className="data-action-group">
            <select
              className="data-control"
              aria-label="Recording frequency"
              value={dataHz}
              onChange={(event) => setDataHz(event.target.value)}
              disabled={isRecording || dataActionLoading || !dataServiceHealthy}
            >
              {['1', '2', '5', '10', '20', '50', '100', '150'].map((value) => (
                <option key={value} value={value}>{value} Hz</option>
              ))}
            </select>
            <div className="data-control-group">
              <input
                className="data-control data-control-number"
                aria-label="Loadstep duration"
                type="number"
                min="0.1"
                step="0.1"
                placeholder="30"
                value={loadstepSeconds}
                onChange={(event) => setLoadstepSeconds(event.target.value)}
                disabled={dataActionLoading || !dataServiceHealthy}
              />
              <span className="data-control-unit">s</span>
            </div>
            <button
              className={isRecording ? 'danger-button' : 'primary-button is-running'}
              disabled={dataActionLoading || !dataServiceHealthy || (!isRecording && !selectedStarredParams.length)}
              onClick={toggleMeasurementRecording}
            >
              {dataActionLoading ? 'Working…' : isRecording ? 'Stop recording' : 'Start recording'}
            </button>
            <button
              className={isTakingLoadstep ? 'danger-button' : 'secondary-button'}
              disabled={dataActionLoading || !dataServiceHealthy || !isRecording || isTakingLoadstep || !isLoadstepDurationValid}
              onClick={takeDataLoadstep}
            >
              {isTakingLoadstep
                ? loadstepRemainingSeconds != null
                  ? `Loadstep active (${loadstepRemainingSeconds}s)`
                  : 'Loadstep active'
                : 'Take loadstep'}
            </button>
          </div>
        </div>

        {latestCompletedLoadstep && (
          <div className="data-loadstep-status">
            <strong>Latest loadstep: {latestCompletedLoadstep?.name || 'completed'}</strong>
            <span>
              {latestCompletedLoadstep?.duration_seconds || '-'}s window
              {' • '}
              {latestLoadstepEntries.length} value{latestLoadstepEntries.length === 1 ? '' : 's'}
              {' • '}
              {latestCompletedLoadstep?.timestamp
                ? new Date(latestCompletedLoadstep.timestamp).toLocaleTimeString()
                : 'time unknown'}
            </span>

            {latestLoadstepEntries.length > 0 && (
              <div className="data-loadstep-row" title="Latest loadstep values">
                {latestLoadstepEntries.map(([name, value]) => (
                  <span key={name} className="data-loadstep-chip">
                    <strong>{name}</strong>
                    <span>{stringifyDataValue(value)}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="rules-toolbar">
          <div>
            <h3>Data</h3>
            <div className="small-text">Live snapshot values. Search anything and star parameters to pin them to the top and use them for recording setup.</div>
          </div>
          <div className="button-row compact-actions">
            <span className={`pill ${dataServiceHealthy ? 'pill-ok' : 'pill-bad'}`}>
              data service {dataServiceHealthy ? 'available' : 'unavailable'}
            </span>
            <span className={`pill ${selectedStarredParams.length ? 'pill-ok' : 'pill-neutral'}`}>
              favorites {selectedStarredParams.length}
            </span>
          </div>
        </div>

        <div className="data-toolbar">
          <input
            className="data-search-input"
            type="search"
            placeholder="Search parameter, value, or owner…"
            value={dataSearch}
            onChange={(e) => setDataSearch(e.target.value)}
          />
          <div className="small-text">{dataRows.length} row{dataRows.length === 1 ? '' : 's'}</div>
        </div>

        {!dataRows.length ? (
          <p className="muted">No snapshot values available.</p>
        ) : (
          <div className="data-table-wrap">
            <div className="data-table-head">
              <span></span>
              <span>Parameter</span>
              <span>Value</span>
              <span>Owner</span>
            </div>
            <div className="data-table-body">
              {dataRows.map((row) => (
                <div key={row.key} className={`data-table-row ${row.isStarred ? 'is-starred' : ''}`}>
                  <button
                    className={`star-button ${row.isStarred ? 'is-starred' : ''}`}
                    onClick={() => toggleStarredParam(row.key)}
                    title={row.isStarred ? 'Unpin parameter' : 'Pin parameter'}
                    aria-label={row.isStarred ? `Unpin ${row.key}` : `Pin ${row.key}`}
                  >
                    ★
                  </button>
                  <strong className="data-param-name">{row.key}</strong>
                  <div className="data-param-value">
                    {shouldCollapseDataValue(row.value) ? (
                      <button
                        type="button"
                        className={`data-value-toggle ${expandedDataKeys.has(row.key) ? 'is-expanded' : ''}`}
                        onClick={() => toggleExpandedDataKey(row.key)}
                        title={expandedDataKeys.has(row.key) ? 'Collapse value' : 'Expand value'}
                      >
                        <span className="data-value-toggle-label">
                          {expandedDataKeys.has(row.key) ? '▼' : '▶'}
                        </span>
                        <span className={`data-value-text ${expandedDataKeys.has(row.key) ? 'is-expanded' : ''}`}>
                          {expandedDataKeys.has(row.key)
                            ? <ExpandedDataValue value={row.value} />
                            : formatCollapsedDataValue(row.value)}
                        </span>
                      </button>
                    ) : (
                      <span className="data-value-text">{stringifyDataValue(row.value)}</span>
                    )}
                  </div>
                  <span className="data-param-owner">{row.owner || '-'}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
