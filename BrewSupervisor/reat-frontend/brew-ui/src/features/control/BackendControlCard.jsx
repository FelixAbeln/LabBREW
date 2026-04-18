function toBoolean(value) {
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true' || normalized === '1' || normalized === 'on') return true
    if (normalized === 'false' || normalized === '0' || normalized === 'off' || normalized === '') return false
  }
  return Boolean(value)
}

function hasDraft(controlDrafts, target) {
  return Object.prototype.hasOwnProperty.call(controlDrafts || {}, target)
}

function controlValue(controlDrafts, target, fallback) {
  if (!target) return fallback
  return hasDraft(controlDrafts, target) ? controlDrafts[target] : fallback
}

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

function applyOnEnter(event, { target, isWriting, controlUiLoading, onWrite, control, overrideValue }) {
  if (event.key !== 'Enter') return
  if (!target || isWriting || controlUiLoading) return
  event.preventDefault()
  onWrite(control, overrideValue)
}

function renderActionButton({ label, className, disabled, onClick }) {
  return (
    <button className={className} disabled={disabled} onClick={onClick}>
      {label}
    </button>
  )
}

function buildFallbackSections(controls) {
  const items = (Array.isArray(controls) ? controls : [])
    .filter((control) => control && control.id)
    .map((control) => ({
      kind: 'control',
      control_id: String(control.id),
      title: String(control.label || control.target || control.id),
      description: String(control.hint || '').trim() || undefined,
    }))
  return items.length ? [{ id: 'controls', title: null, items }] : []
}

function StaticAppItem({ itemSpec }) {
  const kind = String(itemSpec?.kind || '').trim().toLowerCase()
  if (kind === 'text' || kind === 'notice') {
    const text = String(itemSpec?.text || itemSpec?.description || itemSpec?.title || '').trim()
    if (!text) return null
    return <div className="small-text">{text}</div>
  }
  if (kind === 'metric' || kind === 'readonly') {
    const label = String(itemSpec?.label || itemSpec?.title || '').trim()
    const value = itemSpec?.value == null ? '-' : String(itemSpec.value)
    const unit = String(itemSpec?.unit || '').trim()
    return (
      <div className="control-item-row control-item-row--stacked">
        <div className="control-item-meta">
          <strong>{label || 'Value'}</strong>
          <div className="small-text">{value}{unit ? ` ${unit}` : ''}</div>
        </div>
      </div>
    )
  }
  return null
}

