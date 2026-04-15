import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { getWorkspaceModule, getWorkspaceModules } from './workspaceModuleCatalog';
import {
  GRID_CONTRACT,
  clampInt,
  getAutoGrowMaxRowsForType,
  getGridColumnsForViewport,
  isAutoGrowEnabledInColumns,
  isAutoGrowEnabledForType,
  normalizeGridInt,
  normalizeWidgetPlacement,
  normalizeWidgetSize,
  widgetsOverlap,
} from './workspaceGridContract';

const GRID_ROW_HEIGHT = GRID_CONTRACT.cellModel.rowHeightPx;
const GRID_MAX_ROWS = GRID_CONTRACT.cellModel.maxRows;
const MIN_WIDGET_ROWS = GRID_CONTRACT.cellModel.minRows;
const DRAG_START_THRESHOLD_PX = GRID_CONTRACT.interaction.dragStartThresholdPx;

function fitLayoutToColumns(layout, columns) {
  return {
    cols: clampInt(layout?.cols, 1, columns),
    rows: clampInt(layout?.rows, MIN_WIDGET_ROWS, GRID_MAX_ROWS),
  };
}

function buildResponsiveWidgetLayout(widgets, columns, rowOverrides = {}) {
  const baseColumns = GRID_CONTRACT.cellModel.columns;
  const autoGrowEnabledForViewport = isAutoGrowEnabledInColumns(columns);
  return (Array.isArray(widgets) ? widgets : [])
    .map((widget, index) => {
      const widgetId = String(widget?.id || '');
      const widgetType = String(widget?.type || '');
      const canonicalSize = resolveWidgetLayout(widget);
      const canonicalPlacement = resolveWidgetPlacement(widget, index, canonicalSize);
      const overrideRows = Number(rowOverrides?.[widgetId]);
      const effectiveRows = Number.isFinite(overrideRows) && overrideRows > 0
        && autoGrowEnabledForViewport
        && isAutoGrowEnabledForType(widgetType)
        ? clampInt(overrideRows, MIN_WIDGET_ROWS, getAutoGrowMaxRowsForType(widgetType))
        : canonicalSize.rows;

      const projectedCols = clampInt(
        Math.round((canonicalSize.cols * columns) / baseColumns),
        1,
        columns,
      );
      const canonicalMaxX = Math.max(1, baseColumns - canonicalSize.cols + 1);
      const projectedMaxX = Math.max(1, columns - projectedCols + 1);
      const xRatio = canonicalMaxX > 1 ? (canonicalPlacement.x - 1) / (canonicalMaxX - 1) : 0;
      const projectedX = clampInt(
        Math.round(xRatio * Math.max(0, projectedMaxX - 1)) + 1,
        1,
        projectedMaxX,
      );

      return {
        widget,
        x: projectedX,
        y: canonicalPlacement.y,
        rows: effectiveRows,
        cols: projectedCols,
      };
    });
}

function resolveWidgetLayout(widget) {
  return normalizeWidgetSize(widget);
}

function resolveWidgetPlacement(widget, index, layout) {
  return normalizeWidgetPlacement(widget, index, layout);
}

function moduleSearchText(moduleDef) {
  return `${moduleDef?.label || ''} ${moduleDef?.category || ''} ${moduleDef?.description || ''}`.toLowerCase();
}

function getGridMetrics(element, columnCount) {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  const styles = window.getComputedStyle(element);
  const gap = Number.parseFloat(styles.gap || styles.columnGap || '12') || 12;
  const stepX = Math.max(24, (rect.width - gap * (columnCount - 1)) / columnCount) + gap;
  const stepY = GRID_ROW_HEIGHT + gap;
  return { rect, stepX, stepY };
}

