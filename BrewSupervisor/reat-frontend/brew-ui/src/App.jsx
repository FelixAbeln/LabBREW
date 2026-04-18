import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import './features/parameterdb/parameterdb.css'
import './features/data/data.css'
import './features/archive/archive.css'
import './features/rules/rules.css'
import './features/control/control.css'
import { api, ApiResponseError } from './api/client'
import { createBrewApi } from './api/brewApi'
import { buildMeasurementSessionName } from './features/data/dataValueUtils'
import { loadDataTabPayload } from './features/data/loaders'
import { loadArchiveTabPayload } from './features/archive/loaders'
import { loadDashboardData, loadFermentersData } from './features/fermenters/loaders'
import { loadRuleEditorPayload, loadRulesTabPayload } from './features/rules/loaders'
import { makeEmptyRuleForm, normalizeRuleForm } from './features/rules/ruleUtils'
import { useRuleForm } from './features/rules/useRuleForm'
import { collectIssues, isImportValidationPayload } from './features/schedule/importValidation'
import { getRunToggle } from './features/schedule/scheduleUtils'
import { AppShell } from './features/app/AppShell'
import { FermenterTabContent } from './features/app/FermenterTabContent'
import { useAdaptivePolling } from './hooks/useAdaptivePolling'
import { ArchiveViewerPage } from './features/archive/ArchiveViewerPage'
import { getWorkspaceModule } from './features/app/workspaceModuleCatalog'
import {
  GRID_CONTRACT,
  WORKSPACE_RESIZE_PRESETS,
  autoPackWidgets,
  clampInt,
  normalizeGridInt,
  normalizeWidgetPlacement,
  normalizeWidgetSize,
  resolveAutoPlacedWidget,
} from './features/app/workspaceGridContract'

