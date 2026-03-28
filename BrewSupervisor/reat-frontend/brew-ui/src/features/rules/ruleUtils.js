export function makeEmptyActionForm() {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type: 'takeover',
    targetsText: '',
    value: '',
    duration: '',
    reason: 'Safety takeover',
  }
}

export function makeEmptyRuleForm() {
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

export function normalizeRuleForm(rule) {
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
        reason: action?.reason || 'Safety takeover',
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

export function formatRuleCondition(rule) {
  const condition = rule?.condition || {}
  const params = condition?.params && typeof condition.params === 'object' ? condition.params : {}
  const extras = Object.entries(params).map(([key, value]) => `${key}=${String(value)}`)
  const base = [condition.source || '?', condition.operator || '?', extras.join(', ')].filter(Boolean).join(' ')
  return condition.for_s ? `${base} for ${condition.for_s}s` : base
}

export function formatRuleAction(rule) {
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