function snapFromPointer(element, clientX, clientY, cols, rows, columnCount) {
  const metrics = getGridMetrics(element, columnCount);
  if (!metrics) return { x: 1, y: 1 };
  const relativeX = Math.max(0, clientX - metrics.rect.left);
  const relativeY = Math.max(0, clientY - metrics.rect.top);
  const x = clampInt(Math.floor(relativeX / metrics.stepX) + 1, 1, Math.max(1, columnCount - cols + 1));
  const y = clampInt(Math.floor(relativeY / metrics.stepY) + 1, 1, GRID_MAX_ROWS);
  return { x, y };
}

export function CustomLayoutTab({
  selected,
  customTab,
  editMode,
  scenarioProps,
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
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const [autoRowsById, setAutoRowsById] = useState({});
  const canvasRef = useRef(null);
  const editorDockRef = useRef(null);
  const moduleShellRefs = useRef(new Map());

  const activeColumns = useMemo(
    () => getGridColumnsForViewport(viewportWidth),
    [viewportWidth],
  );

  const moduleContext = {
    scenarioProps,
    dataProps,
    controlProps,
    archiveProps,
    rulesProps,
    systemProps,
    selected,
  };

  const availableModules = useMemo(
    () => getWorkspaceModules(moduleContext),
    [scenarioProps, dataProps, controlProps, archiveProps, rulesProps, systemProps, selected],
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

  const renderedWidgets = useMemo(
    () => buildResponsiveWidgetLayout(widgets, activeColumns, autoRowsById),
    [widgets, activeColumns, autoRowsById],
  );

  const renderedWidgetById = useMemo(() => {
    const map = new Map();
    renderedWidgets.forEach((entry) => {
      map.set(String(entry.widget?.id), entry);
    });
    return map;
  }, [renderedWidgets]);

  useEffect(() => {
    const handleResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    setAutoRowsById({});
  }, [customTab?.id]);

  useEffect(() => {
    if (!renderedWidgets.length) return undefined;

    const gridEl = canvasRef.current;
    if (!gridEl) return undefined;

    const styles = window.getComputedStyle(gridEl);
    const gap = Number.parseFloat(styles.rowGap || styles.gap || '12') || 12;
    const rowStep = GRID_ROW_HEIGHT + gap;
    const observers = [];
    const autoGrowEnabledForViewport = isAutoGrowEnabledInColumns(activeColumns);
    const minOverflowPx = clampInt(
      GRID_CONTRACT.autoGrow.minOverflowPx,
      0,
      GRID_CONTRACT.cellModel.rowHeightPx,
    );

    const allowedWidgetIds = new Set(
      renderedWidgets
        .filter((entry) => autoGrowEnabledForViewport && isAutoGrowEnabledForType(entry.widget?.type))
        .map((entry) => String(entry.widget?.id || '')),
    );

    setAutoRowsById((current) => {
      const next = { ...current };
      let changed = false;
      Object.keys(next).forEach((widgetId) => {
        if (!allowedWidgetIds.has(widgetId)) {
          delete next[widgetId];
          changed = true;
        }
      });
      return changed ? next : current;
    });

    const applyMeasuredRows = (widgetId, measuredRows, baselineRows) => {
      setAutoRowsById((current) => {
        const next = { ...current };
        if (measuredRows <= baselineRows) {
          if (!(widgetId in next)) return current;
          delete next[widgetId];
          return next;
        }
        if (next[widgetId] === measuredRows) return current;
        next[widgetId] = measuredRows;
        return next;
      });
    };

    renderedWidgets.forEach((entry) => {
      const widgetId = String(entry.widget?.id || '');
      if (!widgetId) return;
      if (!autoGrowEnabledForViewport) return;
      if (!isAutoGrowEnabledForType(entry.widget?.type)) return;
      const node = moduleShellRefs.current.get(widgetId);
      if (!node) return;

      const maxRows = getAutoGrowMaxRowsForType(entry.widget?.type);
      const baselineRows = resolveWidgetLayout(entry.widget).rows;
      const measure = () => {
        const contentHeight = Math.max(node.scrollHeight, node.offsetHeight);
        const baselineHeight = baselineRows * rowStep;
        const overflowPx = contentHeight - baselineHeight;
        if (overflowPx <= minOverflowPx) {
          applyMeasuredRows(widgetId, baselineRows, baselineRows);
          return;
        }

        const measuredRows = clampInt(Math.ceil((contentHeight + gap) / rowStep), MIN_WIDGET_ROWS, maxRows);
        applyMeasuredRows(widgetId, measuredRows, baselineRows);
      };

      measure();
      const observer = new ResizeObserver(() => measure());
      observer.observe(node);
      observers.push(observer);
    });

    return () => {
      observers.forEach((observer) => observer.disconnect());
    };
  }, [renderedWidgets, activeColumns]);

  function registerModuleShell(widgetId, node) {
    const key = String(widgetId || '');
    if (!key) return;
    if (!node) {
      moduleShellRefs.current.delete(key);
      return;
    }
    moduleShellRefs.current.set(key, node);
  }

  useLayoutEffect(() => {
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
      const nextLayout = fitLayoutToColumns(
        normalizeWidgetSize({ cols: moduleDef?.defaultCols || 6, rows: moduleDef?.defaultRows || 1 }),
        activeColumns,
      );
      const nextPosition = snapFromPointer(canvasRef.current, event.clientX, event.clientY, nextLayout.cols, nextLayout.rows, activeColumns);
      onAddWidget?.(customTab?.id, payload.moduleType, nextPosition, nextLayout);
      return;
    }

    if (payload.source === 'canvas' && payload.widgetId) {
      const rendered = renderedWidgetById.get(String(payload.widgetId));
      if (!rendered) return;
      const nextPosition = snapFromPointer(canvasRef.current, event.clientX, event.clientY, rendered.cols, rendered.rows, activeColumns);
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
      const nextLayout = fitLayoutToColumns(
        normalizeWidgetSize({ cols: moduleDef?.defaultCols || 6, rows: moduleDef?.defaultRows || 1 }),
        activeColumns,
      );
      const cols = nextLayout.cols;
      const rows = nextLayout.rows;
      const position = snapFromPointer(canvasRef.current, event.clientX, event.clientY, cols, rows, activeColumns);
      setDragPreview({ x: position.x, y: position.y, cols, rows, mode: 'add' });
      return;
    }

    if (payload.source === 'canvas' && payload.widgetId) {
      const rendered = renderedWidgetById.get(String(payload.widgetId));
      if (!rendered) return;
      const position = snapFromPointer(canvasRef.current, event.clientX, event.clientY, rendered.cols, rendered.rows, activeColumns);
      setDragPreview({ x: position.x, y: position.y, cols: rendered.cols, rows: rendered.rows, mode: 'move' });
    }
  }

  function maximizeWidgetInDirection(event, widget, edge) {
    if (!editMode || !widget) return;
    event.preventDefault();
    event.stopPropagation();

    const rendered = renderedWidgetById.get(String(widget?.id));
    if (!rendered) return;
    const layout = { cols: rendered.cols, rows: rendered.rows };
    const placement = { x: rendered.x, y: rendered.y };
    const occupied = renderedWidgets
      .filter((entry) => String(entry.widget?.id) !== String(widget?.id))
      .map((entry) => ({ x: entry.x, y: entry.y, cols: entry.cols, rows: entry.rows }));

    const fits = (cols, rows) => {
      const candidate = { x: placement.x, y: placement.y, cols, rows };
      return !occupied.some((item) => widgetsOverlap(candidate, item));
    };

    let nextCols = layout.cols;
    let nextRows = layout.rows;

    if (edge.includes('e')) {
      for (let cols = layout.cols; cols <= Math.max(1, activeColumns - placement.x + 1); cols += 1) {
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

    const rendered = renderedWidgetById.get(String(widget?.id));
    if (!rendered) return;
    const layout = { cols: rendered.cols, rows: rendered.rows };
    const placement = { x: rendered.x, y: rendered.y };

    const handleMove = (moveEvent) => {
      const metrics = getGridMetrics(canvasRef.current, activeColumns);
      if (!metrics) return;

      const travelX = Math.abs(moveEvent.clientX - event.clientX);
      const travelY = Math.abs(moveEvent.clientY - event.clientY);
      if (Math.max(travelX, travelY) < DRAG_START_THRESHOLD_PX) return;

      const next = { cols: layout.cols, rows: layout.rows };

      if (edge.includes('e')) {
        const widthPx = Math.max(metrics.stepX, moveEvent.clientX - widgetElement.getBoundingClientRect().left);
        next.cols = clampInt(Math.round(widthPx / metrics.stepX), 1, Math.max(1, activeColumns - placement.x + 1));
      }

      if (edge.includes('s')) {
        const heightPx = Math.max(metrics.stepY, moveEvent.clientY - widgetElement.getBoundingClientRect().top);
        next.rows = clampInt(Math.round(heightPx / metrics.stepY), MIN_WIDGET_ROWS, GRID_MAX_ROWS);
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
        <div className="custom-layout-canvas" style={{ '--workspace-grid-columns': String(activeColumns) }}>
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

            {renderedWidgets.map((rendered) => {
              const widget = rendered.widget;
              const moduleDef = getWorkspaceModule(widget?.type, moduleContext);
              if (!moduleDef) return null;
              const autoGrowEnabled = isAutoGrowEnabledInColumns(activeColumns) && isAutoGrowEnabledForType(widget?.type);
              const layout = { cols: rendered.cols, rows: rendered.rows };
              const placement = { x: rendered.x, y: rendered.y };
              return (
                <section
                  key={String(widget.id)}
                  className={`custom-layout-card ${editMode ? 'is-editing' : ''}`}
                  style={{
                    gridColumn: `${placement.x} / span ${Math.min(activeColumns, layout.cols)}`,
                    gridRow: `${placement.y} / span ${Math.min(GRID_MAX_ROWS, layout.rows)}`,
                    ['--widget-rows']: String(layout.rows),
                  }}
                  draggable={Boolean(editMode)}
                  tabIndex={editMode ? 0 : -1}
                  onKeyDown={(event) => {
                    if (!editMode) return;
                    const key = event.key;
                    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(key)) return;

                    const layoutForMove = resolveWidgetLayout(widget);
                    const renderedForMove = renderedWidgetById.get(String(widget?.id));
                    if (!renderedForMove) return;
                    const placementForMove = { x: renderedForMove.x, y: renderedForMove.y };
                    const boost = event.shiftKey;
                    const deltaX = boost ? GRID_CONTRACT.interaction.keyboardNudgeBoostCols : GRID_CONTRACT.interaction.keyboardNudgeCols;
                    const deltaY = boost ? GRID_CONTRACT.interaction.keyboardNudgeBoostRows : GRID_CONTRACT.interaction.keyboardNudgeRows;

                    let nextX = placementForMove.x;
                    let nextY = placementForMove.y;
                    if (key === 'ArrowLeft') nextX -= deltaX;
                    if (key === 'ArrowRight') nextX += deltaX;
                    if (key === 'ArrowUp') nextY -= deltaY;
                    if (key === 'ArrowDown') nextY += deltaY;

                    const bounded = {
                      x: clampInt(normalizeGridInt(nextX, 1), 1, Math.max(1, activeColumns - layoutForMove.cols + 1)),
                      y: clampInt(normalizeGridInt(nextY, 1), 1, GRID_MAX_ROWS),
                    };
                    onMoveWidget?.(customTab?.id, widget.id, bounded);
                    event.preventDefault();
                  }}
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

                  <div className={`custom-layout-card-body custom-layout-card-body--bare ${autoGrowEnabled ? 'is-auto-grow' : ''}`}>
                    <div className="workspace-module-shell" ref={(node) => registerModuleShell(widget.id, node)}>
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
