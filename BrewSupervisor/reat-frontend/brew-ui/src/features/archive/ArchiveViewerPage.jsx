import { useCallback, useMemo, useRef, useState } from 'react'

const SERIES_COLORS = ['#4dd0e1', '#ffb74d', '#81c784', '#e57373', '#90caf9', '#ce93d8']

function toFixedNumber(value, digits = 3) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(digits)
}

function formatTimestamp(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  const date = new Date(numeric * 1000)
  if (Number.isNaN(date.getTime())) return String(numeric)
  return date.toLocaleString()
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function findNearestPoint(points, xTarget) {
  if (!Array.isArray(points) || !points.length) return null
  let best = points[0]
  let bestDist = Math.abs(points[0].x - xTarget)
  for (let idx = 1; idx < points.length; idx += 1) {
    const candidate = points[idx]
    const dist = Math.abs(candidate.x - xTarget)
    if (dist < bestDist) {
      best = candidate
      bestDist = dist
    }
  }
  return best
}

export function ArchiveViewerPage({ archiveName, archiveViewPayload, archiveViewLoading, archiveViewError, onClose }) {
  const measurement = useMemo(
    () => (archiveViewPayload?.measurement && typeof archiveViewPayload.measurement === 'object'
      ? archiveViewPayload.measurement
      : null),
    [archiveViewPayload],
  )
  const parameters = useMemo(
    () => (Array.isArray(measurement?.parameters) ? measurement.parameters : []),
    [measurement],
  )

  const [selectedParams, setSelectedParams] = useState([])
  const [pinnedParams, setPinnedParams] = useState([])
  const [candidateParam, setCandidateParam] = useState('')
  const [panelTab, setPanelTab] = useState('browser')
  const [seriesFilter, setSeriesFilter] = useState('')
  const [viewport, setViewport] = useState({ start: 0, end: 1 })
  const [cursorFraction, setCursorFraction] = useState(null)
  const chartRef = useRef(null)
  const dragRef = useRef(null)

  const activeSelectedParams = useMemo(
    () => selectedParams.filter((name) => parameters.includes(name)),
    [parameters, selectedParams],
  )

  const activePinnedParams = useMemo(
    () => pinnedParams.filter((name) => parameters.includes(name)),
    [parameters, pinnedParams],
  )

  const activeCandidateParam = useMemo(() => {
    if (parameters.includes(candidateParam)) return candidateParam
    return parameters[0] || ''
  }, [candidateParam, parameters])

  function toggleSeries(name) {
    setSelectedParams((current) => {
      if (current.includes(name)) {
        return current.filter((item) => item !== name)
      }
      return [...current, name]
    })
  }

  function selectCandidate(name) {
    setCandidateParam(name)
    setSelectedParams((current) => {
      if (!name || current.includes(name)) return current
      return [...current, name]
    })
  }

  function unplotCandidate() {
    if (!activeCandidateParam) return
    setSelectedParams((current) => current.filter((item) => item !== activeCandidateParam))
  }

  const getSeriesColor = useCallback((name) => {
    const idx = activeSelectedParams.indexOf(name)
    if (idx < 0) return '#506274'
    return SERIES_COLORS[idx % SERIES_COLORS.length]
  }, [activeSelectedParams])

  function togglePin(name) {
    setPinnedParams((current) => {
      if (current.includes(name)) return current.filter((item) => item !== name)
      return [name, ...current]
    })
  }

  const filteredParameters = useMemo(() => {
    const q = seriesFilter.trim().toLowerCase()
    if (!q) return parameters
    return parameters.filter((name) => name.toLowerCase().includes(q))
  }, [parameters, seriesFilter])

  const browserParameters = useMemo(() => {
    if (!filteredParameters.length) return []
    const pinnedSet = new Set(activePinnedParams)
    const pinned = []
    const regular = []
    filteredParameters.forEach((name) => {
      if (pinnedSet.has(name)) pinned.push(name)
      else regular.push(name)
    })
    return [...pinned, ...regular]
  }, [activePinnedParams, filteredParameters])

  const chartData = useMemo(() => {
    const samples = Array.isArray(measurement?.samples) ? measurement.samples : []
    if (!samples.length || !activeSelectedParams.length) {
      return {
        series: [],
        visibleSeries: [],
        fullXMin: null,
        fullXMax: null,
        viewXMin: null,
        viewXMax: null,
        minY: null,
        maxY: null,
        totalPointCount: 0,
      }
    }

    const series = activeSelectedParams.map((name, index) => ({
      name,
      color: SERIES_COLORS[index % SERIES_COLORS.length],
      points: [],
    }))

    samples.forEach((sample, sampleIndex) => {
      const ts = Number(sample?.timestamp)
      const x = Number.isFinite(ts) ? ts : sampleIndex
      series.forEach((entry) => {
        const raw = sample?.data?.[entry.name]
        const y = Number(raw)
        if (!Number.isFinite(y)) return
        entry.points.push({
          x,
          y,
          datetime: sample?.datetime || '',
        })
      })
    })

    const allX = series.flatMap((entry) => entry.points.map((point) => point.x))
    if (!allX.length) {
      return {
        series,
        visibleSeries: series.map((entry) => ({ ...entry, polyline: '', visiblePoints: [] })),
        fullXMin: null,
        fullXMax: null,
        viewXMin: null,
        viewXMax: null,
        minY: null,
        maxY: null,
        totalPointCount: 0,
      }
    }

    const fullXMin = Math.min(...allX)
    const fullXMax = Math.max(...allX)
    const fullXSpan = Math.max(1e-9, fullXMax - fullXMin)
    const viewXMin = fullXMin + fullXSpan * viewport.start
    const viewXMax = fullXMin + fullXSpan * viewport.end

    const visibleSeries = series.map((entry) => {
      const visiblePoints = entry.points.filter((point) => point.x >= viewXMin && point.x <= viewXMax)
      return { ...entry, visiblePoints }
    })

    const allVisibleY = visibleSeries.flatMap((entry) => entry.visiblePoints.map((point) => point.y))
    const minY = allVisibleY.length ? Math.min(...allVisibleY) : null
    const maxY = allVisibleY.length ? Math.max(...allVisibleY) : null
    const ySpan = Math.max(1e-9, (maxY ?? 0) - (minY ?? 0))
    const xSpan = Math.max(1e-9, viewXMax - viewXMin)

    const mappedVisibleSeries = visibleSeries.map((entry) => {
      const polyline = entry.visiblePoints
        .map((point) => {
          const x = ((point.x - viewXMin) / xSpan) * 100
          const y = 100 - ((point.y - (minY ?? 0)) / ySpan) * 100
          return `${x.toFixed(3)},${y.toFixed(3)}`
        })
        .join(' ')
      return {
        ...entry,
        polyline,
      }
    })

    return {
      series,
      visibleSeries: mappedVisibleSeries,
      fullXMin,
      fullXMax,
      viewXMin,
      viewXMax,
      minY,
      maxY,
      totalPointCount: series.reduce((sum, item) => sum + item.points.length, 0),
    }
  }, [activeSelectedParams, measurement, viewport.end, viewport.start])

  const cursorData = useMemo(() => {
    if (cursorFraction == null || !Number.isFinite(chartData.viewXMin) || !Number.isFinite(chartData.viewXMax)) {
      return null
    }
    const xTarget = chartData.viewXMin + (chartData.viewXMax - chartData.viewXMin) * clamp(cursorFraction, 0, 1)
    const readings = chartData.series
      .map((entry) => {
        const point = findNearestPoint(entry.points, xTarget)
        if (!point) return null
        return {
          name: entry.name,
          color: entry.color,
          x: point.x,
          y: point.y,
          datetime: point.datetime,
        }
      })
      .filter(Boolean)
    if (!readings.length) return null
    const anchor = readings[0]
    return {
      cursorPercent: clamp(cursorFraction, 0, 1) * 100,
      x: anchor.x,
      datetime: anchor.datetime,
      readings,
    }
  }, [chartData, cursorFraction])

  const seriesStats = useMemo(() => {
    const samples = Array.isArray(measurement?.samples) ? measurement.samples : []
    return activeSelectedParams.map((name) => {
      const values = samples
        .map((sample) => Number(sample?.data?.[name]))
        .filter((value) => Number.isFinite(value))
      if (!values.length) {
        return {
          name,
          color: getSeriesColor(name),
          min: '-',
          max: '-',
          avg: '-',
          last: '-',
          count: 0,
        }
      }
      const min = Math.min(...values)
      const max = Math.max(...values)
      const avg = values.reduce((sum, value) => sum + value, 0) / values.length
      const last = values[values.length - 1]
      return {
        name,
        color: getSeriesColor(name),
        min: toFixedNumber(min),
        max: toFixedNumber(max),
        avg: toFixedNumber(avg),
        last: toFixedNumber(last),
        count: values.length,
      }
    })
  }, [activeSelectedParams, getSeriesColor, measurement])

  function handleChartWheel(event) {
    event.preventDefault()
    if (!chartRef.current || !Number.isFinite(chartData.fullXMin) || !Number.isFinite(chartData.fullXMax)) return
    const rect = chartRef.current.getBoundingClientRect()
    if (!rect.width) return
    const pointer = clamp((event.clientX - rect.left) / rect.width, 0, 1)
    const factor = event.deltaY > 0 ? 1.12 : 0.88

    setViewport((current) => {
      const currentSpan = current.end - current.start
      const nextSpan = clamp(currentSpan * factor, 0.01, 1)
      const anchor = current.start + currentSpan * pointer
      let nextStart = anchor - nextSpan * pointer
      let nextEnd = nextStart + nextSpan
      if (nextStart < 0) {
        nextStart = 0
        nextEnd = nextSpan
      }
      if (nextEnd > 1) {
        nextEnd = 1
        nextStart = 1 - nextSpan
      }
      return { start: clamp(nextStart, 0, 1), end: clamp(nextEnd, 0, 1) }
    })
  }

  function handleChartMouseDown(event) {
    if (!chartRef.current) return
    const rect = chartRef.current.getBoundingClientRect()
    dragRef.current = {
      startX: event.clientX,
      width: rect.width,
      viewportAtStart: viewport,
    }
  }

  function handleChartMouseMove(event) {
    if (!chartRef.current) return
    const rect = chartRef.current.getBoundingClientRect()
    if (rect.width) {
      const fraction = clamp((event.clientX - rect.left) / rect.width, 0, 1)
      setCursorFraction(fraction)
    }

    if (!dragRef.current || !dragRef.current.width) return
    const deltaFraction = (event.clientX - dragRef.current.startX) / dragRef.current.width
    const span = dragRef.current.viewportAtStart.end - dragRef.current.viewportAtStart.start
    let nextStart = dragRef.current.viewportAtStart.start - deltaFraction * span
    let nextEnd = dragRef.current.viewportAtStart.end - deltaFraction * span
    if (nextStart < 0) {
      nextStart = 0
      nextEnd = span
    }
    if (nextEnd > 1) {
      nextEnd = 1
      nextStart = 1 - span
    }
    setViewport({ start: clamp(nextStart, 0, 1), end: clamp(nextEnd, 0, 1) })
  }

  function stopDragging() {
    dragRef.current = null
  }

  return (
    <div className="pdb-page archive-viewer-page">
      <div className="pdb-page-header">
        <div className="archive-viewer-title-stack">
          <div className="pdb-page-title">
            <span className="pdb-page-icon pdb-page-icon-archive">◫</span>
            <span>Data Viewer</span>
          </div>
          <div className="archive-viewer-subheader">
            <span>{archiveName || 'Archive Viewer'}</span>
            <span>Member: {measurement?.member || '-'}</span>
            <span>Samples: {measurement?.sample_count ?? 0}</span>
            <span>Rendered: {chartData.totalPointCount}</span>
          </div>
        </div>
        <div className="pdb-page-actions">
          <button className="pdb-close-btn" onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      {archiveViewError ? (
        <div className="pdb-page-error">{archiveViewError}</div>
      ) : archiveViewLoading ? (
        <div className="pdb-page-body">
          <div className="pdb-loading">Loading archive data...</div>
        </div>
      ) : !archiveViewPayload ? (
        <div className="pdb-page-body">
          <div className="pdb-empty">No archive data loaded.</div>
        </div>
      ) : (
        <div className="pdb-page-body archive-viewer-body">
          <div className="archive-viewer-workbench">
            <section className="archive-viewer-browser-panel">
              <div className="archive-viewer-controls-head">
                <div className="archive-viewer-panel-title">Parameter Browser</div>
                <div className="archive-viewer-tabstrip" role="tablist" aria-label="Viewer sections">
                  <button
                    className={`archive-viewer-tab ${panelTab === 'browser' ? 'active' : ''}`}
                    type="button"
                    role="tab"
                    aria-selected={panelTab === 'browser'}
                    onClick={() => setPanelTab('browser')}
                  >
                    Parameters
                  </button>
                  <button
                    className={`archive-viewer-tab ${panelTab === 'stats' ? 'active' : ''}`}
                    type="button"
                    role="tab"
                    aria-selected={panelTab === 'stats'}
                    onClick={() => setPanelTab('stats')}
                  >
                    Statistics
                  </button>
                </div>
              </div>

              {panelTab === 'browser' ? (
                <div className="archive-browser-layout">
                  <div className="pdb-picker-input-row">
                    <input
                      className="pdb-input archive-viewer-series-filter pdb-full"
                      value={seriesFilter}
                      onChange={(event) => setSeriesFilter(event.target.value)}
                      placeholder="Search parameters..."
                    />
                  </div>

                  <div className="archive-viewer-candidate-row">
                    <span className="small-text archive-candidate-label">Selection:</span>
                    <span className="archive-candidate-name">{activeCandidateParam || '-'}</span>
                    <div className="archive-viewer-control-actions">
                      <button
                        className="pdb-btn-secondary pdb-btn-sm"
                        type="button"
                        onClick={unplotCandidate}
                        disabled={!activeCandidateParam || !activeSelectedParams.includes(activeCandidateParam)}
                      >
                        Unplot
                      </button>
                      <button
                        className="pdb-btn-ghost pdb-btn-sm"
                        type="button"
                        onClick={() => togglePin(activeCandidateParam)}
                        disabled={!activeCandidateParam}
                      >
                        {activeCandidateParam && activePinnedParams.includes(activeCandidateParam) ? 'Unpin ★' : 'Pin'}
                      </button>
                    </div>
                  </div>

                  <div className="pdb-picker-list archive-viewer-picker-list" role="listbox" aria-label="Available parameters">
                    {!browserParameters.length ? (
                      <div className="pdb-cell-nil">No matching parameters</div>
                    ) : (
                      browserParameters.map((name) => {
                        const isActive = activeCandidateParam === name
                        const isPlotted = activeSelectedParams.includes(name)
                        const isPinned = activePinnedParams.includes(name)
                        const color = getSeriesColor(name)
                        return (
                          <div key={name} className={`pdb-picker-item ${isActive ? 'pdb-picker-item-active' : ''}`}>
                            <button
                              type="button"
                              className="pdb-picker-item-button archive-picker-item-button"
                              onClick={() => selectCandidate(name)}
                              title={name}
                            >
                              <span className="archive-series-dot" style={{ backgroundColor: isPlotted ? color : '#506274' }} />
                              <span className="archive-viewer-series-name">{name}</span>
                              {isPinned ? <span className="archive-viewer-series-tag">Pinned</span> : null}
                            </button>
                            <button
                              type="button"
                              className={`archive-pin-btn ${isPinned ? 'active' : ''}`}
                              onClick={() => togglePin(name)}
                              title={isPinned ? 'Unpin parameter' : 'Pin parameter'}
                            >
                              {isPinned ? '★' : '+'}
                            </button>
                          </div>
                        )
                      })
                    )}
                  </div>

                </div>
              ) : (
                <div className="archive-stats-layout">
                  <div className="archive-stats-panel" role="tabpanel" aria-label="Series statistics">
                    {!seriesStats.length ? (
                      <div className="pdb-cell-nil">Plot one or more series to see statistics.</div>
                    ) : (
                      <>
                        <div className="archive-stats-body">
                          {seriesStats.map((row) => (
                            <div className="archive-stats-row" key={row.name}>
                              <span className="archive-stats-series">
                                <span className="archive-series-dot" style={{ backgroundColor: row.color }} />
                                <span className="archive-viewer-series-name">{row.name}</span>
                              </span>
                              <div className="archive-stats-metrics">
                                <span className="archive-stats-metric">
                                  <span className="archive-stats-metric-label">Min</span>
                                  <span className="archive-stats-metric-value">{row.min}</span>
                                </span>
                                <span className="archive-stats-metric">
                                  <span className="archive-stats-metric-label">Max</span>
                                  <span className="archive-stats-metric-value">{row.max}</span>
                                </span>
                                <span className="archive-stats-metric">
                                  <span className="archive-stats-metric-label">Avg</span>
                                  <span className="archive-stats-metric-value">{row.avg}</span>
                                </span>
                                <span className="archive-stats-metric">
                                  <span className="archive-stats-metric-label">Last</span>
                                  <span className="archive-stats-metric-value">{row.last}</span>
                                </span>
                                <span className="archive-stats-metric">
                                  <span className="archive-stats-metric-label">Samples</span>
                                  <span className="archive-stats-metric-value">{row.count}</span>
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
            </section>

            <section className="archive-viewer-chart-panel archive-viewer-chart-panel-primary">
              <div className="archive-chart-toolbar">
                <span className="archive-chart-title">Trend</span>
                <span className="small-text">Plotted: {activeSelectedParams.length}</span>
                <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => setViewport({ start: 0, end: 1 })}>
                  Reset zoom
                </button>
                <span className="small-text">Mouse wheel to zoom, drag to pan</span>
              </div>

              <div className="archive-chart-legend" aria-label="Plotted series legend">
                {!activeSelectedParams.length ? (
                  <span className="archive-legend-empty">No series plotted</span>
                ) : (
                  activeSelectedParams.map((name) => (
                    <button
                      key={`legend-${name}`}
                      type="button"
                      className="archive-legend-item"
                      onClick={() => toggleSeries(name)}
                      title={`Unplot ${name}`}
                    >
                      <span className="archive-legend-line" style={{ backgroundColor: getSeriesColor(name) }} />
                      <span className="archive-viewer-series-name">{name}</span>
                    </button>
                  ))
                )}
              </div>

              <div
                ref={chartRef}
                className="archive-chart-frame"
                onWheel={handleChartWheel}
                onMouseDown={handleChartMouseDown}
                onMouseMove={handleChartMouseMove}
                onMouseLeave={() => {
                  setCursorFraction(null)
                  stopDragging()
                }}
                onMouseUp={stopDragging}
              >
                {!chartData.visibleSeries.some((entry) => entry.polyline) ? (
                  <p className="muted">No plotted data yet. Select a parameter from the browser.</p>
                ) : (
                  <>
                    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="archive-chart-svg" role="img" aria-label="Archive time series chart">
                      {cursorData ? (
                        <line
                          x1={cursorData.cursorPercent}
                          x2={cursorData.cursorPercent}
                          y1="0"
                          y2="100"
                          className="archive-chart-cursor-line"
                        />
                      ) : null}
                      {chartData.visibleSeries.map((entry) => (
                        <polyline
                          key={entry.name}
                          points={entry.polyline}
                          className="archive-chart-line"
                          style={{ stroke: entry.color }}
                        />
                      ))}
                    </svg>
                    {cursorData ? (
                      <div className="archive-cursor-tooltip">
                        <strong>{cursorData.datetime || formatTimestamp(cursorData.x)}</strong>
                        {cursorData.readings.map((reading) => (
                          <span key={reading.name} style={{ color: reading.color }}>
                            {reading.name}: {toFixedNumber(reading.y)}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
