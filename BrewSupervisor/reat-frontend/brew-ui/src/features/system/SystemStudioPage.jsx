import { SystemTabContainer } from '../app/containers/SystemTabContainer';

export function SystemStudioPage({
  fermenterId,
  fermenterName,
  systemProps,
  onClose,
}) {
  return (
    <div className="pdb-page" style={{ minHeight: '100vh' }}>
      <div className="pdb-page-header">
        <div className="pdb-page-title">
          <span className="pdb-page-icon pdb-page-icon-system">⛭</span>
          <span>System</span>
          {fermenterName && <span className="pdb-page-mode">{fermenterName}</span>}
          {fermenterId && <span className="pdb-page-mode">{fermenterId}</span>}
        </div>
        <div className="pdb-page-actions">
          <button className="pdb-close-btn" onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      <div className="system-studio-scroll">
        <SystemTabContainer {...systemProps} />
      </div>
    </div>
  )
}

export default SystemStudioPage
