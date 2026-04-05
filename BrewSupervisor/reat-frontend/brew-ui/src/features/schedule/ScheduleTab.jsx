import { useEffect, useRef, useState } from 'react'

export function ScheduleTab({
  schedule,
  scheduleDefinition,
  runToggle,
  loadingAction,
  selected,
  runAction,
  scheduleFile,
  setScheduleFile,
  uploadWorkbook,
  importResult,
  importErrorIssues,
  importWarningIssues,
}) {
  const logRef = useRef(null)
  const fileInputRef = useRef(null)
  const [followLogBottom, setFollowLogBottom] = useState(true)

  const workbookActionDisabledReason =
    !selected
      ? 'Select a fermenter first'
      : !scheduleFile
        ? 'Choose a workbook first'
        : loadingAction
          ? 'Action in progress'
          : ''

  function openWorkbookFilePicker() {
    fileInputRef.current?.click()
  }

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
    el.scrollTo({ top: el.scrollHeight, behavior })
    setFollowLogBottom(true)
  }

  useEffect(() => {
    if (!schedule?.event_log?.length) return
    if (!followLogBottom) return
    const timeoutId = window.setTimeout(() => {
      scrollEventLogToBottom('smooth')
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [schedule?.event_log, followLogBottom])

  return (
    <div className="tab-content-grid">
      <div className="control-bar">
        <div className="control-bar-copy">
          <strong>Schedule controls</strong>
          <span>{runToggle.hint}</span>
        </div>
        <div className="control-button-group">
          <button
            className={`primary-button ${schedule?.state === 'running' ? 'is-running' : schedule?.state === 'paused' ? 'is-restart' : ''}`}
            disabled={!selected || loadingAction}
            onClick={() => runAction('/schedule/start')}
          >
            {schedule?.state === 'running' ? 'Running' : schedule?.state === 'paused' ? 'Restart' : 'Start'}
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

      <div className="info-card schedule-card">
          <div className="card-header-row">
            <h3>Schedule</h3>
            <span className={`pill ${schedule?.state === 'running' ? 'pill-ok' : schedule?.state === 'paused' ? 'pill-warn' : 'pill-neutral'}`}>
              {schedule?.state || 'idle'}
            </span>
          </div>
          <div className="info-rows-grid">
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
          <div className="info-row">
            <span>Index</span>
            <strong>{schedule?.current_step_index ?? '-'}</strong>
          </div>
          <div className="info-row info-row-block">
            <span>Step</span>
            <strong>{schedule?.current_step_name || '-'}</strong>
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
        </div>

      <div className="info-card workbook-card">
        <h3>Schedule workbook</h3>
        <div className="upload-row">
          <button type="button" className="file-picker-button" onClick={openWorkbookFilePicker}>
            Choose workbook
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            onClick={(e) => {
              // Allow re-selecting the same file and still trigger onChange.
              e.currentTarget.value = ''
            }}
            onChange={(e) => setScheduleFile(e.target.files?.[0] || null)}
            className="hidden-file-input"
          />

          <div className="selected-file-name">
            {scheduleFile ? scheduleFile.name : 'No file selected'}
          </div>
        </div>

        <div className="button-row">
          <button
            className="secondary-button"
            disabled={!selected || !scheduleFile || loadingAction}
            title={workbookActionDisabledReason}
            onClick={() => uploadWorkbook('/schedule/validate-import')}
          >
            Validate workbook
          </button>

          <button
            className="primary-button"
            disabled={!selected || !scheduleFile || loadingAction}
            title={workbookActionDisabledReason}
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
                {Array.isArray(importResult.error_codes) && importResult.error_codes.length > 0 && (
                  <div className="validation-code-block">
                    <div className="validation-code-title">Error codes</div>
                    <div className="validation-code-list">
                      {importResult.error_codes.map((code) => (
                        <span key={code} className="validation-code-chip is-error">{code}</span>
                      ))}
                    </div>
                  </div>
                )}
                {importErrorIssues.length > 0 ? (
                  <div className="validation-issue-block">
                    <div className="validation-code-title">{importErrorIssues.length} issue{importErrorIssues.length === 1 ? '' : 's'} found</div>
                    <details className="validation-details" open={importErrorIssues.length <= 4}>
                      <summary>Show issue details</summary>
                      <ul>
                        {importErrorIssues.map((issue, i) => (
                          <li key={`${issue.code || 'error'}-${issue.path || 'path'}-${i}`}>
                            [{issue.code || 'UNKNOWN'}] {issue.message}
                            {issue.path ? ` (${issue.path})` : ''}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </div>
                ) : (
                  <ul>
                    {importResult.errors?.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                )}
              </>
            )}

            {importResult.warnings?.length > 0 && (
              <>
                <div className="warning">⚠ Warnings</div>
                {Array.isArray(importResult.warning_codes) && importResult.warning_codes.length > 0 && (
                  <div className="validation-code-block">
                    <div className="validation-code-title">Warning codes</div>
                    <div className="validation-code-list">
                      {importResult.warning_codes.map((code) => (
                        <span key={code} className="validation-code-chip is-warning">{code}</span>
                      ))}
                    </div>
                  </div>
                )}
                {importWarningIssues.length > 0 ? (
                  <div className="validation-issue-block">
                    <div className="validation-code-title">{importWarningIssues.length} warning issue{importWarningIssues.length === 1 ? '' : 's'}</div>
                    <details className="validation-details" open={importWarningIssues.length <= 3}>
                      <summary>Show warning details</summary>
                      <ul>
                        {importWarningIssues.map((issue, i) => (
                          <li key={`${issue.code || 'warning'}-${issue.path || 'path'}-${i}`}>
                            [{issue.code || 'UNKNOWN'}] {issue.message}
                            {issue.path ? ` (${issue.path})` : ''}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </div>
                ) : (
                  <ul>
                    {importResult.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                )}
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
  )
}
