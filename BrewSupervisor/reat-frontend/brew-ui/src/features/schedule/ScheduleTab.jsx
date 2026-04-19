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

function mergeObjectPatch(target, patch) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return target
  const result = target && typeof target === 'object' && !Array.isArray(target) ? target : {}
  for (const [key, value] of Object.entries(patch)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const base = result[key] && typeof result[key] === 'object' && !Array.isArray(result[key]) ? result[key] : {}
      result[key] = mergeObjectPatch(base, value)
    } else {
      result[key] = value
    }
  }
  return result
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

function pathToLabel(path) {
  const last = path.split('.').pop() || path
  return last.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function flattenSpecSections(spec) {
  if (!spec || typeof spec !== 'object') return []
  return (Array.isArray(spec.sections) ? spec.sections : []).map((section) => ({
    id: section?.id || '',
    title: section?.title || section?.id || 'Fields',
    fields: (Array.isArray(section?.fields) ? section.fields : []).map((f) => String(f || '').trim()).filter(Boolean),
  })).filter((s) => s.fields.length > 0)
}

function inferFieldType(value) {
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return 'number'
  if (Array.isArray(value)) return 'json'
  if (value && typeof value === 'object') return 'json'
  return 'string'
}

function resolveActionTemplate(template, scenarioPackage) {
  const source = String(template || '')
  return source.replace(/\$\{package\.([a-zA-Z0-9_.-]+)\}/g, (_, path) => {
    const value = readPath(scenarioPackage, path)
    if (value === undefined || value === null) return ''
    return String(value)
  })
}

function resolveActionQuery(action, scenarioPackage, editingFilename = '') {
  const raw = action && typeof action === 'object' ? action.query : null
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return editingFilename ? { filename: String(editingFilename) } : {}
  }
  const result = {}
  for (const [key, value] of Object.entries(raw)) {
    if (!key) continue
    result[String(key)] = resolveActionTemplate(value, scenarioPackage)
  }
  if (editingFilename) {
    // While editing a repository package, replace operations must overwrite that file.
    result.filename = String(editingFilename)
  }
  return result
}

function normalizeTagList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean)
  }
  if (typeof value === 'string') {
    return value.split(',').map((item) => item.trim()).filter(Boolean)
  }
  return []
}

function formatRepositoryTimestamp(date = new Date()) {
  const pad2 = (value) => String(value).padStart(2, '0')
  const year = String(date.getFullYear())
  const month = pad2(date.getMonth() + 1)
  const day = pad2(date.getDate())
  const hours = pad2(date.getHours())
  const minutes = pad2(date.getMinutes())
  const seconds = pad2(date.getSeconds())
  return `${year}${month}${day}-${hours}${minutes}${seconds}`
}

function buildRepositoryCopyFilename(filename) {
  const stem = String(filename || '').replace(/\.lbpkg$/i, '')
  const baseName = stem
    .replace(/-copy-\d+$/i, '')
    .replace(/-\d{8}-\d{6}$/i, '')
    .replace(/-copy$/i, '')
    || 'package'
  return `${baseName}-${formatRepositoryTimestamp()}.lbpkg`
}

function buildTemplateInstanceFilename(templateName) {
  const stem = String(templateName || '').replace(/\.lbpkg$/i, '') || 'template'
  return `${stem}-${formatRepositoryTimestamp()}.lbpkg`
}

function resolveRepositorySavePayload(editorSpec, scenarioPackage) {
  const saveSpec = editorSpec && typeof editorSpec === 'object' ? editorSpec.repository_save : null
  const fallbackName = scenarioPackage?.id || scenarioPackage?.name || 'package'

  const filename = String(
    (saveSpec && typeof saveSpec.filename_template === 'string'
      ? resolveActionTemplate(saveSpec.filename_template, scenarioPackage)
      : fallbackName) || fallbackName
  ).trim()

  const tagsPath = saveSpec && typeof saveSpec.tags_path === 'string' ? saveSpec.tags_path : ''
  const versionNotesPath = saveSpec && typeof saveSpec.version_notes_path === 'string' ? saveSpec.version_notes_path : ''
  const notesPath = saveSpec && typeof saveSpec.notes_path === 'string' ? saveSpec.notes_path : ''

  const tagsValue = tagsPath ? readPath(scenarioPackage, tagsPath) : scenarioPackage?.tags
  const versionNotesValue = versionNotesPath ? readPath(scenarioPackage, versionNotesPath) : scenarioPackage?.version
  const notesValue = notesPath ? readPath(scenarioPackage, notesPath) : scenarioPackage?.description

  return {
    filename,
    tags: normalizeTagList(tagsValue),
    versionNotes: String(versionNotesValue || ''),
    notes: String(notesValue || ''),
  }
}

