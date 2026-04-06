import { useLayoutEffect, useMemo, useRef, useState } from 'react'

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
  controlDrafts,
  onDraftChange,
  onWrite,
  onReleaseManualControl,
}) {
  const gridRef = useRef(null)
  const [columnCount, setColumnCount] = useState(1)
  const cards = Array.isArray(controlUiSpec?.cards) ? [...controlUiSpec.cards] : []
  const visibleCards = cards.filter((card) => Array.isArray(card?.controls) && card.controls.length > 0)
  const backendReachable = controlUiSpec?.datasource_backend?.reachable !== false

  visibleCards.sort((a, b) => {
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
  }, [visibleCards, columnCount])

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
          <span>Rendered from control service spec. Writes use manual takeover.</span>
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
                return (
                  <div
                    key={card.card_id || `${card.kind}-${card.title}`}
                    className="info-card control-device-card"
                  >
                    <div className="card-header-row">
                      <h3>{card.title || 'Device'}</h3>
                      <span className={`pill ${card.running ? 'pill-ok' : 'pill-warn'}`}>{card.running ? 'running' : 'stopped'}</span>
                    </div>
                    <div className="small-text">{card.subtitle || card.source_type || '-'}</div>

                    <div className="control-item-stack">
                      {controls.map((control) => {
                        const target = String(control?.target || '').trim()
                        const writeKind = control?.write?.kind || ''
                        const widget = control?.widget || ''
                        const currentValue = control?.current_value
                        const controlLabel = friendlyControlLabel(control, target)
                        const actionLabel = friendlyActionLabel(control, target)
                        const isStackedLayout = widget === 'number_button' || widget === 'button' || writeKind === 'pulse' || widget === 'toggle' || writeKind === 'bool' || widget === 'number' || writeKind === 'number'
                        const draftExists = target && hasDraft(controlDrafts, target)
                        const draftValue = draftExists ? controlDrafts[target] : currentValue
                        const isWriting = controlWriteTarget === target

                        // number_button companion field values (hoisted to avoid IIFE inside JSX)
                        const vtTarget = widget === 'number_button' ? String(control?.value_target || '').trim() : ''
                        const vtDraftExists = vtTarget && hasDraft(controlDrafts, vtTarget)
                        const vtDraftValue = vtDraftExists ? controlDrafts[vtTarget] : control?.value_target_current_value

                        return (
                          <div key={`${control.id || target}-${target}`} className={`control-item-row${isStackedLayout ? ' control-item-row--stacked' : ''}`}>
                            <div className="control-item-meta">
                              <strong>{controlLabel}</strong>
                              <div className="small-text control-item-target">{target || '-'}</div>
                              <div className="small-text">
                                Current: {formatCurrentValue(currentValue)}
                                {control.unit ? ` ${control.unit}` : ''}
                              </div>
                            </div>

                            <div className="control-item-inputs">
                              {widget === 'number_button' ? (
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
                              ) : (widget === 'button' || writeKind === 'pulse') ? (
                                <button
                                  className="warning-button"
                                  disabled={!target || isWriting || controlUiLoading}
                                  onClick={() => onWrite(control, true)}
                                >
                                  {isWriting ? 'Sending…' : actionLabel}
                                </button>
                              ) : (widget === 'toggle' || writeKind === 'bool') ? (
                                <button
                                  className={`toggle-button ${Boolean(draftValue) ? 'is-resume' : 'is-pause'}`}
                                  disabled={!target || isWriting || controlUiLoading}
                                  onClick={() => {
                                    const nextValue = !Boolean(draftValue)
                                    onDraftChange(target, nextValue)
                                    onWrite(control, nextValue)
                                  }}
                                >
                                  {isWriting ? 'Writing…' : (Boolean(draftValue) ? 'On' : 'Off')}
                                </button>
                              ) : widget === 'number' || writeKind === 'number' ? (
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
                              ) : (
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
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
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
