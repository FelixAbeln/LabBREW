export function SystemTab({ selected, healthyServices }) {
  return (
    <div className="tab-content-grid system-layout">
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

      <div className="info-card system-services-card">
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
                  <span className="pill pill-ok">healthy</span>
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
  )
}
