import { getByPath, isFieldVisible } from './schemaUtils.js';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  datasourceFmuDownloadUrl,
  deleteDatasourceFmuFile,
  listDatasourceFmuFiles,
  uploadDatasourceFmuFile,
} from './loaders.js';

function valueToText(value, field) {
  if (field.type === 'json') {
    if (typeof value === 'string') return value;
    return JSON.stringify(value ?? null, null, 2);
  }
  if (field.type === 'parameter_ref_list') return Array.isArray(value) ? value.join(', ') : '';
  if (field.type === 'bool') return Boolean(value);
  return value ?? '';
}

function ParameterPickerModal({ options, selected, multi, onClose, onApply }) {
  const [filter, setFilter] = useState('');
  const [singleValue, setSingleValue] = useState(selected ?? '');
  const [multiValue, setMultiValue] = useState(() => new Set(selected ?? []));

  const visibleOptions = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((item) => item.toLowerCase().includes(needle));
  }, [options, filter]);

  function apply() {
    if (multi) onApply([...multiValue].sort((a, b) => a.localeCompare(b)));
    else onApply(singleValue);
  }

  return (
    <div className="pdb-modal-overlay" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <div className="pdb-modal pdb-modal-sm">
        <div className="pdb-modal-header">
          <h3>{multi ? 'Choose Parameters' : 'Choose Parameter'}</h3>
          <button className="pdb-close-btn" onClick={onClose}>✕</button>
        </div>
        <div className="pdb-modal-body">
          <div className="pdb-field">
            <label className="pdb-label">Filter</label>
            <input
              className="pdb-input"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Search parameters"
            />
          </div>
          <div className="pdb-picker-list">
            {visibleOptions.map((item) => (
              multi ? (
                <label key={item} className="pdb-picker-item">
                  <input
                    type="checkbox"
                    checked={multiValue.has(item)}
                    onChange={(event) => {
                      setMultiValue((current) => {
                        const next = new Set(current);
                        if (event.target.checked) next.add(item);
                        else next.delete(item);
                        return next;
                      });
                    }}
                  />
                  <span>{item}</span>
                </label>
              ) : (
                <button
                  key={item}
                  type="button"
                  className={`pdb-picker-item pdb-picker-item-button ${singleValue === item ? 'pdb-picker-item-active' : ''}`}
                  onClick={() => setSingleValue(item)}
                >
                  {item}
                </button>
              )
            ))}
            {visibleOptions.length === 0 && <div className="pdb-empty">No matching parameters</div>}
          </div>
        </div>
        <div className="pdb-modal-footer">
          <button className="pdb-btn-secondary" onClick={onClose}>Cancel</button>
          <button className="pdb-btn-primary" onClick={apply}>Apply</button>
        </div>
      </div>
    </div>
  );
}

