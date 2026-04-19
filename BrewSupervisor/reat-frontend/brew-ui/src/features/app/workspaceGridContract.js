export const GRID_CONTRACT = {
  cellModel: {
    columns: 12,
    rowHeightPx: 72,
    minCols: 3,
    minRows: 1,
    maxRows: 24,
  },
  snap: {
    axis: 'both',
    rounding: 'floor',
    searchRows: 48,
  },
  collision: {
    mode: 'prevent-overlap',
    autoPackOnDelete: true,
  },
  breakpoints: {
    desktopMinPx: 1101,
    tabletMinPx: 761,
    mobileMaxPx: 760,
    mobileColumns: 1,
    tabletColumns: 6,
    desktopColumns: 12,
  },
  interaction: {
    dragStartThresholdPx: 6,
    resizeHandles: ['e', 's', 'se'],
    keyboardNudgeCols: 1,
    keyboardNudgeRows: 1,
    keyboardNudgeBoostCols: 4,
    keyboardNudgeBoostRows: 4,
  },
  overflow: {
    mode: 'clamp',
  },
  autoGrow: {
    allowedExactTypes: [
      'data-snapshot',
      'scenario-events',
      'scenario-package',
      'schedule-events',
      'schedule-workbook',
    ],
    blockedTypePrefixes: ['control-field:', 'control-card:'],
    maxRowsByType: {
      'data-snapshot': 10,
      'scenario-events': 8,
      'scenario-package': 8,
      'schedule-events': 8,
      'schedule-workbook': 8,
    },
    minOverflowPx: 28,
    minColumnsForAutoGrow: 6,
    defaultMaxRows: 8,
  },
}

export const WORKSPACE_RESIZE_PRESETS = {
  compact: { cols: 4, rows: 1 },
  medium: { cols: 6, rows: 1 },
  wide: { cols: 12, rows: 1 },
  tall: { cols: 6, rows: 2 },
  hero: { cols: 12, rows: 2 },
}

export function getGridColumnsForViewport(viewportWidth) {
  const width = Number(viewportWidth)
  const {
    desktopColumns,
    tabletColumns,
    mobileColumns,
    desktopMinPx,
    tabletMinPx,
  } = GRID_CONTRACT.breakpoints

  if (!Number.isFinite(width) || width >= desktopMinPx) return desktopColumns
  if (width >= tabletMinPx) return tabletColumns
  return mobileColumns
}

export function isAutoGrowEnabledForType(type) {
  const rawType = String(type || '')
  if (!rawType) return false
  const { allowedExactTypes, blockedTypePrefixes } = GRID_CONTRACT.autoGrow
  if (blockedTypePrefixes.some((prefix) => rawType.startsWith(prefix))) return false
  return allowedExactTypes.includes(rawType)
}

export function getAutoGrowMaxRowsForType(type) {
  const rawType = String(type || '')
  const { maxRowsByType, defaultMaxRows } = GRID_CONTRACT.autoGrow
  return clampInt(maxRowsByType[rawType], 1, GRID_CONTRACT.cellModel.maxRows) || clampInt(defaultMaxRows, 1, GRID_CONTRACT.cellModel.maxRows)
}

export function isAutoGrowEnabledInColumns(columns) {
  const value = Number(columns)
  if (!Number.isFinite(value) || value <= 0) return false
  return value >= GRID_CONTRACT.autoGrow.minColumnsForAutoGrow
}

export function clampInt(value, min, max) {
  const numeric = Number(value)
  const rounded = Number.isFinite(numeric) ? Math.round(numeric) : min
  return Math.min(max, Math.max(min, rounded))
}

export function normalizeGridInt(value, fallback) {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? Math.round(numeric) : fallback
}

export function normalizeWidgetSize(layout, fallback = { cols: 6, rows: 1 }) {
  const { columns, minCols, minRows, maxRows } = GRID_CONTRACT.cellModel
  return {
    cols: clampInt(normalizeGridInt(layout?.cols, fallback.cols), minCols, columns),
    rows: clampInt(normalizeGridInt(layout?.rows, fallback.rows), minRows, maxRows),
  }
}

export function normalizeWidgetPlacement(widget, index, layout) {
  const { columns, maxRows } = GRID_CONTRACT.cellModel
  const maxX = Math.max(1, columns - layout.cols + 1)
  return {
    x: clampInt(normalizeGridInt(widget?.x, 1), 1, maxX),
    y: clampInt(
      normalizeGridInt(widget?.y, 1 + index * Math.max(1, layout.rows)),
      1,
      maxRows,
    ),
  }
}

