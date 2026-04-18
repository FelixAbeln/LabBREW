import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'

function ownerClass(owner) {
  const text = String(owner || '').trim()
  if (!text) return 'pill-neutral'
  if (text === 'operator') return 'pill-ok'
  if (text === 'safety') return 'pill-bad'
  return 'pill-warn'
}

export function SystemDebugPage({ fermenterId, fermenterName, onClose }) {
  const [loading, setLoading] = useState(false)
  const [copying, setCopying] = useState(false)
  const [error, setError] = useState('')
  const [uiSpec, setUiSpec] = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [filterText, setFilterText] = useState('')
  const [showOwnedOnly, setShowOwnedOnly] = useState(false)

  async function refreshDebugData() {
    if (!fermenterId) return
    try {
      setLoading(true)
      setError('')
      const [specPayload, snapshotPayload] = await Promise.all([
        api(`/fermenters/${fermenterId}/system/control-ui-spec?include_empty_cards=true`),
        api(`/fermenters/${fermenterId}/system/snapshot`),
      ])
      setUiSpec(specPayload && typeof specPayload === 'object' ? specPayload : null)
      setSnapshot(snapshotPayload && typeof snapshotPayload === 'object' ? snapshotPayload : null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load debug data')
    } finally {
      setLoading(false)
    }
  }

  async function copyDebugPayload() {
    try {
      setCopying(true)
      const payload = {
        fermenter_id: fermenterId,
        ui_spec: uiSpec,
        snapshot,
      }
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not copy debug payload')
    } finally {
      setCopying(false)
    }
  }

  useEffect(() => {
    refreshDebugData().catch(() => {})
  }, [fermenterId])

  const rows = useMemo(() => {
    const cards = Array.isArray(uiSpec?.cards) ? uiSpec.cards : []
    const ownership = snapshot?.ownership && typeof snapshot.ownership === 'object' ? snapshot.ownership : {}

    const items = []
    cards.forEach((card) => {
      const cardTitle = String(card?.title || card?.card_id || '').trim()
      const controls = Array.isArray(card?.controls) ? card.controls : []
      controls.forEach((control) => {
        const target = String(control?.target || '').trim()
        if (!target) return
        const uiOwner = String(control?.current_owner || '').trim() || null
        const ownerMeta = ownership[target]
        const liveOwner = ownerMeta && typeof ownerMeta === 'object'
          ? (String(ownerMeta.owner || '').trim() || null)
          : null
        const effectiveOwner = liveOwner || uiOwner
        const safetyLocked = Boolean(control?.safety_locked)
        items.push({
          cardTitle,
          target,
          source: String(control?.source || '').trim() || '-',
          uiOwner,
          liveOwner,
          effectiveOwner,
          safetyLocked,
          ownerMismatch: uiOwner !== liveOwner,
        })
      })
    })

    const needle = filterText.trim().toLowerCase()
    return items.filter((item) => {
      if (showOwnedOnly && !item.effectiveOwner) return false
      if (!needle) return true
      return item.target.toLowerCase().includes(needle) || item.cardTitle.toLowerCase().includes(needle)
    })
  }, [uiSpec, snapshot, filterText, showOwnedOnly])

  const summary = useMemo(() => {
    let ownedByService = 0
    let ownedByOperator = 0
    let safetyOwned = 0
    rows.forEach((row) => {
      if (!row.effectiveOwner) return
      if (row.effectiveOwner === 'operator') ownedByOperator += 1
      else if (row.effectiveOwner === 'safety') safetyOwned += 1
      else ownedByService += 1
    })
    return { ownedByService, ownedByOperator, safetyOwned }
  }, [rows])

  return (
    <div className="pdb-page" style={{ minHeight: '100vh' }}>
      <div className="pdb-page-header">
        <div className="pdb-page-title">
          <span className="pdb-page-icon">⚑</span>
          <span>System Debug</span>
          {fermenterName ? <span className="pdb-page-mode">{fermenterName}</span> : null}
        </div>
        <div className="pdb-page-actions" style={{ gap: 8 }}>
          <button className="secondary-button" onClick={() => refreshDebugData()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
          <button className="secondary-button" onClick={() => copyDebugPayload()} disabled={copying || !uiSpec}>
            {copying ? 'Copying…' : 'Copy JSON'}
          </button>
          <button className="pdb-close-btn" onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      <div style={{ padding: 16, display: 'grid', gap: 12 }}>
        {error ? <div className="error-banner"><span className="error-banner-message">{error}</span></div> : null}

        <div className="info-card" style={{ display: 'grid', gap: 10 }}>
          <h3 style={{ margin: 0 }}>Ownership Summary</h3>
          <div className="info-row"><span>Total controls</span><strong>{rows.length}</strong></div>
          <div className="info-row"><span>Owned by service</span><strong>{summary.ownedByService}</strong></div>
          <div className="info-row"><span>Owned by operator</span><strong>{summary.ownedByOperator}</strong></div>
          <div className="info-row"><span>Owned by safety</span><strong>{summary.safetyOwned}</strong></div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              className="data-control"
              placeholder="Filter by target or card"
              value={filterText}
              onChange={(event) => setFilterText(event.target.value)}
              style={{ minWidth: 260 }}
            />
            <label className="small-text" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
              <input
                type="checkbox"
                checked={showOwnedOnly}
                onChange={(event) => setShowOwnedOnly(event.target.checked)}
              />
              show only owned
            </label>
          </div>
        </div>

        <div className="info-card" style={{ overflowX: 'auto' }}>
          <h3 style={{ marginTop: 0 }}>Control Ownership Detail</h3>
          <table className="pdb-table" style={{ minWidth: 980 }}>
            <thead>
              <tr>
                <th>Target</th>
                <th>Card</th>
                <th>Source</th>
                <th>UI owner</th>
                <th>Live owner</th>
                <th>Safety</th>
                <th>Mismatch</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.cardTitle}:${row.target}:${row.source}`}>
                  <td>{row.target}</td>
                  <td>{row.cardTitle || '-'}</td>
                  <td>{row.source}</td>
                  <td><span className={`pill ${ownerClass(row.uiOwner)}`}>{row.uiOwner || '-'}</span></td>
                  <td><span className={`pill ${ownerClass(row.liveOwner)}`}>{row.liveOwner || '-'}</span></td>
                  <td>{row.safetyLocked ? 'yes' : 'no'}</td>
                  <td>{row.ownerMismatch ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
