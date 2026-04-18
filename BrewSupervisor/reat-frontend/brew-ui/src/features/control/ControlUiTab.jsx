import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import BackendControlCard, { hasBackendControlCardApp } from './BackendControlCard.jsx'

function formatCurrentValue(value) {
  if (value === undefined) return '-'
  if (value === null) return 'null'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

function hasDraft(drafts, target) {
  return Object.prototype.hasOwnProperty.call(drafts, target)
}

function toBoolean(value) {
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true' || normalized === '1' || normalized === 'on') return true
    if (normalized === 'false' || normalized === '0' || normalized === 'off' || normalized === '') return false
  }
  return Boolean(value)
}

function normalizeForCompare(value, valueType) {
  if (valueType === 'bool') return toBoolean(value)
  if (valueType === 'number') {
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : null
  }
  return value
}

function differsFromExpected(actual, expected, valueType) {
  const left = normalizeForCompare(actual, valueType)
  const right = normalizeForCompare(expected, valueType)
  if (valueType === 'number') {
    if (typeof left !== 'number' || typeof right !== 'number') return true
    return Math.abs(left - right) >= 1e-9
  }
  return left !== right
}

function nodeFromTarget(target, kind) {
  if (!target) return null
  const match = String(target).match(new RegExp(`\\.${kind}\\.(\\d+)\\.`))
  if (!match) return null
  return Number.parseInt(match[1], 10)
}

function friendlyControlLabel(control, target) {
  const explicit = String(control?.label || '').trim()
  if (explicit && explicit !== target) return explicit

  const densityNode = nodeFromTarget(target, 'density')
  if (densityNode !== null && target.endsWith('.calibrate')) return `Density Calibration Node ${densityNode}`

  const pressureNode = nodeFromTarget(target, 'pressure')
  if (pressureNode !== null && target.endsWith('.calibrate')) return `Pressure Zero Node ${pressureNode}`

  const agitatorNode = nodeFromTarget(target, 'agitator')
  if (agitatorNode !== null && target.endsWith('.set_pwm')) return `Agitator PWM Node ${agitatorNode}`

  const parts = String(target || '').split('.').filter(Boolean)
  if (!parts.length) return '-'
  const tail = parts.slice(-2).join(' ')
  return tail.replace(/_/g, ' ')
}

function friendlyActionLabel(control, target) {
  const explicit = String(control?.label || '').trim()
  const writeKind = String(control?.write?.kind || '')
  const widget = String(control?.widget || '')

  if (explicit && explicit !== target) {
    if (widget === 'number_button') return explicit
    if (widget === 'button' || writeKind === 'pulse') return explicit
  }

  const densityNode = nodeFromTarget(target, 'density')
  if (densityNode !== null && target.endsWith('.calibrate')) return `Calibrate Density ${densityNode}`

  const pressureNode = nodeFromTarget(target, 'pressure')
  if (pressureNode !== null && target.endsWith('.calibrate')) return `Zero Pressure ${pressureNode}`

  if (widget === 'toggle' || writeKind === 'bool') return 'Toggle'
  if (widget === 'button' || writeKind === 'pulse') return 'Run'
  return 'Apply'
}

