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
            <div className="rules-form-grid">
              <label className="form-field">
                <span>Rule id</span>
                <input value={ruleForm.id} onChange={(e) => updateRuleForm({ id: e.target.value })} placeholder="manual-pressure-override" />
              </label>
              <label className="form-field checkbox-field">
                <span>Enabled</span>
                <input type="checkbox" checked={ruleForm.enabled} onChange={(e) => updateRuleForm({ enabled: e.target.checked })} />
              </label>
              <label className="form-field">
                <span>Parameter</span>
                <input list="rule-target-options" value={ruleForm.source} onChange={(e) => updateRuleForm({ source: e.target.value })} placeholder="set_temp_Fermentor" />
              </label>
              <label className="form-field">
                <span>Operator</span>
                <select value={ruleForm.operator} onChange={(e) => updateRuleForm({ operator: e.target.value, operatorParams: {} })}>
                  {operators.map((operator) => (
                    <option key={operator.name} value={operator.name}>{operator.label || operator.name}</option>
                  ))}
                </select>
              </label>
              {selectedOperator?.supports_for_s && (
                <label className="form-field">
                  <span>For seconds</span>
                  <input type="number" step="0.1" value={ruleForm.for_s} onChange={(e) => updateRuleForm({ for_s: e.target.value })} placeholder="optional" />
                </label>
              )}
              {Object.entries(selectedOperator?.param_schema || {}).map(([key, schema]) => (
                <label key={key} className="form-field">
                  <span>{key}</span>
                  <input
                    type={schema?.type === 'number' ? 'number' : 'text'}
                    step={schema?.type === 'number' ? 'any' : undefined}
                    value={ruleForm.operatorParams?.[key] ?? ''}
                    onChange={(e) => updateRuleParam(key, e.target.value)}
                    placeholder={schema?.required ? 'required' : 'optional'}
                  />
                </label>
              ))}
            </div>

            <div className="rules-section-title actions-header-row">
              <span>Actions</span>
              <button className="secondary-button" type="button" onClick={addRuleAction}>Add action</button>
            </div>
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
                      <select value={action.type} onChange={(e) => updateRuleAction(action.id, { type: e.target.value })}>
                        <option value="takeover">takeover</option>
                        <option value="set">set</option>
                        <option value="ramp">ramp</option>
                      </select>
                    </label>
                    <label className="form-field form-field-wide">
                      <span>Targets</span>
                      <input list="rule-target-options" value={action.targetsText} onChange={(e) => updateRuleAction(action.id, { targetsText: e.target.value })} placeholder="set_pres_Fermentor, set_temp_Fermentor" />
                    </label>
                    {(action.type === 'set' || action.type === 'ramp') && (
                      <label className="form-field">
                        <span>Value</span>
                        <input type="number" step="any" value={action.value} onChange={(e) => updateRuleAction(action.id, { value: e.target.value })} />
                      </label>
                    )}
                    {action.type === 'takeover' && (
                      <label className="form-field form-field-wide">
                        <span>Reason</span>
                        <input value={action.reason} onChange={(e) => updateRuleAction(action.id, { reason: e.target.value })} />
                      </label>
                    )}
                    {action.type === 'ramp' && (
                      <label className="form-field">
                        <span>Duration (s)</span>
                        <input type="number" step="any" value={action.duration} onChange={(e) => updateRuleAction(action.id, { duration: e.target.value })} />
                      </label>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="rules-form-grid">
              <label className="form-field checkbox-field">
                <span>Release when clear</span>
                <input type="checkbox" checked={ruleForm.releaseWhenClear} onChange={(e) => updateRuleForm({ releaseWhenClear: e.target.checked })} />
              </label>
            </div>

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
