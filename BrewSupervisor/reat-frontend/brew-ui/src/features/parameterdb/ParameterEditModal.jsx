import { useEffect, useMemo, useState } from 'react';
import { createParam, fetchParamTypeUi, setParamValue, updateParamConfig, updateParamMetadata } from './loaders.js';
import { SchemaForm } from './SchemaForm.jsx';
import { buildFormData, buildSections, collectJsonFieldKeys, collectRequiredPaths, getByPath, setByPath } from './schemaUtils.js';

export function ParameterEditModal({ mode, record, fermenterId, paramTypes, parameterNames, onClose, onSaved }) {
  const isCreate = mode === 'create';
  const [paramType, setParamType] = useState(record?.parameter_type ?? Object.keys(paramTypes ?? {})[0] ?? '');
  const [schemaUi, setSchemaUi] = useState(null);
  const sections = useMemo(() => buildSections(schemaUi, mode), [schemaUi, mode]);
  const [draft, setDraft] = useState({});
  const [jsonDrafts, setJsonDrafts] = useState({});
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadSchema() {
      if (!paramType) {
        setSchemaUi(null);
        setDraft({});
        return;
      }

      try {
        const response = await fetchParamTypeUi(fermenterId, paramType);
        if (cancelled) return;
        const ui = response?.ui ?? null;
        setSchemaUi(ui);
        const nextDraft = buildFormData(ui, mode, record, 'parameter_type');
        setDraft(nextDraft);
        const nextJsonDrafts = {};
        collectJsonFieldKeys(buildSections(ui, mode)).forEach((key) => {
          nextJsonDrafts[key] = JSON.stringify(getByPath(nextDraft, key) ?? null, null, 2);
        });
        setJsonDrafts(nextJsonDrafts);
        setErrors({});
      } catch (err) {
        if (!cancelled) {
          setSchemaUi(null);
          setDraft({});
          setErrors({ save: err?.message ?? String(err) });
        }
      }
    }

    loadSchema();
    return () => { cancelled = true; };
  }, [fermenterId, paramType, mode, record]);

  function handleFieldChange(field, rawValue) {
    setDraft((current) => {
      const next = JSON.parse(JSON.stringify(current));
      if (Array.isArray(rawValue)) setByPath(next, field.key, rawValue);
      else if (field.type === 'int') setByPath(next, field.key, rawValue === '' ? null : Number.parseInt(rawValue, 10));
      else if (field.type === 'float') setByPath(next, field.key, rawValue === '' ? null : Number.parseFloat(rawValue));
      else if (field.type === 'parameter_ref_list') setByPath(next, field.key, String(rawValue).split(',').map((item) => item.trim()).filter(Boolean));
      else setByPath(next, field.key, rawValue);
      return next;
    });
    setErrors((current) => {
      const next = { ...current };
      delete next[field.key];
      delete next.save;
      return next;
    });
  }

  function finalizeDraft() {
    const next = JSON.parse(JSON.stringify(draft));
    const nextErrors = {};
    collectJsonFieldKeys(sections).forEach((key) => {
      try {
        const raw = jsonDrafts[key];
        setByPath(next, key, raw == null || raw.trim() === '' ? null : JSON.parse(raw));
      } catch {
        nextErrors[key] = 'Invalid JSON';
      }
    });

    collectRequiredPaths(schemaUi, sections).forEach((key) => {
      const value = getByPath(next, key);
      if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) {
        nextErrors[key] = 'Required';
      }
    });

    if (!paramType) nextErrors.parameter_type = 'Type is required';
    return { next, nextErrors };
  }

  async function handleSave() {
    const { next, nextErrors } = finalizeDraft();
    if (Object.keys(nextErrors).length) {
      setErrors(nextErrors);
      return;
    }
    setSaving(true);
    try {
      if (isCreate) {
        await createParam(
          fermenterId,
          next.name.trim(),
          paramType,
          next.value,
          next.config ?? {},
          next.metadata ?? {},
        );
      } else {
        await Promise.all([
          setParamValue(fermenterId, record.name, next.value),
          updateParamConfig(fermenterId, record.name, next.config ?? {}),
          updateParamMetadata(fermenterId, record.name, next.metadata ?? {}),
        ]);
      }
      onSaved?.();
    } catch (err) {
      setErrors({ save: err?.message ?? String(err) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pdb-modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="pdb-modal">
        <div className="pdb-modal-header">
          <h3>{isCreate ? 'Create Parameter' : `Edit — ${record?.name ?? draft?.name ?? ''}`}</h3>
          <button className="pdb-close-btn" onClick={onClose}>✕</button>
        </div>
        <div className="pdb-modal-body">
          {isCreate ? (
            <div className="pdb-field">
              <label className="pdb-label">Type</label>
              <select
                className={`pdb-input${errors.parameter_type ? ' pdb-input-error' : ''}`}
                value={paramType}
                onChange={e => setParamType(e.target.value)}
              >
                {Object.entries(paramTypes ?? {}).map(([key, spec]) => (
                  <option key={key} value={key}>{spec.display_name ?? key}</option>
                ))}
              </select>
              {errors.parameter_type && <span className="pdb-field-error">{errors.parameter_type}</span>}
            </div>
          ) : (
            <div className="pdb-field">
              <label className="pdb-label">Type</label>
              <div className="pdb-readonly">{record?.parameter_type}</div>
            </div>
          )}
          {schemaUi && sections.length > 0 && (
            <SchemaForm
              sections={sections}
              data={draft}
              errors={errors}
              rawJson={jsonDrafts}
              parameterOptions={parameterNames}
              onFieldChange={handleFieldChange}
              onJsonChange={(key, value) => setJsonDrafts((current) => ({ ...current, [key]: value }))}
            />
          )}
          {errors.save && <div className="pdb-save-error">{errors.save}</div>}
        </div>
        <div className="pdb-modal-footer">
          <button className="pdb-btn-secondary" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="pdb-btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
