import { useEffect, useMemo, useRef, useState } from 'react';
import { getWorkspaceModule, getWorkspaceModules } from './workspaceModuleCatalog';

const GRID_COLUMNS = 12;
const GRID_ROW_HEIGHT = 72;
const GRID_MAX_ROWS = 24;
const MIN_WIDGET_COLS = 3;
const MIN_WIDGET_ROWS = 1;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function resolveWidgetLayout(widget) {
  const cols = Number(widget?.cols);
  const rows = Number(widget?.rows);
  return {
    cols: Number.isFinite(cols) && cols > 0 ? clamp(Math.round(cols), MIN_WIDGET_COLS, GRID_COLUMNS) : 6,
    rows: Number.isFinite(rows) && rows > 0 ? clamp(Math.round(rows), MIN_WIDGET_ROWS, GRID_MAX_ROWS) : 1,
  };
}

function resolveWidgetPlacement(widget, index, layout) {
  const maxX = Math.max(1, GRID_COLUMNS - layout.cols + 1);
  const x = Number(widget?.x);
  const y = Number(widget?.y);
  return {
    x: Number.isFinite(x) && x > 0 ? clamp(Math.round(x), 1, maxX) : 1,
    y: Number.isFinite(y) && y > 0 ? Math.round(y) : 1 + index * Math.max(1, layout.rows),
  };
}

function moduleSearchText(moduleDef) {
  return `${moduleDef?.label || ''} ${moduleDef?.category || ''} ${moduleDef?.description || ''}`.toLowerCase();
}

function getGridMetrics(element) {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  const styles = window.getComputedStyle(element);
  const gap = Number.parseFloat(styles.gap || styles.columnGap || '12') || 12;
  const stepX = Math.max(24, (rect.width - gap * (GRID_COLUMNS - 1)) / GRID_COLUMNS) + gap;
  const stepY = GRID_ROW_HEIGHT + gap;
  return { rect, stepX, stepY };
}

function snapFromPointer(element, clientX, clientY, cols, rows) {
  const metrics = getGridMetrics(element);
  if (!metrics) return { x: 1, y: 1 };
  const relativeX = Math.max(0, clientX - metrics.rect.left);
  const relativeY = Math.max(0, clientY - metrics.rect.top);
  const x = clamp(Math.floor(relativeX / metrics.stepX) + 1, 1, Math.max(1, GRID_COLUMNS - cols + 1));
  const y = clamp(Math.floor(relativeY / metrics.stepY) + 1, 1, GRID_MAX_ROWS);
  return { x, y };
}

function widgetsOverlap(left, right) {
  return !(
    left.x + left.cols - 1 < right.x ||
    right.x + right.cols - 1 < left.x ||
    left.y + left.rows - 1 < right.y ||
    right.y + right.rows - 1 < left.y
  );
}

