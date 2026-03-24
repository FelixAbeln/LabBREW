export function stringifyDataValue(value) {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function shouldCollapseDataValue(value) {
  const text = stringifyDataValue(value)
  return typeof value === 'object' || text.length > 120 || text.includes('\n')
}

export function formatCollapsedDataValue(value) {
  if (value && typeof value === 'object') {
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

export function buildMeasurementSessionName(fermenter) {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  return `${sanitizeSessionSegment(fermenter?.name)}_${sanitizeSessionSegment(fermenter?.id)}_${stamp}`
}
