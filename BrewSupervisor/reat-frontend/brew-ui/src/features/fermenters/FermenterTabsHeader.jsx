export function FermenterTabsHeader({
  selected,
  activeTab,
  onTabChange,
  customTabs = [],
  layoutEditMode = false,
  onToggleLayoutEdit,
  onOpenSystemStudio,
  onOpenSystemDebug,
}) {
  const visibleTabs = customTabs.map((tab) => ({
    id: tab.id,
    label: tab.label || 'Workspace',
  }))

  return (
    <div className="selected-header-row">
      <div>
        <h2>{selected ? `${selected.name} · ${selected.id}` : 'Fermenter'}</h2>
      </div>
      <div className="tab-strip-wrap">
        <div className="tab-row" role="tablist" aria-label="Fermenter views">
          {visibleTabs.map((tab) => (
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
        <div className="control-button-group">
          <button className="secondary-button" type="button" onClick={() => onOpenSystemStudio?.()} title="Open system tools" aria-label="Open system tools">
            System
          </button>
          <button className="secondary-button" type="button" onClick={() => onOpenSystemDebug?.()} title="Open system debug" aria-label="Open system debug">
            Debug
          </button>
          <button
            className={`${layoutEditMode ? 'primary-button' : 'secondary-button'} icon-only-button`}
            type="button"
            onClick={() => onToggleLayoutEdit?.()}
            title={layoutEditMode ? 'Done editing' : 'Edit layout'}
            aria-label={layoutEditMode ? 'Done editing' : 'Edit layout'}
          >
            ✎
          </button>
        </div>
      </div>
    </div>
  )
}