export function CustomLayoutTab({
  selected,
  customTab,
  editMode,
  scheduleProps,
  dataProps,
  controlProps,
  archiveProps,
  rulesProps,
  systemProps,
  onRenameTab,
  onDeleteTab,
  onAddWidget,
  onRemoveWidget,
  onMoveWidget,
  onResizeWidget,
  onCreateTab,
  onSaveToSupervisor,
  saveToSupervisorBusy,
}) {
  const widgets = Array.isArray(customTab?.widgets) ? customTab.widgets : [];
  const [drawerQuery, setDrawerQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('All');
  const [dragPreview, setDragPreview] = useState(null);
  const [editorDockOpen, setEditorDockOpen] = useState(false);
  const [editorDockPeek, setEditorDockPeek] = useState(false);
  const canvasRef = useRef(null);
  const editorDockRef = useRef(null);

  const moduleContext = {
    scheduleProps,
    dataProps,
    controlProps,
    archiveProps,
    rulesProps,
    systemProps,
    selected,
  };

  const availableModules = useMemo(
    () => getWorkspaceModules(moduleContext),
    [scheduleProps, dataProps, controlProps, archiveProps, rulesProps, systemProps, selected],
  );

  const categories = useMemo(
    () => ['All', ...new Set(availableModules.map((item) => item.category))],
    [availableModules],
  );

  const filteredModules = useMemo(() => {
    const query = drawerQuery.trim().toLowerCase();
    return availableModules.filter((moduleDef) => {
      if (activeCategory !== 'All' && moduleDef.category !== activeCategory) return false;
      if (!query) return true;
      return moduleSearchText(moduleDef).includes(query);
    });
  }, [activeCategory, availableModules, drawerQuery]);

  const groupedModules = useMemo(() => {
    const groups = new Map();
    filteredModules.forEach((moduleDef) => {
      const key = String(moduleDef?.category || 'Other');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(moduleDef);
    });
    return Array.from(groups.entries()).map(([category, items]) => ({ category, items }));
  }, [filteredModules]);

  useEffect(() => {
    if (!editMode) {
      setEditorDockOpen(false);
      setEditorDockPeek(false);
      return undefined;
    }

    setEditorDockOpen(false);
    setEditorDockPeek(true);
    const timeoutId = window.setTimeout(() => setEditorDockPeek(false), 950);
    return () => window.clearTimeout(timeoutId);
  }, [editMode, customTab?.id]);

  useEffect(() => {
    if (!editMode || !editorDockOpen) return undefined;

    function handleOutsideClick(event) {
      const dock = editorDockRef.current;
      if (!dock) return;
      if (dock.contains(event.target)) return;
      setEditorDockOpen(false);
    }

    window.addEventListener('click', handleOutsideClick);
    return () => {
      window.removeEventListener('click', handleOutsideClick);
    };
  }, [editMode, editorDockOpen]);

  function handleCanvasDrop(event) {
    if (!editMode) return;
    event.preventDefault();
    setDragPreview(null);
    let payload = null;
    try {
      payload = JSON.parse(event.dataTransfer.getData('application/json'));
    } catch {
      const fallbackId = event.dataTransfer.getData('text/plain');
      if (fallbackId) payload = { source: 'canvas', widgetId: fallbackId };
    }
    if (!payload) return;

    if (payload.source === 'drawer' && payload.moduleType) {
      const moduleDef = getWorkspaceModule(payload.moduleType, moduleContext);
      const nextCols = clamp(Number(moduleDef?.defaultCols || 6), MIN_WIDGET_COLS, GRID_COLUMNS);
      const nextRows = clamp(Number(moduleDef?.defaultRows || 1), MIN_WIDGET_ROWS, GRID_MAX_ROWS);
      const nextPosition = snapFromPointer(canvasRef.current, event.clientX, event.clientY, nextCols, nextRows);
      onAddWidget?.(customTab?.id, payload.moduleType, nextPosition, { cols: nextCols, rows: nextRows });
      return;
    }

    if (payload.source === 'canvas' && payload.widgetId) {
      const widget = widgets.find((item) => String(item?.id) === String(payload.widgetId));
      const layout = resolveWidgetLayout(widget);
      const nextPosition = snapFromPointer(canvasRef.current, event.clientX, event.clientY, layout.cols, layout.rows);
      onMoveWidget?.(customTab?.id, payload.widgetId, nextPosition);
    }
  }

  function updateDragPreview(event) {
    if (!editMode) return;
    let payload = null;
    try {
      payload = JSON.parse(event.dataTransfer.getData('application/json'));
    } catch {
      const fallbackId = event.dataTransfer.getData('text/plain');
      if (fallbackId) payload = { source: 'canvas', widgetId: fallbackId };
    }
    if (!payload) return;

    if (payload.source === 'drawer' && payload.moduleType) {
      const moduleDef = getWorkspaceModule(payload.moduleType, moduleContext);
      const cols = clamp(Number(moduleDef?.defaultCols || 6), MIN_WIDGET_COLS, GRID_COLUMNS);
      const rows = clamp(Number(moduleDef?.defaultRows || 1), MIN_WIDGET_ROWS, GRID_MAX_ROWS);
      const position = snapFromPointer(canvasRef.current, event.clientX, event.clientY, cols, rows);
      setDragPreview({ x: position.x, y: position.y, cols, rows, mode: 'add' });
      return;
    }

    if (payload.source === 'canvas' && payload.widgetId) {
      const widget = widgets.find((item) => String(item?.id) === String(payload.widgetId));
      const layout = resolveWidgetLayout(widget);
      const position = snapFromPointer(canvasRef.current, event.clientX, event.clientY, layout.cols, layout.rows);
      setDragPreview({ x: position.x, y: position.y, cols: layout.cols, rows: layout.rows, mode: 'move' });
    }
  }

  function maximizeWidgetInDirection(event, widget, edge) {
    if (!editMode || !widget) return;
    event.preventDefault();
    event.stopPropagation();

    const layout = resolveWidgetLayout(widget);
    const widgetIndex = widgets.findIndex((item) => String(item?.id) === String(widget?.id));
    const placement = resolveWidgetPlacement(widget, widgetIndex >= 0 ? widgetIndex : 0, layout);
    const occupied = widgets
      .filter((item) => String(item?.id) !== String(widget?.id))
      .map((item, index) => {
        const itemLayout = resolveWidgetLayout(item);
        const itemIndex = widgets.findIndex((entry) => String(entry?.id) === String(item?.id));
        return {
          ...resolveWidgetPlacement(item, itemIndex >= 0 ? itemIndex : index, itemLayout),
          cols: itemLayout.cols,
          rows: itemLayout.rows,
        };
      });

    const fits = (cols, rows) => {
      const candidate = { x: placement.x, y: placement.y, cols, rows };
      return !occupied.some((item) => widgetsOverlap(candidate, item));
    };

    let nextCols = layout.cols;
    let nextRows = layout.rows;

    if (edge.includes('e')) {
      for (let cols = layout.cols; cols <= Math.max(MIN_WIDGET_COLS, GRID_COLUMNS - placement.x + 1); cols += 1) {
        if (!fits(cols, nextRows)) break;
        nextCols = cols;
      }
    }

    if (edge.includes('s')) {
      for (let rows = layout.rows; rows <= GRID_MAX_ROWS; rows += 1) {
        if (!fits(nextCols, rows)) break;
        nextRows = rows;
      }
    }

    setDragPreview({ x: placement.x, y: placement.y, cols: nextCols, rows: nextRows, mode: 'resize' });
    onResizeWidget?.(customTab?.id, widget.id, { cols: nextCols, rows: nextRows });
    window.setTimeout(() => setDragPreview(null), 220);
  }

  function beginResize(event, widget, edge) {
    if (!editMode) return;
    event.preventDefault();
    event.stopPropagation();

    const widgetElement = event.currentTarget.closest('.custom-layout-card');
    if (!widgetElement) return;

    const layout = resolveWidgetLayout(widget);
    const placement = resolveWidgetPlacement(widget, 0, layout);

    const handleMove = (moveEvent) => {
      const metrics = getGridMetrics(canvasRef.current);
      if (!metrics) return;
      const next = { cols: layout.cols, rows: layout.rows };

      if (edge.includes('e')) {
        const widthPx = Math.max(metrics.stepX, moveEvent.clientX - widgetElement.getBoundingClientRect().left);
        next.cols = clamp(Math.round(widthPx / metrics.stepX), MIN_WIDGET_COLS, Math.max(MIN_WIDGET_COLS, GRID_COLUMNS - placement.x + 1));
      }

      if (edge.includes('s')) {
        const heightPx = Math.max(metrics.stepY, moveEvent.clientY - widgetElement.getBoundingClientRect().top);
        next.rows = clamp(Math.round(heightPx / metrics.stepY), MIN_WIDGET_ROWS, GRID_MAX_ROWS);
      }

      setDragPreview({ x: placement.x, y: placement.y, cols: next.cols, rows: next.rows, mode: 'resize' });
      onResizeWidget?.(customTab?.id, widget.id, next);
    };

    const handleUp = () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
      document.body.style.userSelect = '';
      setDragPreview(null);
    };

    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
  }

  return (
    <div className={`tab-content-grid custom-layout-root ${editMode ? 'is-editing' : ''}`}>
      <div className={`workspace-builder-layout ${editMode ? 'is-editing' : ''}`}>
        <div className="custom-layout-canvas">
          {!widgets.length ? (
            <div className="info-card workspace-empty-state">
              <h3>Canvas is empty</h3>
              <p className="muted">Open edit mode, search the module drawer, and drag widgets onto this canvas.</p>
            </div>
          ) : null}

          <div
            className="custom-layout-grid"
            ref={canvasRef}
            onDragOver={(event) => {
              if (!editMode) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
              updateDragPreview(event);
            }}
            onDragLeave={() => setDragPreview(null)}
            onDrop={handleCanvasDrop}
          >
            {dragPreview ? (
              <div
                className={`custom-layout-drop-preview is-${dragPreview.mode}`}
                style={{
                  gridColumn: `${dragPreview.x} / span ${dragPreview.cols}`,
                  gridRow: `${dragPreview.y} / span ${dragPreview.rows}`,
                }}
              />
            ) : null}

            {widgets.map((widget, index) => {
              const moduleDef = getWorkspaceModule(widget?.type, moduleContext);
              if (!moduleDef) return null;
              const layout = resolveWidgetLayout(widget);
              const placement = resolveWidgetPlacement(widget, index, layout);
              return (
                <section
                  key={String(widget.id)}
                  className={`custom-layout-card ${editMode ? 'is-editing' : ''}`}
                  style={{
                    gridColumn: `${placement.x} / span ${Math.min(12, layout.cols)}`,
                    gridRow: `${placement.y} / span ${Math.min(GRID_MAX_ROWS, layout.rows)}`,
                    ['--widget-rows']: String(layout.rows),
                  }}
                  draggable={Boolean(editMode)}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setData('application/json', JSON.stringify({ source: 'canvas', widgetId: String(widget.id) }));
                    event.dataTransfer.setData('text/plain', String(widget.id));
                  }}
                >
                  {editMode ? (
                    <div className="custom-layout-floating-toolbar">
                      <span className="widget-drag-pill" title={moduleDef.label}>Move</span>
                      <span className="small-text">{moduleDef.label}</span>
                      <button className="secondary-button" type="button" onClick={() => onRemoveWidget?.(customTab?.id, widget.id)}>
                        Remove
                      </button>
                    </div>
                  ) : null}

                  <div className="custom-layout-card-body custom-layout-card-body--bare">
                    <div className="workspace-module-shell">
                      {moduleDef.render(moduleContext)}
                    </div>
                  </div>

                  {editMode ? (
                    <>
                      <span
                        className="widget-resize-handle widget-resize-e"
                        title="Drag to resize width, or double-click to fill right"
                        onMouseDown={(event) => beginResize(event, widget, 'e')}
                        onDoubleClick={(event) => maximizeWidgetInDirection(event, widget, 'e')}
                      />
                      <span
                        className="widget-resize-handle widget-resize-s"
                        title="Drag to resize height, or double-click to fill down"
                        onMouseDown={(event) => beginResize(event, widget, 's')}
                        onDoubleClick={(event) => maximizeWidgetInDirection(event, widget, 's')}
                      />
                      <span
                        className="widget-resize-handle widget-resize-se"
                        title="Drag to resize, or double-click to fill remaining space"
                        onMouseDown={(event) => beginResize(event, widget, 'se')}
                        onDoubleClick={(event) => maximizeWidgetInDirection(event, widget, 'se')}
                      />
                    </>
                  ) : null}
                </section>
              );
            })}
          </div>
        </div>
      </div>

      {editMode ? (
        <div ref={editorDockRef} className={`workspace-editor-dock ${editorDockOpen ? 'is-open' : 'is-collapsed'} ${editorDockPeek ? 'is-peeking' : ''}`}>
          <div className="workspace-editor-dock-panel">
            <aside className="info-card workspace-module-drawer" data-no-sidebar-autoclose="true">
              <div className="workspace-drawer-header">
                <div className="card-header-row">
                  <h3>{customTab?.label || 'Workspace'}</h3>
                  <div className="control-button-group workspace-drawer-actions">
                    <button
                      className="secondary-button icon-only-button workspace-save-button"
                      type="button"
                      onClick={() => onSaveToSupervisor?.()}
                      title={saveToSupervisorBusy ? 'Saving workspaces to supervisor…' : 'Save workspaces to supervisor'}
                      aria-label={saveToSupervisorBusy ? 'Saving workspaces to supervisor' : 'Save workspaces to supervisor'}
                      disabled={!selected?.id || saveToSupervisorBusy}
                    >
                      {saveToSupervisorBusy ? (
                        '…'
                      ) : (
                        <svg className="workspace-save-icon" viewBox="0 0 18 18" aria-hidden="true">
                          <path className="save-body" d="M3 2.5h8.7l2.8 2.8v10.2H3z" />
                          <rect className="save-cutout" x="6" y="3.7" width="5.2" height="3.2" rx="0.4" />
                          <rect className="save-cutout" x="6" y="10.2" width="5.8" height="3" rx="0.5" />
                        </svg>
                      )}
                    </button>
                    <button className="secondary-button icon-only-button" type="button" onClick={() => onCreateTab?.()} title="Create workspace" aria-label="Create workspace">
                      +
                    </button>
                    <button
                      className="warning-button icon-only-button"
                      type="button"
                      onClick={() => onDeleteTab?.(customTab?.id)}
                      title="Delete workspace"
                      aria-label="Delete workspace"
                    >
                      🗑
                    </button>
                  </div>
                </div>
                <p className="workspace-drawer-subtitle">Filters and your widget library for this canvas.</p>
              </div>

              <div className="workspace-drawer-controls">
                <label className="form-field form-field-wide">
                  <span>Name</span>
                  <input
                    type="text"
                    value={String(customTab?.label || '')}
                    onChange={(event) => onRenameTab?.(customTab?.id, event.target.value)}
                    placeholder="My workspace"
                  />
                </label>

                <input
                  className="data-search-input"
                  type="search"
                  value={drawerQuery}
                  placeholder="Search modules…"
                  onChange={(event) => setDrawerQuery(event.target.value)}
                />

                <div className="workspace-category-strip">
                  {categories.map((category) => (
                    <button
                      key={category}
                      type="button"
                      className={activeCategory === category ? 'primary-button' : 'secondary-button'}
                      onClick={() => setActiveCategory(category)}
                    >
                      {category}
                    </button>
                  ))}
                </div>
              </div>

              <div className="workspace-library-section">
                <div className="workspace-library-header">
                  <strong>Modules</strong>
                  <span className="tag">{filteredModules.length}</span>
                </div>

                <div className="workspace-module-list-scroll">
                  {groupedModules.length ? groupedModules.map((group) => (
                    <section key={group.category} className="workspace-module-group">
                      <div className="workspace-module-group-title">{group.category}</div>
                      <div className="workspace-module-list">
                        {group.items.map((moduleDef) => (
                          <button
                            key={moduleDef.type}
                            type="button"
                            className="workspace-module-chip"
                            draggable
                            onDragStart={(event) => {
                              event.dataTransfer.effectAllowed = 'copyMove';
                              event.dataTransfer.setData('application/json', JSON.stringify({ source: 'drawer', moduleType: moduleDef.type }));
                            }}
                            onClick={() => onAddWidget?.(customTab?.id, moduleDef.type, null, { cols: moduleDef.defaultCols, rows: moduleDef.defaultRows })}
                          >
                            <strong>{moduleDef.label}</strong>
                            {moduleDef.description ? <span className="small-text">{moduleDef.description}</span> : null}
                          </button>
                        ))}
                      </div>
                    </section>
                  )) : <p className="muted">No modules match the current search.</p>}
                </div>
              </div>
            </aside>

            <button
              className="workspace-editor-toggle"
              type="button"
              onClick={() => setEditorDockOpen((current) => !current)}
              aria-label={editorDockOpen ? 'Collapse workspace editor' : 'Expand workspace editor'}
              title={editorDockOpen ? 'Hide editor' : 'Show editor'}
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
    </div>
  );
}

export default CustomLayoutTab;
