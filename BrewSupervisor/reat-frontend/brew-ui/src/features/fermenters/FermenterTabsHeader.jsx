const TABS = [
  { id: 'schedule', label: 'Schedule' },
  { id: 'data', label: 'Data' },
  { id: 'archive', label: 'Archive' },
  { id: 'rules', label: 'Rules' },
  { id: 'system', label: 'System' },
]

export function FermenterTabsHeader({ selected, activeTab, onTabChange }) {
  return (
    <div className="selected-header-row">
      <div>
        <h2>{selected ? `${selected.name} · ${selected.id}` : 'Fermenter'}</h2>
      </div>
      <div className="tab-row" role="tablist" aria-label="Fermenter views">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => onTabChange(tab.id)}
            role="tab"
            aria-selected={activeTab === tab.id}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  )
}
