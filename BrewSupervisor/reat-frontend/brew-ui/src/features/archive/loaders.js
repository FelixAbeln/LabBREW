export async function loadArchiveTabPayload(brewApi, fermenterId, options = {}) {
  if (!fermenterId) return null
  const outputDir = options.outputDir || undefined
  return brewApi.getDataArchives(fermenterId, { outputDir })
}
