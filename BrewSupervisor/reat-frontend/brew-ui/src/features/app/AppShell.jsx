import { useEffect, useRef, useState } from 'react';
import { FermenterSidebar } from '../fermenters/FermenterSidebar';
import { FermenterTabsHeader } from '../fermenters/FermenterTabsHeader';

export function AppShell({
  fermenters,
  selected,
  onSelect,
  error,
  activeTab,
  onTabChange,
  children,
}) {
  const sidebarDockRef = useRef(null);
  const [errorDismissed, setErrorDismissed] = useState(false);

  const [sidebarHidden, setSidebarHidden] = useState(() => {
    try {
      return window.localStorage.getItem('brew-ui.sidebar-hidden') === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem('brew-ui.sidebar-hidden', sidebarHidden ? '1' : '0');
    } catch {
      // Ignore storage failures and keep UI responsive.
    }
  }, [sidebarHidden]);

  useEffect(() => {
    if (sidebarHidden) return undefined;

    function handleOutsidePointerDown(event) {
      const dock = sidebarDockRef.current;
      if (!dock) return;
      if (dock.contains(event.target)) return;
      setSidebarHidden(true);
    }

    window.addEventListener('pointerdown', handleOutsidePointerDown);
    return () => {
      window.removeEventListener('pointerdown', handleOutsidePointerDown);
    };
  }, [sidebarHidden]);

  useEffect(() => {
    setErrorDismissed(false);
  }, [error]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>LabBREW</h1>
          <p>Fermenter dashboard through LabBREW</p>
        </div>
      </header>

      {error && !errorDismissed && (
        <div className="error-banner">
          <span className="error-banner-message">{error}</span>
          <button
            type="button"
            className="error-banner-close"
            aria-label="Dismiss error"
            onClick={() => setErrorDismissed(true)}
          >
            ×
          </button>
        </div>
      )}

      <div ref={sidebarDockRef} className={`sidebar-dock ${sidebarHidden ? 'is-collapsed' : ''}`}>
        <div className="sidebar-dock-panel">
          <FermenterSidebar
            fermenters={fermenters}
            selectedId={selected?.id || null}
            onSelect={onSelect}
          />
          <button
            className="sidebar-dock-toggle"
            type="button"
            onClick={() => setSidebarHidden((current) => !current)}
            aria-label={sidebarHidden ? 'Expand fermenter sidebar' : 'Collapse fermenter sidebar'}
            title={sidebarHidden ? 'Show fermenters' : 'Hide fermenters'}
          >
            <span className="sidebar-dock-toggle-menu" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
          </button>
        </div>
      </div>

      <div className="main-grid">
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
