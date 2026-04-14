import { buildRuleEditorApp } from './ruleEditorSchema'

function getRuleFieldValue(ruleForm, key) {
  if (String(key).startsWith('operatorParams.')) {
    const paramKey = String(key).slice('operatorParams.'.length)
    return ruleForm?.operatorParams?.[paramKey] ?? ''
  }
  return ruleForm?.[key] ?? ''
}

function setRuleFieldValue(field, rawValue, updateRuleForm, updateRuleParam) {
  const key = String(field?.key || '')
  if (!key) return
  if (key === 'operator') {
    updateRuleForm({ operator: rawValue, operatorParams: {} })
    return
  }
  if (key.startsWith('operatorParams.')) {
    updateRuleParam(key.slice('operatorParams.'.length), rawValue)
    return
  }
  updateRuleForm({ [key]: rawValue })
}

function RuleFieldItem({ field, ruleForm, updateRuleForm, updateRuleParam }) {
  const value = getRuleFieldValue(ruleForm, field?.key)
  const fieldType = String(field?.type || 'string')

  if (fieldType === 'bool') {
    return (
      <label className="form-field checkbox-field">
        <span>{field.label}</span>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => setRuleFieldValue(field, event.target.checked, updateRuleForm, updateRuleParam)}
        />
      </label>
    )
  }

  let input = null
  if (fieldType === 'enum') {
    const options = Array.isArray(field?.options) ? field.options : []
    input = (
      <select
        value={String(value ?? '')}
        onChange={(event) => setRuleFieldValue(field, event.target.value, updateRuleForm, updateRuleParam)}
      >
        {options.map((option) => {
          const optionValue = typeof option === 'object' ? option.value : option
          const optionLabel = typeof option === 'object' ? option.label : option
          return <option key={String(optionValue)} value={String(optionValue)}>{String(optionLabel)}</option>
        })}
      </select>
    )
  } else {
    input = (
      <input
        type={fieldType === 'float' || fieldType === 'number' ? 'number' : 'text'}
        step={field?.step ?? (fieldType === 'float' || fieldType === 'number' ? 'any' : undefined)}
        list={field?.list || undefined}
        value={String(value ?? '')}
        onChange={(event) => setRuleFieldValue(field, event.target.value, updateRuleForm, updateRuleParam)}
        placeholder={field?.placeholder || ''}
      />
    )
  }

  return (
    <label className={`form-field ${field?.wide ? 'form-field-wide' : ''}`}>
      <span>{field.label}</span>
      {input}
      {field?.help ? <small className="muted">{field.help}</small> : null}
    </label>
  )
}

