import { createRequestLayer } from './requestLayer'

export function createBrewApi(apiClient) {
  const requestLayer = createRequestLayer(apiClient)

  function invalidateFermenter(id) {
    if (!id) return
    requestLayer.invalidate(`/fermenters/${id}`)
  }

  function invalidateFermenters() {
    requestLayer.invalidate('/fermenters')
  }

  return {
    getFermenters(options = {}) {
      return requestLayer.get('/fermenters', {
        ttlMs: 6000,
        bypassCache: Boolean(options.force),
      })
    },

    getDashboard(id, options = {}) {
      return requestLayer.get(`/fermenters/${id}/dashboard`, {
        ttlMs: 1200,
        bypassCache: Boolean(options.force),
      })
    },

    getSnapshot(id, options = {}) {
      return requestLayer.get(`/fermenters/${id}/system/snapshot`, {
        ttlMs: 1200,
        bypassCache: Boolean(options.force),
      })
    },

    getRules(id, options = {}) {
      return requestLayer.get(`/fermenters/${id}/rules/`, {
        ttlMs: 1800,
        bypassCache: Boolean(options.force),
      })
    },

    getOperators(id, options = {}) {
      return requestLayer.get(`/fermenters/${id}/system/operators`, {
        ttlMs: 30000,
        bypassCache: Boolean(options.force),
      })
    },

    getDataStatus(id, options = {}) {
      return requestLayer.get(`/fermenters/${id}/data/status`, {
        ttlMs: 1500,
        bypassCache: Boolean(options.force),
      })
    },

    getDataArchives(id, options = {}) {
      const outputDir = options.outputDir ? `?output_dir=${encodeURIComponent(options.outputDir)}` : ''
      return requestLayer.get(`/fermenters/${id}/data/archives${outputDir}`, {
        ttlMs: 2000,
        bypassCache: Boolean(options.force),
      })
    },

    getDataArchiveView(id, name, options = {}) {
      const params = new URLSearchParams()
      if (options.outputDir) params.set('output_dir', options.outputDir)
      if (Number.isFinite(options.maxPoints)) params.set('max_points', String(options.maxPoints))
      const query = params.toString()
      return requestLayer.get(
        `/fermenters/${id}/data/archives/view/${encodeURIComponent(name)}${query ? `?${query}` : ''}`,
        {
          ttlMs: 1000,
          bypassCache: Boolean(options.force),
        },
      )
    },

    getAgentRepoStatus(id, options = {}) {
      const force = options.force ? '?force=1' : ''
      return requestLayer.get(`/fermenters/${id}/agent/repo/status${force}`, {
        ttlMs: 10000,
        bypassCache: Boolean(options.force),
      })
    },

    getAgentPersistence(id, options = {}) {
      return requestLayer.get(`/fermenters/${id}/agent/persistence`, {
        ttlMs: 5000,
        bypassCache: Boolean(options.force),
      })
    },

    getWorkspaceLayouts(id, options = {}) {
      return requestLayer.get(`/fermenters/${id}/workspace-layouts`, {
        ttlMs: 1500,
        bypassCache: Boolean(options.force),
      })
    },

    saveWorkspaceLayouts(id, payload) {
      requestLayer.invalidate(`/fermenters/${id}/workspace-layouts`)
      return apiClient(`/fermenters/${id}/workspace-layouts`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    },

    applyAgentRepoUpdate(id) {
      return apiClient(`/fermenters/${id}/agent/repo/update`, {
        method: 'POST',
        body: JSON.stringify({}),
      })
    },

    deleteDataArchive(id, name, options = {}) {
      const outputDir = options.outputDir ? `?output_dir=${encodeURIComponent(options.outputDir)}` : ''
      return apiClient(`/fermenters/${id}/data/archives/${encodeURIComponent(name)}${outputDir}`, {
        method: 'DELETE',
      })
    },

    invalidateFermenter,
    invalidateFermenters,

    async mutate(path, options) {
      const result = await apiClient(path, options)
      return result
    },
  }
}
