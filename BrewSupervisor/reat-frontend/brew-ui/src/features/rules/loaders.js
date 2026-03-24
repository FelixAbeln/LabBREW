export async function loadRulesTabPayload(brewApi, fermenterId) {
  if (!fermenterId) return { rulesPayload: [], snapshotPayload: null }

  const [rulesPayload, snapshotPayload] = await Promise.all([
    brewApi.getRules(fermenterId),
    brewApi.getSnapshot(fermenterId),
  ])

  return {
    rulesPayload: Array.isArray(rulesPayload) ? rulesPayload : [],
    snapshotPayload: snapshotPayload && typeof snapshotPayload === 'object' ? snapshotPayload : null,
  }
}

export async function loadRuleEditorPayload(brewApi, fermenterId) {
  if (!fermenterId) return { operatorPayload: [], snapshotPayload: null }

  const [operatorPayload, snapshotPayload] = await Promise.all([
    brewApi.getOperators(fermenterId),
    brewApi.getSnapshot(fermenterId),
  ])

  return {
    operatorPayload: Array.isArray(operatorPayload) ? operatorPayload : [],
    snapshotPayload: snapshotPayload && typeof snapshotPayload === 'object' ? snapshotPayload : null,
  }
}
