import { useState } from 'react'

export function PersistenceStatusCard({ title, status }) {
  const backend = typeof status?.backend === 'string' ? status.backend : '-'
  const errorText = typeof status?.last_error === 'string' ? status.last_error : ''

  return (
    <div className="system-service-item" style={{ marginTop: 16 }}>
      <div className="system-service-header">
        <strong>{title}</strong>
        <span className={`pill ${statusPillClass(status)}`}>{statusPillLabel(status)}</span>
      </div>
      <div className="small-text">Backend: {backend}</div>
      <div className="small-text">Target: {backendTargetText(status)}</div>
      <div className="small-text">Last save: {status?.last_save_ok === false ? 'failed' : status?.last_save_ok === true ? 'ok' : '-'}</div>
      <div className="small-text">Last success: {formatTimestamp(status?.last_success_at)}</div>
      <div className="small-text">Error: {errorText || status?.reason || '-'}</div>
    </div>
  )
}

function shortSha(value) {
  if (typeof value !== 'string' || !value.trim()) return '-'
  return value.slice(0, 8)
}

function formatTimestamp(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '-'
  try {
    return new Date(value * 1000).toLocaleString()
  } catch {
    return '-'
  }
}

function statusPillClass(status) {
  if (!status) return 'pill-warn'
  if (status.available === false || status.healthy === false) return 'pill-bad'
  if (status.last_save_ok === false) return 'pill-warn'
  return 'pill-ok'
}

function statusPillLabel(status) {
  if (!status) return 'unknown'
  if (status.available === false || status.healthy === false) return 'degraded'
  if (status.last_save_ok === false) return 'save failed'
  return 'healthy'
}

function backendTargetText(status) {
  if (!status || typeof status !== 'object') return '-'
  if (status.backend === 'postgres' && status.postgres && typeof status.postgres === 'object') {
    return `${status.postgres.host || '-'}:${status.postgres.port || '-'} / ${status.postgres.database || '-'}`
  }
  if (status.backend === 'json') {
    return status.path || '-'
  }
  return '-'
}

function UpdateConfirmModal({ onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="update-confirm-title">
      <div className="modal-box">
        <h3 id="update-confirm-title" style={{ marginTop: 0 }}>Apply update?</h3>
        <p>
          Applying the update will <strong>restart all services</strong> on this node.
        </p>
        <ul style={{ marginBottom: '1rem', paddingLeft: '1.25rem' }}>
          <li>Any running schedule will be <strong>aborted</strong>.</li>
          <li>All active setpoints will be <strong>released</strong>.</li>
          <li>The node will be unreachable for a few seconds during the restart.</li>
        </ul>
        <p>Make sure the process is in a safe, manual state before continuing.</p>
        <div className="control-button-group" style={{ justifyContent: 'flex-end', marginTop: '1.25rem' }}>
          <button className="secondary-button" onClick={onCancel}>Cancel</button>
          <button className="primary-button danger-button" onClick={onConfirm}>Yes, update and restart</button>
        </div>
      </div>
    </div>
  )
}

