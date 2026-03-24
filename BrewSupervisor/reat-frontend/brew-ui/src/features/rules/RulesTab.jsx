import { formatRuleAction, formatRuleCondition } from './ruleUtils'

export function RulesTab({
  selected,
  rules,
  activeRuleIds,
  heldRuleIds,
  rulesSnapshot,
  loadingAction,
  deletingRuleId,
  openAddRule,
  openEditRule,
  releaseHeldRule,
  deleteRule,
}) {
  return (
    <div className="tab-content-grid rules-tab-layout">
      <div className="info-card rules-card">
        <div className="rules-toolbar">
          <div>
            <h3>Rules</h3>
            <div className="small-text">Manual override rules. Opens snapshot and operator data only when editing.</div>
          </div>
          <div className="button-row compact-actions">
            <button
              className="primary-button"
              disabled={!selected}
              onClick={openAddRule}
            >
              Add rule
            </button>
          </div>
        </div>

        {!rules.length ? (
          <p className="muted">No rules configured.</p>
        ) : (
          <div className="rules-list">
            {rules.map((rule) => {
              const isActiveRule = activeRuleIds.has(rule.id)
              const isHeldRule = heldRuleIds.has(rule.id)
              const ruleStateClass = isActiveRule ? 'is-active' : isHeldRule ? 'is-held' : ''
              const activeMeta = rulesSnapshot?.active_rules?.[rule.id] || null
              const heldMeta = rulesSnapshot?.held_rules?.[rule.id] || null
              const ownedTargets = activeMeta?.owned_targets || heldMeta?.owned_targets || []

              return (
                <div key={rule.id} className={`rule-item ${ruleStateClass}`}>
                  <div className="rule-item-header">
                    <div>
                      <div className="rule-title-row">
                        <strong>{rule.id}</strong>
                        <span className={`pill ${rule.enabled !== false ? 'pill-ok' : 'pill-warn'}`}>
                          {rule.enabled !== false ? 'enabled' : 'disabled'}
                        </span>
                        {isActiveRule && <span className="pill pill-rule-active">triggered</span>}
                        {!isActiveRule && isHeldRule && <span className="pill pill-rule-held">holding control</span>}
                        {rule.release_when_clear !== false && <span className="tag">release when clear</span>}
                      </div>
                      <div className="small-text">Condition: {formatRuleCondition(rule)}</div>
                      <div className="small-text">Action: {formatRuleAction(rule)}</div>
                      {(isActiveRule || isHeldRule) && (
                        <div className="small-text">
                          Targets: {Array.isArray(ownedTargets) && ownedTargets.length ? ownedTargets.join(', ') : '-'}
                        </div>
                      )}
                    </div>
                    <div className="button-row compact-actions">
                      {!isActiveRule && isHeldRule && (
                        <button
                          className="warning-button"
                          disabled={loadingAction || !ownedTargets.length}
                          onClick={() => releaseHeldRule(rule.id, ownedTargets)}
                        >
                          {loadingAction ? 'Releasing…' : 'Release'}
                        </button>
                      )}
                      <button className="secondary-button" onClick={() => openEditRule(rule)}>Edit</button>
                      <button
                        className="danger-button"
                        disabled={deletingRuleId === rule.id}
                        onClick={() => deleteRule(rule.id)}
                      >
                        {deletingRuleId === rule.id ? 'Deleting…' : 'Delete'}
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
