function AvailabilityTag({ label, value }) {
  return (
    <span className={`pill ${value ? 'pill-ok' : 'pill-bad'}`}>
      {label}: {value ? 'yes' : 'no'}
    </span>
  )
}

export function FermenterSidebar({ fermenters, selectedId, onSelect }) {
  return (
    <aside className="panel">
      <h2>Fermenters</h2>
      {fermenters.length === 0 ? (
        <p className="muted">No fermenters discovered.</p>
      ) : (
        <div className="fermenter-list">
          {fermenters.map((fermenter) => (
            <button
              key={fermenter.id}
              className={`fermenter-card ${selectedId === fermenter.id ? 'selected' : ''}`}
              onClick={() => onSelect(fermenter.id)}
            >
              <div className="fermenter-top">
                <strong>{fermenter.name}</strong>
                <span className={`pill ${fermenter.online ? 'pill-ok' : 'pill-bad'}`}>
                  {fermenter.online ? 'online' : 'offline'}
                </span>
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
          ))}
        </div>
      )}
    </aside>
  )
}
