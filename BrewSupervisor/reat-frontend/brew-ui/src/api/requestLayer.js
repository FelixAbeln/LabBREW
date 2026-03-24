export function createRequestLayer(requestFn) {
  const inFlight = new Map()
  const cache = new Map()

  function getCacheKey(path, params) {
    if (!params || typeof params !== 'object' || !Object.keys(params).length) {
      return path
    }

    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== null)
        .map(([key, value]) => [key, String(value)]),
    )

    return query.size ? `${path}?${query.toString()}` : path
  }

  async function get(path, options = {}) {
    const { ttlMs = 0, params = null, bypassCache = false } = options
    const key = getCacheKey(path, params)
    const now = Date.now()

    if (!bypassCache && ttlMs > 0 && cache.has(key)) {
      const entry = cache.get(key)
      if (entry.expiresAt > now) {
        return entry.value
      }
      cache.delete(key)
    }

    if (inFlight.has(key)) {
      return inFlight.get(key)
    }

    const requestPath = key
    const promise = requestFn(requestPath)
      .then((value) => {
        if (ttlMs > 0) {
          cache.set(key, {
            value,
            expiresAt: Date.now() + ttlMs,
          })
        }
        return value
      })
      .finally(() => {
        inFlight.delete(key)
      })

    inFlight.set(key, promise)
    return promise
  }

  function invalidate(pathPrefix = '') {
    for (const key of cache.keys()) {
      if (!pathPrefix || key.startsWith(pathPrefix)) {
        cache.delete(key)
      }
    }
  }

  return {
    get,
    invalidate,
  }
}
