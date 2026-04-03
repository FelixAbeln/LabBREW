function cloneValue(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

export function getByPath(obj, path) {
  return String(path)
    .split('.')
    .reduce((current, key) => (current == null ? undefined : current[key]), obj);
}

export function setByPath(obj, path, value) {
  const parts = String(path).split('.');
  let current = obj;
  for (let index = 0; index < parts.length - 1; index += 1) {
    const key = parts[index];
    if (current[key] == null || typeof current[key] !== 'object' || Array.isArray(current[key])) {
      current[key] = {};
    }
    current = current[key];
  }
  current[parts[parts.length - 1]] = value;
}

export function isFieldVisible(field, data) {
  const visibleWhen = field?.visible_when;
  if (!visibleWhen || typeof visibleWhen !== 'object' || Array.isArray(visibleWhen)) return true;

  return Object.entries(visibleWhen).every(([path, expected]) => {
    const actual = getByPath(data, path);
    if (Array.isArray(expected)) {
      const actualText = String(actual ?? '');
      return expected.some((candidate) => String(candidate) === actualText);
    }
    if (expected === null) return actual == null || actual === '';
    if (typeof expected === 'boolean') return Boolean(actual) === expected;
    return String(actual ?? '') === String(expected);
  });
}

export function buildSections(schemaUi, mode) {
  const source = schemaUi?.[mode]?.sections ?? [];
  const sections = cloneValue(source) ?? [];
  if (
    mode === 'create' &&
    !sections.some((section) => (section?.fields ?? []).some((field) => field?.key === 'name'))
  ) {
    sections.unshift({
      title: 'Identity',
      fields: [{ key: 'name', label: 'Name', type: 'string', required: true }],
    });
  }
  return sections;
}

export function buildFormData(schemaUi, mode, record, typeKey) {
  if (!schemaUi) return {};
  if (mode === 'create') {
    const defaults = cloneValue(schemaUi?.create?.defaults ?? {});
    return {
      name: defaults?.name ?? '',
      [typeKey]: schemaUi[typeKey],
      config: defaults?.config ?? {},
      metadata: defaults?.metadata ?? {},
      value: defaults?.value ?? null,
      state: defaults?.state ?? {},
    };
  }

  const data = cloneValue(record ?? {});
  const editDefaults = cloneValue(schemaUi?.edit?.defaults ?? {});
  Object.entries(editDefaults).forEach(([key, value]) => {
    if (key === 'config' && value && typeof value === 'object' && !Array.isArray(value)) {
      data.config = { ...value, ...(data.config ?? {}) };
    } else if (data[key] === undefined) {
      data[key] = value;
    }
  });
  data.name ??= '';
  data[typeKey] ??= record?.[typeKey] ?? schemaUi[typeKey];
  data.config ??= {};
  data.metadata ??= {};
  data.value ??= null;
  data.state ??= {};
  return data;
}

export function collectRequiredPaths(schemaUi, sections, data = {}) {
  const required = new Set(schemaUi?.create?.required ?? []);
  sections.forEach((section) => {
    (section?.fields ?? []).forEach((field) => {
      if (field?.required && field?.key && isFieldVisible(field, data)) required.add(field.key);
    });
  });
  return [...required];
}

export function collectJsonFieldKeys(sections) {
  return sections.flatMap((section) =>
    (section?.fields ?? [])
      .filter((field) => field?.type === 'json')
      .map((field) => field.key),
  );
}

function normalizeList(value) {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean);
  if (typeof value === 'string') return value.trim() ? [value.trim()] : [];
  if (value && typeof value === 'object') {
    return Object.values(value).flatMap((item) => normalizeList(item));
  }
  return [];
}

export function deriveSourceLinks(record, schemaUi) {
  const sections = buildSections(schemaUi, 'edit');
  const feedsFrom = new Set();

  normalizeList(schemaUi?.graph?.depends_on).forEach((item) => feedsFrom.add(item));

  sections.forEach((section) => {
    (section?.fields ?? []).forEach((field) => {
      if (!field?.key?.startsWith('config.')) return;
      const value = getByPath(record, field.key);
      const key = field.key.toLowerCase();
      const label = String(field.label ?? '').toLowerCase();
      const refs = normalizeList(value);
      if (!refs.length) return;

      if (field.type === 'parameter_ref' || field.type === 'parameter_ref_list' || key.includes('input_binding')) {
        refs.forEach((item) => feedsFrom.add(item));
        return;
      }

      if (key.endsWith('parameter_name') || key.endsWith('_param') || key.endsWith('_params')) {
        const isFeed = key.includes('set_') || key.includes('input') || label.includes('set ') || label.includes('input');
        if (isFeed) refs.forEach((item) => feedsFrom.add(item));
      }
    });
  });

  return {
    feedsFrom: [...feedsFrom].sort((a, b) => a.localeCompare(b)),
  };
}

export function derivePublishedParametersByOwner(params) {
  const result = {};
  Object.entries(params ?? {}).forEach(([name, record]) => {
    const metadata = record?.metadata ?? {};
    if (metadata?.created_by !== 'data_source') return;
    const owner = String(metadata?.owner ?? '').trim();
    if (!owner) return;
    if (!result[owner]) result[owner] = [];
    result[owner].push(name);
  });
  Object.keys(result).forEach((owner) => {
    result[owner].sort((a, b) => a.localeCompare(b));
  });
  return result;
}