export function SystemLauncherPanel({
  onOpenParameterDB,
  onOpenStorageManager,
  onOpenRulesStudio,
  className = 'info-card system-launcher-card',
}) {
  const actions = [
    onOpenStorageManager
      ? {
          key: 'storage',
          title: 'Storage Manager',
          description: 'Browse, create, move, and delete managed files.',
          cta: 'Open Storage',
          onClick: onOpenStorageManager,
        }
      : null,
    onOpenParameterDB
      ? {
          key: 'parameterdb',
          title: 'ParameterDB',
          description: 'View parameters, dependency graph, and source config.',
          cta: 'Open ParameterDB',
          onClick: onOpenParameterDB,
        }
      : null,
    onOpenRulesStudio
      ? {
          key: 'rules',
          title: 'Rules Studio',
          description: 'Open the dedicated automation rules workspace.',
          cta: 'Open Rules',
          onClick: onOpenRulesStudio,
        }
      : null,
  ].filter(Boolean)

  if (!actions.length) return null

  return (
    <div className={className}>
      <div className="card-header-row">
        <h3>System Tools</h3>
        <span className="tag">{actions.length} launchers</span>
      </div>
      <div className="system-launcher-grid">
        {actions.map((action) => (
          <button key={action.key} type="button" className="system-launcher-button" onClick={action.onClick}>
            <span className="system-launcher-button-title">{action.title}</span>
            <span className="system-launcher-button-desc">{action.description}</span>
            <span className="system-launcher-button-cta">{action.cta}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export function SystemTab({
  selected,
  healthyServices,
  onOpenParameterDB,
  onOpenStorageManager,
  onOpenRulesStudio,
  persistenceStatus,
  persistenceLoading,
  datasourcePersistenceStatus,
  rulesPersistenceStatus,
  repoUpdateStatus,
  repoStatusLoading,
  repoUpdateLoading,
  onRefreshRepoStatus,
  onApplyRepoUpdate,
}) {
  const [showUpdateConfirm, setShowUpdateConfirm] = useState(false)
  const updateError = typeof repoUpdateStatus?.error === 'string' ? repoUpdateStatus.error : ''
  const isOutdated = Boolean(repoUpdateStatus?.outdated)

  function handleUpdateClick() {
    setShowUpdateConfirm(true)
  }

  function handleConfirmUpdate() {
    setShowUpdateConfirm(false)
    onApplyRepoUpdate()
  }

  return (
    <>
      {showUpdateConfirm && (
        <UpdateConfirmModal
          onConfirm={handleConfirmUpdate}
          onCancel={() => setShowUpdateConfirm(false)}
        />
      )}
    <div className="tab-content-grid system-layout">
      <SystemLauncherPanel
        onOpenStorageManager={onOpenStorageManager}
        onOpenParameterDB={onOpenParameterDB}
        onOpenRulesStudio={onOpenRulesStudio}
      />

      <div className="system-left-column">
        <div className="info-card system-node-card">
          <h3>Node</h3>
          <div className="info-row">
            <span>Name</span>
            <strong>{selected.name}</strong>
          </div>
          <div className="info-row">
            <span>ID</span>
            <strong>{selected.id}</strong>
          </div>
          <div className="info-row">
            <span>Address</span>
            <strong>{selected.address}</strong>
          </div>
          <div className="info-row">
            <span>Host</span>
            <strong>{selected.host || '-'}</strong>
          </div>
          <div className="info-row info-row-block">
            <span>Agent</span>
            <strong>{selected.agent_base_url || '-'}</strong>
          </div>
        </div>

        <div className="info-card system-node-card">
          <h3>GitHub Update</h3>
          <div className="system-service-item">
            <div className="system-service-header">
              <strong>Repository status</strong>
              {updateError ? (
                <span className="pill pill-bad">check failed</span>
              ) : isOutdated ? (
                <span className="pill pill-warn">update available</span>
              ) : (
                <span className="pill pill-ok">up to date</span>
              )}
            </div>
            <div className="small-text">Local: {shortSha(repoUpdateStatus?.local_revision)}</div>
            <div className="small-text">Remote: {shortSha(repoUpdateStatus?.remote_revision)}</div>
            <div className="small-text">Branch: {repoUpdateStatus?.branch || '-'}</div>
            {updateError && <div className="small-text">Error: {updateError}</div>}
            <div className="control-button-group" style={{ marginTop: 10 }}>
              <button className="secondary-button" onClick={onRefreshRepoStatus} disabled={repoStatusLoading || repoUpdateLoading}>
                {repoStatusLoading ? 'Checking…' : 'Check updates'}
              </button>
              <button
                className="primary-button"
                onClick={handleUpdateClick}
                disabled={repoUpdateLoading || repoStatusLoading || updateError || !isOutdated}
              >
                {repoUpdateLoading ? 'Updating…' : 'Update from GitHub'}
              </button>
            </div>
          </div>
        </div>

        <div className="info-card system-node-card">
          <h3>Persistence</h3>
          <PersistenceStatusCard
            title="ParameterDB snapshot backend"
            status={persistenceStatus}
          />
          <PersistenceStatusCard
            title="Source config backend"
            status={datasourcePersistenceStatus}
          />
          <PersistenceStatusCard
            title="Control rules backend"
            status={rulesPersistenceStatus}
          />
        </div>
      </div>

      <div className="info-card system-services-card system-right-column">
        <div className="card-header-row">
          <h3>Healthy services</h3>
          <span className="tag">{healthyServices.length} active</span>
        </div>
        {!healthyServices.length ? (
          <p className="muted">No healthy services reported.</p>
        ) : (
          <div className="system-service-stack">
            {healthyServices.map(([name, service]) => (
              <div key={name} className="system-service-item">
                <div className="system-service-header">
                  <strong>{name}</strong>
                  <div className="tag-row">
                    <span className="pill pill-ok">healthy</span>
                    {service?.update?.outdated && <span className="pill pill-warn">outdated</span>}
                  </div>
                </div>
                <div className="small-text">Base URL: {service?.base_url || '-'}</div>
                <div className="small-text">Reason: {service?.reason || '-'}</div>
                <div className="small-text">
                  Provides: {Array.isArray(service?.provides) ? service.provides.join(', ') : '-'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
    </>
  )
}
