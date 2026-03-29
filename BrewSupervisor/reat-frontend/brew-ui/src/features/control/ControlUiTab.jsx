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
  const backendReachable = controlUiSpec?.datasource_backend?.reachable !== false

  cards.sort((a, b) => {
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
      const maxByCards = Math.max(1, cards.length)
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
  }, [cards.length, selected?.id])

  const cardColumns = useMemo(() => {
    const buckets = Array.from({ length: Math.max(1, columnCount) }, () => ({
      items: [],
      weight: 0,
    }))

    for (const card of cards) {
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
  }, [cards, columnCount])

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

      {!cards.length ? (
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
                const emptyCard = !controls.length
                return (
                  <div
                    key={card.card_id || `${card.kind}-${card.title}`}
                    className={`info-card control-device-card ${emptyCard ? 'is-empty' : ''}`}
                  >
                    <div className="card-header-row">
                      <h3>{card.title || 'Device'}</h3>
                      <span className={`pill ${card.running ? 'pill-ok' : 'pill-warn'}`}>{card.running ? 'running' : 'stopped'}</span>
                    </div>
                    <div className="small-text">{card.subtitle || card.source_type || '-'}</div>

                    {!controls.length ? (
                      <p className="muted">No writable controls for this device.</p>
                    ) : (
                      <div className="control-item-stack">
                        {controls.map((control) => {
                          const target = String(control?.target || '').trim()
                          const writeKind = control?.write?.kind || ''
                          const widget = control?.widget || ''
                          const currentValue = control?.current_value
                          const draftExists = target && hasDraft(controlDrafts, target)
                          const draftValue = draftExists ? controlDrafts[target] : currentValue
                          const isWriting = controlWriteTarget === target

                          return (
                            <div key={`${control.id || target}-${target}`} className="control-item-row">
                              <div className="control-item-meta">
                                <strong>{control.label || target}</strong>
                                <div className="small-text control-item-target">{target || '-'}</div>
                                <div className="small-text">
                                  Current: {formatCurrentValue(currentValue)}
                                  {control.unit ? ` ${control.unit}` : ''}
                                </div>
                              </div>

                              <div className="control-item-inputs">
                                {(widget === 'button' || writeKind === 'pulse') ? (
                                  <button
                                    className="warning-button"
                                    disabled={!target || isWriting || controlUiLoading}
                                    onClick={() => onWrite(control, true)}
                                  >
                                    {isWriting ? 'Sending…' : (control.label || 'Pulse')}
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
                    )}
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