function SplitStartButton({ scenario, loadingAction, selected, runAction }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [indexInput, setIndexInput] = useState('')
  const menuRef = useRef(null)
  const popoverRef = useRef(null)
  const inputRef = useRef(null)
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0, width: 200 })

  const isRunning = scenario?.state === 'running'
  const isRestart = scenario?.state === 'paused'
  const mainLabel = isRunning ? 'Running' : isRestart ? 'Restart' : 'Start'
  const mainClass = `primary-button split-start-main${isRunning ? ' is-running' : isRestart ? ' is-restart' : ''}`

  useEffect(() => {
    if (!menuOpen) return undefined
    const updateMenuPosition = () => {
      const rect = menuRef.current?.getBoundingClientRect()
      if (!rect) return
      setMenuPosition({
        top: rect.bottom + 6,
        left: rect.left,
        width: Math.max(200, rect.width),
      })
    }
    updateMenuPosition()
    if (inputRef.current) inputRef.current.focus()
    function onMouseDown(e) {
      const inAnchor = menuRef.current?.contains(e.target)
      const inPopover = popoverRef.current?.contains(e.target)
      if (!inAnchor && !inPopover) setMenuOpen(false)
    }
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    window.addEventListener('mousedown', onMouseDown)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
      window.removeEventListener('mousedown', onMouseDown)
    }
  }, [menuOpen])

  function handleMainClick() {
    runAction('/scenario/run/start')
  }

  function handleStartAtIndex() {
    const runIndex = parseInt(indexInput, 10)
    if (!Number.isFinite(runIndex) || runIndex < 1) return
    runAction('/scenario/run/start', { run_index: runIndex })
    setMenuOpen(false)
    setIndexInput('')
  }

  return (
    <div className="split-start-wrap" ref={menuRef}>
      <button
        className={mainClass}
        disabled={!selected || loadingAction}
        onClick={handleMainClick}
      >
        {mainLabel}
      </button>
      <button
        className="primary-button split-start-chevron"
        disabled={!selected || loadingAction}
        onClick={() => setMenuOpen((o) => !o)}
        aria-label="Start at run index"
        title="Start at run index…"
      >
        ▾
      </button>
      {menuOpen && typeof document !== 'undefined' ? createPortal((
        <div
          ref={popoverRef}
          className="split-start-popover"
          style={{ top: `${menuPosition.top}px`, left: `${menuPosition.left}px`, minWidth: `${menuPosition.width}px` }}
        >
          <label className="split-start-label">Start at run index</label>
          <div className="split-start-row">
            <input
              ref={inputRef}
              className="pdb-input split-start-input"
              type="number"
              min="1"
              placeholder="1"
              value={indexInput}
              onChange={(e) => setIndexInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleStartAtIndex() }}
            />
            <button
              className="pdb-btn-primary"
              disabled={indexInput === '' || !Number.isFinite(parseInt(indexInput, 10))}
              onClick={handleStartAtIndex}
            >
              Go
            </button>
          </div>
        </div>
      ), document.body) : null}
    </div>
  )
}

