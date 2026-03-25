import { FermenterSidebar } from '../fermenters/FermenterSidebar';
import { FermenterTabsHeader } from '../fermenters/FermenterTabsHeader';

export function AppShell({
  fermenters,
  selected,
  onSelect,
  onRefresh,
  error,
  activeTab,
  onTabChange,
  children,
}) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>LabBREW</h1>
          <p>Fermenter dashboard through LabBREW</p>
        </div>
        <button className="primary-button" onClick={onRefresh}>
          Refresh
        </button>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="main-grid">
        <FermenterSidebar
          fermenters={fermenters}
          selectedId={selected?.id || null}
          onSelect={onSelect}
        />

        <section className="content-column">
          <div className="panel selected-panel">
            <FermenterTabsHeader
              selected={selected}
              activeTab={activeTab}
              onTabChange={onTabChange}
            />
            {children}
          </div>
        </section>
      </div>
    </div>
  );
}
