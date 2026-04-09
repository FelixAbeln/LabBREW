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

function App() {
  const brewApiRef = useRef(null)
  if (!brewApiRef.current) {
    brewApiRef.current = createBrewApi(api)
  }
  const brewApi = brewApiRef.current

  const [fermenters, setFermenters] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [schedule, setSchedule] = useState(null)
  const [ownedTargetValues, setOwnedTargetValues] = useState([])
  const [error, setError] = useState('')
  const [loadingAction, setLoadingAction] = useState(false)
  const [scheduleFile, setScheduleFile] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [scheduleDefinition, setScheduleDefinition] = useState(null)
  const dashboardRequestRef = useRef(0)
  const [activeTab, setActiveTab] = useState('control')
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
  const [controlDrafts, setControlDrafts] = useState({})
  const [dataActionLoading, setDataActionLoading] = useState(false)
  const [dataServiceStatus, setDataServiceStatus] = useState(null)
  const [repoUpdateStatus, setRepoUpdateStatus] = useState(null)
  const [repoStatusLoading, setRepoStatusLoading] = useState(false)
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
            setError('')
            await api(`/fermenters/${selected.id}/control/manual-write`, {
              method: 'POST',
              body: JSON.stringify({ target: valueTarget, value: sgNumeric, reason: 'manual control ui' }),
            })
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error')
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
        setError(`Could not write ${control.label || target}: ${reason}`)
        return
      }
      brewApi.invalidateFermenter(selected.id)
      await Promise.all([
        loadControlUiSpec(selected.id, { quiet: true }),
        loadDetails(selected.id),
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
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

  async function releaseManualControl(targets = null) {
    if (!selected?.id) return
    try {
      setLoadingAction(true)
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
    } finally {
      setLoadingAction(false)
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

  const runToggle = useMemo(() => getRunToggle(schedule?.state || null), [schedule?.state])
  const importErrorIssues = useMemo(() => collectIssues(importResult, 'error'), [importResult])
  const importWarningIssues = useMemo(() => collectIssues(importResult, 'warning'), [importResult])

  const healthyServices = useMemo(() => {
    const services = Object.entries(selected?.services || {})
    return services.filter(([, service]) => service?.healthy)
  }, [selected])

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

  const loadFermenters = useCallback(async () => {
    const data = await loadFermentersData(brewApi)
    setFermenters(data)
    if (!selectedId && data.length) {
      setSelectedId(data[0].id)
    }
    return data
  }, [brewApi, selectedId])

  const loadDetails = useCallback(async (id) => {
    const requestId = dashboardRequestRef.current + 1
    dashboardRequestRef.current = requestId

    const payload = await loadDashboardData(brewApi, id)
    if (dashboardRequestRef.current !== requestId) return

    if (payload?.fermenter) {
      setFermenters((current) =>
        current.map((item) => (item.id === payload.fermenter.id ? payload.fermenter : item)),
      )
    }

    setSchedule(payload?.schedule || null)
    setScheduleDefinition(payload?.schedule_definition || null)
    setOwnedTargetValues(Array.isArray(payload?.owned_target_values) ? payload.owned_target_values : [])
  }, [brewApi])

  const refreshRepoUpdateStatus = useCallback(async (id = selectedId, { force = false, quiet = false } = {}) => {
    if (!id) return null
    if (!quiet) setRepoStatusLoading(true)
    try {
      const payload = await brewApi.getAgentRepoStatus(id, { force })
      const status = payload?.status && typeof payload.status === 'object' ? payload.status : null
      setRepoUpdateStatus(status)
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
  }, [brewApi, loadDetails, loadFermenters, selectedId])

  async function runAction(path) {
    if (!selected) return
    try {
      setLoadingAction(true)
      setError('')
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

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  useEffect(() => {
    const summaryStatus = selected?.summary?.repo_update
    setRepoUpdateStatus(summaryStatus && typeof summaryStatus === 'object' ? summaryStatus : null)
  }, [selected?.id, selected?.summary])

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
      if (activeTab === 'schedule') return 1000
      if (activeTab === 'control') return 2000
      if (activeTab === 'rules' || activeTab === 'data') return 2500
      return 2000
    },
  })

  useAdaptivePolling({
    enabled: activeTab === 'control' && Boolean(selected?.id),
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
    enabled: activeTab === 'rules' && Boolean(selected?.id),
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
    enabled: activeTab === 'data' && Boolean(selected?.id),
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
    enabled: activeTab === 'archive' && Boolean(selected?.id),
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
    enabled: activeTab === 'system' && Boolean(selected?.id),
    task: async () => {
      try {
        await refreshRepoUpdateStatus(selected.id, { force: false, quiet: true })
      } catch {
        // Suppress errors in quiet polling mode to avoid unhandled promise rejections
      }
    },
    getDelay: () => 20000,
  })


  useEffect(() => {
    try {
      window.localStorage.setItem('brew-ui.starred-params', JSON.stringify(starredParams))
    } catch {
      // Ignore storage failures and keep UI responsive.
    }
  }, [starredParams])

  useEffect(() => {
    if (activeTab !== 'archive' || !selected?.id) return
    loadArchiveTab(selected.id).catch((err) => {
      setError(err instanceof Error ? err.message : 'Unknown error')
    })
  }, [activeTab, loadArchiveTab, selected?.id])

  useEffect(() => {
    archiveViewRequestRef.current += 1
    setSelectedArchiveName('')
    setArchiveViewPayload(null)
    setArchiveViewError('')
    setArchiveViewLoading(false)
  }, [selected?.id])

  useEffect(() => {
    if (activeTab !== 'control' || !selected?.id) return
    loadControlUiSpec(selected.id).catch((err) => {
      setError(err instanceof Error ? err.message : 'Unknown error')
    })
  }, [activeTab, loadControlUiSpec, selected?.id])

  function toggleStarredParam(name) {
    setStarredParams((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    )
  }

  const scheduleTabProps = {
    schedule,
    scheduleDefinition,
    runToggle,
    loadingAction,
    selected,
    runAction,
    ownedTargetValues,
    scheduleFile,
    setScheduleFile,
    uploadWorkbook,
    importResult,
    importErrorIssues,
    importWarningIssues,
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
    controlDrafts,
    onDraftChange: updateControlDraft,
    onWrite: writeControlValue,
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
    repoUpdateStatus,
    repoStatusLoading,
    repoUpdateLoading,
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

  return (
    <AppShell
      fermenters={fermenters}
      selected={selected}
      onSelect={setSelectedId}
      error={error}
      activeTab={activeTab}
      onTabChange={setActiveTab}
    >
      <FermenterTabContent
        selected={selected}
        activeTab={activeTab}
        scheduleProps={scheduleTabProps}
        dataProps={dataTabProps}
        controlProps={controlTabProps}
        archiveProps={archiveTabProps}
        rulesProps={rulesTabProps}
        systemProps={systemTabProps}
        globalView={globalView}
        setGlobalView={setGlobalView}
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