export function ScenarioControlsBar({ scenario, runToggle, loadingAction, selected, runAction }) {
  return (
    <div className="control-bar">
      <div className="control-bar-copy">
        <strong>Run controls</strong>
        <span>{runToggle.hint}</span>
      </div>
      <div className="control-button-group">
        <SplitStartButton scenario={scenario} loadingAction={loadingAction} selected={selected} runAction={runAction} />
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

export function ScenarioQueueCard({
  scenarioQueue,
  scenarioQueueEnabled,
  queueAdvanceOnStop,
  scenarioPackage,
  selected,
  loadingAction,
  setScenarioQueueEntries,
  enqueueScenarioRun,
  removeScenarioQueueEntry,
  clearScenarioQueue,
}) {
  const queueItems = Array.isArray(scenarioQueue) ? scenarioQueue : []

  function updateQueueEntry(index, patch) {
    if (index < 0 || index >= queueItems.length) return
    const nextEntries = queueItems.map((item, idx) => (idx === index ? { ...item, ...patch } : item))
    setScenarioQueueEntries(nextEntries, queueAdvanceOnStop, scenarioQueueEnabled)
  }

  function moveQueueEntry(index, direction) {
    const target = index + direction
    if (index < 0 || index >= queueItems.length) return
    if (target < 0 || target >= queueItems.length) return
    const nextEntries = [...queueItems]
    const [moved] = nextEntries.splice(index, 1)
    nextEntries.splice(target, 0, moved)
    setScenarioQueueEntries(nextEntries, queueAdvanceOnStop, scenarioQueueEnabled)
  }

  return (
    <div className="info-card scenario-queue-card">
      <div className="card-header-row">
        <h3>Run queue</h3>
        <button
          className="warning-button icon-only-button"
          title="Clear queue"
          disabled={!selected || loadingAction || !queueItems.length}
          onClick={clearScenarioQueue}
        >
          <svg className="trash-icon" viewBox="0 0 18 18" aria-hidden="true">
            <path className="trash-body" d="M4 2h10v1H4zm1 2h8v11c0 0.55-0.45 1-1 1H6c-0.55 0-1-0.45-1-1V4zm2-1v-1h2V2h2v1h2v1H7V3z" />
            <rect className="trash-line" x="7" y="5" width="1" height="8" />
            <rect className="trash-line" x="10" y="5" width="1" height="8" />
          </svg>
        </button>
      </div>

      <div className="scenario-queue-controls">
        <label className="small-text" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={Boolean(scenarioQueueEnabled)}
            disabled={!selected || loadingAction}
            onChange={(e) => setScenarioQueueEntries(queueItems, queueAdvanceOnStop, e.target.checked)}
          />
          Queue enabled
        </label>
        <label className="small-text" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={Boolean(queueAdvanceOnStop)}
            disabled={!selected || loadingAction}
            onChange={(e) => setScenarioQueueEntries(queueItems, e.target.checked, scenarioQueueEnabled)}
          />
          Auto-advance when stopped (not only completed)
        </label>
        <div className="small-text">Enabled entries: {queueItems.filter((item) => item?.enabled !== false).length} / {queueItems.length}</div>
      </div>

      <div className="event-list">
        {!queueItems.length ? (
          <p className="muted" style={{ margin: 0, padding: '4px 0' }}>Queue is empty.</p>
        ) : (
          queueItems.map((item, index) => (
            <div key={`${item.package_id}-${index}`} className="event-item">
              <div className="queue-entry-main-row">
                <div style={{ minWidth: 0 }}>
                  <strong>{item.label || item.package_id}</strong>
                  <div className="small-text">id: {item.package_id}</div>
                  {item.package_filename ? <div className="small-text">file: {item.package_filename}</div> : null}
                  {item.run_index ? <div className="small-text">run index: {item.run_index}</div> : null}
                </div>
                <div className="button-row" style={{ gap: '6px' }}>
                  <button
                    className="secondary-button"
                    disabled={!selected || loadingAction || index <= 0}
                    onClick={() => moveQueueEntry(index, -1)}
                  >
                    Up
                  </button>
                  <button
                    className="secondary-button"
                    disabled={!selected || loadingAction || index >= queueItems.length - 1}
                    onClick={() => moveQueueEntry(index, 1)}
                  >
                    Down
                  </button>
                  <button
                    className="warning-button icon-only-button"
                    disabled={!selected || loadingAction}
                    onClick={() => removeScenarioQueueEntry(index)}
                    title="Remove from queue"
                  >
                    <svg className="trash-icon" viewBox="0 0 18 18" aria-hidden="true">
                      <path className="trash-body" d="M4 2h10v1H4zm1 2h8v11c0 0.55-0.45 1-1 1H6c-0.55 0-1-0.45-1-1V4zm2-1v-1h2V2h2v1h2v1H7V3z" />
                      <rect className="trash-line" x="7" y="5" width="1" height="8" />
                      <rect className="trash-line" x="10" y="5" width="1" height="8" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="queue-entry-footer-row">
                <label className="small-text queue-entry-enabled-toggle">
                  <input
                    type="checkbox"
                    checked={item?.enabled !== false}
                    disabled={!selected || loadingAction}
                    onChange={(e) => updateQueueEntry(index, { enabled: e.target.checked })}
                  />
                  Enabled
                </label>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export function ScenarioPackageCard({
  selected,
  loadingAction,
  importResult,
  importErrorIssues,
  importWarningIssues,
  scenarioPackage,
  tunePackagePatch,
  listScenarioRepositoryPackages,
  saveScenarioRepositoryPackage,
  readScenarioRepositoryPackage,
  importScenarioRepositoryPackage,
  copyScenarioRepositoryPackage,
  enqueueScenarioRun,
  listScenarioRepositoryTemplates,
  createScenarioRepositoryPackageFromTemplate,
  renameScenarioRepositoryPackage,
  deleteScenarioRepositoryPackage,
  updateScenarioRepositoryMetadata,
  uploadScenarioRepositoryPackage,
  getScenarioRepositoryDownloadUrl,
  uploadFileToEndpoint,
}) {
  const uploadFileInputRef = useRef(null)
  const [editorModalOpen, setEditorModalOpen] = useState(false)
  const [specEditorError, setSpecEditorError] = useState('')
  const [specFieldDrafts, setSpecFieldDrafts] = useState({})
  const [repoPackages, setRepoPackages] = useState([])
  const [repoError, setRepoError] = useState('')
  const [repoBusy, setRepoBusy] = useState(false)
  const [repoSearch, setRepoSearch] = useState('')
  const [repoTagFilter, setRepoTagFilter] = useState('')
  const [fileUploadFiles, setFileUploadFiles] = useState({})
  const [repoEditingFilename, setRepoEditingFilename] = useState('')
  const [repoEditingPackage, setRepoEditingPackage] = useState(null)
  const [templateMenuOpen, setTemplateMenuOpen] = useState(false)
  const [templateItems, setTemplateItems] = useState([])
  const [repoActionsOpenFor, setRepoActionsOpenFor] = useState('')
  const [importResultVisible, setImportResultVisible] = useState(false)
  const importDismissTimerRef = useRef(null)
  const templateMenuRef = useRef(null)
  const repoActionsMenuRef = useRef(null)
  const lastImportResultRef = useRef(importResult)

  useEffect(() => {
    if (lastImportResultRef.current === importResult) {
      return () => clearTimeout(importDismissTimerRef.current)
    }
    lastImportResultRef.current = importResult
    if (importResult) {
      setImportResultVisible(true)
      clearTimeout(importDismissTimerRef.current)
      importDismissTimerRef.current = setTimeout(() => setImportResultVisible(false), 4000)
    } else {
      setImportResultVisible(false)
    }
    return () => clearTimeout(importDismissTimerRef.current)
  }, [importResult])

  const packageForEditor = repoEditingPackage || scenarioPackage

  async function refreshRepository() {
    if (!selected || !listScenarioRepositoryPackages) return
    try {
      setRepoBusy(true)
      setRepoError('')
      const payload = await listScenarioRepositoryPackages()
      setRepoPackages(Array.isArray(payload?.packages) ? payload.packages : [])
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to load package repository')
    } finally {
      setRepoBusy(false)
    }
  }

  async function refreshTemplates() {
    if (!selected || !listScenarioRepositoryTemplates) {
      setTemplateItems([])
      return
    }
    const payload = await listScenarioRepositoryTemplates()
    setTemplateItems(Array.isArray(payload?.templates) ? payload.templates : [])
  }

  useEffect(() => {
    if (!selected?.id) {
      setRepoPackages([])
      setTemplateItems([])
      setRepoError('')
      setTemplateMenuOpen(false)
      return
    }
    refreshRepository().catch(() => {})
    refreshTemplates().catch(() => {})
  }, [selected?.id])

  useEffect(() => {
    if (!templateMenuOpen) return undefined
    function onMouseDown(event) {
      if (!templateMenuRef.current) return
      if (!templateMenuRef.current.contains(event.target)) {
        setTemplateMenuOpen(false)
      }
    }
    window.addEventListener('mousedown', onMouseDown)
    return () => window.removeEventListener('mousedown', onMouseDown)
  }, [templateMenuOpen])

  useEffect(() => {
    if (!repoActionsOpenFor) return undefined
    function onMouseDown(event) {
      if (!repoActionsMenuRef.current) return
      if (!repoActionsMenuRef.current.contains(event.target)) {
        setRepoActionsOpenFor('')
      }
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') setRepoActionsOpenFor('')
    }
    window.addEventListener('mousedown', onMouseDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [repoActionsOpenFor])

  async function saveCurrentToRepository() {
    if (!saveScenarioRepositoryPackage) return
    try {
      setRepoBusy(true)
      setRepoError('')
      const sourcePackage = packageForEditor
      const savePayload = resolveRepositorySavePayload(resolvedEditorSpec, sourcePackage)
      await saveScenarioRepositoryPackage({
        filename: repoEditingFilename || savePayload.filename,
        packagePayload: sourcePackage,
        tags: savePayload.tags,
        versionNotes: savePayload.versionNotes,
        notes: savePayload.notes,
      })
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to save package to repository')
    } finally {
      setRepoBusy(false)
    }
  }

  async function uploadPackageToRepository(file) {
    if (!uploadScenarioRepositoryPackage || !file) return
    try {
      setRepoBusy(true)
      setRepoError('')
      await uploadScenarioRepositoryPackage({
        file,
        filename: file.name,
      })
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to upload package to repository')
    } finally {
      setRepoBusy(false)
    }
  }

  function openRepositoryUploadPicker() {
    uploadFileInputRef.current?.click()
  }

  async function editRepositoryPackage(filename) {
    if (!filename || !readScenarioRepositoryPackage) return
    try {
      setRepoBusy(true)
      setRepoError('')
      const payload = await readScenarioRepositoryPackage(filename)
      const packagePayload = payload && typeof payload.scenario_package === 'object' ? payload.scenario_package : null
      if (!packagePayload) {
        throw new Error('Repository package payload missing')
      }
      setRepoEditingPackage(packagePayload)
      setRepoEditingFilename(filename)
      setEditorModalOpen(true)
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to load repository package for editing')
    } finally {
      setRepoBusy(false)
    }
  }

  async function importFromRepository(filename) {
    if (!importScenarioRepositoryPackage || !filename) return
    try {
      setRepoBusy(true)
      setRepoError('')
      await importScenarioRepositoryPackage(filename)
      setRepoEditingFilename('')
      setRepoEditingPackage(null)
      setEditorModalOpen(false)
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to import package from repository')
    } finally {
      setRepoBusy(false)
    }
  }

  async function queueFromRepository(item) {
    if (!enqueueScenarioRun || !item) return
    try {
      setRepoBusy(true)
      setRepoError('')
      const payload = await readScenarioRepositoryPackage(item.name)
      const packagePayload = payload && typeof payload.scenario_package === 'object' ? payload.scenario_package : null
      const packageId = String(packagePayload?.id || '').trim()
      await enqueueScenarioRun({
        package_id: packageId,
        package_filename: String(item?.name || '').trim(),
        label: String(packagePayload?.name || packageId),
        package_payload: packagePayload,
      })
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to queue package')
    } finally {
      setRepoBusy(false)
    }
  }

  async function copyRepositoryPackage(filename) {
    if (!copyScenarioRepositoryPackage || !filename) return
    const targetName = buildRepositoryCopyFilename(filename)
    try {
      setRepoBusy(true)
      setRepoError('')
      await copyScenarioRepositoryPackage(filename, targetName)
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to copy package')
    } finally {
      setRepoBusy(false)
    }
  }

  async function createFromTemplate(templateName) {
    if (!createScenarioRepositoryPackageFromTemplate || !templateName) return
    const suggestedName = buildTemplateInstanceFilename(templateName)
    const enteredName = window.prompt('New package filename', suggestedName)
    if (!enteredName) return
    try {
      setRepoBusy(true)
      setRepoError('')
      await createScenarioRepositoryPackageFromTemplate({
        templateFilename: templateName,
        filename: enteredName,
      })
      setTemplateMenuOpen(false)
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to create package from template')
    } finally {
      setRepoBusy(false)
    }
  }

  async function renameRepositoryPackage(filename) {
    if (!renameScenarioRepositoryPackage || !filename) return
    const currentStem = filename.replace(/\.lbpkg$/i, '')
    const proposed = window.prompt('Rename package', `${currentStem}-v2`)
    if (!proposed) return
    try {
      setRepoBusy(true)
      setRepoError('')
      await renameScenarioRepositoryPackage(filename, proposed)
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to rename package')
    } finally {
      setRepoBusy(false)
    }
  }

  async function deleteRepositoryPackage(filename) {
    if (!deleteScenarioRepositoryPackage || !filename) return
    if (!window.confirm(`Delete ${filename}?`)) return
    try {
      setRepoBusy(true)
      setRepoError('')
      await deleteScenarioRepositoryPackage(filename)
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to delete package')
    } finally {
      setRepoBusy(false)
    }
  }

  function downloadRepositoryPackage(filename) {
    if (!filename || !getScenarioRepositoryDownloadUrl) return
    const url = getScenarioRepositoryDownloadUrl(filename)
    if (!url) {
      setRepoError('Download URL is unavailable for this package')
      return
    }
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  }

  async function saveRepositoryMetadata(filename) {
    if (!updateScenarioRepositoryMetadata || !filename) return
    try {
      setRepoBusy(true)
      setRepoError('')
      const tags = Array.isArray(scenarioPackage?.tags) ? scenarioPackage.tags : []
      await updateScenarioRepositoryMetadata({
        filename,
        tags,
        versionNotes: scenarioPackage?.version || '',
        notes: scenarioPackage?.description || '',
      })
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : 'Failed to update metadata')
    } finally {
      setRepoBusy(false)
    }
  }

  async function handleSpecFileUploadAction(action) {
    if (!uploadFileToEndpoint) return
    const file = fileUploadFiles[action.id]
    if (!file) return
    const endpoint = String(action?.endpoint || '').trim()
    if (!endpoint) {
      setRepoError('Upload action is missing endpoint in editor spec')
      return
    }
    const query = resolveActionQuery(action, packageForEditor, repoEditingFilename)
    try {
      setRepoBusy(true)
      setRepoError('')
      const result = await uploadFileToEndpoint(endpoint, file, query)
      if (repoEditingFilename && result && typeof result.scenario_package === 'object') {
        setRepoEditingPackage(result.scenario_package)
      }
      if (repoEditingFilename && result && typeof result.saved === 'object' && typeof result.saved.name === 'string') {
        setRepoEditingFilename(result.saved.name)
      }
      setFileUploadFiles((prev) => ({ ...prev, [action.id]: null }))
      await refreshRepository()
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : `Failed: ${action.label}`)
    } finally {
      setRepoBusy(false)
    }
  }

  const visibleRepoPackages = useMemo(() => {
    const query = repoSearch.trim().toLowerCase()
    const tagQuery = repoTagFilter.trim().toLowerCase()
    const filtered = repoPackages.filter((item) => {
      const tags = Array.isArray(item?.tags) ? item.tags : []
      const haystack = `${item?.name || ''} ${tags.join(' ')} ${item?.version_notes || ''} ${item?.notes || ''}`.toLowerCase()
      if (query && !haystack.includes(query)) return false
      if (tagQuery && !tags.some((tag) => String(tag).toLowerCase().includes(tagQuery))) return false
      return true
    })
    filtered.sort((a, b) => {
      const ta = a.modified_at || ''
      const tb = b.modified_at || ''
      if (ta > tb) return -1
      if (ta < tb) return 1
      return 0
    })
    return filtered
  }, [repoPackages, repoSearch, repoTagFilter])

  const resolvedEditorSpec = useMemo(() => {
    const editorSpecMeta = packageForEditor?.editor_spec
    const artifactPathFromSpec = String(editorSpecMeta?.artifact || editorSpecMeta?.schema_artifact || '').trim()
    const artifacts = Array.isArray(packageForEditor?.artifacts) ? packageForEditor.artifacts : []
    if (!artifactPathFromSpec) return null
    const artifact = artifacts.find((item) => String(item?.path || '').trim() === artifactPathFromSpec)
    if (!artifact?.content_b64) return null
    try {
      const parsed = JSON.parse(decodeBase64Text(artifact.content_b64))
      if (parsed && typeof parsed === 'object') return parsed
    } catch {
      return null
    }
    return null
  }, [packageForEditor])

  const editorSpecArtifactStatus = useMemo(() => {
    const editorSpecMeta = packageForEditor?.editor_spec
    const artifactPathFromSpec = String(editorSpecMeta?.artifact || editorSpecMeta?.schema_artifact || '').trim()
    if (!artifactPathFromSpec) return 'Package editor_spec.artifact is missing.'
    if (!resolvedEditorSpec) return `Unable to load editor spec artifact: ${artifactPathFromSpec}`
    return ''
  }, [packageForEditor, resolvedEditorSpec])

  const specFieldPaths = useMemo(() => flattenSpecFields(resolvedEditorSpec), [resolvedEditorSpec])
  const specSections = useMemo(() => flattenSpecSections(resolvedEditorSpec), [resolvedEditorSpec])

  const specFieldTypes = useMemo(() => {
    const result = {}
    for (const path of specFieldPaths) {
      result[path] = inferFieldType(readPath(packageForEditor, path))
    }
    return result
  }, [packageForEditor, specFieldPaths])

  useEffect(() => {
    const nextDrafts = {}
    for (const path of specFieldPaths) {
      const value = readPath(packageForEditor, path)
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
  }, [packageForEditor, specFieldPaths])

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
    if (!specFieldPaths.length) return
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
    if (repoEditingFilename) {
      const nextPackage = JSON.parse(JSON.stringify(packageForEditor || {}))
      mergeObjectPatch(nextPackage, patch)
      setRepoEditingPackage(nextPackage)
      if (saveScenarioRepositoryPackage) {
        try {
          setRepoBusy(true)
          const savePayload = resolveRepositorySavePayload(resolvedEditorSpec, nextPackage)
          await saveScenarioRepositoryPackage({
            filename: repoEditingFilename,
            packagePayload: nextPackage,
            tags: savePayload.tags,
            versionNotes: savePayload.versionNotes,
            notes: savePayload.notes,
          })
          await refreshRepository()
        } catch (err) {
          setSpecEditorError(err instanceof Error ? err.message : 'Failed to save edits to repository file')
          return
        } finally {
          setRepoBusy(false)
        }
      }
    } else {
      if (!tunePackagePatch) return
      await tunePackagePatch(patch)
    }
    setEditorModalOpen(false)
  }

  return (
    <div className="scenario-builder-content">
      <div className="scenario-repo-panel">
        <input
          ref={uploadFileInputRef}
          type="file"
          accept=".zip,.lbpkg"
          onClick={(e) => { e.currentTarget.value = '' }}
          onChange={(e) => {
            const file = e.target.files?.[0] || null
            if (file) uploadPackageToRepository(file)
          }}
          className="hidden-file-input"
        />
        <div className="scenario-repo-toolbar">
          <input
            className="pdb-input scenario-repo-search"
            value={repoSearch}
            onChange={(e) => setRepoSearch(e.target.value)}
            placeholder="Search packages…"
          />
          <input
            className="pdb-input scenario-repo-tag"
            value={repoTagFilter}
            onChange={(e) => setRepoTagFilter(e.target.value)}
            placeholder="Tag filter"
          />
          <button
            className="pdb-btn-ghost"
            disabled={!selected || loadingAction || repoBusy}
            onClick={() => refreshRepository()}
            title="Refresh list"
          >
            ↻
          </button>
          <div className="scenario-template-menu-wrap" ref={templateMenuRef}>
            <button
              className="pdb-btn-primary"
              disabled={!selected || loadingAction || repoBusy}
              onClick={() => setTemplateMenuOpen((open) => !open)}
              title="Create package from template"
            >
              +
            </button>
            {templateMenuOpen && (
              <div className="scenario-template-menu" role="menu" aria-label="Template selection menu">
                {!templateItems.length ? (
                  <div className="scenario-template-empty">No templates found</div>
                ) : (
                  templateItems.map((template) => (
                    <button
                      key={template.name}
                      className="scenario-template-menu-item"
                      onClick={() => createFromTemplate(template.name)}
                      disabled={repoBusy || loadingAction}
                    >
                      {template.name}
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
          <button
            className="pdb-btn-primary"
            disabled={!selected || loadingAction || repoBusy}
            onClick={openRepositoryUploadPicker}
          >
            ↑ Upload
          </button>
        </div>
        {repoError ? <div className="pdb-save-error">✖ {repoError}</div> : null}
        <div className="package-repo-list">
          {!visibleRepoPackages.length ? (
            <div className="muted">No repository packages found.</div>
          ) : (
            visibleRepoPackages.map((item) => {
              const loadedFilename = scenarioPackage?.metadata?.archive_filename || ''
              const isActive = loadedFilename && item.name === loadedFilename
              return (
              <div
                key={item.name}
                className={`package-repo-item${isActive ? ' is-active' : ''}${repoActionsOpenFor === item.name ? ' is-menu-open' : ''}`}
              >
                <div className="package-repo-meta">
                  <strong>{item.name}{isActive ? <span className="repo-active-badge">● active</span> : null}</strong>
                  <span className="small-text">{item.size} bytes · {item.modified_at || '-'}</span>
                  <span className="small-text">tags: {(item.tags || []).join(', ') || '-'}</span>
                  <span className="small-text">version notes: {item.version_notes || '-'}</span>
                </div>
                <div className="repo-actions-wrap" ref={repoActionsOpenFor === item.name ? repoActionsMenuRef : null}>
                  <button
                    className="pdb-btn-secondary repo-actions-trigger"
                    disabled={!selected || loadingAction || repoBusy}
                    onClick={() => setRepoActionsOpenFor((open) => (open === item.name ? '' : item.name))}
                    aria-haspopup="menu"
                    aria-expanded={repoActionsOpenFor === item.name}
                  >
                    Actions ▾
                  </button>
                  {repoActionsOpenFor === item.name && (
                    <div className="repo-actions-menu" role="menu" aria-label={`Repository actions for ${item.name}`}>
                      <button
                        className="repo-actions-menu-item"
                        disabled={!selected || loadingAction || repoBusy}
                        onClick={() => {
                          setRepoActionsOpenFor('')
                          importFromRepository(item.name)
                        }}
                      >
                        Load
                      </button>
                      <button
                        className="repo-actions-menu-item"
                        disabled={!selected || loadingAction || repoBusy || !enqueueScenarioRun}
                        onClick={() => {
                          setRepoActionsOpenFor('')
                          queueFromRepository(item)
                        }}
                      >
                        Queue
                      </button>
                      <button
                        className="repo-actions-menu-item"
                        disabled={!selected || loadingAction || repoBusy}
                        onClick={() => {
                          setRepoActionsOpenFor('')
                          editRepositoryPackage(item.name)
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="repo-actions-menu-item"
                        disabled={!selected || loadingAction || repoBusy}
                        onClick={() => {
                          setRepoActionsOpenFor('')
                          copyRepositoryPackage(item.name)
                        }}
                      >
                        Copy
                      </button>
                      <button
                        className="repo-actions-menu-item"
                        disabled={!selected || loadingAction || repoBusy}
                        onClick={() => {
                          setRepoActionsOpenFor('')
                          renameRepositoryPackage(item.name)
                        }}
                      >
                        Rename
                      </button>
                      <button
                        className="repo-actions-menu-item"
                        disabled={!selected || loadingAction || repoBusy}
                        onClick={() => {
                          setRepoActionsOpenFor('')
                          deleteRepositoryPackage(item.name)
                        }}
                      >
                        Delete
                      </button>
                      <button
                        className="repo-actions-menu-item"
                        disabled={!selected || loadingAction || repoBusy || !getScenarioRepositoryDownloadUrl}
                        onClick={() => {
                          setRepoActionsOpenFor('')
                          downloadRepositoryPackage(item.name)
                        }}
                      >
                        Download
                      </button>
                    </div>
                  )}
                </div>
              </div>
              )
            })
          )}
        </div>
      </div>

      {editorModalOpen && typeof document !== 'undefined' ? createPortal((
        <div className="pdb-modal-overlay scenario-editor-overlay" onClick={(event) => event.target === event.currentTarget && setEditorModalOpen(false)}>
          <div className="pdb-modal pdb-modal-editor scenario-package-editor-modal" onClick={(event) => event.stopPropagation()}>
            <div className="pdb-modal-header">
              <h3>{repoEditingFilename ? `Edit Repository Package: ${repoEditingFilename}` : 'Edit Scenario Package'}</h3>
              <button
                className="pdb-close-btn"
                onClick={() => {
                  setEditorModalOpen(false)
                  if (repoEditingFilename) {
                    setRepoEditingFilename('')
                    setRepoEditingPackage(null)
                  }
                }}
              >
                ✕
              </button>
            </div>

            <div className="pdb-modal-body">
              {editorSpecArtifactStatus ? (
                <div className="pdb-save-error">✖ {editorSpecArtifactStatus}</div>
              ) : !specSections.length ? (
                <div className="pdb-empty">No editable fields were found in the loaded spec.</div>
              ) : (
                specSections.map((section, sectionIndex) => (
                  <div key={section.id} className="pdb-section" style={sectionIndex === 0 ? { borderTop: 'none', paddingTop: 0, marginTop: 0 } : undefined}>
                    <div className="pdb-section-title">{section.title}</div>
                    <div className="pdb-section-fields">
                      {section.fields.map((path) => {
                        const type = specFieldTypes[path] || 'string'
                        const value = specFieldDrafts[path] ?? ''
                        return (
                          <div key={path} className="pdb-field">
                            <label className="pdb-label">{pathToLabel(path)}</label>
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
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))
              )}
              {specEditorError && <div className="pdb-save-error">✖ {specEditorError}</div>}

              {Array.isArray(resolvedEditorSpec?.file_upload_actions) && resolvedEditorSpec.file_upload_actions.length > 0 && (
                <div className="pdb-section">
                  <div className="pdb-section-title">Package Functions</div>
                  {resolvedEditorSpec.file_upload_actions.map((action) => (
                    <div key={action.id} className="pdb-field">
                      <label className="pdb-label">{action.label}{action.description ? ` — ${action.description}` : ''}</label>
                      <div className="upload-row">
                        <input
                          type="file"
                          accept={action.accept || '*'}
                          onClick={(e) => { e.currentTarget.value = '' }}
                          onChange={(e) => setFileUploadFiles((prev) => ({ ...prev, [action.id]: e.target.files?.[0] || null }))}
                          disabled={!selected || loadingAction || repoBusy}
                        />
                        <div className="selected-file-name">{fileUploadFiles[action.id] ? fileUploadFiles[action.id].name : 'No file selected'}</div>
                        <button
                          className="pdb-btn-primary"
                          disabled={!selected || loadingAction || repoBusy || !fileUploadFiles[action.id]}
                          onClick={() => handleSpecFileUploadAction(action)}
                        >
                          {action.label}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

            </div>

            <div className="pdb-modal-footer">
              <button
                className="pdb-btn-secondary"
                disabled={loadingAction}
                onClick={() => {
                  setEditorModalOpen(false)
                  if (repoEditingFilename) {
                    setRepoEditingFilename('')
                    setRepoEditingPackage(null)
                  }
                }}
              >
                Close
              </button>
              <button
                className="pdb-btn-secondary"
                disabled={!selected || loadingAction || repoBusy || !packageForEditor}
                onClick={saveCurrentToRepository}
              >
                {repoEditingFilename ? 'Save to repository file' : 'Save current to repository'}
              </button>
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

      {importResult && importResultVisible && typeof document !== 'undefined' ? createPortal((
        <div className="import-result scenario-import-result-float">
          <button
            className="import-result-dismiss"
            onClick={() => setImportResultVisible(false)}
            aria-label="Dismiss"
          >✕</button>
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
          <div className="import-result-progress" />
        </div>
      ), document.body) : null}

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
      <div className="event-log-wrap">
        <div ref={logRef} className="event-list" onScroll={handleEventLogScroll}>
          {!scenario?.event_log?.length ? (
            <p className="muted" style={{ margin: 0, padding: '4px 0' }}>No events yet.</p>
          ) : (
            scenario.event_log.map((event, index) => (
              <div key={index} className="event-item">{event}</div>
            ))
          )}
        </div>
        {scenario?.event_log?.length > 0 && !followLogBottom && (
          <button className="log-jump-button" onClick={() => scrollEventLogToBottom()} aria-label="Jump to latest log entry" title="Jump to latest">
            ↓
          </button>
        )}
      </div>
    </div>
  )
}

export function ScenarioTab(props) {
  const {
    scenario,
    scenarioPackage,
    scenarioQueue,
    scenarioQueueEnabled,
    queueAdvanceOnStop,
    runToggle,
    loadingAction,
    selected,
    runAction,
    setScenarioQueueEntries,
    enqueueScenarioRun,
    removeScenarioQueueEntry,
    clearScenarioQueue,
    runNextQueued,
    scenarioFile,
    setScenarioFile,
    uploadWorkbook,
    importResult,
    importErrorIssues,
    importWarningIssues,
    tunePackagePatch,
    listScenarioRepositoryPackages,
    saveScenarioRepositoryPackage,
    readScenarioRepositoryPackage,
    importScenarioRepositoryPackage,
    copyScenarioRepositoryPackage,
    listScenarioRepositoryTemplates,
    createScenarioRepositoryPackageFromTemplate,
    renameScenarioRepositoryPackage,
    deleteScenarioRepositoryPackage,
    updateScenarioRepositoryMetadata,
    uploadScenarioRepositoryPackage,
    getScenarioRepositoryDownloadUrl,
    uploadFileToEndpoint,
  } = props
  return (
    <div className="tab-content-grid">
      <ScenarioControlsBar scenario={scenario} runToggle={runToggle} loadingAction={loadingAction} selected={selected} runAction={runAction} />
      <ScenarioSummaryCard scenario={scenario} scenarioPackage={scenarioPackage} />
      <ScenarioQueueCard
        scenarioQueue={scenarioQueue}
        scenarioQueueEnabled={scenarioQueueEnabled}
        queueAdvanceOnStop={queueAdvanceOnStop}
        scenarioPackage={scenarioPackage}
        selected={selected}
        loadingAction={loadingAction}
        setScenarioQueueEntries={setScenarioQueueEntries}
        enqueueScenarioRun={enqueueScenarioRun}
        removeScenarioQueueEntry={removeScenarioQueueEntry}
        clearScenarioQueue={clearScenarioQueue}
      />
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
        tunePackagePatch={tunePackagePatch}
        listScenarioRepositoryPackages={listScenarioRepositoryPackages}
        saveScenarioRepositoryPackage={saveScenarioRepositoryPackage}
        readScenarioRepositoryPackage={readScenarioRepositoryPackage}
        importScenarioRepositoryPackage={importScenarioRepositoryPackage}
        copyScenarioRepositoryPackage={copyScenarioRepositoryPackage}
        enqueueScenarioRun={enqueueScenarioRun}
        listScenarioRepositoryTemplates={listScenarioRepositoryTemplates}
        createScenarioRepositoryPackageFromTemplate={createScenarioRepositoryPackageFromTemplate}
        renameScenarioRepositoryPackage={renameScenarioRepositoryPackage}
        deleteScenarioRepositoryPackage={deleteScenarioRepositoryPackage}
        updateScenarioRepositoryMetadata={updateScenarioRepositoryMetadata}
        uploadScenarioRepositoryPackage={uploadScenarioRepositoryPackage}
        getScenarioRepositoryDownloadUrl={getScenarioRepositoryDownloadUrl}
        uploadFileToEndpoint={uploadFileToEndpoint}
      />
      <ScenarioEventLogCard scenario={scenario} />
    </div>
  )
}
