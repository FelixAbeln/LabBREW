export function isImportValidationPayload(payload) {
  return Boolean(
    payload &&
      typeof payload === 'object' &&
      ('valid' in payload || 'errors' in payload || 'issues' in payload),
  )
}

export function collectIssues(payload, level) {
  if (!payload || !Array.isArray(payload.issues)) return []
  const filtered = payload.issues.filter((issue) => issue?.level === level)
  const seen = new Set()
  const deduped = []
  for (const issue of filtered) {
    const key = `${issue.code || ''}::${issue.path || ''}::${issue.message || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(issue)
  }
  return deduped
}
