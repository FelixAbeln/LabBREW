import { api } from '../../api/client.js';

function base(fermenterId) {
  return `/fermenters/${encodeURIComponent(fermenterId)}/parameterdb`;
}

export async function fetchParams(fermenterId)       { return api(`${base(fermenterId)}/params`); }
export async function fetchGraph(fermenterId)        { return api(`${base(fermenterId)}/graph`); }
export async function fetchStats(fermenterId)        { return api(`${base(fermenterId)}/stats`); }
export async function exportSnapshotFile(fermenterId){ return api(`${base(fermenterId)}/snapshot-file`); }
export async function importSnapshotFile(fermenterId, snapshot, options = {}) {
  return api(`${base(fermenterId)}/snapshot-file`, {
    method: 'POST',
    body: JSON.stringify({
      snapshot,
      replace_existing: options.replaceExisting ?? true,
      save_to_disk: options.saveToDisk ?? true,
    }),
  });
}
export async function fetchParamTypes(fermenterId)   { return api(`${base(fermenterId)}/param-types`); }
export async function fetchParamTypeUi(fermenterId, parameterType) {
  return api(`${base(fermenterId)}/param-types/${encodeURIComponent(parameterType)}/ui`);
}
export async function fetchSources(fermenterId)      { return api(`${base(fermenterId)}/sources`); }
export async function fetchSourceTypes(fermenterId)  { return api(`${base(fermenterId)}/source-types`); }

export async function fetchSourceTypeUi(fermenterId, sourceType, name = null, mode = null) {
  const q = new URLSearchParams();
  if (name) q.set('name', name);
  if (mode) q.set('mode', mode);
  return api(`${base(fermenterId)}/source-types/${encodeURIComponent(sourceType)}/ui?${q}`);
}

export async function createParam(fermenterId, name, parameter_type, value, config, metadata) {
  return api(`${base(fermenterId)}/params`, {
    method: 'POST',
    body: JSON.stringify({ name, parameter_type, value, config, metadata }),
  });
}

export async function setParamValue(fermenterId, name, value) {
  return api(`${base(fermenterId)}/params/${encodeParamName(name)}/value`, {
    method: 'PUT',
    body: JSON.stringify({ value }),
  });
}

export async function updateParamConfig(fermenterId, name, config) {
  return api(`${base(fermenterId)}/params/${encodeParamName(name)}/config`, {
    method: 'PUT',
    body: JSON.stringify({ config }),
  });
}

export async function updateParamMetadata(fermenterId, name, metadata) {
  return api(`${base(fermenterId)}/params/${encodeParamName(name)}/metadata`, {
    method: 'PUT',
    body: JSON.stringify({ metadata }),
  });
}

export async function deleteParam(fermenterId, name) {
  return api(`${base(fermenterId)}/params/${encodeParamName(name)}`, { method: 'DELETE' });
}

export async function createSource(fermenterId, name, source_type, config) {
  return api(`${base(fermenterId)}/sources`, {
    method: 'POST',
    body: JSON.stringify({ name, source_type, config }),
  });
}

export async function updateSource(fermenterId, name, config) {
  return api(`${base(fermenterId)}/sources/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify({ config }),
  });
}

export async function deleteSource(fermenterId, name) {
  return api(`${base(fermenterId)}/sources/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

// Parameter names can contain dots (e.g. twin.connected) – encode each segment
function encodeParamName(name) {
  return name.split('/').map(encodeURIComponent).join('/');
}
