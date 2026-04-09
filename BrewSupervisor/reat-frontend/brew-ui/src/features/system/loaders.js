import { api } from '../../api/client';
import { API_BASE } from '../../api/client';

function base(fermenterId) {
  return `/fermenters/${encodeURIComponent(fermenterId)}/agents/storage`;
}

export async function fetchAgentStorageOverview(fermenterId) {
  return api(base(fermenterId));
}

export async function fetchAgentStorageEntries(fermenterId, payload) {
  return api(`${base(fermenterId)}/list`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function createAgentStorageFolder(fermenterId, payload) {
  return api(`${base(fermenterId)}/mkdir`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function moveAgentStorageEntry(fermenterId, payload) {
  return api(`${base(fermenterId)}/move`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function deleteAgentStorageEntry(fermenterId, payload) {
  return api(`${base(fermenterId)}/delete`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function addAgentNetworkDrive(fermenterId, payload) {
  return api(`${base(fermenterId)}/network-drive`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function readAgentStorageFile(fermenterId, payload) {
  return api(`${base(fermenterId)}/read-file`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function writeAgentStorageFile(fermenterId, payload) {
  return api(`${base(fermenterId)}/write-file`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function agentStorageDownloadUrl(fermenterId, payload) {
  const params = new URLSearchParams({
    agent_base_url: String(payload.agent_base_url || ''),
    root: String(payload.root || ''),
    path: String(payload.path || ''),
  });
  return `${API_BASE}${base(fermenterId)}/download?${params.toString()}`;
}