function RuleActionList({ ruleForm, addRuleAction, removeRuleAction, updateRuleAction }) {
  return (
    <div className="rule-action-stack">
      {(ruleForm.actions || []).map((action, index) => (
        <div key={action.id} className="rule-action-card">
          <div className="card-header-row rule-action-card-header">
            <strong>Action {index + 1}</strong>
            <button
              className="secondary-button"
              type="button"
              onClick={() => removeRuleAction(action.id)}
              disabled={(ruleForm.actions || []).length === 1}
            >
              Remove
            </button>
          </div>
          <div className="rules-form-grid">
            <label className="form-field">
              <span>Type</span>
              <select value={action.type} onChange={(event) => updateRuleAction(action.id, { type: event.target.value })}>
                <option value="takeover">takeover</option>
                <option value="set">set</option>
                <option value="ramp">ramp</option>
              </select>
            </label>
            <label className="form-field form-field-wide">
              <span>Targets</span>
              <input
                list="rule-target-options"
                value={action.targetsText}
                onChange={(event) => updateRuleAction(action.id, { targetsText: event.target.value })}
                placeholder="set_pres_Fermentor, set_temp_Fermentor"
              />
            </label>
            {(action.type === 'set' || action.type === 'ramp') && (
              <label className="form-field">
                <span>Value</span>
                <input type="number" step="any" value={action.value} onChange={(event) => updateRuleAction(action.id, { value: event.target.value })} />
              </label>
            )}
            {action.type === 'takeover' && (
              <label className="form-field form-field-wide">
                <span>Reason</span>
                <input value={action.reason} onChange={(event) => updateRuleAction(action.id, { reason: event.target.value })} />
              </label>
            )}
            {action.type === 'ramp' && (
              <label className="form-field">
                <span>Duration (s)</span>
                <input type="number" step="any" value={action.duration} onChange={(event) => updateRuleAction(action.id, { duration: event.target.value })} />
              </label>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export function RuleEditorModal({
  rulesModalOpen,
  ruleForm,
  savingRule,
  closeRuleModal,
  rulesEditorLoading,
  updateRuleForm,
  operators,
  selectedOperator,
  updateRuleParam,
  addRuleAction,
  removeRuleAction,
  updateRuleAction,
  snapshotKeys,
  saveRule,
}) {
  if (!rulesModalOpen || !ruleForm) return null

  const editorApp = buildRuleEditorApp({ ruleForm, operators, selectedOperator })

  return (
    <div className="modal-backdrop" onClick={closeRuleModal}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="card-header-row">
          <h3>{ruleForm.id ? `Edit ${ruleForm.id}` : 'Add rule'}</h3>
          <button className="secondary-button" disabled={savingRule} onClick={closeRuleModal}>Close</button>
        </div>

        {rulesEditorLoading ? (
          <p className="muted">Loading operators and snapshot…</p>
        ) : (
          <>
            {editorApp.sections.map((section, sectionIndex) => {
              const hasActionList = (section.items || []).some((item) => item?.kind === 'action_list')
              return (
                <div key={String(section?.id || sectionIndex)}>
                  <div className={`rules-section-title${hasActionList ? ' actions-header-row' : ''}`}>
                    <span>{section.title}</span>
                    {hasActionList ? (
                      <button className="secondary-button" type="button" onClick={addRuleAction}>
                        {(section.items || []).find((item) => item?.kind === 'action_list')?.add_label || 'Add action'}
                      </button>
                    ) : null}
                  </div>
                  {section.description ? <p className="muted">{section.description}</p> : null}
                  <div className="rules-form-grid">
                    {(section.items || []).map((item, itemIndex) => {
                      if (item?.kind === 'field' && item?.field) {
                        return (
                          <RuleFieldItem
                            key={item.field.key || `${sectionIndex}-${itemIndex}`}
                            field={item.field}
                            ruleForm={ruleForm}
                            updateRuleForm={updateRuleForm}
                            updateRuleParam={updateRuleParam}
                          />
                        )
                      }
                      if (item?.kind === 'notice') {
                        return <div key={`${sectionIndex}-${itemIndex}`} className="muted">{String(item.text || '')}</div>
                      }
                      if (item?.kind === 'action_list') {
                        return (
                          <div key={`${sectionIndex}-${itemIndex}`} className="form-field form-field-wide" style={{ gridColumn: '1 / -1' }}>
                            <RuleActionList
                              ruleForm={ruleForm}
                              addRuleAction={addRuleAction}
                              removeRuleAction={removeRuleAction}
                              updateRuleAction={updateRuleAction}
                            />
                          </div>
                        )
                      }
                      return null
                    })}
                  </div>
                </div>
              )
            })}

            <datalist id="rule-target-options">
              {snapshotKeys.map((key) => <option key={key} value={key} />)}
            </datalist>
          </>
        )}

        <div className="button-row modal-actions">
          <button className="secondary-button" disabled={savingRule} onClick={closeRuleModal}>Cancel</button>
          <button className="primary-button" disabled={savingRule || rulesEditorLoading} onClick={saveRule}>
            {savingRule ? 'Saving…' : 'Save rule'}
          </button>
        </div>
      </div>
    </div>
  )
}
