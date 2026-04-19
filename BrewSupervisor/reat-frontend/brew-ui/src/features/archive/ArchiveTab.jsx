import { API_BASE } from '../../api/client'

function formatBytes(value) {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = bytes / 1024
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(size >= 100 ? 0 : size >= 10 ? 1 : 2)} ${units[unitIndex]}`
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString()
}

export function ArchiveSummaryCard({ archivePayload }) {
  const archives = Array.isArray(archivePayload?.archives) ? archivePayload.archives : []
  const disk = archivePayload?.disk && typeof archivePayload.disk === 'object' ? archivePayload.disk : null
  const outputDir = archivePayload?.output_dir || ''

  return (
    <div className="info-card archive-summary-card">
      <div className="control-bar-copy">
        <strong>Archives</strong>
        <span>Compressed run bundles ({archives.length}){outputDir ? ` in ${outputDir}` : ''}</span>
      </div>
      {!disk ? (
        <p className="muted">No disk metrics available.</p>
      ) : (
        <div className="archive-disk-grid">
          <div className="archive-disk-card"><span className="small-text">Free</span><strong>{formatBytes(disk.free_bytes)}</strong></div>
          <div className="archive-disk-card"><span className="small-text">Used</span><strong>{formatBytes(disk.used_bytes)}</strong></div>
          <div className="archive-disk-card"><span className="small-text">Total</span><strong>{formatBytes(disk.total_bytes)}</strong></div>
        </div>
      )}
    </div>
  )
}

export function ArchiveFilesCard({ selected, archivePayload, deletingArchiveName, onDelete, onView }) {
  const archives = Array.isArray(archivePayload?.archives) ? archivePayload.archives : []
  const outputDir = archivePayload?.output_dir || ''

  return (
    <div className="info-card archive-files-card">
      <h3>Archive files</h3>
      {!archives.length ? (
        <p className="muted">No archives yet. Stop a measurement run to generate one.</p>
      ) : (
        <div className="archive-table-wrap">
          <div className="archive-table-head">
            <span>Name</span>
            <span>Size</span>
            <span>Modified</span>
            <span>Actions</span>
          </div>
          <div className="archive-table-body">
            {archives.map((archive) => {
              const name = archive?.name || ''
              const downloadHref = `${API_BASE}/fermenters/${selected.id}/data/archives/download/${encodeURIComponent(name)}${outputDir ? `?output_dir=${encodeURIComponent(outputDir)}` : ''}`
              return (
                <div key={name} className="archive-table-row">
                  <strong className="archive-name">{name || '-'}</strong>
                  <span>{formatBytes(archive?.size_bytes)}</span>
                  <span>{formatDate(archive?.modified_at)}</span>
                  <div className="button-row compact-actions">
                    <button className="secondary-button" disabled={!name} onClick={() => onView(name)}>View</button>
                    <a className="secondary-button" href={downloadHref}>Download</a>
                    <button className="danger-button" disabled={deletingArchiveName === name || !name} onClick={() => onDelete(name)}>
                      {deletingArchiveName === name ? 'Deleting...' : 'Delete'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function ArchiveTab(props) {
  const { selected, archivePayload, deletingArchiveName, onDelete, onView } = props
  return (
    <div className="tab-content-grid archive-tab-grid">
      <ArchiveSummaryCard archivePayload={archivePayload} />
      <ArchiveFilesCard selected={selected} archivePayload={archivePayload} deletingArchiveName={deletingArchiveName} onDelete={onDelete} onView={onView} />
    </div>
  )
}