function createUiId(prefix) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`
}

function encodeTextToBase64(text) {
  const bytes = new TextEncoder().encode(String(text || ''))
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize)
    binary += String.fromCharCode(...chunk)
  }
  return window.btoa(binary)
}

function moveListItem(items, fromIndex, toIndex) {
  if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return items
  const next = [...items]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(toIndex, 0, moved)
  return next
}

function defaultWidgetLayout(type) {
  const moduleDef = getWorkspaceModule(type)
  if (moduleDef) {
    return normalizeWidgetSize({
      cols: Number(moduleDef.defaultCols || 6),
      rows: Number(moduleDef.defaultRows || 1),
    })
  }
  return normalizeWidgetSize({ cols: 6, rows: 1 })
}

function buildCustomWidget(type, position = null, layoutOverride = null) {
  const resolved = resolveAutoPlacedWidget([], type, {
    preferredPosition: position,
    layoutOverride,
    getDefaultLayout: defaultWidgetLayout,
  })
  return {
    id: createUiId('widget'),
    type,
    cols: resolved.cols,
    rows: resolved.rows,
    x: resolved.x,
    y: resolved.y,
  }
}

function buildCustomTab(label = 'Custom Workspace') {
  return {
    id: createUiId('custom-tab'),
    label: String(label || '').trim() || 'Workspace',
    widgets: [
      buildCustomWidget('system-actions', { x: 1, y: 1 }, { cols: 12, rows: 1 }),
      buildCustomWidget('data-recording', { x: 1, y: 3 }, { cols: 8, rows: 1 }),
      buildCustomWidget('data-snapshot', { x: 1, y: 5 }, { cols: 12, rows: 4 }),
    ],
  }
}

function App() {
  const brewApiRef = useRef(null)
  if (!brewApiRef.current) {
    brewApiRef.current = createBrewApi(api)
  }
  const brewApi = brewApiRef.current

  const [fermenters, setFermenters] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [scenario, setScenario] = useState(null)
  const [ownedTargetValues, setOwnedTargetValues] = useState([])
  const [error, setError] = useState('')
  const [loadingAction, setLoadingAction] = useState(false)
  const [scenarioFile, setScenarioFile] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [scenarioPackage, setScenarioPackage] = useState(null)
  const dashboardRequestRef = useRef(0)
  const sharedWorkspaceSignatureRef = useRef('')
  const [activeTab, setActiveTab] = useState('')
  const [globalView, setGlobalView] = useState(null)
  const [rules, setRules] = useState([])
  const [rulesModalOpen, setRulesModalOpen] = useState(false)
  const [rulesEditorLoading, setRulesEditorLoading] = useState(false)
  const [savingRule, setSavingRule] = useState(false)
  const [deletingRuleId, setDeletingRuleId] = useState('')
  const [operators, setOperators] = useState([])
  const [snapshotKeys, setSnapshotKeys] = useState([])
  const [rulesSnapshot, setRulesSnapshot] = useState(null)
  const [controlUiSpec, setControlUiSpec] = useState(null)
  const [controlUiLoading, setControlUiLoading] = useState(false)
  const [controlWriteTarget, setControlWriteTarget] = useState('')
  const [controlWriteError, setControlWriteError] = useState(null)
  const [pendingControlWrites, setPendingControlWrites] = useState({})
  const [controlDrafts, setControlDrafts] = useState({})
  const [dataActionLoading, setDataActionLoading] = useState(false)
  const [dataServiceStatus, setDataServiceStatus] = useState(null)
  const [repoUpdateStatus, setRepoUpdateStatus] = useState(null)
  const [persistenceStatus, setPersistenceStatus] = useState(null)
  const [healthyServices, setHealthyServices] = useState([])
  const [repoStatusLoading, setRepoStatusLoading] = useState(false)
  const [persistenceLoading, setPersistenceLoading] = useState(false)
  const [workspaceSaveLoading, setWorkspaceSaveLoading] = useState(false)
  const [datasourcePersistenceStatus, setDatasourcePersistenceStatus] = useState(null)
  const [rulesPersistenceStatus, setRulesPersistenceStatus] = useState(null)
  const [repoUpdateLoading, setRepoUpdateLoading] = useState(false)
  const [archivePayload, setArchivePayload] = useState(null)
  const [selectedArchiveName, setSelectedArchiveName] = useState('')
  const [archiveViewPayload, setArchiveViewPayload] = useState(null)
  const [archiveViewLoading, setArchiveViewLoading] = useState(false)
  const [archiveViewError, setArchiveViewError] = useState('')
  const archiveViewRequestRef = useRef(0)
  const [deletingArchiveName, setDeletingArchiveName] = useState('')
  const [dataHz, setDataHz] = useState('10')
  const [loadstepSeconds, setLoadstepSeconds] = useState('30')
  const [starredParams, setStarredParams] = useState(() => {
    try {
      const raw = window.localStorage.getItem('brew-ui.starred-params')
      return raw ? JSON.parse(raw) : []
    } catch {
      return []
    }
  })
  const [layoutEditMode, setLayoutEditMode] = useState(false)
  const [customTabs, setCustomTabs] = useState(() => {
    try {
      const raw = window.localStorage.getItem('brew-ui.custom-tabs')
      const parsed = raw ? JSON.parse(raw) : []
      if (Array.isArray(parsed) && parsed.length) return parsed
    } catch {
      // Ignore storage failures and fall back to a default workspace.
    }
    return [buildCustomTab('Workspace 1')]
  })
  const [controlCardLayouts, setControlCardLayouts] = useState(() => {
    try {
      const raw = window.localStorage.getItem('brew-ui.control-card-layouts')
      const parsed = raw ? JSON.parse(raw) : {}
      return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
      return {}
    }
  })
  const { ruleForm, setRuleForm, updateRuleForm, updateRuleParam, addRuleAction, removeRuleAction, updateRuleAction } = useRuleForm()

  const operatorMap = useMemo(() => new Map(operators.map((item) => [item.name, item])), [operators])

  const selectedOperator = useMemo(() => {
    if (!ruleForm?.operator) return null
    return operatorMap.get(ruleForm.operator) || null
  }, [operatorMap, ruleForm?.operator])

  const loadDataTab = useCallback(async (id = selectedId) => {
    if (!id) return null
    const selectedFermenter = fermenters.find((item) => item.id === id) || null
    const { snapshotPayload, statusPayload } = await loadDataTabPayload(brewApi, id, {
      includeStatus: Boolean(selectedFermenter?.services?.data_service?.healthy),
    })
    setRulesSnapshot(snapshotPayload && typeof snapshotPayload === 'object' ? snapshotPayload : null)
    setDataServiceStatus(statusPayload && typeof statusPayload === 'object' ? statusPayload : null)
    return { snapshotPayload, statusPayload }
  }, [brewApi, fermenters, selectedId])

  const getArchiveOutputDir = useCallback(() => {
    const archiveOutputDir = archivePayload?.output_dir
    if (typeof archiveOutputDir === 'string') {
      const trimmedArchiveOutputDir = archiveOutputDir.trim()
      if (trimmedArchiveOutputDir) return trimmedArchiveOutputDir
    }
    const outputDir = dataServiceStatus?.config?.output_dir
    if (typeof outputDir !== 'string') return undefined
    const trimmed = outputDir.trim()
    return trimmed || undefined
  }, [archivePayload?.output_dir, dataServiceStatus?.config?.output_dir])

  const loadArchiveTab = useCallback(async (id = selectedId) => {
    if (!id) return null
    const payload = await loadArchiveTabPayload(brewApi, id, {
      outputDir: getArchiveOutputDir(),
    })
    setArchivePayload(payload && typeof payload === 'object' ? payload : null)
    const archives = Array.isArray(payload?.archives) ? payload.archives : []
    if (selectedArchiveName && !archives.some((item) => item?.name === selectedArchiveName)) {
      setSelectedArchiveName('')
      setArchiveViewPayload(null)
      setArchiveViewError('')
    }
    return payload
  }, [brewApi, getArchiveOutputDir, selectedArchiveName, selectedId])

  async function deleteArchive(name) {
    if (!selected?.id || !name) return
    if (!window.confirm(`Delete archive ${name}? This cannot be undone.`)) return

    try {
      setDeletingArchiveName(name)
      setError('')
      await brewApi.deleteDataArchive(selected.id, name, {
        outputDir: getArchiveOutputDir(),
      })
      if (selectedArchiveName === name) {
        setSelectedArchiveName('')
        setArchiveViewPayload(null)
        setArchiveViewError('')
      }
      brewApi.invalidateFermenter(selected.id)
      await loadArchiveTab(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setDeletingArchiveName('')
    }
  }

  async function viewArchive(name) {
    if (!selected?.id || !name || archiveViewLoading) return
    const requestId = archiveViewRequestRef.current + 1
    archiveViewRequestRef.current = requestId
    try {
      setArchiveViewLoading(true)
      setArchiveViewError('')
      setArchiveViewPayload(null)
      setSelectedArchiveName(name)
      setGlobalView('archive-viewer')
      const payload = await brewApi.getDataArchiveView(selected.id, name, {
        outputDir: getArchiveOutputDir(),
        maxPoints: 1800,
        force: true,
      })
      if (archiveViewRequestRef.current !== requestId) return
      setArchiveViewPayload(payload && typeof payload === 'object' ? payload : null)
    } catch (err) {
      if (archiveViewRequestRef.current !== requestId) return
      setArchiveViewPayload(null)
      setArchiveViewError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      if (archiveViewRequestRef.current === requestId) {
        setArchiveViewLoading(false)
      }
    }
  }

  async function toggleMeasurementRecording() {
    if (!selected?.id || dataActionLoading) return

    try {
      setDataActionLoading(true)
      setError('')

      if (isRecording) {
        await api(`/fermenters/${selected.id}/data/measurement/stop`, {
          method: 'POST',
        })
      } else {
        if (!dataServiceHealthy) {
          setError('Data service is not available for this fermenter')
          return
        }

        if (!selectedStarredParams.length) {
          setError('Star at least one parameter in the Data tab before starting a recording')
          return
        }

        await api(`/fermenters/${selected.id}/data/measurement/setup`, {
          method: 'POST',
          body: JSON.stringify({
            parameters: selectedStarredParams,
            hz: Number(dataHz),
            output_format: 'parquet',
            session_name: buildMeasurementSessionName(selected),
            include_payloads: scenarioPackage
              ? [
                {
                  name: 'scenario.package.snapshot.json',
                  media_type: 'application/json',
                  content_b64: encodeTextToBase64(JSON.stringify(scenarioPackage, null, 2)),
                },
              ]
              : [],
          }),
        })

        await api(`/fermenters/${selected.id}/data/measurement/start`, {
          method: 'POST',
        })
      }

      brewApi.invalidateFermenter(selected.id)
      brewApi.invalidateFermenters()
      await Promise.all([loadFermenters(), loadDataTab(selected.id)])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setDataActionLoading(false)
    }
  }

  async function takeDataLoadstep() {
    if (!selected?.id || dataActionLoading) return
    if (!isLoadstepDurationValid) {
      setError('Loadstep duration must be a number greater than 0 seconds')
      return
    }

    try {
      setDataActionLoading(true)
      setError('')
      await api(`/fermenters/${selected.id}/data/loadstep/take`, {
        method: 'POST',
        body: JSON.stringify({
          duration_seconds: loadstepDurationSeconds,
        }),
      })
      brewApi.invalidateFermenter(selected.id)
      await loadDataTab(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setDataActionLoading(false)
    }
  }

  const loadRules = useCallback(async (id = selectedId) => {
    if (!id) return
    const { rulesPayload, snapshotPayload } = await loadRulesTabPayload(brewApi, id)
    setRules(rulesPayload)
    setRulesSnapshot(snapshotPayload)
  }, [brewApi, selectedId])

  const loadControlUiSpec = useCallback(async (id = selectedId, { quiet = false, includeEmptyCards = false } = {}) => {
    if (!id) return null
    if (!quiet) setControlUiLoading(true)
    try {
      const params = new URLSearchParams()
      if (includeEmptyCards) {
        params.set('include_empty_cards', 'true')
      }
      const query = params.toString()
      const payload = await api(`/fermenters/${id}/system/control-ui-spec${query ? `?${query}` : ''}`)
      setControlUiSpec(payload && typeof payload === 'object' ? payload : null)
      return payload
    } finally {
      if (!quiet) setControlUiLoading(false)
    }
  }, [selectedId])

  function updateControlDraft(target, value) {
    if (!target) return
    setControlDrafts((current) => ({
      ...current,
      [target]: value,
    }))
  }

  async function writeControlValue(control, explicitValue) {
    if (!selected?.id || !control || typeof control !== 'object') return
    const target = String(control.target || '').trim()
    if (!target) {
      setError('Control target is missing')
      return
    }

    const writeKind = control?.write?.kind || ''
    const widget = control?.widget || ''
    const expectsNumber = writeKind === 'number' || widget === 'number'
    const expectsBool = writeKind === 'bool' || widget === 'toggle'
    const expectsPulse = writeKind === 'pulse' || widget === 'button'

    // number_button: SG companion field + calibrate trigger in one row.
    // Write the number value to value_target first, then pulse the trigger.
    if (widget === 'number_button') {
      const valueTarget = String(control?.value_target || '').trim()
      if (valueTarget) {
        const sgRaw = Object.prototype.hasOwnProperty.call(controlDrafts, valueTarget)
          ? controlDrafts[valueTarget]
          : control?.value_target_current_value
        const sgNumeric = Number(sgRaw)
        if (Number.isFinite(sgNumeric)) {
          try {
            setControlWriteTarget(target)
            setControlWriteError(null)
            setError('')
            await api(`/fermenters/${selected.id}/control/manual-write`, {
              method: 'POST',
              body: JSON.stringify({ target: valueTarget, value: sgNumeric, reason: 'manual control ui' }),
            })
          } catch (err) {
            const message = err instanceof Error ? err.message : 'Unknown error'
            setError(message)
            setControlWriteError({ target, message })
            setControlWriteTarget('')
            return
          }
        }
      }
      // Fall through with explicit true to pulse the trigger
      explicitValue = true
    }
    let value = explicitValue
    if (value === undefined) {
      value = Object.prototype.hasOwnProperty.call(controlDrafts, target)
        ? controlDrafts[target]
        : control.current_value
    }

    if (expectsNumber) {
      const numeric = Number(value)
      if (!Number.isFinite(numeric)) {
        setError(`Control ${control.label || target} requires a numeric value`)
        return
      }
      value = numeric
    } else if (expectsBool) {
      if (typeof value === 'string') {
        const lowered = value.trim().toLowerCase()
        value = lowered === 'true' || lowered === '1' || lowered === 'on'
      } else {
        value = Boolean(value)
      }
    } else if (expectsPulse) {
      value = explicitValue === undefined ? true : Boolean(explicitValue)
    }

    try {
      setControlWriteTarget(target)
      setControlWriteError(null)
      setError('')
      const result = await api(`/fermenters/${selected.id}/control/manual-write`, {
        method: 'POST',
        body: JSON.stringify({
          target,
          value,
          reason: 'manual control ui',
        }),
      })
      if (result && !result.ok) {
        const reason = result.reason || (result.blocked ? `target owned by ${result.current_owner || 'another process'}` : 'write rejected')
        const message = `Could not write ${control.label || target}: ${reason}`
        setError(message)
        setControlWriteError({ target, message: reason })
        return
      }
      setControlWriteError(null)
      if (!expectsPulse) {
        const valueType = expectsBool ? 'bool' : (expectsNumber ? 'number' : 'raw')
        const now = Date.now()
        const observeAfter = now + 1000
        const expiresAt = now + 30000
        setPendingControlWrites((current) => ({
          ...current,
          [target]: {
            expected: value,
            valueType,
            observeAfter,
            expiresAt,
            label: String(control.label || target),
          },
        }))
      }
      brewApi.invalidateFermenter(selected.id)
      await Promise.all([
        loadControlUiSpec(selected.id, { quiet: true }),
        loadDetails(selected.id),
      ])
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError(message)
      setControlWriteError({ target, message })
    } finally {
      setControlWriteTarget('')
    }
  }

  async function loadRuleEditorData(id = selectedId) {
    if (!id) return
    setRulesEditorLoading(true)
    try {
      const { operatorPayload, snapshotPayload } = await loadRuleEditorPayload(brewApi, id)
      setOperators(operatorPayload)
      const values = snapshotPayload?.values && typeof snapshotPayload.values === 'object' ? snapshotPayload.values : {}
      setSnapshotKeys(Object.keys(values).sort((a, b) => a.localeCompare(b)))
    } finally {
      setRulesEditorLoading(false)
    }
  }

  async function openAddRule() {
    if (!selected?.id) return
    setGlobalView('rules-studio')
    setRulesModalOpen(true)
    setRuleForm(makeEmptyRuleForm())
    try {
      await loadRuleEditorData(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  async function openEditRule(rule) {
    if (!selected?.id) return
    setGlobalView('rules-studio')
    setRulesModalOpen(true)
    setRuleForm(normalizeRuleForm(rule))
    try {
      await loadRuleEditorData(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  function closeRuleModal() {
    if (savingRule) return
    setRulesModalOpen(false)
    setRuleForm(null)
  }

  async function saveRule() {
    if (!selected?.id || !ruleForm) return

    const operatorDefinition = operatorMap.get(ruleForm.operator)
    const condition = {
      source: ruleForm.source.trim(),
      operator: ruleForm.operator,
      params: {},
    }

    if (!condition.source) {
      setError('Rule source is required')
      return
    }

    if (ruleForm.for_s !== '' && ruleForm.for_s !== null) {
      condition.for_s = Number(ruleForm.for_s)
    }

    for (const [key, schema] of Object.entries(operatorDefinition?.param_schema || {})) {
      const rawValue = ruleForm.operatorParams?.[key]
      if ((rawValue === '' || rawValue === undefined) && schema?.required) {
        setError(`Operator field ${key} is required`)
        return
      }
      if (rawValue === '' || rawValue === undefined) continue
      condition.params[key] = schema?.type === 'number' ? Number(rawValue) : rawValue
    }

    const actions = []
    for (const [index, actionForm] of (ruleForm.actions || []).entries()) {
      const targets = String(actionForm.targetsText || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)

      if (!targets.length) {
        setError(`Action ${index + 1} needs at least one target`)
        return
      }

      const action = {
        type: actionForm.type,
        targets,
      }

      if (actionForm.type === 'set' || actionForm.type === 'ramp') {
        if (actionForm.value === '') {
          setError(`Action ${index + 1} value is required`)
          return
        }
        action.value = Number(actionForm.value)
      }

      if (actionForm.type === 'takeover' || actionForm.type === 'ramp') {
        action.owner = 'safety'
      }

      if (actionForm.type === 'takeover' && (actionForm.reason || '').trim()) {
        action.reason = actionForm.reason.trim()
      }

      if (actionForm.type === 'ramp') {
        if (actionForm.duration === '') {
          setError(`Action ${index + 1} duration is required`)
          return
        }
        action.duration = Number(actionForm.duration)
      }

      actions.push(action)
    }

    const payload = {
      id: ruleForm.id.trim(),
      enabled: ruleForm.enabled,
      condition,
      actions,
      release_when_clear: ruleForm.releaseWhenClear,
    }

    if (!payload.id) {
      setError('Rule id is required')
      return
    }

    try {
      setSavingRule(true)
      setError('')

      if (ruleForm.originalId) {
        await api(`/fermenters/${selected.id}/rules/${encodeURIComponent(ruleForm.originalId)}`, {
          method: 'DELETE',
        })
      }

      await api(`/fermenters/${selected.id}/rules/`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      brewApi.invalidateFermenter(selected.id)
      setRulesModalOpen(false)
      setRuleForm(null)
      await loadRules(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setSavingRule(false)
    }
  }

  async function releaseHeldRule(ruleId, targets) {
    if (!selected?.id || !Array.isArray(targets) || !targets.length) return
    try {
      setLoadingAction(true)
      setError('')
      await Promise.all(
        targets.map((target) =>
          api(`/fermenters/${selected.id}/control/reset`, {
            method: 'POST',
            body: JSON.stringify({ target }),
          }),
        ),
      )
      brewApi.invalidateFermenter(selected.id)
      await Promise.all([loadRules(selected.id), loadDetails(selected.id)])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoadingAction(false)
    }
  }

  async function releaseManualControl(targets = null, options = {}) {
    if (!selected?.id) return
    const { manageLoading = true, propagateError = false } = options || {}
    try {
      if (manageLoading) setLoadingAction(true)
      setError('')
      const payload = Array.isArray(targets) ? { targets } : {}
      await api(`/fermenters/${selected.id}/control/release-manual`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      brewApi.invalidateFermenter(selected.id)
      await Promise.all([loadRules(selected.id), loadDetails(selected.id)])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
      if (propagateError) throw err
    } finally {
      if (manageLoading) setLoadingAction(false)
    }
  }

  async function deleteRule(ruleId) {
    if (!selected?.id || !ruleId) return
    try {
      setDeletingRuleId(ruleId)
      setError('')
      await api(`/fermenters/${selected.id}/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })
      brewApi.invalidateFermenter(selected.id)
      await loadRules(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setDeletingRuleId('')
    }
  }

  const selected = useMemo(() => {
    if (!fermenters.length) return null
    return fermenters.find((f) => f.id === selectedId) || fermenters[0]
  }, [fermenters, selectedId])

  function addCustomTab() {
    const nextTab = buildCustomTab(`Workspace ${customTabs.length + 1}`)
    setCustomTabs((current) => [...current, nextTab])
    setActiveTab(nextTab.id)
    setLayoutEditMode(true)
  }

  function renameCustomTab(tabId, label) {
    setCustomTabs((current) => current.map((tab) => (
      tab.id === tabId
        ? { ...tab, label: String(label || '').trimStart() }
        : tab
    )))
  }

  function deleteCustomTab(tabId) {
    if (!tabId) return
    const doomed = customTabs.find((tab) => tab.id === tabId)
    const tabLabel = String(doomed?.label || 'this workspace').trim() || 'this workspace'
    if (!window.confirm(`Delete ${tabLabel}?`)) return

    const fallbackTab = customTabs.find((tab) => tab.id !== tabId) || null
    setCustomTabs((current) => {
      const remaining = current.filter((tab) => tab.id !== tabId)
      return remaining.length ? remaining : [buildCustomTab('Workspace 1')]
    })

    if (activeTab === tabId) {
      setActiveTab(fallbackTab?.id || '')
    }
  }

  function addWidgetToCustomTab(tabId, type, placement = null, layoutOverride = null) {
    if (!tabId || !type) return
    setCustomTabs((current) => current.map((tab) => {
      if (tab.id !== tabId) return tab
      const widgets = Array.isArray(tab.widgets) ? [...tab.widgets] : []
      const resolved = resolveAutoPlacedWidget(widgets, type, {
        preferredPosition: placement,
        layoutOverride,
        getDefaultLayout: defaultWidgetLayout,
      })
      const nextWidget = {
        id: createUiId('widget'),
        type,
        cols: resolved.cols,
        rows: resolved.rows,
        x: resolved.x,
        y: resolved.y,
      }
      widgets.push(nextWidget)
      return {
        ...tab,
        widgets,
      }
    }))
  }

  function removeWidgetFromCustomTab(tabId, widgetId) {
    if (!tabId || !widgetId) return
    setCustomTabs((current) => current.map((tab) => {
      if (tab.id !== tabId) return tab
      const remainingWidgets = (Array.isArray(tab.widgets) ? tab.widgets : []).filter((widget) => widget?.id !== widgetId)
      return {
        ...tab,
        widgets: GRID_CONTRACT.collision.autoPackOnDelete ? autoPackWidgets(remainingWidgets) : remainingWidgets,
      }
    }))
  }

  function moveWidgetInCustomTab(tabId, draggedId, target) {
    if (!tabId || !draggedId || !target) return
    setCustomTabs((current) => current.map((tab) => {
      if (tab.id !== tabId) return tab
      const widgets = Array.isArray(tab.widgets) ? [...tab.widgets] : []

      if (target && typeof target === 'object') {
        return {
          ...tab,
          widgets: widgets.map((widget) => {
            if (widget?.id !== draggedId) return widget
            const size = normalizeWidgetSize(widget)
            const currentPosition = normalizeWidgetPlacement(widget, 0, size)
            const nextPosition = normalizeWidgetPlacement(
              {
                x: normalizeGridInt(target.x, currentPosition.x),
                y: normalizeGridInt(target.y, currentPosition.y),
              },
              0,
              size,
            )
            return {
              ...widget,
              x: nextPosition.x,
              y: nextPosition.y,
            }
          }),
        }
      }

      const targetId = String(target)
      if (!targetId || draggedId === targetId) return tab
      const fromIndex = widgets.findIndex((widget) => widget?.id === draggedId)
      const toIndex = widgets.findIndex((widget) => widget?.id === targetId)
      if (fromIndex < 0 || toIndex < 0) return tab
      return {
        ...tab,
        widgets: moveListItem(widgets, fromIndex, toIndex),
      }
    }))
  }

  function resizeCustomWidget(tabId, widgetId, preset) {
    const presetLayouts = WORKSPACE_RESIZE_PRESETS
    const nextLayout = preset && typeof preset === 'object'
      ? normalizeWidgetSize(preset)
      : presetLayouts[String(preset || '')]
    if (!tabId || !widgetId || !nextLayout) return
    setCustomTabs((current) => current.map((tab) => {
      if (tab.id !== tabId) return tab
      return {
        ...tab,
        widgets: (Array.isArray(tab.widgets) ? tab.widgets : []).map((widget) => {
          if (widget?.id !== widgetId) return widget
          const normalizedLayout = normalizeWidgetSize(nextLayout, widget)
          const normalizedPosition = normalizeWidgetPlacement(widget, 0, normalizedLayout)
          return {
            ...widget,
            cols: normalizedLayout.cols,
            rows: normalizedLayout.rows,
            x: normalizedPosition.x,
            y: normalizedPosition.y,
          }
        }),
      }
    }))
  }

  function reorderControlCard(draggedId, targetId) {
    if (!draggedId || !targetId || draggedId === targetId) return
    const layoutKey = selected?.id || '__global__'
    const baseCardIds = (Array.isArray(controlUiSpec?.cards) ? controlUiSpec.cards : [])
      .filter((card) => Array.isArray(card?.controls) && card.controls.length > 0)
      .map((card) => String(card?.card_id || `${card?.kind}-${card?.title}`))
    setControlCardLayouts((current) => {
      const existing = Array.isArray(current[layoutKey])
        ? current[layoutKey].filter((id) => baseCardIds.includes(id))
        : []
      const merged = [...existing, ...baseCardIds.filter((id) => !existing.includes(id))]
      const fromIndex = merged.indexOf(String(draggedId))
      const toIndex = merged.indexOf(String(targetId))
      if (fromIndex < 0 || toIndex < 0) return current
      return {
        ...current,
        [layoutKey]: moveListItem(merged, fromIndex, toIndex),
      }
    })
  }

  const controlCardOrder = useMemo(() => {
    const layoutKey = selected?.id || '__global__'
    return Array.isArray(controlCardLayouts[layoutKey]) ? controlCardLayouts[layoutKey] : []
  }, [controlCardLayouts, selected?.id])

  const applySharedWorkspaceLayout = useCallback((fermenterId, payload) => {
    const layout = payload?.workspace_layout && typeof payload.workspace_layout === 'object'
      ? payload.workspace_layout
      : null
    if (!layout || !Array.isArray(layout.tabs) || !layout.tabs.length) return null

    const signature = JSON.stringify({
      fermenter_id: fermenterId,
      updated_at: layout.updated_at || '',
      active_tab: layout.active_tab || '',
      tabs: layout.tabs,
      control_card_order: Array.isArray(layout.control_card_order) ? layout.control_card_order : [],
    })

    if (sharedWorkspaceSignatureRef.current === signature) return layout
    sharedWorkspaceSignatureRef.current = signature

    setCustomTabs(layout.tabs)
    if (Array.isArray(layout.control_card_order)) {
      setControlCardLayouts((current) => ({
        ...current,
        [fermenterId]: layout.control_card_order,
      }))
    }

    if (layout.active_tab && layout.tabs.some((tab) => tab?.id === layout.active_tab)) {
      setActiveTab(layout.active_tab)
    } else if (!layout.tabs.some((tab) => tab?.id === activeTab)) {
      setActiveTab(String(layout.tabs[0]?.id || ''))
    }

    return layout
  }, [activeTab])

  const loadSharedWorkspaceLayouts = useCallback(async (id = selectedId, { force = false, quiet = false } = {}) => {
    if (!id) return null
    try {
      const payload = await brewApi.getWorkspaceLayouts(id, { force })
      return applySharedWorkspaceLayout(id, payload)
    } catch (err) {
      if (!quiet) {
        setError(err instanceof Error ? err.message : 'Failed to load shared workspaces')
      }
      return null
    }
  }, [applySharedWorkspaceLayout, brewApi, selectedId])

  const saveWorkspaceLayoutsToSupervisor = useCallback(async (id = selected?.id) => {
    if (!id) return null
    try {
      setWorkspaceSaveLoading(true)
      setError('')
      const payload = await brewApi.saveWorkspaceLayouts(id, {
        tabs: customTabs,
        active_tab: activeTab,
        control_card_order: controlCardOrder,
      })
      return applySharedWorkspaceLayout(id, payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save workspaces to supervisor')
      return null
    } finally {
      setWorkspaceSaveLoading(false)
    }
  }, [activeTab, applySharedWorkspaceLayout, brewApi, controlCardOrder, customTabs, selected?.id])

  const activeCustomTab = useMemo(
    () => customTabs.find((tab) => tab?.id === activeTab) || null,
    [activeTab, customTabs],
  )

  const activeCustomWidgetTypes = useMemo(
    () => new Set((Array.isArray(activeCustomTab?.widgets) ? activeCustomTab.widgets : []).map((widget) => String(widget?.type || ''))),
    [activeCustomTab],
  )

  const hasCustomModulePrefix = (prefix) => Array.from(activeCustomWidgetTypes).some((type) => type.startsWith(prefix))

  const showControlTab = hasCustomModulePrefix('control')
  const showDataTab = hasCustomModulePrefix('data')
  const showArchiveTab = hasCustomModulePrefix('archive')
  const showRulesTab = globalView === 'rules-studio' || hasCustomModulePrefix('rules')
  const showSystemTab = globalView === 'system-studio' || hasCustomModulePrefix('system')

  const runToggle = useMemo(() => getRunToggle(scenario?.state || null), [scenario?.state])
  const importErrorIssues = useMemo(() => collectIssues(importResult, 'error'), [importResult])
  const importWarningIssues = useMemo(() => collectIssues(importResult, 'warning'), [importResult])

  useEffect(() => {
    if (!selected?.id) {
      setHealthyServices([])
      return
    }
    const servicesObject = selected?.services
    if (!servicesObject || typeof servicesObject !== 'object') return
    const serviceEntries = Object.entries(servicesObject)
    if (!serviceEntries.length) return
    setHealthyServices(serviceEntries.filter(([, service]) => service?.healthy))
  }, [selected?.id, selected?.services])

  const selectedStarredParams = useMemo(() => {
    const values = rulesSnapshot?.values && typeof rulesSnapshot.values === 'object' ? rulesSnapshot.values : {}
    const availableKeys = new Set(Object.keys(values))
    return starredParams.filter((name) => availableKeys.has(name))
  }, [rulesSnapshot, starredParams])

  const dataServiceHealthy = Boolean(selected?.services?.data_service?.healthy)
  const isRecording = Boolean(dataServiceStatus?.recording)
  const activeLoadsteps = Array.isArray(dataServiceStatus?.active_loadsteps)
    ? dataServiceStatus.active_loadsteps.filter((item) => item && typeof item === 'object')
    : []
  const completedLoadsteps = Array.isArray(dataServiceStatus?.completed_loadsteps)
    ? dataServiceStatus.completed_loadsteps.filter((item) => item && typeof item === 'object')
    : []
  const currentLoadstep = activeLoadsteps[0] || null
  const latestCompletedLoadstep = completedLoadsteps[completedLoadsteps.length - 1] || null
  const isTakingLoadstep = activeLoadsteps.length > 0
  const loadstepRemainingSeconds = currentLoadstep?.remaining_seconds != null
    ? Math.max(0, Math.ceil(Number(currentLoadstep.remaining_seconds) || 0))
    : null
  const loadstepDurationSeconds = Number(loadstepSeconds)
  const isLoadstepDurationValid = Number.isFinite(loadstepDurationSeconds) && loadstepDurationSeconds > 0
  const latestLoadstepEntries = useMemo(() => {
    const average = latestCompletedLoadstep?.average
    if (!average || typeof average !== 'object') return []
    return Object.entries(average).sort(([a], [b]) => a.localeCompare(b))
  }, [latestCompletedLoadstep])

  const activeRuleIds = useMemo(
    () => new Set(Object.keys(rulesSnapshot?.active_rules || {})),
    [rulesSnapshot],
  )

  const heldRuleIds = useMemo(
    () => new Set(Object.keys(rulesSnapshot?.held_rules || {})),
    [rulesSnapshot],
  )

  useEffect(() => {
    setPendingControlWrites({})
  }, [selected?.id])

  useEffect(() => {
    const timerId = window.setInterval(() => {
      const now = Date.now()
      setPendingControlWrites((current) => {
        const entries = Object.entries(current)
        if (!entries.length) return current
        const next = {}
        let changed = false
        for (const [target, pending] of entries) {
          if (now < pending.expiresAt) {
            next[target] = pending
          } else {
            changed = true
          }
        }
        return changed ? next : current
      })
    }, 1000)

    return () => window.clearInterval(timerId)
  }, [])

  const loadFermenters = useCallback(async () => {
    const data = await loadFermentersData(brewApi)
    setFermenters(data)
    if (!selectedId && data.length) {
      setSelectedId(data[0].id)
    }
    return data
  }, [brewApi, selectedId])

  const loadDetails = useCallback(async (id, options = {}) => {
    const requestId = dashboardRequestRef.current + 1
    dashboardRequestRef.current = requestId

    const payload = await loadDashboardData(brewApi, id, options)
    if (dashboardRequestRef.current !== requestId) return

    if (payload?.fermenter) {
      setFermenters((current) =>
        current.map((item) => (item.id === payload.fermenter.id ? payload.fermenter : item)),
      )
    }

    setScenario(payload?.schedule || null)
    setScenarioPackage(payload?.scenario_package || payload?.schedule_definition || null)
    setOwnedTargetValues(Array.isArray(payload?.owned_target_values) ? payload.owned_target_values : [])
  }, [brewApi])

  const refreshRepoUpdateStatus = useCallback(async (id = selectedId, { force = false, quiet = false } = {}) => {
    if (!id) return null
    if (!quiet) setRepoStatusLoading(true)
    try {
      const payload = await brewApi.getAgentRepoStatus(id, { force })
      const status = payload?.status && typeof payload.status === 'object' ? payload.status : null
      if (status) setRepoUpdateStatus(status)
      return status
    } catch (err) {
      if (!quiet) {
        setError(err instanceof Error ? err.message : 'Failed to refresh update status')
      } else {
        console.warn('Repo update status polling failed', err)
      }
      return null
    } finally {
      if (!quiet) setRepoStatusLoading(false)
    }
  }, [brewApi, selectedId])

  const refreshPersistenceStatus = useCallback(async (id = selectedId, { force = false, quiet = false } = {}) => {
    if (!id) return null
    if (!quiet) setPersistenceLoading(true)
    try {
      const payload = await brewApi.getAgentPersistence(id, { force })
      const status = payload?.persistence && typeof payload.persistence === 'object' ? payload.persistence : null
      const datasourceStatus = payload?.datasource_persistence && typeof payload.datasource_persistence === 'object'
        ? payload.datasource_persistence
        : null
      const rulesStatus = payload?.rules_persistence && typeof payload.rules_persistence === 'object'
        ? payload.rules_persistence
        : null
      if (status) setPersistenceStatus(status)
      if (datasourceStatus) setDatasourcePersistenceStatus(datasourceStatus)
      if (rulesStatus) setRulesPersistenceStatus(rulesStatus)
      return { persistence: status, datasource_persistence: datasourceStatus, rules_persistence: rulesStatus }
    } catch (err) {
      if (!quiet) {
        setError(err instanceof Error ? err.message : 'Failed to refresh persistence status')
      } else {
        console.warn('Persistence status polling failed', err)
      }
      return null
    } finally {
      if (!quiet) setPersistenceLoading(false)
    }
  }, [brewApi, selectedId])

  async function applyRepoUpdate() {
    if (!selected?.id || repoUpdateLoading) return
    try {
      setRepoUpdateLoading(true)
      setError('')
      const payload = await brewApi.applyAgentRepoUpdate(selected.id)
      const nextStatus = payload?.after && typeof payload.after === 'object' ? payload.after : null
      if (nextStatus) setRepoUpdateStatus(nextStatus)
      brewApi.invalidateFermenter(selected.id)
      brewApi.invalidateFermenters()
      await Promise.all([
        loadFermenters(),
        loadDetails(selected.id),
        refreshRepoUpdateStatus(selected.id, { force: true, quiet: true }),
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setRepoUpdateLoading(false)
    }
  }

  const refreshAll = useCallback(async () => {
    try {
      setError('')
      brewApi.invalidateFermenters()
      const data = await loadFermenters()

      if (!data.length) {
        setSelectedId(null)
        setScenario(null)
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
  }, [brewApi, loadDetails, loadFermenters, selectedId])

  async function runAction(path) {
    if (!selected) return
    try {
      setLoadingAction(true)
      setError('')

      if (path === '/scenario/run/start' || path === '/scenario/run/resume') {
        try {
          const controlPayload = await loadControlUiSpec(selected.id, {
            quiet: true,
            includeEmptyCards: true,
          })
          const cards = Array.isArray(controlPayload?.cards) ? controlPayload.cards : []
          const operatorOwned = []
          const seenTargets = new Set()

          cards.forEach((card) => {
            const controls = Array.isArray(card?.controls) ? card.controls : []
            controls.forEach((control) => {
              const target = String(control?.target || '').trim()
              const currentOwner = String(control?.current_owner || '').trim()
              if (!target || currentOwner !== 'operator' || seenTargets.has(target)) return
              seenTargets.add(target)
              operatorOwned.push({
                target,
                label: String(control?.label || target).trim() || target,
              })
            })
          })

          if (operatorOwned.length) {
            const preview = operatorOwned
              .slice(0, 6)
              .map((item) => `- ${item.label} (${item.target})`)
              .join('\n')
            const remainder = operatorOwned.length > 6
              ? `\n- and ${operatorOwned.length - 6} more`
              : ''
            const shouldRelease = window.confirm(
              `Some controls are currently owned by operator:\n\n${preview}${remainder}\n\nPress OK to release manual ownership and continue.\nPress Cancel to continue without takeover. If ownership is still blocked, the scenario will pause.`,
            )
            if (shouldRelease) {
              await releaseManualControl(
                operatorOwned.map((item) => item.target),
                { manageLoading: false, propagateError: true },
              )
            }
          }
        } catch (preflightErr) {
          console.warn('Ownership preflight failed; continuing with scenario action.', preflightErr)
        }
      }

      await api(`/fermenters/${selected.id}${path}`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
      brewApi.invalidateFermenter(selected.id)
      brewApi.invalidateFermenters()
      await loadFermenters()
      await loadDetails(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoadingAction(false)
    }
  }

  async function uploadWorkbook(path) {
    if (!selected || !scenarioFile) return

    try {
      setLoadingAction(true)
      setError('')
      setImportResult(null)

      const formData = new FormData()
      formData.append('file', scenarioFile)

      const result = await api(`/fermenters/${selected.id}${path}`, {
        method: 'PUT',
        body: formData,
      })

      brewApi.invalidateFermenter(selected.id)
      brewApi.invalidateFermenters()
      setImportResult(result)
      await loadFermenters()
      await loadDetails(selected.id)
    } catch (err) {
      if (err instanceof ApiResponseError && isImportValidationPayload(err.payload)) {
        setImportResult(err.payload)
      } else {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    } finally {
      setLoadingAction(false)
    }
  }

  async function tunePackagePatch(packagePatch) {
    if (!selected?.id || !packagePatch || typeof packagePatch !== 'object') return
    try {
      setLoadingAction(true)
      setError('')
      const response = await api(`/fermenters/${selected.id}/scenario/package/tune`, {
        method: 'POST',
        body: JSON.stringify({
          package_patch: packagePatch,
        }),
      })
      if (!response?.ok) {
        const detail = response?.error || 'Failed to apply package patch'
        throw new Error(String(detail))
      }
      brewApi.invalidateFermenter(selected.id)
      await loadDetails(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoadingAction(false)
    }
  }

  async function listScenarioRepositoryPackages() {
    if (!selected?.id) return { ok: false, packages: [] }
    return api(`/fermenters/${selected.id}/scenario/repository`)
  }

  async function saveScenarioRepositoryPackage({ filename, packagePayload, tags, versionNotes, notes }) {
    if (!selected?.id) return { ok: false }
    const result = await api(`/fermenters/${selected.id}/scenario/repository/save`, {
      method: 'POST',
      body: JSON.stringify({
        filename,
        package: packagePayload || scenarioPackage || undefined,
        tags: Array.isArray(tags) ? tags : undefined,
        version_notes: typeof versionNotes === 'string' ? versionNotes : undefined,
        notes: typeof notes === 'string' ? notes : undefined,
      }),
    })
    brewApi.invalidateFermenter(selected.id)
    await loadDetails(selected.id)
    return result
  }

  async function importScenarioRepositoryPackage(filename) {
    if (!selected?.id) return { ok: false }
    const result = await api(`/fermenters/${selected.id}/scenario/repository/import`, {
      method: 'POST',
      body: JSON.stringify({ filename }),
    })
    setImportResult(result)
    if (result && typeof result === 'object' && result.ok === false) {
      const firstError = Array.isArray(result.errors) ? result.errors[0] : null
      const errorMessage =
        (firstError && typeof firstError === 'object' && String(firstError.message || '').trim())
        || String(result.error || '').trim()
        || 'Failed to load package into scenario service'
      throw new Error(errorMessage)
    }
    if (result && typeof result === 'object' && result.scenario_package && typeof result.scenario_package === 'object') {
      setScenarioPackage(result.scenario_package)
      const nextProgram = result.scenario_package?.program
      if (nextProgram && typeof nextProgram === 'object') {
        setScenario(nextProgram)
      }
    }
    brewApi.invalidateFermenter(selected.id)
    brewApi.invalidateFermenters()
    await loadFermenters()
    await loadDetails(selected.id, { force: true })
    return result
  }

  async function readScenarioRepositoryPackage(filename) {
    if (!selected?.id) return { ok: false }
    return api(`/fermenters/${selected.id}/scenario/repository/read/${encodeURIComponent(filename)}`)
  }

  async function copyScenarioRepositoryPackage(sourceFilename, targetFilename) {
    if (!selected?.id) return { ok: false }
    return api(`/fermenters/${selected.id}/scenario/repository/copy`, {
      method: 'POST',
      body: JSON.stringify({
        source_filename: sourceFilename,
        target_filename: targetFilename,
      }),
    })
  }

  async function renameScenarioRepositoryPackage(sourceFilename, targetFilename) {
    if (!selected?.id) return { ok: false }
    return api(`/fermenters/${selected.id}/scenario/repository/rename`, {
      method: 'POST',
      body: JSON.stringify({
        source_filename: sourceFilename,
        target_filename: targetFilename,
      }),
    })
  }

  async function deleteScenarioRepositoryPackage(filename) {
    if (!selected?.id) return { ok: false }
    return api(`/fermenters/${selected.id}/scenario/repository/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    })
  }

  async function updateScenarioRepositoryMetadata({ filename, tags, versionNotes, notes }) {
    if (!selected?.id) return { ok: false }
    return api(`/fermenters/${selected.id}/scenario/repository/metadata`, {
      method: 'POST',
      body: JSON.stringify({
        filename,
        tags: Array.isArray(tags) ? tags : [],
        version_notes: versionNotes || '',
        notes: notes || '',
      }),
    })
  }

  async function uploadScenarioRepositoryPackage({ file, filename }) {
    if (!selected?.id || !file) return { ok: false }
    return uploadFileToEndpoint('repository/upload-package', file, { filename })
  }

  function getScenarioRepositoryDownloadUrl(filename) {
    if (!selected?.id || !filename) return ''
    return `${window.location.origin}/fermenters/${selected.id}/scenario/repository/download/${encodeURIComponent(filename)}`
  }

  async function convertExcelToRepositoryPackage({ file, filename }) {
    if (!selected?.id || !file) return { ok: false }
    return uploadFileToEndpoint('repository/convert-excel', file, { filename })
  }

  /**
   * Generic file upload action declared by a package's editor_spec.file_upload_actions.
   * endpointSuffix is relative to /fermenters/{id}/scenario/, e.g. "repository/convert-excel".
   */
  async function uploadFileToEndpoint(endpointSuffix, file, extraParams = {}) {
    if (!selected?.id || !file) return { ok: false }
    const formData = new FormData()
    formData.append('file', file)
    const params = new URLSearchParams()
    const normalizedParams = { ...extraParams }
    if (String(endpointSuffix || '').trim() === 'repository/convert-excel' && normalizedParams.import_now == null) {
      normalizedParams.import_now = 'true'
    }
    for (const [key, value] of Object.entries(normalizedParams)) {
      if (value != null && value !== '') params.set(key, String(value))
    }
    const query = params.toString()
    const result = await api(`/fermenters/${selected.id}/scenario/${endpointSuffix}${query ? `?${query}` : ''}`, {
      method: 'POST',
      body: formData,
    })

    const importNowParam = String(normalizedParams?.import_now || '').toLowerCase()
    const shouldRefreshImportedState =
      importNowParam === '1' || importNowParam === 'true' || Boolean(result?.imported)

    if (result && typeof result === 'object' && result.imported && result.imported.ok === false) {
      const importedForwarded = result.imported.forwarded
      const importedMessage =
        (importedForwarded && typeof importedForwarded === 'object' && String(importedForwarded.error || '').trim())
        || 'Scenario service rejected imported package'
      throw new Error(importedMessage)
    }

    if (shouldRefreshImportedState) {
      setImportResult(result)
      if (result && typeof result === 'object' && result.scenario_package && typeof result.scenario_package === 'object') {
        setScenarioPackage(result.scenario_package)
        const nextProgram = result.scenario_package?.program
        if (nextProgram && typeof nextProgram === 'object') {
          setScenario(nextProgram)
        }
      }
      brewApi.invalidateFermenter(selected.id)
      brewApi.invalidateFermenters()
      await loadFermenters()
      await loadDetails(selected.id, { force: true })
    }

    return result
  }

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  useEffect(() => {
    if (!selected?.id) {
      sharedWorkspaceSignatureRef.current = ''
      setRepoUpdateStatus(null)
      setPersistenceStatus(null)
      setDatasourcePersistenceStatus(null)
      setRulesPersistenceStatus(null)
    }
  }, [selected?.id])

  useEffect(() => {
    const summaryStatus = selected?.summary?.repo_update
    if (summaryStatus && typeof summaryStatus === 'object') {
      setRepoUpdateStatus(summaryStatus)
    }
  }, [selected?.summary?.repo_update])

  useEffect(() => {
    const summaryStatus = selected?.summary?.persistence
    if (summaryStatus && typeof summaryStatus === 'object') {
      setPersistenceStatus(summaryStatus)
    }
  }, [selected?.summary?.persistence])

  useEffect(() => {
    const summaryStatus = selected?.summary?.datasource_persistence
    if (summaryStatus && typeof summaryStatus === 'object') {
      setDatasourcePersistenceStatus(summaryStatus)
    }
  }, [selected?.summary?.datasource_persistence])

  useEffect(() => {
    const summaryStatus = selected?.summary?.rules_persistence
    if (summaryStatus && typeof summaryStatus === 'object') {
      setRulesPersistenceStatus(summaryStatus)
    }
  }, [selected?.summary?.rules_persistence])

  useEffect(() => {
    if (!selected?.id || layoutEditMode) return
    loadSharedWorkspaceLayouts(selected.id, { force: true, quiet: true }).catch(() => {})
  }, [layoutEditMode, loadSharedWorkspaceLayouts, selected?.id])

  useAdaptivePolling({
    enabled: Boolean(selected?.id),
    task: async () => {
      try {
        await loadDetails(selected.id)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    },
    getDelay: () => {
      if (hasCustomModulePrefix('scenario') || hasCustomModulePrefix('schedule')) return 1000
      if (hasCustomModulePrefix('control')) return 2000
      if (hasCustomModulePrefix('rules') || hasCustomModulePrefix('data')) return 2500
      return 2000
    },
  })

  useAdaptivePolling({
    enabled: showControlTab && Boolean(selected?.id),
    task: async () => {
      try {
        await loadControlUiSpec(selected.id, { quiet: true })
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    },
    getDelay: () => 3000,
  })

  useAdaptivePolling({
    enabled: showRulesTab && Boolean(selected?.id),
    task: async () => {
      try {
        await loadRules(selected.id)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    },
    getDelay: () => 3000,
  })

  useAdaptivePolling({
    enabled: showDataTab && Boolean(selected?.id),
    task: async () => {
      try {
        await loadDataTab(selected.id)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    },
    getDelay: () => 3000,
  })

  useAdaptivePolling({
    enabled: showArchiveTab && Boolean(selected?.id),
    task: async () => {
      try {
        await loadArchiveTab(selected.id)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    },
    getDelay: () => 5000,
  })

  useAdaptivePolling({
    enabled: true,
    task: async () => {
      await loadFermenters().catch(() => {})
    },
    getDelay: () => 15000,
  })

  useAdaptivePolling({
    enabled: Boolean(selected?.id) && !layoutEditMode,
    task: async () => {
      try {
        await loadSharedWorkspaceLayouts(selected.id, { force: true, quiet: true })
      } catch {
        // Shared layout polling is best-effort and should stay silent.
      }
    },
    getDelay: () => 4000,
  })

  useAdaptivePolling({
    enabled: showSystemTab && Boolean(selected?.id),
    task: async () => {
      try {
        await refreshRepoUpdateStatus(selected.id, { force: false, quiet: true })
      } catch {
        // Suppress errors in quiet polling mode to avoid unhandled promise rejections
      }
    },
    getDelay: () => 20000,
  })

  useAdaptivePolling({
    enabled: showSystemTab && Boolean(selected?.id),
    task: async () => {
      try {
        await refreshPersistenceStatus(selected.id, { force: false, quiet: true })
      } catch {
        // Suppress errors in quiet polling mode to avoid unhandled promise rejections
      }
    },
    getDelay: () => 10000,
  })


  useEffect(() => {
    try {
      window.localStorage.setItem('brew-ui.starred-params', JSON.stringify(starredParams))
    } catch {
      // Ignore storage failures and keep UI responsive.
    }
  }, [starredParams])

  useEffect(() => {
    try {
      window.localStorage.setItem('brew-ui.custom-tabs', JSON.stringify(customTabs))
    } catch {
      // Ignore storage failures and keep UI responsive.
    }
  }, [customTabs])

  useEffect(() => {
    try {
      window.localStorage.setItem('brew-ui.control-card-layouts', JSON.stringify(controlCardLayouts))
    } catch {
      // Ignore storage failures and keep UI responsive.
    }
  }, [controlCardLayouts])

  useEffect(() => {
    if (!Array.isArray(customTabs) || !customTabs.length) return
    if (customTabs.some((tab) => tab?.id === activeTab)) return
    setActiveTab(customTabs[0]?.id || '')
  }, [activeTab, customTabs])

  useEffect(() => {
    if (!showArchiveTab || !selected?.id) return
    loadArchiveTab(selected.id).catch((err) => {
      setError(err instanceof Error ? err.message : 'Unknown error')
    })
  }, [showArchiveTab, loadArchiveTab, selected?.id])

  useEffect(() => {
    archiveViewRequestRef.current += 1
    setSelectedArchiveName('')
    setArchiveViewPayload(null)
    setArchiveViewError('')
    setArchiveViewLoading(false)
  }, [selected?.id])

  useEffect(() => {
    if (!showControlTab || !selected?.id) return
    loadControlUiSpec(selected.id).catch((err) => {
      setError(err instanceof Error ? err.message : 'Unknown error')
    })
  }, [showControlTab, loadControlUiSpec, selected?.id])

  function toggleStarredParam(name) {
    setStarredParams((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    )
  }

  const scenarioTabProps = {
    scenario,
    scenarioPackage,
    runToggle,
    loadingAction,
    selected,
    runAction,
    ownedTargetValues,
    scenarioFile,
    setScenarioFile,
    uploadWorkbook,
    tunePackagePatch,
    listScenarioRepositoryPackages,
    saveScenarioRepositoryPackage,
    readScenarioRepositoryPackage,
    importScenarioRepositoryPackage,
    copyScenarioRepositoryPackage,
    renameScenarioRepositoryPackage,
    deleteScenarioRepositoryPackage,
    updateScenarioRepositoryMetadata,
    uploadScenarioRepositoryPackage,
    getScenarioRepositoryDownloadUrl,
    uploadFileToEndpoint,
    importResult,
    importErrorIssues,
    importWarningIssues,
    onOpenScenarioBuilder: () => setGlobalView('scenario-builder'),
  }

  const dataTabProps = {
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
  }

  const controlTabProps = {
    selected,
    controlUiSpec,
    controlUiLoading,
    controlWriteTarget,
    controlWriteError,
    pendingControlWrites,
    controlDrafts,
    layoutEditMode,
    controlCardOrder,
    onDraftChange: updateControlDraft,
    onWrite: writeControlValue,
    onReorderCard: reorderControlCard,
    onReleaseManualControl: () => releaseManualControl(),
  }

  const archiveTabProps = {
    selected,
    archivePayload,
    deletingArchiveName,
    onDelete: deleteArchive,
    onView: viewArchive,
  }

  const rulesTabProps = {
    selected,
    rules,
    activeRuleIds,
    heldRuleIds,
    rulesSnapshot,
    loadingAction,
    deletingRuleId,
    openAddRule,
    openEditRule,
    releaseHeldRule,
    deleteRule,
  }

  const systemTabProps = {
    selected,
    healthyServices,
    onOpenParameterDB: () => setGlobalView('parameterdb'),
    onOpenStorageManager: () => setGlobalView('storage-manager'),
    onOpenRulesStudio: () => setGlobalView('rules-studio'),
    onOpenScenarioBuilder: () => setGlobalView('scenario-builder'),
    persistenceStatus,
    persistenceLoading,
    datasourcePersistenceStatus,
    rulesPersistenceStatus,
    repoUpdateStatus,
    repoStatusLoading,
    repoUpdateLoading,
    onRefreshPersistenceStatus: () => refreshPersistenceStatus(selected?.id, { force: true }),
    onRefreshRepoStatus: () => refreshRepoUpdateStatus(selected?.id, { force: true }),
    onApplyRepoUpdate: applyRepoUpdate,
  }

  const ruleEditorProps = {
    rulesModalOpen,
    ruleForm,
    savingRule,
    closeRuleModal,
    rulesEditorLoading,
    updateRuleForm,
    operators,
    selectedOperator,
    updateRuleParam,
    addRuleAction,
    removeRuleAction,
    updateRuleAction,
    snapshotKeys,
    saveRule,
  }

  const showDebugLink = useMemo(() => {
    try {
      return new URLSearchParams(window.location.search).has('debug')
    } catch {
      return false
    }
  }, [])

  return (
    <AppShell
      fermenters={fermenters}
      selected={selected}
      onSelect={setSelectedId}
      error={error}
      activeTab={activeTab}
      onTabChange={setActiveTab}
      customTabs={customTabs}
      layoutEditMode={layoutEditMode}
      onToggleLayoutEdit={() => setLayoutEditMode((current) => !current)}
      onOpenSystemStudio={() => setGlobalView('system-studio')}
      onOpenSystemDebug={() => setGlobalView('system-debug')}
      showDebugLink={showDebugLink}
    >
      <FermenterTabContent
        selected={selected}
        activeTab={activeTab}
        onSaveSharedWorkspaceLayouts={() => saveWorkspaceLayoutsToSupervisor(selected?.id)}
        workspaceSaveLoading={workspaceSaveLoading}
        scenarioProps={scenarioTabProps}
        dataProps={dataTabProps}
        controlProps={controlTabProps}
        archiveProps={archiveTabProps}
        rulesProps={rulesTabProps}
        systemProps={systemTabProps}
        customTabs={customTabs}
        layoutEditMode={layoutEditMode}
        onRenameCustomTab={renameCustomTab}
        onDeleteCustomTab={deleteCustomTab}
        onAddCustomWidget={addWidgetToCustomTab}
        onRemoveCustomWidget={removeWidgetFromCustomTab}
        onMoveCustomWidget={moveWidgetInCustomTab}
        onResizeCustomWidget={resizeCustomWidget}
        onCreateCustomTab={addCustomTab}
        globalView={globalView}
        setGlobalView={setGlobalView}
        onOpenSystemDebug={() => setGlobalView('system-debug')}
        showDebugLink={showDebugLink}
        ruleEditorProps={ruleEditorProps}
        archiveViewPayload={archiveViewPayload}
        selectedArchiveName={selectedArchiveName}
        archiveViewLoading={archiveViewLoading}
        archiveViewError={archiveViewError}
      />
    </AppShell>
  )
}

export default App
