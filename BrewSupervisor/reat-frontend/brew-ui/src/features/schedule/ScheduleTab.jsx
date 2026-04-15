import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

function decodeBase64Text(contentB64) {
  const raw = window.atob(String(contentB64 || ''))
  const bytes = Uint8Array.from(raw, (char) => char.charCodeAt(0))
  return new TextDecoder('utf-8').decode(bytes)
}

function readPath(root, path) {
  if (!root || typeof root !== 'object') return undefined
  const parts = String(path || '').split('.').filter(Boolean)
  let cursor = root
  for (const part of parts) {
    if (!cursor || typeof cursor !== 'object' || !(part in cursor)) return undefined
    cursor = cursor[part]
  }
  return cursor
}

function writePath(root, path, value) {
  const parts = String(path || '').split('.').filter(Boolean)
  if (!parts.length) return
  let cursor = root
  for (let i = 0; i < parts.length - 1; i += 1) {
    const key = parts[i]
    if (!cursor[key] || typeof cursor[key] !== 'object' || Array.isArray(cursor[key])) {
      cursor[key] = {}
    }
    cursor = cursor[key]
  }
  cursor[parts[parts.length - 1]] = value
}

function flattenSpecFields(spec) {
  if (!spec || typeof spec !== 'object') return []
  const sections = Array.isArray(spec.sections) ? spec.sections : []
  const fields = []
  for (const section of sections) {
    const sectionFields = Array.isArray(section?.fields) ? section.fields : []
    for (const field of sectionFields) {
      const path = String(field || '').trim()
      if (!path || fields.includes(path)) continue
      fields.push(path)
    }
  }
  return fields
}

function inferFieldType(value) {
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return 'number'
  if (Array.isArray(value)) return 'json'
  if (value && typeof value === 'object') return 'json'
  return 'string'
}

export function ScenarioControlsBar({ scenario, runToggle, loadingAction, selected, runAction }) {
  return (
    <div className="control-bar">
      <div className="control-bar-copy">
        <strong>Run controls</strong>
        <span>{runToggle.hint}</span>
      </div>
      <div className="control-button-group">
        <button
          className={`primary-button ${scenario?.state === 'running' ? 'is-running' : scenario?.state === 'paused' ? 'is-restart' : ''}`}
          disabled={!selected || loadingAction}
          onClick={() => runAction('/scenario/run/start')}
        >
          {scenario?.state === 'running' ? 'Running' : scenario?.state === 'paused' ? 'Restart' : 'Start'}
        </button>
        <button
          className={runToggle.className}
          disabled={!selected || loadingAction || runToggle.disabled}
          onClick={() => runToggle.path && runAction(runToggle.path)}
        >
          {runToggle.label}
        </button>
        <button className="secondary-button" disabled={!selected || loadingAction} onClick={() => runAction('/scenario/run/stop')}>
          Stop
        </button>
        <button className="secondary-button" disabled={!selected || loadingAction} onClick={() => runAction('/scenario/run/previous')}>
          Previous
        </button>
        <button className="secondary-button" disabled={!selected || loadingAction} onClick={() => runAction('/scenario/run/next')}>
          Next
        </button>
      </div>
    </div>
  )
}

export function ScenarioSummaryCard({ scenario, scenarioPackage }) {
  return (
    <div className="info-card schedule-card">
      <div className="card-header-row">
        <h3>Scenario</h3>
        <span className={`pill ${scenario?.state === 'running' ? 'pill-ok' : scenario?.state === 'paused' ? 'pill-warn' : 'pill-neutral'}`}>
          {scenario?.state || 'idle'}
        </span>
      </div>
      <div className="info-rows-grid">
        <div className="info-row"><span>Package name</span><strong>{scenarioPackage?.name || '-'}</strong></div>
        <div className="info-row"><span>Package id</span><strong>{scenarioPackage?.id || '-'}</strong></div>
        <div className="info-row"><span>Run phase</span><strong>{scenario?.phase || '-'}</strong></div>
        <div className="info-row"><span>Run index</span><strong>{scenario?.current_step_index ?? '-'}</strong></div>
        <div className="info-row info-row-block"><span>Step</span><strong>{scenario?.current_step_name || '-'}</strong></div>
        <div className="info-row info-row-block"><span>Wait</span><strong>{scenario?.wait_message || '-'}</strong></div>
        <div className="info-row info-row-block"><span>Pause reason</span><strong>{scenario?.pause_reason || '-'}</strong></div>
      </div>
    </div>
  )
}

