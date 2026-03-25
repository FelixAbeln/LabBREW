export async function loadDataTabPayload(brewApi, fermenterId, options = {}) {
  if (!fermenterId) return { snapshotPayload: null, statusPayload: null }

  const snapshotPromise = brewApi.getSnapshot(fermenterId)
  const statusPromise = options.includeStatus
    ? brewApi.getDataStatus(fermenterId).catch(() => null)
    : Promise.resolve(null)

  const [snapshotPayload, statusPayload] = await Promise.all([snapshotPromise, statusPromise])
  return { snapshotPayload, statusPayload }
}
