export const API_BASE = 'http://127.0.0.1:8782'

export class ApiResponseError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.name = 'ApiResponseError'
    this.status = status
    this.payload = payload
  }
}

function formatApiErrorDetail(detail) {
  if (detail == null) {
    return ''
  }

  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => formatApiErrorDetail(item))
      .filter(Boolean)
      .join('; ')
  }

  if (typeof detail === 'object') {
    const location = Array.isArray(detail.loc) ? detail.loc.join('.') : ''
    const message = typeof detail.msg === 'string'
      ? detail.msg
      : typeof detail.detail === 'string'
        ? detail.detail
        : typeof detail.error === 'string'
          ? detail.error
          : ''

    if (location && message) {
      return `${location}: ${message}`
    }
    if (message) {
      return message
    }

    const nested = Object.entries(detail)
      .map(([key, value]) => {
        const formatted = formatApiErrorDetail(value)
        if (!formatted) {
          return ''
        }
        return typeof value === 'object' && value !== null ? formatted : `${key}: ${formatted}`
      })
      .filter(Boolean)
      .join('; ')

    return nested || JSON.stringify(detail)
  }

  return String(detail)
}

export async function api(path, options = {}) {
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
    const message = formatApiErrorDetail(payload?.detail ?? payload?.error ?? payload) || `HTTP ${response.status}`

    if (typeof payload === 'string') {
      throw new ApiResponseError(message, response.status, payload)
    }
    throw new ApiResponseError(message, response.status, payload)
  }

  return payload
}