function FmuFilePickerField({ fermenterId, field, value, disabled, onFieldChange }) {
  const [files, setFiles] = useState([]);
  const [selectedName, setSelectedName] = useState('');
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [removingName, setRemovingName] = useState('');
  const [error, setError] = useState('');

  const refreshFiles = useCallback(async () => {
    if (!fermenterId) return;
    setLoading(true);
    setError('');
    try {
      const response = await listDatasourceFmuFiles(fermenterId);
      const nextFiles = Array.isArray(response?.files) ? response.files : [];
      setFiles(nextFiles);
      setSelectedName((current) => {
        if (current && nextFiles.some((item) => item.name === current)) {
          return current;
        }
        return '';
      });
    } catch (err) {
      setError(err?.message ?? String(err));
    } finally {
      setLoading(false);
    }
  }, [fermenterId]);

  useEffect(() => {
    refreshFiles();
  }, [refreshFiles]);

  async function handleUpload(event) {
    const file = event.target.files?.[0] || null;
    event.target.value = '';
    if (!file || !fermenterId) return;
    setUploading(true);
    setError('');
    try {
      const response = await uploadDatasourceFmuFile(fermenterId, file);
      const localPath = String(response?.file?.local_path || '').trim();
      const name = String(response?.file?.name || '').trim();
      if (localPath) {
        onFieldChange(field, localPath);
      }
      if (name) {
        setSelectedName(name);
      }
      await refreshFiles();
    } catch (err) {
      setError(err?.message ?? String(err));
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(filename) {
    if (!fermenterId || !filename) return;
    setRemovingName(filename);
    setError('');
    try {
      await deleteDatasourceFmuFile(fermenterId, filename);
      if (selectedName === filename) {
        setSelectedName('');
      }
      if (String(value || '').toLowerCase().endsWith(`\\${filename.toLowerCase()}`) || String(value || '').toLowerCase().endsWith(`/${filename.toLowerCase()}`)) {
        onFieldChange(field, '');
      }
      await refreshFiles();
    } catch (err) {
      setError(err?.message ?? String(err));
    } finally {
      setRemovingName('');
    }
  }

  const currentPath = String(value || '');

  return (
    <div className="pdb-field-stack">
      <div className="pdb-picker-input-row">
        <input
          className="pdb-input"
          value={currentPath}
          onChange={(event) => onFieldChange(field, event.target.value)}
          disabled={disabled}
          placeholder="No FMU selected"
        />
        {!disabled && (
          <>
            <button type="button" className="pdb-btn-ghost pdb-btn-sm" onClick={refreshFiles} disabled={loading || uploading}>
              {loading ? '…' : 'Refresh'}
            </button>
            <label className="pdb-btn-ghost pdb-btn-sm" style={{ cursor: uploading ? 'wait' : 'pointer' }}>
              {uploading ? 'Uploading…' : 'Upload .fmu'}
              <input
                type="file"
                accept=".fmu,application/octet-stream"
                className="hidden-file-input"
                onChange={handleUpload}
                disabled={uploading}
              />
            </label>
          </>
        )}
      </div>
      <div className="pdb-picker-input-row">
        <select
          className="pdb-input"
          value={selectedName}
          onChange={(event) => setSelectedName(event.target.value)}
          disabled={disabled || files.length === 0}
        >
          <option value="">Choose uploaded FMU…</option>
          {files.map((item) => (
            <option key={item.name} value={item.name}>{item.name}</option>
          ))}
        </select>
        {!disabled && (
          <button
            type="button"
            className="pdb-btn-ghost pdb-btn-sm"
            disabled={!selectedName}
            onClick={() => {
              const selected = files.find((item) => item.name === selectedName);
              if (selected?.local_path) {
                onFieldChange(field, selected.local_path);
              }
            }}
          >
            Use
          </button>
        )}
      </div>
      {files.length > 0 && (
        <div className="pdb-picker-list">
          {files.map((item) => (
            <div key={item.name} className="pdb-picker-item pdb-picker-row">
              <span>{item.name}</span>
              <div className="pdb-picker-actions">
                {fermenterId && (
                  <a className="pdb-btn-ghost pdb-btn-sm" href={datasourceFmuDownloadUrl(fermenterId, item.name)} target="_blank" rel="noreferrer">
                    Download
                  </a>
                )}
                {!disabled && (
                  <button
                    type="button"
                    className="pdb-btn-danger pdb-btn-sm"
                    disabled={removingName === item.name}
                    onClick={() => handleDelete(item.name)}
                  >
                    {removingName === item.name ? '…' : 'Delete'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {error && <div className="pdb-field-error">{error}</div>}
    </div>
  );
}

export function SchemaForm({
  fermenterId,
  sections,
  data,
  errors,
  rawJson,
  parameterOptions,
  onFieldChange,
  onJsonChange,
}) {
  const [pickerState, setPickerState] = useState(null);

  function openPicker(field, value, multi = false) {
    setPickerState({
      field,
      multi,
      selected: multi
        ? (Array.isArray(value) ? value : String(value || '').split(',').map((item) => item.trim()).filter(Boolean))
        : String(value ?? ''),
    });
  }

  return sections.map((section) => (
    <div key={section.title} className="pdb-section">
      <div className="pdb-section-title">{section.title}</div>
      {section.description && <div className="pdb-field-help">{section.description}</div>}
      <div className="pdb-section-fields">
        {(section.fields ?? []).map((field) => {
          if (!isFieldVisible(field, data)) return null;
          const value = getByPath(data, field.key);
          const shown = field.type === 'json' ? rawJson[field.key] ?? valueToText(value, field) : valueToText(value, field);
          const error = errors[field.key];
          const commonProps = {
            className: `pdb-input${error ? ' pdb-input-error' : ''}`,
            disabled: Boolean(field.readonly) || field.type === 'readonly',
          };

          let input = null;
          if (field.type === 'text' || field.type === 'code' || field.type === 'json') {
            input = (
              <textarea
                className={`pdb-textarea${error ? ' pdb-input-error' : ''}`}
                rows={field.type === 'text' || field.type === 'code' ? 5 : 6}
                value={shown}
                onChange={(event) => {
                  if (field.type === 'json') onJsonChange(field.key, event.target.value);
                  else onFieldChange(field, event.target.value);
                }}
                spellCheck={false}
                disabled={Boolean(field.readonly)}
              />
            );
          } else if (field.type === 'bool') {
            input = (
              <label className="pdb-checkbox-row">
                <input
                  type="checkbox"
                  checked={Boolean(shown)}
                  onChange={(event) => onFieldChange(field, event.target.checked)}
                  disabled={Boolean(field.readonly)}
                />
                <span>{field.label}</span>
              </label>
            );
          } else if (field.type === 'enum') {
            const choices = field.choices ?? field.options ?? [];
            input = (
              <select
                {...commonProps}
                value={String(shown)}
                onChange={(event) => onFieldChange(field, event.target.value)}
              >
                {choices.map((choice) => (
                  <option key={choice} value={choice}>{choice}</option>
                ))}
              </select>
            );
          } else if (field.type === 'parameter_ref') {
            input = (
              <div className="pdb-picker-input-row">
                <input
                  {...commonProps}
                  value={Array.isArray(value) ? value.join(', ') : String(shown)}
                  onChange={(event) => onFieldChange(field, event.target.value)}
                  placeholder="Select parameter"
                />
                {!commonProps.disabled && (
                  <button type="button" className="pdb-btn-ghost pdb-btn-sm" onClick={() => openPicker(field, value, Array.isArray(value))}>
                    Pick…
                  </button>
                )}
              </div>
            );
          } else if (field.type === 'parameter_ref_list') {
            input = (
              <div className="pdb-picker-input-row">
                <input
                  {...commonProps}
                  value={Array.isArray(value) ? value.join(', ') : String(shown)}
                  onChange={(event) => onFieldChange(field, event.target.value)}
                  placeholder="Select parameters"
                />
                {!commonProps.disabled && (
                  <button type="button" className="pdb-btn-ghost pdb-btn-sm" onClick={() => openPicker(field, value, true)}>
                    Pick…
                  </button>
                )}
              </div>
            );
          } else if (field.type === 'fmu_file') {
            input = (
              <FmuFilePickerField
                fermenterId={fermenterId}
                field={field}
                value={value}
                disabled={commonProps.disabled}
                onFieldChange={onFieldChange}
              />
            );
          } else {
            input = (
              <input
                {...commonProps}
                value={String(shown)}
                onChange={(event) => onFieldChange(field, event.target.value)}
              />
            );
          }

          return (
            <div key={field.key} className="pdb-field">
              {field.type !== 'bool' && <label className="pdb-label">{field.label}{field.required ? ' *' : ''}</label>}
              {input}
              {field.help && <div className="pdb-field-help">{field.help}</div>}
              {error && <div className="pdb-field-error">{error}</div>}
            </div>
          );
        })}
      </div>
      {pickerState && (
        <ParameterPickerModal
          options={parameterOptions}
          selected={pickerState.selected}
          multi={pickerState.multi}
          onClose={() => setPickerState(null)}
          onApply={(value) => {
            onFieldChange(
              pickerState.field,
              pickerState.multi ? value.join(', ') : value,
            );
            setPickerState(null);
          }}
        />
      )}
    </div>
  ));
}