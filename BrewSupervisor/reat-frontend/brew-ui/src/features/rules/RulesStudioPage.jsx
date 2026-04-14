import { RulesTabContainer } from '../app/containers/RulesTabContainer';

export function RulesStudioPage({
  fermenterId,
  fermenterName,
  rulesProps,
  onClose,
}) {
  const ruleCount = Array.isArray(rulesProps?.rules) ? rulesProps.rules.length : 0

  return (
    <div className="pdb-page" style={{ minHeight: '100vh' }}>
      <div className="pdb-page-header">
        <div className="pdb-page-title">
          <span className="pdb-page-icon">⚙</span>
          <span>Rules Studio</span>
          {fermenterName && <span className="pdb-page-mode">{fermenterName}</span>}
          <span className="pdb-page-mode">{ruleCount} rule{ruleCount === 1 ? '' : 's'}</span>
        </div>
        <div className="pdb-page-actions">
          <button className="pdb-btn-ghost pdb-btn-sm" onClick={() => rulesProps?.openAddRule?.()}>
            + Add Rule
          </button>
          <button className="pdb-close-btn" onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      <div className="pdb-view-tabs">
        <span style={{ fontSize: 12, color: '#475569' }}>
          Create and edit automation rules for {fermenterName || fermenterId || 'this fermenter'}.
        </span>
      </div>

      <div style={{ padding: 16, overflow: 'auto', flex: 1 }}>
        <RulesTabContainer {...rulesProps} />
      </div>
    </div>
  )
}

export default RulesStudioPage
