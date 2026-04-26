const STALE_INVALID_REASONS = new Set([
  'mirror_source_invalid',
  'datasource_silent',
  'dependency_stale',
]);

export function isStaleOnlyState(state, { hasInvalidOverride = false } = {}) {
  const reasons = state?.parameter_invalid_reasons;
  if (hasInvalidOverride) return false;
  if (state?.parameter_valid !== false) return false;
  if (!Array.isArray(reasons) || reasons.length === 0) return false;
  return reasons.every((reason) => STALE_INVALID_REASONS.has(reason));
}

export function isInvalidState(state, { invalidConfig = false, hasInvalidOverride = false } = {}) {
  const staleOnly = isStaleOnlyState(state, { hasInvalidOverride });
  return Boolean(hasInvalidOverride || invalidConfig || (!staleOnly && state?.parameter_valid === false));
}