export function widgetsOverlap(left, right) {
  return !(
    left.x + left.cols - 1 < right.x ||
    right.x + right.cols - 1 < left.x ||
    left.y + left.rows - 1 < right.y ||
    right.y + right.rows - 1 < left.y
  )
}

export function normalizePlacedWidgets(widgets) {
  return (Array.isArray(widgets) ? widgets : []).map((widget, index) => {
    const size = normalizeWidgetSize(widget)
    const placement = normalizeWidgetPlacement(widget, index, size)
    return {
      ...placement,
      cols: size.cols,
      rows: size.rows,
    }
  })
}

export function findNextWidgetPosition(widgets, layout) {
  const { columns } = GRID_CONTRACT.cellModel
  const { searchRows } = GRID_CONTRACT.snap
  const placed = normalizePlacedWidgets(widgets)

  for (let y = 1; y <= searchRows; y += 1) {
    for (let x = 1; x <= Math.max(1, columns - layout.cols + 1); x += 1) {
      const candidate = { x, y, cols: layout.cols, rows: layout.rows }
      if (!placed.some((widget) => widgetsOverlap(candidate, widget))) {
        return { x, y }
      }
    }
  }

  const maxRow = placed.reduce((max, widget) => Math.max(max, widget.y + widget.rows), 1)
  return { x: 1, y: maxRow }
}

function getAutoSizeCandidates(type, layout) {
  const rawType = String(type || '')
  const preferred = []
  const add = (cols, rows) => {
    const next = normalizeWidgetSize({ cols, rows }, layout)
    if (!preferred.some((item) => item.cols === next.cols && item.rows === next.rows)) {
      preferred.push(next)
    }
  }

  if (rawType.endsWith('-full') || rawType === 'data-snapshot' || rawType === 'archive-files' || rawType === 'scenario-events' || rawType === 'schedule-events') {
    add(12, Math.max(3, layout.rows))
    add(9, Math.max(3, layout.rows))
  } else if (rawType === 'data-recording' || rawType === 'system-actions' || rawType === 'scenario-controls' || rawType === 'schedule-controls') {
    add(8, 1)
    add(6, 1)
    add(12, 1)
  } else if (rawType === 'scenario-package' || rawType === 'schedule-workbook' || rawType === 'system-persistence' || rawType === 'system-services') {
    add(8, 2)
    add(6, 2)
  } else if (rawType === 'scenario-summary' || rawType === 'schedule-summary' || rawType === 'data-loadstep' || rawType === 'archive-summary' || rawType === 'system-node') {
    add(4, 1)
    add(3, 1)
    add(6, 1)
  } else if (rawType.startsWith('control-card:')) {
    add(layout.cols >= 8 ? 8 : 6, Math.max(2, layout.rows))
    add(12, Math.max(2, layout.rows))
  } else if (rawType.startsWith('control-field:')) {
    add(layout.cols >= 6 ? 6 : 4, 1)
    add(4, 1)
  }

  add(layout.cols, layout.rows)
  return preferred
}

export function resolveAutoPlacedWidget(
  widgets,
  type,
  {
    preferredPosition = null,
    layoutOverride = null,
    getDefaultLayout,
  } = {},
) {
  const fallbackLayout =
    typeof getDefaultLayout === 'function' ? getDefaultLayout(type) : { cols: 6, rows: 1 }
  const desiredLayout = normalizeWidgetSize(layoutOverride, fallbackLayout)
  const placed = normalizePlacedWidgets(widgets)
  const sizeCandidates = getAutoSizeCandidates(type, desiredLayout)

  if (preferredPosition && typeof preferredPosition === 'object') {
    for (const candidate of sizeCandidates) {
      const positioned = {
        ...normalizeWidgetPlacement(preferredPosition, 0, candidate),
        cols: candidate.cols,
        rows: candidate.rows,
      }
      if (!placed.some((widget) => widgetsOverlap(positioned, widget))) {
        return positioned
      }
    }
  }

  for (const candidate of sizeCandidates) {
    const nextPosition = findNextWidgetPosition(widgets, candidate)
    const positioned = { ...nextPosition, cols: candidate.cols, rows: candidate.rows }
    if (!placed.some((widget) => widgetsOverlap(positioned, widget))) {
      return positioned
    }
  }

  return {
    x: 1,
    y: 1,
    cols: desiredLayout.cols,
    rows: desiredLayout.rows,
  }
}

export function autoPackWidgets(widgets) {
  if (!Array.isArray(widgets)) return []
  const packed = []

  for (const widget of widgets) {
    const size = normalizeWidgetSize(widget)
    const nextPosition = findNextWidgetPosition(packed, size)
    packed.push({
      ...widget,
      x: nextPosition.x,
      y: nextPosition.y,
      cols: size.cols,
      rows: size.rows,
    })
  }

  return packed
}
