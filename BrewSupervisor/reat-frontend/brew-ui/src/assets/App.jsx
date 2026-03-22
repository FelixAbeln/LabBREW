import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const API_BASE = 'http://127.0.0.1:8782'

async function api(path, options = {}) {
  const headers = {
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers || {}),
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    if (typeof payload === 'string') {
      throw new Error(payload || `HTTP ${response.status}`)
    }
    throw new Error(payload?.detail || payload?.error || JSON.stringify(payload) || `HTTP ${response.status}`)
  }

  return payload
}

function getRunToggle(state) {
  if (state === 'paused') {
    return {
      label: 'Resume',
      path: '/schedule/resume',
      className: 'toggle-button is-resume is-paused',
      disabled: false,
      hint: 'Schedule is paused',
    }
  }

  if (state === 'running') {
    return {
      label: 'Pause',
      path: '/schedule/pause',
      className: 'toggle-button is-pause',
      disabled: false,
      hint: 'Schedule is running',
    }
  }

  return {
    label: 'Pause',
    path: null,
    className: 'toggle-button',
    disabled: true,
    hint: 'Schedule not running',
  }
}

function App() {
  const [fermenters, setFermenters] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [schedule, setSchedule] = useState(null)
  const [ownedTargetValues, setOwnedTargetValues] = useState([])
  const [error, setError] = useState('')
  const [loadingAction, setLoadingAction] = useState(false)
  const [scheduleFile, setScheduleFile] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [scheduleDefinition, setScheduleDefinition] = useState(null)
  const [activeTab, setActiveTab] = useState('schedule')
  const [followLogBottom, setFollowLogBottom] = useState(true)
  const logRef = useRef(null)

  const selected = useMemo(() => {
    if (!fermenters.length) return null
    return fermenters.find((f) => f.id === selectedId) || fermenters[0]
  }, [fermenters, selectedId])

  const runToggle = useMemo(() => getRunToggle(schedule?.state || null), [schedule?.state])

  const healthyServices = useMemo(() => {
    const services = Object.entries(selected?.services || {})
    return services.filter(([, service]) => service?.healthy)
  }, [selected])


  function handleEventLogScroll() {
    const el = logRef.current
    if (!el) return

    const threshold = 28
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setFollowLogBottom(distanceFromBottom <= threshold)
  }

  function scrollEventLogToBottom(behavior = 'smooth') {
    const el = logRef.current
    if (!el) return

    el.scrollTo({
      top: el.scrollHeight,
      behavior,
    })
    setFollowLogBottom(true)
  }

  async function loadFermenters() {
    const data = await api('/fermenters')
    setFermenters(data)
    if (!selectedId && data.length) {
      setSelectedId(data[0].id)
    }
    return data
  }

  async function loadDetails(id) {
    const [statusResult, scheduleResult] = await Promise.allSettled([
      api(`/fermenters/${id}/schedule/status`),
      api(`/fermenters/${id}/schedule`),
    ])

    const nextSchedule = statusResult.status === 'fulfilled' ? statusResult.value : null
    setSchedule(nextSchedule)

    if (scheduleResult.status === 'fulfilled') {
      setScheduleDefinition(scheduleResult.value?.schedule || null)
    } else {
      setScheduleDefinition(null)
    }

    const ownedTargets = Array.isArray(nextSchedule?.owned_targets)
      ? nextSchedule.owned_targets
      : []

    if (!ownedTargets.length) {
      setOwnedTargetValues([])
      return
    }

    const targetResults = await Promise.allSettled(
      ownedTargets.map((target) =>
        api(`/fermenters/${id}/control/read/${encodeURIComponent(target)}`),
      ),
    )

    setOwnedTargetValues(
      ownedTargets.map((target, index) => {
        const result = targetResults[index]
        if (result.status === 'fulfilled') {
          return {
            target,
            ok: Boolean(result.value?.ok),
            value: result.value?.value ?? '-',
            owner: result.value?.current_owner ?? null,
          }
        }
        return {
          target,
          ok: false,
          value: 'read failed',
          owner: null,
        }
      }),
    )
  }

  async function refreshAll() {
    try {
      setError('')
      const data = await loadFermenters()

      if (!data.length) {
        setSelectedId(null)
        setSchedule(null)
        setOwnedTargetValues([])
        return
      }

      const nextSelectedId =
        selectedId && data.some((f) => f.id === selectedId)
          ? selectedId
          : data[0].id

      setSelectedId(nextSelectedId)
      await loadDetails(nextSelectedId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  async function runAction(path) {
    if (!selected) return
    try {
      setLoadingAction(true)
      setError('')
      await api(`/fermenters/${selected.id}${path}`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      await loadFermenters()
      await loadDetails(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoadingAction(false)
    }
  }

  async function uploadWorkbook(path) {
    if (!selected || !scheduleFile) return

    try {
      setLoadingAction(true)
      setError('')
      setImportResult(null)

      const formData = new FormData()
      formData.append('file', scheduleFile)

      const result = await api(`/fermenters/${selected.id}${path}`, {
        method: 'PUT',
        body: formData,
      })

      setImportResult(result)
      await loadFermenters()
      await loadDetails(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoadingAction(false)
    }
  }

  useEffect(() => {
    refreshAll()
  }, [])

  useEffect(() => {
    if (!selected?.id) return

    loadDetails(selected.id).catch((err) => {
      setError(err instanceof Error ? err.message : 'Unknown error')
    })

    const intervalId = window.setInterval(() => {
      loadFermenters().catch(() => {})
      loadDetails(selected.id).catch(() => {})
    }, 1500)

    return () => window.clearInterval(intervalId)
  }, [selected?.id])

  useEffect(() => {
    if (!schedule?.event_log?.length) return
    if (!followLogBottom) return

    const timeoutId = window.setTimeout(() => {
      scrollEventLogToBottom('smooth')
    }, 0)

    return () => window.clearTimeout(timeoutId)
  }, [schedule?.event_log, followLogBottom])

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>Brew UI</h1>
          <p>Fermenter dashboard through BrewSupervisor</p>
        </div>
        <button className="primary-button" onClick={refreshAll}>
          Refresh
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="main-grid">
        <aside className="panel">
          <h2>Fermenters</h2>
          {fermenters.length === 0 ? (
            <p className="muted">No fermenters discovered.</p>
          ) : (
            <div className="fermenter-list">
              {fermenters.map((fermenter) => (
                <button
                  key={fermenter.id}
                  className={`fermenter-card ${
                    selected?.id === fermenter.id ? 'selected' : ''
                  }`}
                  onClick={() => setSelectedId(fermenter.id)}
                >
                  <div className="fermenter-top">
                    <strong>{fermenter.name}</strong>
                    <span
                      className={`pill ${
                        fermenter.online ? 'pill-ok' : 'pill-bad'
                      }`}
                    >
                      {fermenter.online ? 'online' : 'offline'}
                    </span>
                  </div>
                  <div className="small-text">{fermenter.id}</div>
                  <div className="small-text">{fermenter.address}</div>
                  <div className="tag-row">
                    <span className="tag">
                      schedule:{' '}
                      {String(fermenter.summary?.schedule_available ?? false)}
                    </span>
                    <span className="tag">
                      control:{' '}
                      {String(fermenter.summary?.control_available ?? false)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="content-column">
          <div className="panel selected-panel">
            <div className="selected-header-row">
              <div>
                <h2>Selected fermenter</h2>
                {selected && <p className="muted selected-subtitle">{selected.name} · {selected.id}</p>}
              </div>
              <div className="tab-row" role="tablist" aria-label="Fermenter views">
                <button
                  className={`tab-button ${activeTab === 'schedule' ? 'active' : ''}`}
                  onClick={() => setActiveTab('schedule')}
                  role="tab"
                  aria-selected={activeTab === 'schedule'}
                >
                  Schedule
                </button>
                <button
                  className={`tab-button ${activeTab === 'system' ? 'active' : ''}`}
                  onClick={() => setActiveTab('system')}
                  role="tab"
                  aria-selected={activeTab === 'system'}
                >
                  System
                </button>
              </div>
            </div>

            {!selected ? (
              <p className="muted">Select a fermenter.</p>
            ) : activeTab === 'schedule' ? (
              <div className="tab-content-grid">
                <div className="control-bar">
                  <div className="control-bar-copy">
                    <strong>Schedule controls</strong>
                    <span>{runToggle.hint}</span>
                  </div>
                  <div className="control-button-group">
                    <button
                      className="primary-button"
                      disabled={!selected || loadingAction}
                      onClick={() => runAction('/schedule/start')}
                    >
                      Start
                    </button>
                    <button
                      className={runToggle.className}
                      disabled={!selected || loadingAction || runToggle.disabled}
                      onClick={() => runToggle.path && runAction(runToggle.path)}
                    >
                      {runToggle.label}
                    </button>
                    <button
                      className="danger-button"
                      disabled={!selected || loadingAction}
                      onClick={() => runAction('/schedule/stop')}
                    >
                      Stop
                    </button>
                    <button
                      className="secondary-button"
                      disabled={!selected || loadingAction}
                      onClick={() => runAction('/schedule/previous')}
                    >
                      Previous
                    </button>
                    <button
                      className="secondary-button"
                      disabled={!selected || loadingAction}
                      onClick={() => runAction('/schedule/next')}
                    >
                      Next
                    </button>
                  </div>
                </div>

                <div className="schedule-layout">
                  <div className="info-card schedule-card">
                    <div className="card-header-row">
                      <h3>Schedule</h3>
                      <span className={`pill ${schedule?.state === 'running' ? 'pill-ok' : schedule?.state === 'paused' ? 'pill-warn' : 'pill-neutral'}`}>
                        {schedule?.state || 'idle'}
                      </span>
                    </div>
                    <div className="info-row">
                      <span>Schedule name</span>
                      <strong>{scheduleDefinition?.name || '-'}</strong>
                    </div>
                    <div className="info-row">
                      <span>Schedule id</span>
                      <strong>{scheduleDefinition?.id || '-'}</strong>
                    </div>
                    <div className="info-row">
                      <span>Phase</span>
                      <strong>{schedule?.phase || '-'}</strong>
                    </div>
                    <div className="info-row info-row-block">
                      <span>Step</span>
                      <strong>{schedule?.current_step_name || '-'}</strong>
                    </div>
                    <div className="info-row">
                      <span>Index</span>
                      <strong>{schedule?.current_step_index ?? '-'}</strong>
                    </div>
                    <div className="info-row info-row-block">
                      <span>Wait</span>
                      <strong>{schedule?.wait_message || '-'}</strong>
                    </div>
                    <div className="info-row info-row-block">
                      <span>Pause reason</span>
                      <strong>{schedule?.pause_reason || '-'}</strong>
                    </div>
                  </div>

                  <div className="info-card setpoints-card">
                    <div className="card-header-row">
                      <h3>Current setpoints</h3>
                      <span className="tag">{ownedTargetValues.length} target{ownedTargetValues.length === 1 ? '' : 's'}</span>
                    </div>
                    {!ownedTargetValues.length ? (
                      <p className="muted">No schedule-owned targets right now.</p>
                    ) : (
                      <div className="setpoint-table">
                        <div className="setpoint-table-head">
                          <span>Target</span>
                          <span>Value</span>
                          <span>Owner</span>
                          <span>Status</span>
                        </div>
                        <div className="setpoint-table-body">
                          {ownedTargetValues.map((item) => (
                            <div key={item.target} className="setpoint-table-row">
                              <strong className="setpoint-name">{item.target}</strong>
                              <span className="setpoint-value">{String(item.value)}</span>
                              <span className="setpoint-owner">{item.owner || '-'}</span>
                              <span className={`pill ${item.ok ? 'pill-ok' : 'pill-bad'}`}>
                                {item.ok ? 'read ok' : 'read failed'}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="info-card workbook-card">
                  <h3>Schedule workbook</h3>
                  <div className="upload-row">
                    <label className="file-picker-button">
                      Choose workbook
                      <input
                        type="file"
                        accept=".xlsx"
                        onChange={(e) => setScheduleFile(e.target.files?.[0] || null)}
                        className="hidden-file-input"
                      />
                    </label>

                    <div className="selected-file-name">
                      {scheduleFile ? scheduleFile.name : 'No file selected'}
                    </div>
                  </div>

                  <div className="button-row">
                    <button
                      className="secondary-button"
                      disabled={!selected || !scheduleFile || loadingAction}
                      onClick={() => uploadWorkbook('/schedule/validate-import')}
                    >
                      Validate workbook
                    </button>

                    <button
                      className="primary-button"
                      disabled={!selected || !scheduleFile || loadingAction}
                      onClick={() => uploadWorkbook('/schedule/import')}
                    >
                      Import workbook
                    </button>
                  </div>

                  {importResult && (
                    <div className="import-result">
                      {importResult.valid ? (
                        <>
                          <div className="success">✔ Schedule valid</div>
                          <div className="summary">
                            <div>Name: {importResult.schedule?.name}</div>
                            <div>Setup steps: {importResult.summary?.setup_step_count}</div>
                            <div>Plan steps: {importResult.summary?.plan_step_count}</div>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="error">✖ Validation failed</div>
                          <ul>
                            {importResult.errors?.map((e, i) => (
                              <li key={i}>{e}</li>
                            ))}
                          </ul>
                        </>
                      )}

                      {importResult.warnings?.length > 0 && (
                        <>
                          <div className="warning">⚠ Warnings</div>
                          <ul>
                            {importResult.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  )}
                </div>

                <div className="info-card">
                  <div className="card-header-row">
                    <h3>Event log</h3>
                    <span className="small-text">Newest entries append at the bottom</span>
                  </div>
                  {!schedule?.event_log?.length ? (
                    <p className="muted">No events yet.</p>
                  ) : (
                    <div className="event-log-wrap">
                      <div ref={logRef} className="event-list" onScroll={handleEventLogScroll}>
                        {schedule.event_log.map((event, index) => (
                          <div key={index} className="event-item">
                            {event}
                          </div>
                        ))}
                      </div>
                      {!followLogBottom && (
                        <button
                          className="log-jump-button"
                          onClick={() => scrollEventLogToBottom()}
                          aria-label="Jump to latest log entry"
                          title="Jump to latest"
                        >
                          ↓
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="tab-content-grid system-layout">
                <div className="info-card system-node-card">
                  <h3>Node</h3>
                  <div className="info-row">
                    <span>Name</span>
                    <strong>{selected.name}</strong>
                  </div>
                  <div className="info-row">
                    <span>ID</span>
                    <strong>{selected.id}</strong>
                  </div>
                  <div className="info-row">
                    <span>Address</span>
                    <strong>{selected.address}</strong>
                  </div>
                  <div className="info-row">
                    <span>Host</span>
                    <strong>{selected.host || '-'}</strong>
                  </div>
                  <div className="info-row info-row-block">
                    <span>Agent</span>
                    <strong>{selected.agent_base_url || '-'}</strong>
                  </div>
                </div>

                <div className="info-card system-services-card">
                  <div className="card-header-row">
                    <h3>Healthy services</h3>
                    <span className="tag">{healthyServices.length} active</span>
                  </div>
                  {!healthyServices.length ? (
                    <p className="muted">No healthy services reported.</p>
                  ) : (
                    <div className="system-service-stack">
                      {healthyServices.map(([name, service]) => (
                        <div key={name} className="system-service-item">
                          <div className="system-service-header">
                            <strong>{name}</strong>
                            <span className="pill pill-ok">healthy</span>
                          </div>
                          <div className="small-text">Base URL: {service?.base_url || '-'}</div>
                          <div className="small-text">Reason: {service?.reason || '-'}</div>
                          <div className="small-text">
                            Provides: {Array.isArray(service?.provides) ? service.provides.join(', ') : '-'}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

export default App