export function ScenarioPackageCard({
  selected,
  loadingAction,
  scenarioFile,
  setScenarioFile,
  uploadWorkbook,
  importResult,
  importErrorIssues,
  importWarningIssues,
  scenarioPackage,
  tunePackageArtifact,
  tuneEditorSpec,
  tunePackagePatch,
}) {
  const fileInputRef = useRef(null)
  const [artifactPath, setArtifactPath] = useState('data/program.json')
  const [artifactFile, setArtifactFile] = useState(null)
  const [editorSpecText, setEditorSpecText] = useState('')
  const [editorModalOpen, setEditorModalOpen] = useState(false)
  const [specEditorError, setSpecEditorError] = useState('')
  const [specFieldDrafts, setSpecFieldDrafts] = useState({})

  const resolvedEditorSpec = useMemo(() => {
    const editorSpecMeta = scenarioPackage?.editor_spec
    const artifactPathFromSpec = String(editorSpecMeta?.artifact || editorSpecMeta?.schema_artifact || '').trim()
    const artifacts = Array.isArray(scenarioPackage?.artifacts) ? scenarioPackage.artifacts : []
    if (artifactPathFromSpec) {
      const artifact = artifacts.find((item) => String(item?.path || '').trim() === artifactPathFromSpec)
      if (artifact?.content_b64) {
        try {
          const parsed = JSON.parse(decodeBase64Text(artifact.content_b64))
          if (parsed && typeof parsed === 'object') return parsed
        } catch {
          // Fall back to manifest-level spec below.
        }
      }
    }
    if (editorSpecMeta && typeof editorSpecMeta === 'object') {
      return editorSpecMeta
    }
    return null
  }, [scenarioPackage])

  const specFieldPaths = useMemo(() => flattenSpecFields(resolvedEditorSpec), [resolvedEditorSpec])

  const specFieldTypes = useMemo(() => {
    const result = {}
    for (const path of specFieldPaths) {
      result[path] = inferFieldType(readPath(scenarioPackage, path))
    }
    return result
  }, [scenarioPackage, specFieldPaths])

  useEffect(() => {
    const editorSpec = scenarioPackage?.editor_spec
    if (!editorSpec || typeof editorSpec !== 'object') {
      setEditorSpecText('')
      return
    }
    try {
      setEditorSpecText(JSON.stringify(editorSpec, null, 2))
    } catch {
      setEditorSpecText('')
    }
  }, [scenarioPackage])

  useEffect(() => {
    const nextDrafts = {}
    for (const path of specFieldPaths) {
      const value = readPath(scenarioPackage, path)
      if (value === undefined || value === null) {
        nextDrafts[path] = ''
      } else if (typeof value === 'object') {
        try {
          nextDrafts[path] = JSON.stringify(value, null, 2)
        } catch {
          nextDrafts[path] = ''
        }
      } else {
        nextDrafts[path] = String(value)
      }
    }
    setSpecFieldDrafts(nextDrafts)
    setSpecEditorError('')
  }, [scenarioPackage, specFieldPaths])

  useEffect(() => {
    if (!editorModalOpen) return undefined
    function onKeyDown(event) {
      if (event.key === 'Escape') {
        setEditorModalOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [editorModalOpen])

  useEffect(() => {
    if (!editorModalOpen) return undefined
    const body = document.body
    const previousOverflow = body.style.overflow
    const previousPaddingRight = body.style.paddingRight
    const scrollbarCompensation = window.innerWidth - document.documentElement.clientWidth

    body.classList.add('modal-open')
    body.style.overflow = 'hidden'
    if (scrollbarCompensation > 0) {
      body.style.paddingRight = `${scrollbarCompensation}px`
    }

    return () => {
      body.classList.remove('modal-open')
      body.style.overflow = previousOverflow
      body.style.paddingRight = previousPaddingRight
    }
  }, [editorModalOpen])

  async function applySpecEditorPatch() {
    if (!tunePackagePatch || !specFieldPaths.length) return
    const patch = {}
    try {
      for (const path of specFieldPaths) {
        const raw = specFieldDrafts[path] ?? ''
        const fieldType = specFieldTypes[path] || 'string'
        let parsedValue
        if (fieldType === 'boolean') {
          const lowered = String(raw).trim().toLowerCase()
          parsedValue = lowered === 'true' || lowered === '1' || lowered === 'on'
        } else if (fieldType === 'number') {
          const numberValue = Number(raw)
          if (!Number.isFinite(numberValue)) {
            throw new Error(`Field ${path} requires a numeric value`)
          }
          parsedValue = numberValue
        } else if (fieldType === 'json') {
          parsedValue = raw.trim() ? JSON.parse(raw) : null
        } else {
          parsedValue = String(raw)
        }
        writePath(patch, path, parsedValue)
      }
    } catch (err) {
      setSpecEditorError(err instanceof Error ? err.message : 'Invalid edit payload')
      return
    }

    setSpecEditorError('')
    await tunePackagePatch(patch)
    setEditorModalOpen(false)
  }

  const packageActionDisabledReason =
    !selected
      ? 'Select a fermenter first'
      : !scenarioFile
        ? 'Choose a package file first'
        : loadingAction
          ? 'Action in progress'
          : ''

  function openPackageFilePicker() {
    fileInputRef.current?.click()
  }

  return (
    <div className="info-card workbook-card">
      <h3>Scenario package workbook</h3>
      <div className="upload-row">
        <button type="button" className="file-picker-button" onClick={openPackageFilePicker}>Choose package file</button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip,.lbpkg"
          onClick={(e) => {
            e.currentTarget.value = ''
          }}
          onChange={(e) => setScenarioFile(e.target.files?.[0] || null)}
          className="hidden-file-input"
        />
        <div className="selected-file-name">{scenarioFile ? scenarioFile.name : 'No file selected'}</div>
      </div>

      <div className="button-row">
        <button
          className="secondary-button"
          disabled={!selected || !scenarioFile || loadingAction}
          title={packageActionDisabledReason}
          onClick={() => uploadWorkbook('/scenario/validate-import')}
        >
          Validate package
        </button>
        <button
          className="primary-button"
          disabled={!selected || !scenarioFile || loadingAction}
          title={packageActionDisabledReason}
          onClick={() => uploadWorkbook('/scenario/import')}
        >
          Import package
        </button>
        <button
          className="secondary-button"
          disabled={!selected || loadingAction || !scenarioPackage}
          onClick={() => setEditorModalOpen(true)}
        >
          Edit package
        </button>
      </div>

      {editorModalOpen && typeof document !== 'undefined' ? createPortal((
        <div className="pdb-modal-overlay scenario-editor-overlay" onClick={(event) => event.target === event.currentTarget && setEditorModalOpen(false)}>
          <div className="pdb-modal pdb-modal-editor scenario-package-editor-modal" onClick={(event) => event.stopPropagation()}>
            <div className="pdb-modal-header">
              <h3>Edit Scenario Package</h3>
              <button className="pdb-close-btn" onClick={() => setEditorModalOpen(false)}>✕</button>
            </div>

            <div className="pdb-modal-body scenario-package-editor-body">
              <div className="scenario-package-editor-section">
                <div className="scenario-package-editor-title-row">
                  <h4>Spec-driven fields</h4>
                  <span className="small-text">Generated from editor spec artifact</span>
                </div>
                {!specFieldPaths.length ? (
                  <div className="muted">No editable fields were found in the loaded spec.</div>
                ) : (
                  <div className="scenario-spec-field-grid">
                    {specFieldPaths.map((path) => {
                      const type = specFieldTypes[path] || 'string'
                      const value = specFieldDrafts[path] ?? ''
                      return (
                        <label key={path} className="scenario-spec-field-item">
                          <div className="scenario-spec-field-header">
                            <span>{path}</span>
                            <span className="scenario-spec-field-type">{type}</span>
                          </div>
                          {type === 'json' ? (
                            <textarea
                              rows={6}
                              className="pdb-textarea"
                              value={value}
                              onChange={(e) => setSpecFieldDrafts((current) => ({ ...current, [path]: e.target.value }))}
                              disabled={!selected || loadingAction}
                            />
                          ) : (
                            <input
                              className="pdb-input"
                              type={type === 'number' ? 'number' : 'text'}
                              value={value}
                              onChange={(e) => setSpecFieldDrafts((current) => ({ ...current, [path]: e.target.value }))}
                              disabled={!selected || loadingAction}
                            />
                          )}
                        </label>
                      )
                    })}
                  </div>
                )}
                {specEditorError && <div className="error">✖ {specEditorError}</div>}
              </div>

              <div className="scenario-package-editor-section">
                <div className="scenario-package-editor-title-row">
                  <h4>Artifact update</h4>
                  <span className="small-text">Patch JSON/CSV/TXT artifacts in package</span>
                </div>
                <div className="scenario-artifact-controls">
                  <label className="scenario-spec-field-item">
                    <div className="scenario-spec-field-header">
                      <span>Artifact path</span>
                    </div>
                    <input
                      className="pdb-input"
                      type="text"
                      value={artifactPath}
                      onChange={(e) => setArtifactPath(e.target.value)}
                      placeholder="data/program.json"
                      disabled={!selected || loadingAction}
                    />
                  </label>
                  <div className="upload-row">
                    <input
                      type="file"
                      accept=".json,.csv,.txt"
                      onClick={(e) => {
                        e.currentTarget.value = ''
                      }}
                      onChange={(e) => setArtifactFile(e.target.files?.[0] || null)}
                      disabled={!selected || loadingAction}
                    />
                    <div className="selected-file-name">{artifactFile ? artifactFile.name : 'No artifact file selected'}</div>
                    <button
                      className="secondary-button"
                      disabled={!selected || !artifactFile || !artifactPath.trim() || loadingAction}
                      onClick={() => tunePackageArtifact?.({ path: artifactPath.trim(), file: artifactFile })}
                    >
                      Apply artifact update
                    </button>
                  </div>
                </div>
              </div>

              <div className="scenario-package-editor-section">
                <div className="scenario-package-editor-title-row">
                  <h4>Editor spec JSON</h4>
                  <span className="small-text">Advanced: replace loaded editor spec</span>
                </div>
                <textarea
                  className="pdb-textarea"
                  rows={10}
                  value={editorSpecText}
                  onChange={(e) => setEditorSpecText(e.target.value)}
                  placeholder={`{\n  "artifact": "editor/spec.json"\n}`}
                  disabled={!selected || loadingAction}
                />
                <div className="button-row">
                  <button
                    className="secondary-button"
                    disabled={!selected || !editorSpecText.trim() || loadingAction}
                    onClick={() => tuneEditorSpec?.(editorSpecText)}
                  >
                    Apply editor spec
                  </button>
                </div>
              </div>
            </div>

            <div className="pdb-modal-footer">
              <button className="pdb-btn-secondary" disabled={loadingAction} onClick={() => setEditorModalOpen(false)}>Close</button>
              <button
                className="pdb-btn-primary"
                disabled={!selected || loadingAction || !specFieldPaths.length}
                onClick={applySpecEditorPatch}
              >
                Apply spec edits
              </button>
            </div>
          </div>
        </div>
      ), document.body) : null}

      {importResult && (
        <div className="import-result">
          {importResult.valid ? (
            <>
              <div className="success">✔ Scenario package valid</div>
              <div className="summary">
                <div>Name: {importResult.scenario_package?.name || importResult.schedule?.name}</div>
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
                <ul>{importResult.errors?.map((e, i) => <li key={i}>{typeof e === 'string' ? e : (e?.message || JSON.stringify(e))}</li>)}</ul>
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
                <ul>{importResult.warnings.map((w, i) => <li key={i}>{typeof w === 'string' ? w : (w?.message || JSON.stringify(w))}</li>)}</ul>
              )}
            </>
          )}
        </div>
      )}

      <div className="package-tune-panel">
        <h4>Package editing</h4>
      </div>
    </div>
  )
}

export function ScenarioEventLogCard({ scenario }) {
  const logRef = useRef(null)
  const [followLogBottom, setFollowLogBottom] = useState(true)

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
    if (!scenario?.event_log?.length) return
    if (!followLogBottom) return
    const timeoutId = window.setTimeout(() => {
      scrollEventLogToBottom('smooth')
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [scenario?.event_log, followLogBottom])

  return (
    <div className="info-card scenario-event-log-card">
      <div className="card-header-row">
        <h3>Event log</h3>
        <span className="small-text">Newest entries append at the bottom</span>
      </div>
      {!scenario?.event_log?.length ? (
        <p className="muted">No events yet.</p>
      ) : (
        <div className="event-log-wrap">
          <div ref={logRef} className="event-list" onScroll={handleEventLogScroll}>
            {scenario.event_log.map((event, index) => (
              <div key={index} className="event-item">{event}</div>
            ))}
          </div>
          {!followLogBottom && (
            <button className="log-jump-button" onClick={() => scrollEventLogToBottom()} aria-label="Jump to latest log entry" title="Jump to latest">
              ↓
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function ScenarioTab(props) {
  const {
    scenario,
    scenarioPackage,
    runToggle,
    loadingAction,
    selected,
    runAction,
    scenarioFile,
    setScenarioFile,
    uploadWorkbook,
    importResult,
    importErrorIssues,
    importWarningIssues,
    tunePackageArtifact,
    tuneEditorSpec,
    tunePackagePatch,
  } = props
  return (
    <div className="tab-content-grid">
      <ScenarioControlsBar scenario={scenario} runToggle={runToggle} loadingAction={loadingAction} selected={selected} runAction={runAction} />
      <ScenarioSummaryCard scenario={scenario} scenarioPackage={scenarioPackage} />
      <ScenarioPackageCard
        selected={selected}
        loadingAction={loadingAction}
        scenarioFile={scenarioFile}
        setScenarioFile={setScenarioFile}
        uploadWorkbook={uploadWorkbook}
        importResult={importResult}
        importErrorIssues={importErrorIssues}
        importWarningIssues={importWarningIssues}
        scenarioPackage={scenarioPackage}
        tunePackageArtifact={tunePackageArtifact}
        tuneEditorSpec={tuneEditorSpec}
        tunePackagePatch={tunePackagePatch}
      />
      <ScenarioEventLogCard scenario={scenario} />
    </div>
  )
}
