import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { FermenterSidebar } from '../fermenters/FermenterSidebar';
import { FermenterTabsHeader } from '../fermenters/FermenterTabsHeader';

const APP_LOGO_ASCII = String.raw`██╗      █████╗ ██████╗ ██████╗ ██████╗ ███████╗██╗    ██╗
██║     ██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔════╝██║    ██║
██║     ███████║██████╔╝██████╔╝██████╔╝█████╗  ██║ █╗ ██║
██║     ██╔══██║██╔══██╗██╔══██╗██╔══██╗██╔══╝  ██║███╗██║
███████╗██║  ██║██████╔╝██████╔╝██║  ██║███████╗╚███╔███╔╝
╚══════╝╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚══╝╚══╝`;

export function AppShell({
  fermenters,
  selected,
  onSelect,
  error,
  activeTab,
  onTabChange,
  customTabs,
  layoutEditMode,
  onToggleLayoutEdit,
  onOpenSystemStudio,
  onOpenSystemDebug,
  showDebugLink,
  children,
}) {
  const sidebarDockRef = useRef(null);
  const [dismissedError, setDismissedError] = useState('');
  const [sidebarPeek, setSidebarPeek] = useState(false);

  const [sidebarHidden, setSidebarHidden] = useState(() => {
    try {
      return window.localStorage.getItem('brew-ui.sidebar-hidden') === '1';
    } catch {
      return false;
    }
  });
  const showFermenterSidebar = Array.isArray(fermenters) && fermenters.length > 1;

  useEffect(() => {
    try {
      window.localStorage.setItem('brew-ui.sidebar-hidden', sidebarHidden ? '1' : '0');
    } catch {
      // Ignore storage failures and keep UI responsive.
    }
  }, [sidebarHidden]);

  useEffect(() => {
    if (!showFermenterSidebar || sidebarHidden) return undefined;

    function handleOutsideClick(event) {
      const dock = sidebarDockRef.current;
      if (!dock) return;
      const target = event.target;
      if (target && typeof target.closest === 'function') {
        if (target.closest('[data-no-sidebar-autoclose="true"]')) return;
      }
      if (dock.contains(event.target)) return;
      setSidebarHidden(true);
    }

    window.addEventListener('click', handleOutsideClick);
    return () => {
      window.removeEventListener('click', handleOutsideClick);
    };
  }, [showFermenterSidebar, sidebarHidden]);

  const visibleError = error && error !== dismissedError ? error : '';

  useLayoutEffect(() => {
    if (!showFermenterSidebar) {
      setSidebarPeek(false);
      setSidebarHidden(true);
      return undefined;
    }

    setSidebarHidden(true);
    setSidebarPeek(true);
    const timeoutId = window.setTimeout(() => setSidebarPeek(false), 950);
    return () => window.clearTimeout(timeoutId);
  }, [showFermenterSidebar]);

  useEffect(() => {
    if (!showFermenterSidebar) return;
    if (!sidebarHidden) {
      setSidebarPeek(false);
    }
  }, [showFermenterSidebar, sidebarHidden]);

  useEffect(() => {
    if (showFermenterSidebar) return;
    setSidebarHidden(true);
  }, [showFermenterSidebar]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div
          className="app-logo-block"
          role="img"
          aria-label="LabBREW logo rendered as ASCII art"
          data-logo-label="LabBREW"
        >
          <pre className="app-logo-ascii" aria-hidden="true">
            {APP_LOGO_ASCII}
          </pre>
          <span className="sr-only">LabBREW logo</span>
        </div>
      </header>

      {visibleError && (
        <div className="error-banner">
          <span className="error-banner-message">{visibleError}</span>
          <button
            type="button"
            className="error-banner-close"
            aria-label="Dismiss error"
            onClick={() => setDismissedError(visibleError)}
          >
            ×
          </button>
        </div>
      )}

      {showFermenterSidebar ? (
        <div ref={sidebarDockRef} className={`sidebar-dock ${sidebarHidden ? 'is-collapsed' : 'is-open'} ${sidebarPeek ? 'is-peeking' : ''}`}>
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
      ) : null}

      <div className="main-grid">
        <section className={`content-column ${selected ? '' : 'content-column-empty'}`.trim()}>
          {selected ? (
            <div className="panel selected-panel">
              <FermenterTabsHeader
                selected={selected}
                activeTab={activeTab}
                onTabChange={onTabChange}
                customTabs={customTabs}
                layoutEditMode={layoutEditMode}
                onToggleLayoutEdit={onToggleLayoutEdit}
                onOpenSystemStudio={onOpenSystemStudio}
                onOpenSystemDebug={onOpenSystemDebug}
                showDebugLink={showDebugLink}
              />
              {children}
            </div>
          ) : (
            children
          )}
        </section>
      </div>
    </div>
  );
}
