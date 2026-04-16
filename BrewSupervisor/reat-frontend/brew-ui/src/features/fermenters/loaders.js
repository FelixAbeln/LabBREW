export async function loadFermentersData(brewApi) {
  return brewApi.getFermenters()
}

export async function loadDashboardData(brewApi, fermenterId, options = {}) {
  if (!fermenterId) return null
  return brewApi.getDashboard(fermenterId, { force: Boolean(options.force) })
}
