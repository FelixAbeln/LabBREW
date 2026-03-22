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



function makeEmptyActionForm() {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type: 'takeover',
    targetsText: '',
    value: '',
    duration: '',
    owner: 'manual_override',
    reason: 'Manual UI override',
  }
}

function makeEmptyRuleForm() {
  return {
    id: '',
    enabled: true,
    source: '',
    operator: '==',
    for_s: '',
    operatorParams: {},
    actions: [makeEmptyActionForm()],
    releaseWhenClear: true,
    originalId: '',
  }
}

function normalizeRuleForm(rule) {
  const condition = rule?.condition || {}
  const params = condition?.params && typeof condition.params === 'object' ? condition.params : {}
  const actions = Array.isArray(rule?.actions) && rule.actions.length
    ? rule.actions.map((action, index) => ({
        id: `${rule?.id || 'rule'}-${index}`,
        type: action?.type || action?.kind || 'takeover',
        targetsText: Array.isArray(action?.targets)
          ? action.targets.join(', ')
          : action?.target || '',
        value: action?.value ?? '',
        duration: action?.duration ?? '',
        owner: action?.owner || 'manual_override',
        reason: action?.reason || 'Manual UI override',
      }))
    : [makeEmptyActionForm()]

  return {
    id: rule?.id || '',
    enabled: rule?.enabled !== false,
    source: condition?.source || '',
    operator: condition?.operator || '==',
    for_s: condition?.for_s ?? '',
    operatorParams: { ...params },
    actions,
    releaseWhenClear: rule?.release_when_clear !== false,
    originalId: rule?.id || '',
  }
}

function formatRuleCondition(rule) {
  const condition = rule?.condition || {}
  const params = condition?.params && typeof condition.params === 'object' ? condition.params : {}
  const extras = Object.entries(params).map(([key, value]) => `${key}=${String(value)}`)
  const base = [condition.source || '?', condition.operator || '?', extras.join(', ')].filter(Boolean).join(' ')
  return condition.for_s ? `${base} for ${condition.for_s}s` : base
}

function formatRuleAction(rule) {
  const actions = Array.isArray(rule?.actions) ? rule.actions : []
  if (!actions.length) return 'No actions'
  return actions.map((action) => {
    const type = action?.type || action?.kind || 'action'
    const targets = Array.isArray(action?.targets) ? action.targets.join(', ') : action?.target || '-'
    const parts = [type, targets]
    if (action.value !== undefined) parts.push(`→ ${String(action.value)}`)
    if (action.duration !== undefined) parts.push(`in ${String(action.duration)}s`)
    return parts.join(' ')
  }).join(' • ')
}


