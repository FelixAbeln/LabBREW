import { useState } from 'react'

function shortSha(value) {
  if (typeof value !== 'string' || !value.trim()) return '-'
  return value.slice(0, 8)
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

export function SystemTab({
  selected,
  healthyServices,
  onOpenParameterDB,
  onOpenStorageManager,
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
      {(onOpenParameterDB || onOpenStorageManager) && (
        <>
        {onOpenStorageManager && (
          <div className="control-bar pdb-open-btn-card pdb-open-btn-sticky">
            <div className="control-bar-copy">
              <strong>Storage Manager</strong>
              <span>Open the cross-agent storage manager to browse, create, move and delete managed files.</span>
            </div>
            <div className="control-button-group">
              <button className="primary-button" onClick={onOpenStorageManager}>Storage</button>
            </div>
          </div>
        )}
        {onOpenParameterDB && (
        <div className="control-bar pdb-open-btn-card pdb-open-btn-sticky">
          <div className="control-bar-copy">
            <strong>ParameterDB</strong>
            <span>View and manage the local ParameterDB - parameters, dependencies graph and data sources.</span>
          </div>
          <div className="control-button-group">
            <button className="primary-button" onClick={onOpenParameterDB}>ParameterDB</button>
          </div>
        </div>
        )}
        </>
      )}

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