function ControlAppItem({
  control,
  itemSpec,
  controlDrafts,
  controlUiLoading,
  controlWriteTarget,
  controlWriteError,
  onDraftChange,
  onWrite,
}) {
  const target = String(control?.target || '').trim()
  const writeKind = String(control?.write?.kind || '')
  const widget = String(control?.widget || '')
  const isWriting = controlWriteTarget === target
  const draftValue = controlValue(controlDrafts, target, control?.current_value)
  const inlineError = controlWriteError?.target === target ? controlWriteError.message : ''
  const actionLabel = String(itemSpec?.action_label || (widget === 'button' || writeKind === 'pulse' ? 'Run' : 'Apply'))
  const title = String(itemSpec?.title || control?.label || target || '-').trim() || '-'
  const description = String(itemSpec?.description || control?.hint || '').trim()
  const currentOwner = String(control?.current_owner || '').trim()
  const normalizedOwner = currentOwner.toLowerCase()
  const safetyLocked = Boolean(control?.safety_locked) || normalizedOwner === 'safety'
  const isServiceOwned = Boolean(currentOwner && currentOwner !== 'operator')
  const canTakeControl = Boolean(target && widget !== 'button' && widget !== 'number_button' && writeKind !== 'pulse' && !safetyLocked)
  const requiresTakeover = isServiceOwned

  let inputs = null
  if (widget === 'number_button') {
    const valueTarget = String(control?.value_target || '').trim()
    const valueDraft = controlValue(controlDrafts, valueTarget, control?.value_target_current_value)
    inputs = (
      <>
        <input
          className="data-control"
          type="number"
          step={control?.value_write?.step ?? 'any'}
          min={control?.value_write?.min}
          max={control?.value_write?.max}
          value={String(valueDraft ?? '')}
          onChange={(event) => onDraftChange(valueTarget, event.target.value)}
          onKeyDown={(event) => applyOnEnter(event, { target, isWriting, controlUiLoading, onWrite, control })}
        />
        {renderActionButton({
          label: isWriting ? 'Sending…' : actionLabel,
          className: 'warning-button',
          disabled: !target || controlUiLoading || isWriting,
          onClick: () => onWrite(control),
        })}
      </>
    )
  } else if (widget === 'button' || writeKind === 'pulse') {
    inputs = renderActionButton({
      label: isWriting ? 'Sending…' : actionLabel,
      className: 'warning-button',
      disabled: !target || controlUiLoading || isWriting,
      onClick: () => onWrite(control, true),
    })
  } else if (widget === 'toggle' || writeKind === 'bool') {
    inputs = (
      <button
        className={`toggle-button ${toBoolean(control?.current_value) ? 'is-resume' : 'is-pause'}`}
        disabled={!target || controlUiLoading || isWriting}
        onClick={() => onWrite(control, !toBoolean(control?.current_value))}
      >
        {isWriting ? 'Writing…' : (toBoolean(control?.current_value) ? 'On' : 'Off')}
      </button>
    )
  } else if (widget === 'number' || writeKind === 'number') {
    inputs = (
      <>
        <input
          className="data-control"
          type="number"
          step={control?.write?.step ?? 'any'}
          min={control?.write?.min}
          max={control?.write?.max}
          value={draftValue ?? ''}
          onChange={(event) => onDraftChange(target, event.target.value)}
          onKeyDown={(event) => applyOnEnter(event, { target, isWriting, controlUiLoading, onWrite, control })}
        />
        {renderActionButton({
          label: isWriting ? 'Writing…' : actionLabel,
          className: 'primary-button',
          disabled: !target || controlUiLoading || isWriting,
          onClick: () => onWrite(control),
        })}
      </>
    )
  } else {
    inputs = (
      <>
        <input
          className="data-control"
          type="text"
          value={draftValue ?? ''}
          onChange={(event) => onDraftChange(target, event.target.value)}
          onKeyDown={(event) => applyOnEnter(event, { target, isWriting, controlUiLoading, onWrite, control })}
        />
        {renderActionButton({
          label: isWriting ? 'Writing…' : actionLabel,
          className: 'primary-button',
          disabled: !target || controlUiLoading || isWriting,
          onClick: () => onWrite(control),
        })}
      </>
    )
  }

  return (
    <div className={`control-item-row control-item-row--stacked${isServiceOwned ? ' control-item-row--service-owned' : ''}`}>
      <div className="control-item-meta">
        <strong>{title}</strong>
        <div className="small-text control-item-target">{target || '-'}</div>
        <div className="small-text">
          Current: {formatCurrentValue(control?.current_value ?? control?.value_target_current_value ?? '-')}
          {control?.unit ? ` ${control.unit}` : ''}
        </div>
        {description ? <div className="small-text">{description}</div> : null}
        {isServiceOwned ? (
          <div className="control-owner-banner" role="status" aria-live="polite">
            <strong>Owned: {currentOwner}</strong>
          </div>
        ) : null}
        {control?.safety_locked ? <div className="small-text warning">Safety locked</div> : null}
      </div>
      <div className="control-item-inputs">
        {!requiresTakeover ? inputs : null}
        {requiresTakeover && canTakeControl ? (
          <button
            className="warning-button control-takeover-button"
            disabled={controlUiLoading || isWriting}
            onClick={() => onWrite(control, draftValue)}
          >
            {isWriting ? 'Taking…' : 'Take control'}
          </button>
        ) : null}
        {requiresTakeover && !canTakeControl ? (
          <div className="small-text warning">{safetyLocked ? 'Safety lock active; takeover disabled.' : 'This control is owned and cannot be taken over from this widget.'}</div>
        ) : null}
        {inlineError ? <div className="small-text warning">Write failed: {inlineError}</div> : null}
      </div>
    </div>
  )
}

export function hasBackendControlCardApp(card) {
  const appSpec = card?.app || card?.card_app
  return Boolean(appSpec && appSpec.kind === 'sections' && Array.isArray(appSpec.sections))
}

export function BackendControlCard({
  card,
  controlDrafts,
  controlUiLoading,
  controlWriteTarget,
  controlWriteError,
  onDraftChange,
  onWrite,
}) {
  const appSpec = card?.app || card?.card_app || {}
  const controls = Array.isArray(card?.controls) ? card.controls : []
  const sections = Array.isArray(appSpec?.sections) && appSpec.sections.length ? appSpec.sections : buildFallbackSections(controls)
  const controlById = new Map(controls.map((control) => [String(control?.id || ''), control]))

  return (
    <div className="info-card control-device-card">
      <div className="card-header-row">
        <h3>{card?.title || 'Device'}</h3>
        <span className={`pill ${card?.running ? 'pill-ok' : 'pill-warn'}`}>{card?.running ? 'running' : 'stopped'}</span>
      </div>
      <div className="control-item-stack">
        {sections.map((section, sectionIndex) => {
          const items = Array.isArray(section?.items) ? section.items : []
          if (!items.length) return null
          return (
            <div key={String(section?.id || section?.title || sectionIndex)} className="control-device-card-backend-section">
              {section?.title && !(sections.length === 1 && String(section.title).trim() === String(card?.title || '').trim()) ? (
                <div className="card-header-row">
                  <strong>{String(section.title)}</strong>
                </div>
              ) : null}
              {section?.description ? <div className="small-text">{String(section.description)}</div> : null}
              {items.map((item, itemIndex) => {
                if (String(item?.kind || '').trim().toLowerCase() !== 'control') {
                  return <StaticAppItem key={String(item?.id || `${sectionIndex}-${itemIndex}`)} itemSpec={item} />
                }
                const control = controlById.get(String(item?.control_id || ''))
                if (!control) return null
                return (
                  <ControlAppItem
                    key={String(item?.control_id)}
                    control={control}
                    itemSpec={item}
                    controlDrafts={controlDrafts}
                    controlUiLoading={controlUiLoading}
                    controlWriteTarget={controlWriteTarget}
                    controlWriteError={controlWriteError}
                    onDraftChange={onDraftChange}
                    onWrite={onWrite}
                  />
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default BackendControlCard