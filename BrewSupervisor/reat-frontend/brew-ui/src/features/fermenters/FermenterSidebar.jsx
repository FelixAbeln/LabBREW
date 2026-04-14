function AvailabilityTag({ label, value }) {
  return (
    <span className={`pill ${value ? 'pill-ok' : 'pill-bad'}`}>
      {label}: {value ? 'yes' : 'no'}
    </span>
  )
}

function getPersistenceBadge(fermenter) {
  const summary = fermenter.summary || {}
  const backends = [
    { name: 'ParameterDB', status: summary.persistence },
    { name: 'Datasources', status: summary.datasource_persistence },
    { name: 'Rules', status: summary.rules_persistence },
  ]

  let hasUnavailable = false
  let hasUnhealthy = false
  const errors = []

  for (const backend of backends) {
    if (!backend.status || typeof backend.status !== 'object') continue

    if (backend.status.available === false) {
      hasUnavailable = true
      errors.push(`${backend.name} unavailable`)
    } else if (backend.status.healthy === false || backend.status.last_save_ok === false) {
      hasUnhealthy = true
      if (typeof backend.status.last_error === 'string') {
        errors.push(`${backend.name}: ${backend.status.last_error.trim()}`)
      }
    }
  }

  if (hasUnavailable) {
    return {
      className: 'pill-bad',
      label: 'persistence',
      title: errors.length > 0 ? errors.join('; ') : 'Persistence unavailable',
    }
  }

  if (hasUnhealthy) {
    return {
      className: 'pill-warn',
      label: 'persistence',
      title: errors.length > 0 ? errors.join('; ') : 'Persistence degraded',
    }
  }

  return null
}

export function FermenterSidebar({ fermenters, selectedId, onSelect }) {
  return (
    <aside className="panel sidebar-panel">
      <h2>Fermenters</h2>
      {fermenters.length === 0 ? (
        <p className="muted">No fermenters discovered.</p>
      ) : (
        <div className="fermenter-list">
          {fermenters.map((fermenter) => {
            const persistenceBadge = getPersistenceBadge(fermenter)
            return (
              <button
                key={fermenter.id}
                className={`fermenter-card ${selectedId === fermenter.id ? 'selected' : ''}`}
                onClick={() => onSelect(fermenter.id)}
              >
                <div className="fermenter-top">
                  <strong>{fermenter.name}</strong>
                  <div className="tag-row">
                    {persistenceBadge && (
                      <span
                        className={`pill ${persistenceBadge.className}`}
                        title={persistenceBadge.title}
                        aria-label={persistenceBadge.title}
                      >
                        {persistenceBadge.label}
                      </span>
                    )}
                    <span className={`pill ${fermenter.online ? 'pill-ok' : 'pill-bad'}`}>
                      {fermenter.online ? 'online' : 'offline'}
                    </span>
                  </div>
                </div>
                <div className="small-text">{fermenter.id}</div>
                <div className="small-text">{fermenter.address}</div>
                <div className="tag-row">
                  <AvailabilityTag
                    label="schedule"
                    value={Boolean(fermenter.summary?.schedule_available)}
                  />
                  <AvailabilityTag
                    label="control"
                    value={Boolean(fermenter.summary?.control_available)}
                  />
                  <AvailabilityTag
                    label="data"
                    value={Boolean(fermenter.summary?.data_available)}
                  />
                </div>
              </button>
            )
          })}
        </div>
      )}
    </aside>
  )
}
