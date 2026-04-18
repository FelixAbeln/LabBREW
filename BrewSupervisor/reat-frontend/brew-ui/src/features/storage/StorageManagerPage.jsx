import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  addAgentNetworkDrive,
  agentStorageDownloadUrl,
  createAgentStorageFolder,
  deleteAgentStorageEntry,
  fetchAgentStorageEntries,
  fetchAgentStorageOverview,
  moveAgentStorageEntry,
  readAgentStorageFile,
  writeAgentStorageFile,
} from '../system/loaders';

function formatBytes(value) {
  const num = Number(value);
  if (!Number.isFinite(num) || num < 0) return '-';
  if (num < 1024) return `${num} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let next = num / 1024;
  for (let idx = 0; idx < units.length; idx += 1) {
    if (next < 1024 || idx === units.length - 1) return `${next.toFixed(next >= 10 ? 1 : 2)} ${units[idx]}`;
    next /= 1024;
  }
  return `${num} B`;
}

function toPathSegments(pathValue) {
  const clean = String(pathValue || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  if (!clean) return [];
  return clean.split('/').filter(Boolean);
}

function parentPath(pathValue) {
  const segments = toPathSegments(pathValue);
  if (!segments.length) return '';
  return segments.slice(0, -1).join('/');
}

function joinPath(folderPath, leafName) {
  const folder = String(folderPath || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const leaf = String(leafName || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  if (!folder) return leaf;
  if (!leaf) return folder;
  return `${folder}/${leaf}`;
}

function isJsonPath(pathValue) {
  return String(pathValue || '').toLowerCase().endsWith('.json');
}

function isYamlPath(pathValue) {
  const lower = String(pathValue || '').toLowerCase();
  return lower.endsWith('.yaml') || lower.endsWith('.yml');
}

function StorageActionModal({
  title,
  fields,
  submitLabel,
  submitDisabled = false,
  busy = false,
  error = '',
  onChange,
  onCancel,
  onSubmit,
}) {
  return (
    <div className="pdb-modal-overlay" onClick={(event) => event.target === event.currentTarget && onCancel()}>
      <div className="pdb-modal pdb-modal-wide" onClick={(event) => event.stopPropagation()}>
        <div className="pdb-modal-header">
          <span>{title}</span>
          <button className="pdb-close-btn pdb-close-btn-sm" type="button" onClick={onCancel} title="Close">✕</button>
        </div>
        <div className="pdb-modal-body">
          {fields.map((field) => (
            <div key={field.key} className="pdb-field" style={{ marginBottom: 10 }}>
              <label className="pdb-label">{field.label}</label>
              {field.type === 'select' ? (
                <select
                  className="pdb-input pdb-full"
                  value={field.value}
                  onChange={(event) => onChange(field.key, event.target.value)}
                  autoFocus={field.autoFocus}
                >
                  {field.options.map((option) => (
                    <option key={option.value || '__root'} value={option.value}>{option.label}</option>
                  ))}
                </select>
              ) : field.readOnly ? (
                <div className="pdb-readonly pdb-readonly-wrap">{field.value || '-'}</div>
              ) : (
                <input
                  className="pdb-input pdb-full"
                  type="text"
                  value={field.value}
                  onChange={(event) => onChange(field.key, event.target.value)}
                  placeholder={field.placeholder || ''}
                  autoFocus={field.autoFocus}
                />
              )}
            </div>
          ))}
          {error ? <div className="pdb-save-error">{error}</div> : null}
        </div>
        <div className="pdb-modal-footer">
          <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={onCancel}>Cancel</button>
          <button className="pdb-btn-primary pdb-btn-sm" type="button" onClick={onSubmit} disabled={submitDisabled || busy}>
            {busy ? 'Saving…' : submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function StorageEditorModal({ title, pathLabel, content, loading, saving, error, canFormatJson, canFormatYaml, onChange, onFormatJson, onCancel, onSave }) {
  return (
    <div className="pdb-modal-overlay" onClick={(event) => event.target === event.currentTarget && onCancel()}>
      <div className="pdb-modal pdb-modal-editor" onClick={(event) => event.stopPropagation()}>
        <div className="pdb-modal-header">
          <span>{title}</span>
          <button className="pdb-close-btn pdb-close-btn-sm" type="button" onClick={onCancel} title="Close">✕</button>
        </div>
        <div className="pdb-modal-body">
          <div className="pdb-field" style={{ marginBottom: 10 }}>
            <label className="pdb-label">File</label>
            <div className="pdb-readonly pdb-readonly-wrap">{pathLabel}</div>
          </div>
          <div className="pdb-field" style={{ marginBottom: 0 }}>
            <label className="pdb-label">Contents</label>
            <textarea
              className="pdb-textarea"
              style={{ minHeight: 360 }}
              value={content}
              onChange={(event) => onChange(event.target.value)}
              spellCheck={false}
              disabled={loading || saving}
              autoFocus
            />
          </div>
          {error ? <div className="pdb-save-error">{error}</div> : null}
        </div>
        <div className="pdb-modal-footer">
          {canFormatJson ? <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={onFormatJson} disabled={loading || saving}>Format JSON</button> : null}
          {canFormatYaml ? <div className="pdb-readonly" style={{ marginRight: 'auto' }}>YAML is validated and formatted on save.</div> : null}
          <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={onCancel}>Cancel</button>
          <button className="pdb-btn-primary pdb-btn-sm" type="button" onClick={onSave} disabled={loading || saving}>
            {saving ? 'Saving…' : loading ? 'Loading…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

function AgentStorageCard({ fermenterId, agent, agents, selectedAgentBaseUrl, onSelectAgentBaseUrl, onRefreshOverview }) {
  const roots = useMemo(() => Array.isArray(agent?.storage?.roots) ? agent.storage.roots : [], [agent]);
  const [rootKey, setRootKey] = useState('');
  const [path, setPath] = useState('');
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState('');
  const [moveSource, setMoveSource] = useState('');
  const [moveTargetFolder, setMoveTargetFolder] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const [folderOptions, setFolderOptions] = useState([{ value: '', label: 'root' }]);
  const [renameDraft, setRenameDraft] = useState({ path: '', value: '' });
  const [newFolderName, setNewFolderName] = useState(null);
  const [editorState, setEditorState] = useState(null);
  const folderOptionsCacheRef = useRef(new Map());

  const folderOptionsCacheKey = useCallback((nextRoot = rootKey) => {
    const base = String(agent?.agent_base_url || '').trim();
    const root = String(nextRoot || '').trim();
    if (!base || !root) return '';
    return `${base}::${root}`;
  }, [agent?.agent_base_url, rootKey]);

  function invalidateFolderOptionsCache(nextRoot = rootKey) {
    const key = folderOptionsCacheKey(nextRoot);
    if (!key) return;
    folderOptionsCacheRef.current.delete(key);
  }

  function closeMoveMenu() {
    setMoveSource('');
    setMoveTargetFolder('');
  }

  function closeRenameMenu() {
    setRenameDraft({ path: '', value: '' });
  }

  function closeNewFolderMenu() {
    setNewFolderName(null);
  }

  function closeEditor() {
    setEditorState(null);
  }

  useEffect(() => {
    if (!roots.length) {
      setRootKey('');
      setPath('');
      return;
    }
    setRootKey((current) => {
      if (current && roots.some((item) => item?.key === current)) return current;
      return String(roots[0]?.key || '');
    });
    setPath('');
  }, [roots]);

  const refreshEntries = useCallback(async (nextRoot = rootKey, nextPath = path) => {
    if (!fermenterId || !agent?.agent_base_url || !nextRoot) return;
    setError('');
    try {
      const response = await fetchAgentStorageEntries(fermenterId, {
        agent_base_url: agent.agent_base_url,
        root: nextRoot,
        path: nextPath,
      });
      setEntries(Array.isArray(response?.entries) ? response.entries : []);
    } catch (err) {
      setEntries([]);
      setError(err?.message ?? String(err));
    }
  }, [agent?.agent_base_url, fermenterId, path, rootKey]);

  useEffect(() => {
    refreshEntries();
  }, [refreshEntries]);

  useEffect(() => {
    async function loadFolderOptions() {
      if (!moveSource || !fermenterId || !agent?.agent_base_url || !rootKey) {
        setFolderOptions([{ value: '', label: 'root' }]);
        return;
      }

      const cacheKey = folderOptionsCacheKey(rootKey);
      const cached = cacheKey ? folderOptionsCacheRef.current.get(cacheKey) : null;
      if (Array.isArray(cached) && cached.length) {
        setFolderOptions(cached);
        return;
      }

      const seen = new Set(['']);
      const nextOptions = [{ value: '', label: 'root' }];

      async function walk(folderPath, depth) {
        const response = await fetchAgentStorageEntries(fermenterId, {
          agent_base_url: agent.agent_base_url,
          root: rootKey,
          path: folderPath,
        });
        const listed = Array.isArray(response?.entries) ? response.entries : [];
        const dirs = listed.filter((entry) => entry?.kind === 'directory' && typeof entry.path === 'string');
        dirs.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
        for (const entry of dirs) {
          const value = String(entry.path || '');
          if (seen.has(value)) continue;
          seen.add(value);
          nextOptions.push({
            value,
            label: `${'  '.repeat(depth + 1)}${String(entry.name || value)}`,
          });
          await walk(value, depth + 1);
        }
      }

      try {
        await walk('', 0);
        if (cacheKey) {
          folderOptionsCacheRef.current.set(cacheKey, nextOptions);
        }
        setFolderOptions(nextOptions);
      } catch {
        setFolderOptions([{ value: '', label: 'root' }]);
      }
    }

    loadFolderOptions();
  }, [moveSource, fermenterId, agent?.agent_base_url, folderOptionsCacheKey, rootKey]);

  async function createFolder() {
    if (!rootKey || actionBusy || !String(newFolderName || '').trim()) return;
    setActionBusy(true);
    setError('');
    try {
      await createAgentStorageFolder(fermenterId, {
        agent_base_url: agent.agent_base_url,
        root: rootKey,
        path,
        name: String(newFolderName).trim(),
      });
      invalidateFolderOptionsCache(rootKey);
      closeNewFolderMenu();
      await refreshEntries();
      onRefreshOverview();
    } catch (err) {
      setError(err?.message ?? String(err));
    } finally {
      setActionBusy(false);
    }
  }

  async function moveEntry() {
    if (!moveSource.trim() || !rootKey || actionBusy) return;
    const sourceLeaf = toPathSegments(moveSource).slice(-1)[0] || '';
    const dstPath = joinPath(moveTargetFolder, sourceLeaf);
    if (!dstPath) return;
    setActionBusy(true);
    setError('');
    try {
      await moveAgentStorageEntry(fermenterId, {
        agent_base_url: agent.agent_base_url,
        root: rootKey,
        src_path: moveSource.trim(),
        dst_path: dstPath,
      });
      invalidateFolderOptionsCache(rootKey);
      closeMoveMenu();
      await refreshEntries();
      onRefreshOverview();
    } catch (err) {
      setError(err?.message ?? String(err));
    } finally {
      setActionBusy(false);
    }
  }

  async function deleteEntry(entry) {
    if (!entry || !entry.path || actionBusy) return;
    const label = String(entry.path);
    if (!window.confirm(`Delete ${label}?`)) return;
    setActionBusy(true);
    setError('');
    try {
      await deleteAgentStorageEntry(fermenterId, {
        agent_base_url: agent.agent_base_url,
        root: rootKey,
        path: label,
        recursive: entry.kind === 'directory',
      });
      invalidateFolderOptionsCache(rootKey);
      await refreshEntries();
      onRefreshOverview();
    } catch (err) {
      setError(err?.message ?? String(err));
    } finally {
      setActionBusy(false);
    }
  }

  function downloadEntry(entry) {
    if (!entry?.path || !rootKey) return;
    const url = agentStorageDownloadUrl(fermenterId, {
      agent_base_url: agent.agent_base_url,
      root: rootKey,
      path: entry.path,
    });
    const link = document.createElement('a');
    link.href = url;
    link.download = entry.name || 'download';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function openEditor(entry) {
    if (!entry?.path || !rootKey || actionBusy) return;
    setEditorState({
      path: String(entry.path),
      content: '',
      loading: true,
      saving: false,
      error: '',
    });
    try {
      const response = await readAgentStorageFile(fermenterId, {
        agent_base_url: agent.agent_base_url,
        root: rootKey,
        path: entry.path,
      });
      setEditorState({
        path: String(response?.path || entry.path),
        content: String(response?.content || ''),
        originalContent: String(response?.content || ''),
        loading: false,
        saving: false,
        error: '',
      });
    } catch (err) {
      setEditorState({
        path: String(entry.path),
        content: '',
        originalContent: '',
        loading: false,
        saving: false,
        error: err?.message ?? String(err),
      });
    }
  }

  function formatEditorJson() {
    setEditorState((current) => {
      if (!current) return current;
      try {
        const parsed = JSON.parse(current.content || '');
        return {
          ...current,
          content: `${JSON.stringify(parsed, null, 2)}\n`,
          error: '',
        };
      } catch (err) {
        return {
          ...current,
          error: err?.message ?? String(err),
        };
      }
    });
  }

  async function saveEditor() {
    if (!editorState?.path || editorState.loading || editorState.saving) return;
    setEditorState((current) => current ? { ...current, saving: true, error: '' } : current);
    try {
      const response = await writeAgentStorageFile(fermenterId, {
        agent_base_url: agent.agent_base_url,
        root: rootKey,
        path: editorState.path,
        content: editorState.content,
      });
      setEditorState((current) => current ? {
        ...current,
        content: String(response?.content ?? current.content),
        originalContent: String(response?.content ?? current.content),
        saving: false,
        error: '',
      } : current);
      await refreshEntries();
      onRefreshOverview();
    } catch (err) {
      setEditorState((current) => current ? { ...current, saving: false, error: err?.message ?? String(err) } : current);
    }
  }

  function requestCloseEditor() {
    if (editorState && editorState.content !== editorState.originalContent) {
      const confirmed = window.confirm('Discard unsaved changes?');
      if (!confirmed) {
        return;
      }
    }
    closeEditor();
  }

  async function renameEntry() {
    if (!renameDraft.path || !rootKey || actionBusy) return;
    const srcPath = String(renameDraft.path);
    const currentName = toPathSegments(srcPath).slice(-1)[0] || '';
    const nextName = String(renameDraft.value || '').trim();
    if (!nextName || nextName === currentName) return;
    const dstPath = joinPath(parentPath(srcPath), nextName);
    setActionBusy(true);
    setError('');
    try {
      await moveAgentStorageEntry(fermenterId, {
        agent_base_url: agent.agent_base_url,
        root: rootKey,
        src_path: srcPath,
        dst_path: dstPath,
      });
      invalidateFolderOptionsCache(rootKey);
      if (moveSource === srcPath) {
        closeMoveMenu();
      }
      closeRenameMenu();
      await refreshEntries();
      onRefreshOverview();
    } catch (err) {
      setError(err?.message ?? String(err));
    } finally {
      setActionBusy(false);
    }
  }

  const selectedRoot = roots.find((item) => item?.key === rootKey) || null;
  const disk = selectedRoot?.disk || null;
  const crumbs = toPathSegments(path);
  function queueMove(entry) {
    if (!entry?.path) return;
    setMoveSource(String(entry.path));
    setMoveTargetFolder(path || '');
  }

  function queueRename(entry) {
    if (!entry?.path) return;
    setRenameDraft({
      path: String(entry.path),
      value: String(entry.name || '').trim(),
    });
  }

  return (
    <div className="sm-panel">
      <div className="sm-top-row">
        <div className="sm-title-row">
          <div className="sm-agent-name">{agent?.node_name || 'Agent'}</div>
          <span className={`pill ${agent?.reachable ? 'pill-ok' : 'pill-bad'}`}>{agent?.reachable ? 'reachable' : 'offline'}</span>
        </div>
        <div className="pdb-field sm-agent-picker">
          <label className="pdb-label">Agent</label>
          <select className="pdb-input" value={selectedAgentBaseUrl} onChange={(event) => onSelectAgentBaseUrl(event.target.value)} disabled={!Array.isArray(agents) || !agents.length}>
            {(Array.isArray(agents) ? agents : []).map((item) => (
              <option key={item.agent_base_url} value={item.agent_base_url}>
                {item.node_name || item.node_id || 'Agent'} - {item.agent_base_url}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="sm-meta-row">
        <span className="pdb-page-util">Services: {Array.isArray(agent?.services_hint) && agent.services_hint.length ? agent.services_hint.join(', ') : '-'}</span>
        {agent?.error ? <span className="pdb-util-warn pdb-page-util">Error: {agent.error}</span> : null}
      </div>

      <div className="sm-controls-row">
        <div className="pdb-field sm-root-field">
          <label className="pdb-label">Storage Root</label>
          {roots.length <= 1 ? (
            <div className="pdb-readonly">{selectedRoot?.path || '-'}</div>
          ) : (
            <select className="pdb-input" value={rootKey} onChange={(event) => { setRootKey(event.target.value); setPath(''); }} disabled={!roots.length || !agent?.reachable}>
              {roots.map((root) => (
                <option key={root.key} value={root.key}>{root.key} ({root.path})</option>
              ))}
            </select>
          )}
        </div>
        <button className="pdb-btn-primary pdb-btn-sm" type="button" onClick={() => setNewFolderName('')} disabled={actionBusy || !agent?.reachable}>New Folder</button>
      </div>

      {disk && (
        <div className="sm-disk-strip">
          <div className="sm-disk-item"><span>Free</span><strong>{formatBytes(disk.free_bytes)}</strong></div>
          <div className="sm-disk-item"><span>Used</span><strong>{formatBytes(disk.used_bytes)}</strong></div>
          <div className="sm-disk-item"><span>Total</span><strong>{formatBytes(disk.total_bytes)}</strong></div>
        </div>
      )}

      <div className="sm-path-row">
        <span className="pdb-page-util">Path</span>
        <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => setPath('')}>root</button>
        {crumbs.map((segment, idx) => {
          const next = crumbs.slice(0, idx + 1).join('/');
          return (
            <span key={next} className="sm-crumb-item">
              <span className="sm-crumb-sep">/</span>
              <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => setPath(next)}>{segment}</button>
            </span>
          );
        })}
      </div>

      <div className="pdb-table-wrap sm-table-wrap">
        <table className="pdb-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Size</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.path || entry.name}>
                <td className="pdb-cell-name">
                  {entry.kind === 'directory' ? (
                    <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => setPath(entry.path)}>{entry.name}</button>
                  ) : entry.name}
                </td>
                <td>{entry.kind}</td>
                <td>{entry.kind === 'file' ? formatBytes(entry.size_bytes) : '-'}</td>
                <td className="pdb-cell-actions">
                  {entry.path ? (
                    <div className="pdb-action-group">
                      {entry.kind === 'file' ? <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => downloadEntry(entry)} disabled={actionBusy}>Download</button> : null}
                      {entry.kind === 'file' && entry.editable_text ? <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => openEditor(entry)} disabled={actionBusy}>Edit</button> : null}
                      <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => queueMove(entry)} disabled={actionBusy}>Move</button>
                      <button className="pdb-btn-ghost pdb-btn-sm" type="button" onClick={() => queueRename(entry)} disabled={actionBusy}>Rename</button>
                      <button className="pdb-btn-danger pdb-btn-sm" type="button" onClick={() => deleteEntry(entry)} disabled={actionBusy}>Delete</button>
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
            {!entries.length && (
              <tr><td colSpan={4} className="pdb-cell-nil">No entries</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {error && <div className="pdb-save-error">{error}</div>}

      {moveSource ? (
        <StorageActionModal
          title="Move Entry"
          fields={[
            { key: 'source', label: 'Selected Entry', value: moveSource, readOnly: true },
            { key: 'folder', label: 'Destination Folder', value: moveTargetFolder, type: 'select', options: folderOptions, autoFocus: true },
          ]}
          submitLabel="Move"
          submitDisabled={!moveSource.trim()}
          busy={actionBusy}
          error={error}
          onChange={(key, value) => {
            if (key === 'folder') setMoveTargetFolder(value);
          }}
          onCancel={closeMoveMenu}
          onSubmit={moveEntry}
        />
      ) : null}
      {renameDraft.path ? (
        <StorageActionModal
          title="Rename Entry"
          fields={[
            { key: 'source', label: 'Selected Entry', value: renameDraft.path, readOnly: true },
            { key: 'name', label: 'New Name', value: renameDraft.value, placeholder: 'Folder or file name', autoFocus: true },
          ]}
          submitLabel="Rename"
          submitDisabled={!String(renameDraft.value || '').trim()}
          busy={actionBusy}
          error={error}
          onChange={(key, value) => {
            if (key === 'name') setRenameDraft((current) => ({ ...current, value }));
          }}
          onCancel={closeRenameMenu}
          onSubmit={renameEntry}
        />
      ) : null}
      {newFolderName !== null ? (
        <StorageActionModal
          title="New Folder"
          fields={[
            { key: 'path', label: 'Current Path', value: path || 'root', readOnly: true },
            { key: 'name', label: 'Folder Name', value: newFolderName, placeholder: 'Folder name', autoFocus: true },
          ]}
          submitLabel="Create"
          submitDisabled={!String(newFolderName || '').trim()}
          busy={actionBusy}
          error={error}
          onChange={(key, value) => {
            if (key === 'name') setNewFolderName(value);
          }}
          onCancel={closeNewFolderMenu}
          onSubmit={createFolder}
        />
      ) : null}
      {editorState ? (
        <StorageEditorModal
          title="Edit File"
          pathLabel={editorState.path}
          content={editorState.content}
          loading={editorState.loading}
          saving={editorState.saving}
          error={editorState.error}
          canFormatJson={isJsonPath(editorState.path)}
          canFormatYaml={isYamlPath(editorState.path)}
          onChange={(value) => setEditorState((current) => current ? { ...current, content: value, error: '' } : current)}
          onFormatJson={formatEditorJson}
          onCancel={requestCloseEditor}
          onSave={saveEditor}
        />
      ) : null}
    </div>
  );
}

export function StorageManagerPage({ fermenterId, fermenterName, onClose }) {
  const [storageOverview, setStorageOverview] = useState(null);
  const [storageLoading, setStorageLoading] = useState(false);
  const [storageError, setStorageError] = useState('');
  const [networkDriveError, setNetworkDriveError] = useState('');
  const [selectedAgentBaseUrl, setSelectedAgentBaseUrl] = useState('');
  const [networkDriveDraft, setNetworkDriveDraft] = useState(null);

  const refreshStorageOverview = useCallback(async () => {
    if (!fermenterId) return;
    setStorageLoading(true);
    setStorageError('');
    try {
      const payload = await fetchAgentStorageOverview(fermenterId);
      setStorageOverview(payload && typeof payload === 'object' ? payload : null);
    } catch (err) {
      setStorageError(err?.message ?? String(err));
      setStorageOverview(null);
    } finally {
      setStorageLoading(false);
    }
  }, [fermenterId]);

  useEffect(() => {
    refreshStorageOverview();
  }, [refreshStorageOverview]);

  const agents = useMemo(() => (Array.isArray(storageOverview?.agents) ? storageOverview.agents : []), [storageOverview]);

  useEffect(() => {
    if (!agents.length) {
      setSelectedAgentBaseUrl('');
      return;
    }
    setSelectedAgentBaseUrl((current) => {
      if (current && agents.some((item) => item.agent_base_url === current)) {
        return current;
      }
      return String(agents[0]?.agent_base_url || '');
    });
  }, [agents]);

  const selectedAgent = agents.find((agent) => agent.agent_base_url === selectedAgentBaseUrl) || agents[0] || null;

  function closeNetworkDriveMenu() {
    setNetworkDriveDraft(null);
    setNetworkDriveError('');
  }

  async function handleAddNetworkDrive() {
    if (!fermenterId || !networkDriveDraft) return;
    const name = String(networkDriveDraft.name || '').trim();
    const drivePath = String(networkDriveDraft.path || '').trim();
    if (!name || !drivePath) return;

    setStorageLoading(true);
    setNetworkDriveError('');
    try {
      const result = await addAgentNetworkDrive(fermenterId, {
        name,
        path: drivePath,
      });
      const failures = Array.isArray(result?.results) ? result.results.filter((item) => !item?.ok) : [];
      if (failures.length) {
        setNetworkDriveError(`Network drive added with failures on ${failures.length} agent(s).`);
      } else {
        closeNetworkDriveMenu();
      }
      await refreshStorageOverview();
    } catch (err) {
      setNetworkDriveError(err?.message ?? String(err));
    } finally {
      setStorageLoading(false);
    }
  }

  return (
    <div className="pdb-page">
      <div className="pdb-page-header">
        <div className="pdb-page-title">
          <span className="pdb-page-icon pdb-page-icon-storage">▣</span>
          <span>Storage Manager</span>
          {fermenterName && <span className="pdb-page-mode">{fermenterName}</span>}
        </div>
        <div className="pdb-page-actions">
          <button className="pdb-btn-ghost pdb-btn-sm" onClick={() => { setNetworkDriveDraft({ name: '', path: '' }); setNetworkDriveError(''); }} disabled={storageLoading}>
            Add Network Drive
          </button>
          <button className="pdb-btn-ghost pdb-btn-sm" onClick={refreshStorageOverview} disabled={storageLoading}>
            {storageLoading ? 'Refreshing…' : 'Refresh'}
          </button>
          <button className="pdb-close-btn" onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      {networkDriveDraft ? (
        <StorageActionModal
          title="Add Network Drive"
          fields={[
            { key: 'name', label: 'Drive Name', value: networkDriveDraft.name, placeholder: 'shared' },
            { key: 'path', label: 'Network Path', value: networkDriveDraft.path, placeholder: '\\\\server\\brewshare', autoFocus: true },
          ]}
          submitLabel="Add"
          submitDisabled={!String(networkDriveDraft.name || '').trim() || !String(networkDriveDraft.path || '').trim()}
          busy={storageLoading}
          error={networkDriveError}
          onChange={(key, value) => setNetworkDriveDraft((current) => ({ ...current, [key]: value }))}
          onCancel={closeNetworkDriveMenu}
          onSubmit={handleAddNetworkDrive}
        />
      ) : null}

      {storageError && <div className="pdb-page-error">Storage manager unavailable: {storageError}</div>}

      <div className="pdb-page-body">
        {storageLoading && !storageOverview ? (
          <div className="pdb-loading">Loading storage overview…</div>
        ) : selectedAgent ? (
          <div className="pdb-list-container" style={{ padding: '12px 16px 16px' }}>
            <AgentStorageCard
              key={selectedAgent.agent_base_url || `${selectedAgent.node_id}-${selectedAgent.node_name}`}
              fermenterId={fermenterId}
              agent={selectedAgent}
              agents={agents}
              selectedAgentBaseUrl={selectedAgentBaseUrl}
              onSelectAgentBaseUrl={setSelectedAgentBaseUrl}
              onRefreshOverview={refreshStorageOverview}
            />
          </div>
        ) : (
          <div className="pdb-empty">No agent storage information is available.</div>
        )}
      </div>
    </div>
  );
}