export function ControlUiTab({
  selected,
  controlUiSpec,
  controlUiLoading,
  controlWriteTarget,
  controlWriteError,
  pendingControlWrites,
  controlDrafts,
  layoutEditMode,
  controlCardOrder,
  onDraftChange,
  onWrite,
  onReorderCard,
  onReleaseManualControl,
}) {
  const gridRef = useRef(null)
  const [columnCount, setColumnCount] = useState(1)
  const [dragCardId, setDragCardId] = useState('')
  const cards = Array.isArray(controlUiSpec?.cards) ? [...controlUiSpec.cards] : []
  const visibleCards = cards.filter((card) => Array.isArray(card?.controls) && card.controls.length > 0)
  const backendReachable = controlUiSpec?.datasource_backend?.reachable !== false

  visibleCards.sort((a, b) => {
    const aId = String(a?.card_id || `${a?.kind}-${a?.title}`)
    const bId = String(b?.card_id || `${b?.kind}-${b?.title}`)
    const aOrder = Array.isArray(controlCardOrder) ? controlCardOrder.indexOf(aId) : -1
    const bOrder = Array.isArray(controlCardOrder) ? controlCardOrder.indexOf(bId) : -1
    if (aOrder >= 0 || bOrder >= 0) {
      if (aOrder < 0) return 1
      if (bOrder < 0) return -1
      if (aOrder !== bOrder) return aOrder - bOrder
    }
    const aCount = Array.isArray(a?.controls) ? a.controls.length : 0
    const bCount = Array.isArray(b?.controls) ? b.controls.length : 0
    if (bCount !== aCount) return bCount - aCount
    return String(a?.title || '').localeCompare(String(b?.title || ''))
  })

  useLayoutEffect(() => {
    const element = gridRef.current
    if (!element) return

    const minCardWidth = 360
    const gap = 12

    const updateColumns = () => {
      // Measure against the parent container to avoid feedback loops when the grid is temporarily oversized.
      const width = element.parentElement?.clientWidth || element.clientWidth || 0
      const maxByCards = Math.max(1, visibleCards.length)
      const next = Math.min(maxByCards, Math.max(1, Math.floor((width + gap) / (minCardWidth + gap))))
      setColumnCount(next)
    }

    updateColumns()
    const rafId = window.requestAnimationFrame(updateColumns)
    const observer = new ResizeObserver(() => updateColumns())
    if (element.parentElement) {
      observer.observe(element.parentElement)
    }
    observer.observe(element)

    return () => {
      window.cancelAnimationFrame(rafId)
      observer.disconnect()
    }
  }, [visibleCards.length, selected?.id])

  const cardColumns = useMemo(() => {
    if (layoutEditMode) return [visibleCards]

    const buckets = Array.from({ length: Math.max(1, columnCount) }, () => ({
      items: [],
      weight: 0,
    }))

    for (const card of visibleCards) {
      const controls = Array.isArray(card?.controls) ? card.controls : []
      const weight = Math.max(1, controls.length)
      let targetIndex = 0
      for (let index = 1; index < buckets.length; index += 1) {
        if (buckets[index].weight < buckets[targetIndex].weight) {
          targetIndex = index
        }
      }
      buckets[targetIndex].items.push(card)
      buckets[targetIndex].weight += weight
    }

    return buckets.map((bucket) => bucket.items)
  }, [visibleCards, columnCount, layoutEditMode])

  const applyOnEnter = (event, control, target, isWriting) => {
    if (event.key !== 'Enter') return
    if (!target || isWriting || controlUiLoading) return
    event.preventDefault()
    onWrite(control)
  }

  return (
    <div className="tab-content-grid control-ui-layout">
      <div className="control-bar">
        <div className="control-bar-copy">
          <strong>Manual Device Controls</strong>
          {!layoutEditMode ? <span>Rendered from control service spec. Writes use manual takeover.</span> : null}
        </div>
        <div className="control-button-group">
          <button className="warning-button" disabled={!selected || controlUiLoading} onClick={() => onReleaseManualControl?.()}>
            Release Manual Control
          </button>
        </div>
      </div>

      {!backendReachable && (
        <div className="info-card">
          <p className="warning">Datasource backend is unreachable; showing stale/partial control data.</p>
          <div className="small-text">{String(controlUiSpec?.datasource_backend?.error || 'Unknown error')}</div>
        </div>
      )}

      {!visibleCards.length ? (
        <div className="info-card">
          <h3>Control Cards</h3>
          <p className="muted">No control cards available for this fermenter yet.</p>
        </div>
      ) : (
        <div
          className="control-card-grid"
          ref={gridRef}
          style={{ '--control-columns': columnCount }}
        >
          {cardColumns.map((columnCards, columnIndex) => (
            <div className="control-card-column" key={`control-column-${columnIndex}`}>
              {columnCards.map((card) => {
                const controls = Array.isArray(card?.controls) ? card.controls : []
                const cardKey = String(card.card_id || `${card.kind}-${card.title}`)
                const cardBody = hasBackendControlCardApp(card) ? (
                  <BackendControlCard
                    key={cardKey}
                    card={card}
                    controlUiLoading={controlUiLoading}
                    controlWriteTarget={controlWriteTarget}
                    controlWriteError={controlWriteError}
                    controlDrafts={controlDrafts}
                    onDraftChange={onDraftChange}
                    onWrite={onWrite}
                  />
                ) : (
                  <div
                    key={cardKey}
                    className="info-card control-device-card"
                  >
                    <div className="card-header-row">
                      <h3>{card.title || 'Device'}</h3>
                      <span className={`pill ${card.running ? 'pill-ok' : 'pill-warn'}`}>{card.running ? 'running' : 'stopped'}</span>
                    </div>
                    <div className="control-item-stack">
                      {controls.map((control) => {
                        const target = String(control?.target || '').trim()
                        const writeKind = control?.write?.kind || ''
                        const widget = control?.widget || ''
                        const currentValue = control?.current_value
                        const currentOwner = String(control?.current_owner || '').trim()
                        const isSafetyOwned = currentOwner === 'safety'
                        const isSafetyLocked = Boolean(control?.safety_locked)
                        const isSafetyControlled = isSafetyOwned || isSafetyLocked
                        const isServiceOwned = Boolean(currentOwner && currentOwner !== 'operator')
                        const canTakeControl = Boolean(
                          target
                          && widget !== 'button'
                          && widget !== 'number_button'
                          && writeKind !== 'pulse'
                          && !isSafetyControlled
                        )
                        const requiresTakeover = isServiceOwned && !isSafetyControlled
                        const controlLabel = friendlyControlLabel(control, target)
                        const actionLabel = friendlyActionLabel(control, target)
                        const isStackedLayout = widget === 'number_button' || widget === 'button' || writeKind === 'pulse' || widget === 'toggle' || writeKind === 'bool' || widget === 'number' || writeKind === 'number'
                        const draftExists = target && hasDraft(controlDrafts, target)
                        const draftValue = draftExists ? controlDrafts[target] : currentValue
                        const toggleValue = toBoolean(currentValue)
                        const isWriting = controlWriteTarget === target
                        const inlineWriteError = controlWriteError?.target === target ? controlWriteError.message : ''
                        const pendingWrite = pendingControlWrites?.[target]
                        const now = Date.now()
                        const inlineOverwriteNotice = pendingWrite
                          && now >= pendingWrite.observeAfter
                          && differsFromExpected(currentValue, pendingWrite.expected, pendingWrite.valueType)
                          ? `${pendingWrite.label} was overwritten by backend value ${formatCurrentValue(currentValue)}`
                          : ''

                        // number_button companion field values (hoisted to avoid IIFE inside JSX)
                        const vtTarget = widget === 'number_button' ? String(control?.value_target || '').trim() : ''
                        const vtDraftExists = vtTarget && hasDraft(controlDrafts, vtTarget)
                        const vtDraftValue = vtDraftExists ? controlDrafts[vtTarget] : control?.value_target_current_value

                        return (
                          <div key={`${control.id || target}-${target}`} className={`control-item-row${isStackedLayout ? ' control-item-row--stacked' : ''}${isServiceOwned ? ' control-item-row--service-owned' : ''}`}>
                            <div className="control-item-meta">
                              <strong>{controlLabel}</strong>
                              <div className="small-text control-item-target">{target || '-'}</div>
                              <div className="small-text">
                                Current: {formatCurrentValue(currentValue)}
                                {control.unit ? ` ${control.unit}` : ''}
                              </div>
                              {isServiceOwned ? (
                                <div className="control-owner-banner" role="status" aria-live="polite">
                                  <strong>Owned: {currentOwner}</strong>
                                </div>
                              ) : null}
                            </div>

                            <div className="control-item-inputs">
                              {!requiresTakeover && (widget === 'number_button') ? (
                                <>
                                  <input
                                    className="data-control"
                                    type="number"
                                    step={control?.value_write?.step ?? 'any'}
                                    min={control?.value_write?.min}
                                    max={control?.value_write?.max}
                                    value={String(vtDraftValue ?? '')}
                                    placeholder={control.unit || 'value'}
                                    onChange={(event) => onDraftChange(vtTarget, event.target.value)}
                                  />
                                  <button
                                    className="warning-button"
                                    disabled={!target || isWriting || controlUiLoading}
                                    onClick={() => onWrite(control)}
                                  >
                                    {isWriting ? 'Sending…' : actionLabel}
                                  </button>
                                </>
                              ) : !requiresTakeover && (widget === 'button' || writeKind === 'pulse') ? (
                                <button
                                  className="warning-button"
                                  disabled={!target || isWriting || controlUiLoading}
                                  onClick={() => onWrite(control, true)}
                                >
                                  {isWriting ? 'Sending…' : actionLabel}
                                </button>
                              ) : !requiresTakeover && (widget === 'toggle' || writeKind === 'bool') ? (
                                <button
                                  className={`toggle-button ${toggleValue ? 'is-resume' : 'is-pause'}`}
                                  disabled={!target || isWriting || controlUiLoading}
                                  onClick={() => {
                                    const nextValue = !toggleValue
                                    onWrite(control, nextValue)
                                  }}
                                >
                                  {isWriting ? 'Writing…' : (toggleValue ? 'On' : 'Off')}
                                </button>
                              ) : !requiresTakeover && (widget === 'number' || writeKind === 'number') ? (
                                <>
                                  <input
                                    className="data-control"
                                    type="number"
                                    step={control?.write?.step ?? 'any'}
                                    min={control?.write?.min}
                                    max={control?.write?.max}
                                    value={draftValue ?? ''}
                                    onChange={(event) => onDraftChange(target, event.target.value)}
                                    onKeyDown={(event) => applyOnEnter(event, control, target, isWriting)}
                                  />
                                  <button
                                    className="primary-button"
                                    disabled={!target || isWriting || controlUiLoading}
                                    onClick={() => onWrite(control)}
                                  >
                                    {isWriting ? 'Writing…' : 'Apply'}
                                  </button>
                                </>
                              ) : !requiresTakeover ? (
                                <>
                                  <input
                                    className="data-control"
                                    type="text"
                                    value={draftValue ?? ''}
                                    onChange={(event) => onDraftChange(target, event.target.value)}
                                    onKeyDown={(event) => applyOnEnter(event, control, target, isWriting)}
                                  />
                                  <button
                                    className="primary-button"
                                    disabled={!target || isWriting || controlUiLoading}
                                    onClick={() => onWrite(control)}
                                  >
                                    {isWriting ? 'Writing…' : 'Apply'}
                                  </button>
                                </>
                              ) : null}
                              {requiresTakeover && canTakeControl ? (
                                <button
                                  className="warning-button control-takeover-button"
                                  disabled={!target || isWriting || controlUiLoading}
                                  onClick={() => onWrite(control, draftValue)}
                                >
                                  {isWriting ? 'Taking…' : 'Take control'}
                                </button>
                              ) : null}
                              {requiresTakeover && !canTakeControl ? (
                                <div className="small-text warning">This control is owned and cannot be taken over from this widget.</div>
                              ) : null}
                              {inlineOverwriteNotice ? (
                                <div className="small-text control-inline-notice">
                                  <span
                                    className="control-inline-notice-icon"
                                    title="Backend/state machine overrode manual write"
                                    aria-label="Backend/state machine overrode manual write"
                                  >
                                    !
                                  </span>
                                  <span>{inlineOverwriteNotice}</span>
                                </div>
                              ) : null}
                              {inlineWriteError ? <div className="small-text warning">Write failed: {inlineWriteError}</div> : null}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )

                return (
                  <div
                    key={cardKey}
                    className={`layout-draggable-card ${layoutEditMode ? 'is-editable' : ''} ${dragCardId === cardKey ? 'is-dragging' : ''}`}
                    draggable={Boolean(layoutEditMode)}
                    onDragStart={(event) => {
                      if (!layoutEditMode) return
                      setDragCardId(cardKey)
                      event.dataTransfer.effectAllowed = 'move'
                      event.dataTransfer.setData('text/plain', cardKey)
                    }}
                    onDragOver={(event) => {
                      if (!layoutEditMode) return
                      event.preventDefault()
                      event.dataTransfer.dropEffect = 'move'
                    }}
                    onDrop={(event) => {
                      if (!layoutEditMode) return
                      event.preventDefault()
                      const draggedId = event.dataTransfer.getData('text/plain')
                      setDragCardId('')
                      onReorderCard?.(draggedId, cardKey)
                    }}
                    onDragEnd={() => setDragCardId('')}
                  >
                    {cardBody}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