function stringifyDataValue(value) {
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function shouldCollapseDataValue(value) {
  const text = stringifyDataValue(value)
  return typeof value === "object" || text.length > 120 || text.includes("\n")
}

function formatCollapsedDataValue(value) {
  if (value && typeof value === "object") {
    if (Array.isArray(value)) return `array(${value.length}) …`
    const keys = Object.keys(value)
    if (keys.length === 0) return '{}'
    const firstKey = keys[0]
    return `${firstKey}: ${stringifyDataValue(value[firstKey]).slice(0, 36)}…`
  }

  const text = stringifyDataValue(value)
  return text.length > 96 ? `${text.slice(0, 96)}…` : text
}

function sanitizeSessionSegment(value) {
  return String(value || 'node')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'node'
}

function buildMeasurementSessionName(fermenter) {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  return `${sanitizeSessionSegment(fermenter?.name)}_${sanitizeSessionSegment(fermenter?.id)}_${stamp}`
}

function AvailabilityTag({ label, value }) {
  return (
    <span className={`pill ${value ? 'pill-ok' : 'pill-bad'}`}>
      {label}: {value ? 'yes' : 'no'}
    </span>
  )
}


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

function ExpandedDataValue({ value }) {
  if (value !== null && typeof value === 'object') {
    return (
      <div className="json-scroll json-tree">
        <JsonTreeNode value={value} defaultExpanded />
      </div>
    )
  }

  return <span className="data-value-text is-expanded">{stringifyDataValue(value)}</span>
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
  const dashboardRequestRef = useRef(0)
  const [activeTab, setActiveTab] = useState('schedule')
  const [followLogBottom, setFollowLogBottom] = useState(true)
  const logRef = useRef(null)
  const [rules, setRules] = useState([])
  const [rulesModalOpen, setRulesModalOpen] = useState(false)
  const [rulesEditorLoading, setRulesEditorLoading] = useState(false)
  const [savingRule, setSavingRule] = useState(false)
  const [deletingRuleId, setDeletingRuleId] = useState('')
  const [operators, setOperators] = useState([])
  const [snapshotKeys, setSnapshotKeys] = useState([])
  const [rulesSnapshot, setRulesSnapshot] = useState(null)
  const [dataSearch, setDataSearch] = useState('')
  const [dataActionLoading, setDataActionLoading] = useState(false)
  const [dataServiceStatus, setDataServiceStatus] = useState(null)
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
  const [ruleForm, setRuleForm] = useState(null)
  const [expandedDataKeys, setExpandedDataKeys] = useState(() => new Set())

  const operatorMap = useMemo(() => new Map(operators.map((item) => [item.name, item])), [operators])

  const selectedOperator = useMemo(() => {
    if (!ruleForm?.operator) return null
    return operatorMap.get(ruleForm.operator) || null
  }, [operatorMap, ruleForm?.operator])

  function updateRuleForm(patch) {
    setRuleForm((current) => (current ? { ...current, ...patch } : current))
  }

  function updateRuleParam(name, value) {
    setRuleForm((current) => {
      if (!current) return current
      return {
        ...current,
        operatorParams: {
          ...current.operatorParams,
          [name]: value,
        },
      }
    })
  }

  function addRuleAction() {
    setRuleForm((current) => {
      if (!current) return current
      return {
        ...current,
        actions: [...(current.actions || []), makeEmptyActionForm()],
      }
    })
  }

  function removeRuleAction(actionId) {
    setRuleForm((current) => {
      if (!current) return current
      const nextActions = (current.actions || []).filter((action) => action.id !== actionId)
      return {
        ...current,
        actions: nextActions.length ? nextActions : [makeEmptyActionForm()],
      }
    })
  }

  function updateRuleAction(actionId, patch) {
    setRuleForm((current) => {
      if (!current) return current
      return {
        ...current,
        actions: (current.actions || []).map((action) =>
          action.id === actionId ? { ...action, ...patch } : action,
        ),
      }
    })
  }

  async function loadDataTab(id = selectedId) {
    if (!id) return null
    const snapshotPromise = api(`/fermenters/${id}/system/snapshot`)
    const statusPromise = dataServiceHealthy
      ? api(`/fermenters/${id}/data/status`).catch(() => null)
      : Promise.resolve(null)

    const [snapshotPayload, statusPayload] = await Promise.all([snapshotPromise, statusPromise])
    setRulesSnapshot(snapshotPayload && typeof snapshotPayload === 'object' ? snapshotPayload : null)
    setDataServiceStatus(statusPayload && typeof statusPayload === 'object' ? statusPayload : null)
    return { snapshotPayload, statusPayload }
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
      await loadDataTab(selected.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setDataActionLoading(false)
    }
  }

  async function loadRules(id = selectedId) {
    if (!id) return
    const [rulesPayload, snapshotPayload] = await Promise.all([
      api(`/fermenters/${id}/rules/`),
      api(`/fermenters/${id}/system/snapshot`),
    ])
    setRules(Array.isArray(rulesPayload) ? rulesPayload : [])
    setRulesSnapshot(snapshotPayload && typeof snapshotPayload === 'object' ? snapshotPayload : null)
  }

  async function loadRuleEditorData(id = selectedId) {
    if (!id) return
    setRulesEditorLoading(true)
    try {
      const [operatorPayload, snapshotPayload] = await Promise.all([
        api(`/fermenters/${id}/system/operators`),
        api(`/fermenters/${id}/system/snapshot`),
      ])
      setOperators(Array.isArray(operatorPayload) ? operatorPayload : [])
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
        action.owner = (actionForm.owner || '').trim() || 'manual_override'
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
    const requestId = dashboardRequestRef.current + 1
    dashboardRequestRef.current = requestId

    const payload = await api(`/fermenters/${id}/dashboard`)
    if (dashboardRequestRef.current !== requestId) return

    if (payload?.fermenter) {
      setFermenters((current) =>
        current.map((item) => (item.id === payload.fermenter.id ? payload.fermenter : item)),
      )
    }

    setSchedule(payload?.schedule || null)
    setScheduleDefinition(payload?.schedule_definition || null)
    setOwnedTargetValues(Array.isArray(payload?.owned_target_values) ? payload.owned_target_values : [])
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

    let cancelled = false
    let inFlight = false

    const runRefresh = async () => {
      if (cancelled || inFlight) return
      inFlight = true
      try {
        await loadDetails(selected.id)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unknown error')
        }
      } finally {
        inFlight = false
      }
    }

    runRefresh()
    const intervalId = window.setInterval(runRefresh, 500)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [selected?.id])

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      loadFermenters().catch(() => {})
    }, 10000)

    return () => window.clearInterval(intervalId)
  }, [])


  useEffect(() => {
    if (activeTab !== 'rules' || !selected?.id) return

    let cancelled = false
    let inFlight = false

    const runRefresh = async () => {
      if (cancelled || inFlight) return
      inFlight = true
      try {
        await loadRules(selected.id)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unknown error')
        }
      } finally {
        inFlight = false
      }
    }

    runRefresh()
    const intervalId = window.setInterval(runRefresh, 1500)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [activeTab, selected?.id])

  useEffect(() => {
    if (activeTab !== 'data' || !selected?.id) return

    let cancelled = false
    let inFlight = false

    const runRefresh = async () => {
      if (cancelled || inFlight) return
      inFlight = true
      try {
        await loadDataTab(selected.id)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unknown error')
        }
      } finally {
        inFlight = false
      }
    }

    runRefresh()
    const intervalId = window.setInterval(runRefresh, 2000)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [activeTab, selected?.id])


  useEffect(() => {
    try {
      window.localStorage.setItem('brew-ui.starred-params', JSON.stringify(starredParams))
    } catch {}
  }, [starredParams])

  function toggleStarredParam(name) {
    setStarredParams((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    )
  }

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
                    <AvailabilityTag
                      label="schedule"
                      value={Boolean(fermenter.summary?.schedule_available)}
                    />
                    <AvailabilityTag
                      label="control"
                      value={Boolean(fermenter.summary?.control_available)}
                    />
                    <AvailabilityTag
                      label="data"
                      value={Boolean(fermenter.summary?.data_available)}
                    />
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
                <h2>{selected ? `${selected.name} · ${selected.id}` : 'Fermenter'}</h2>
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
                  className={`tab-button ${activeTab === 'data' ? 'active' : ''}`}
                  onClick={() => setActiveTab('data')}
                  role="tab"
                  aria-selected={activeTab === 'data'}
                >
                  Data
                </button>
                <button
                  className={`tab-button ${activeTab === 'rules' ? 'active' : ''}`}
                  onClick={() => setActiveTab('rules')}
                  role="tab"
                  aria-selected={activeTab === 'rules'}
                >
                  Rules
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
            
            ) : activeTab === 'data' ? (
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
            ) : activeTab === 'rules' ? (

              <div className="tab-content-grid rules-tab-layout">
                <div className="info-card rules-card">
                  <div className="rules-toolbar">
                    <div>
                      <h3>Rules</h3>
                      <div className="small-text">Manual override rules. Opens snapshot and operator data only when editing.</div>
                    </div>
                    <div className="button-row compact-actions">
                      <button
                        className="primary-button"
                        disabled={!selected}
                        onClick={openAddRule}
                      >
                        Add rule
                      </button>
                    </div>
                  </div>

                  {!rules.length ? (
                    <p className="muted">No rules configured.</p>
                  ) : (
                    <div className="rules-list">
                      {rules.map((rule) => {
                        const isActiveRule = activeRuleIds.has(rule.id)
                        const isHeldRule = heldRuleIds.has(rule.id)
                        const ruleStateClass = isActiveRule ? 'is-active' : isHeldRule ? 'is-held' : ''
                        const activeMeta = rulesSnapshot?.active_rules?.[rule.id] || null
                        const heldMeta = rulesSnapshot?.held_rules?.[rule.id] || null
                        const ownedTargets = activeMeta?.owned_targets || heldMeta?.owned_targets || []

                        return (
                          <div key={rule.id} className={`rule-item ${ruleStateClass}`}>
                            <div className="rule-item-header">
                              <div>
                                <div className="rule-title-row">
                                  <strong>{rule.id}</strong>
                                  <span className={`pill ${rule.enabled !== false ? 'pill-ok' : 'pill-warn'}`}>
                                    {rule.enabled !== false ? 'enabled' : 'disabled'}
                                  </span>
                                  {isActiveRule && <span className="pill pill-rule-active">triggered</span>}
                                  {!isActiveRule && isHeldRule && <span className="pill pill-rule-held">holding control</span>}
                                  {rule.release_when_clear !== false && <span className="tag">release when clear</span>}
                                </div>
                                <div className="small-text">Condition: {formatRuleCondition(rule)}</div>
                                <div className="small-text">Action: {formatRuleAction(rule)}</div>
                                {(isActiveRule || isHeldRule) && (
                                  <div className="small-text">
                                    Targets: {Array.isArray(ownedTargets) && ownedTargets.length ? ownedTargets.join(', ') : '-'}
                                  </div>
                                )}
                              </div>
                              <div className="button-row compact-actions">
                                {!isActiveRule && isHeldRule && (
                                  <button
                                    className="warning-button"
                                    disabled={loadingAction || !ownedTargets.length}
                                    onClick={() => releaseHeldRule(rule.id, ownedTargets)}
                                  >
                                    {loadingAction ? 'Releasing…' : 'Release'}
                                  </button>
                                )}
                                <button className="secondary-button" onClick={() => openEditRule(rule)}>Edit</button>
                                <button
                                  className="danger-button"
                                  disabled={deletingRuleId === rule.id}
                                  onClick={() => deleteRule(rule.id)}
                                >
                                  {deletingRuleId === rule.id ? 'Deleting…' : 'Delete'}
                                </button>
                              </div>
                            </div>
                          </div>
                        )
                      })}
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

            {rulesModalOpen && ruleForm && (
              <div className="modal-backdrop" onClick={closeRuleModal}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="card-header-row">
                    <h3>{ruleForm.id ? `Edit ${ruleForm.id}` : 'Add rule'}</h3>
                    <button className="secondary-button" disabled={savingRule} onClick={closeRuleModal}>Close</button>
                  </div>

                  {rulesEditorLoading ? (
                    <p className="muted">Loading operators and snapshot…</p>
                  ) : (
                    <>
                      <div className="rules-form-grid">
                        <label className="form-field">
                          <span>Rule id</span>
                          <input value={ruleForm.id} onChange={(e) => updateRuleForm({ id: e.target.value })} placeholder="manual-pressure-override" />
                        </label>
                        <label className="form-field checkbox-field">
                          <span>Enabled</span>
                          <input type="checkbox" checked={ruleForm.enabled} onChange={(e) => updateRuleForm({ enabled: e.target.checked })} />
                        </label>
                        <label className="form-field">
                          <span>Parameter</span>
                          <input list="rule-target-options" value={ruleForm.source} onChange={(e) => updateRuleForm({ source: e.target.value })} placeholder="set_temp_Fermentor" />
                        </label>
                        <label className="form-field">
                          <span>Operator</span>
                          <select value={ruleForm.operator} onChange={(e) => updateRuleForm({ operator: e.target.value, operatorParams: {} })}>
                            {operators.map((operator) => (
                              <option key={operator.name} value={operator.name}>{operator.label || operator.name}</option>
                            ))}
                          </select>
                        </label>
                        {selectedOperator?.supports_for_s && (
                          <label className="form-field">
                            <span>For seconds</span>
                            <input type="number" step="0.1" value={ruleForm.for_s} onChange={(e) => updateRuleForm({ for_s: e.target.value })} placeholder="optional" />
                          </label>
                        )}
                        {Object.entries(selectedOperator?.param_schema || {}).map(([key, schema]) => (
                          <label key={key} className="form-field">
                            <span>{key}</span>
                            <input
                              type={schema?.type === 'number' ? 'number' : 'text'}
                              step={schema?.type === 'number' ? 'any' : undefined}
                              value={ruleForm.operatorParams?.[key] ?? ''}
                              onChange={(e) => updateRuleParam(key, e.target.value)}
                              placeholder={schema?.required ? 'required' : 'optional'}
                            />
                          </label>
                        ))}
                      </div>

                      <div className="rules-section-title actions-header-row">
                        <span>Actions</span>
                        <button className="secondary-button" type="button" onClick={addRuleAction}>Add action</button>
                      </div>
                      <div className="rule-action-stack">
                        {(ruleForm.actions || []).map((action, index) => (
                          <div key={action.id} className="rule-action-card">
                            <div className="card-header-row rule-action-card-header">
                              <strong>Action {index + 1}</strong>
                              <button
                                className="secondary-button"
                                type="button"
                                onClick={() => removeRuleAction(action.id)}
                                disabled={(ruleForm.actions || []).length === 1}
                              >
                                Remove
                              </button>
                            </div>
                            <div className="rules-form-grid">
                              <label className="form-field">
                                <span>Type</span>
                                <select value={action.type} onChange={(e) => updateRuleAction(action.id, { type: e.target.value })}>
                                  <option value="takeover">takeover</option>
                                  <option value="set">set</option>
                                  <option value="ramp">ramp</option>
                                </select>
                              </label>
                              <label className="form-field form-field-wide">
                                <span>Targets</span>
                                <input list="rule-target-options" value={action.targetsText} onChange={(e) => updateRuleAction(action.id, { targetsText: e.target.value })} placeholder="set_pres_Fermentor, set_temp_Fermentor" />
                              </label>
                              {(action.type === 'set' || action.type === 'ramp') && (
                                <label className="form-field">
                                  <span>Value</span>
                                  <input type="number" step="any" value={action.value} onChange={(e) => updateRuleAction(action.id, { value: e.target.value })} />
                                </label>
                              )}
                              {(action.type === 'takeover' || action.type === 'ramp') && (
                                <label className="form-field">
                                  <span>Owner</span>
                                  <input value={action.owner} onChange={(e) => updateRuleAction(action.id, { owner: e.target.value })} />
                                </label>
                              )}
                              {action.type === 'takeover' && (
                                <label className="form-field form-field-wide">
                                  <span>Reason</span>
                                  <input value={action.reason} onChange={(e) => updateRuleAction(action.id, { reason: e.target.value })} />
                                </label>
                              )}
                              {action.type === 'ramp' && (
                                <label className="form-field">
                                  <span>Duration (s)</span>
                                  <input type="number" step="any" value={action.duration} onChange={(e) => updateRuleAction(action.id, { duration: e.target.value })} />
                                </label>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>

                      <div className="rules-form-grid">
                        <label className="form-field checkbox-field">
                          <span>Release when clear</span>
                          <input type="checkbox" checked={ruleForm.releaseWhenClear} onChange={(e) => updateRuleForm({ releaseWhenClear: e.target.checked })} />
                        </label>
                      </div>

                      <datalist id="rule-target-options">
                        {snapshotKeys.map((key) => <option key={key} value={key} />)}
                      </datalist>
                    </>
                  )}

                  <div className="button-row modal-actions">
                    <button className="secondary-button" disabled={savingRule} onClick={closeRuleModal}>Cancel</button>
                    <button className="primary-button" disabled={savingRule || rulesEditorLoading} onClick={saveRule}>
                      {savingRule ? 'Saving…' : 'Save rule'}
                    </button>
                  </div>
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
