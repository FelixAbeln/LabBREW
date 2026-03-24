export const API_BASE = 'http://127.0.0.1:8782'

export class ApiResponseError extends Error {
  constructor(message, status, payload) {
    super(message)
    this.name = 'ApiResponseError'
    this.status = status
    this.payload = payload
  }
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
    if (typeof payload === 'string') {
      throw new ApiResponseError(payload || `HTTP ${response.status}`, response.status, payload)
    }
    throw new ApiResponseError(
      payload?.detail || payload?.error || JSON.stringify(payload) || `HTTP ${response.status}`,
      response.status,
      payload,
    )
  }

  return payload
}
