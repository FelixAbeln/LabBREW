import { ArchiveFilesCard, ArchiveSummaryCard } from '../archive/ArchiveTab';
import BackendControlCard from '../control/BackendControlCard.jsx';
import { DataLoadstepStatusCard, DataRecordingCard, DataSnapshotBrowserCard } from '../data/DataTab';
import { ScenarioControlsBar, ScenarioEventLogCard, ScenarioPackageCard, ScenarioSummaryCard } from '../schedule/ScheduleTab';
import { PersistenceStatusCard, SystemLauncherPanel } from '../system/SystemTab';

function SystemNodeWidget({ systemProps }) {
  const selected = systemProps?.selected || {};
  return (
    <div className="workspace-module-panel system-node-card">
      <h3>Node</h3>
      <div className="info-row"><span>Name</span><strong>{selected.name || '-'}</strong></div>
      <div className="info-row"><span>ID</span><strong>{selected.id || '-'}</strong></div>
      <div className="info-row"><span>Address</span><strong>{selected.address || '-'}</strong></div>
      <div className="info-row"><span>Host</span><strong>{selected.host || '-'}</strong></div>
    </div>
  );
}

function SystemPersistenceWidget({ systemProps }) {
  return (
    <div className="workspace-module-panel system-node-card">
      <h3>Persistence</h3>
      <PersistenceStatusCard
        title="ParameterDB snapshot backend"
        status={systemProps?.persistenceStatus}
      />
      <PersistenceStatusCard title="Source config backend" status={systemProps?.datasourcePersistenceStatus} />
      <PersistenceStatusCard title="Control rules backend" status={systemProps?.rulesPersistenceStatus} />
    </div>
  );
}

function SystemServicesWidget({ systemProps }) {
  const healthyServices = Array.isArray(systemProps?.healthyServices) ? systemProps.healthyServices : [];
  return (
    <div className="workspace-module-panel system-services-card system-right-column">
      <div className="card-header-row">
        <h3>Healthy services</h3>
        <span className="tag">{healthyServices.length} active</span>
      </div>
      {!healthyServices.length ? (
        <p className="muted">No healthy services reported.</p>
      ) : (
        <div className="system-service-stack">
          {healthyServices.map(([name, service]) => (
            <div key={name} className="system-service-item">
              <div className="system-service-header">
                <strong>{name}</strong>
                <div className="tag-row"><span className="pill pill-ok">healthy</span></div>
              </div>
              <div className="small-text">Base URL: {service?.base_url || '-'}</div>
              <div className="small-text">Reason: {service?.reason || '-'}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SystemActionsWidget({ systemProps }) {
  return (
    <SystemLauncherPanel
      onOpenStorageManager={systemProps?.onOpenStorageManager}
      onOpenParameterDB={systemProps?.onOpenParameterDB}
      onOpenRulesStudio={systemProps?.onOpenRulesStudio}
      onOpenScenarioBuilder={systemProps?.onOpenScenarioBuilder}
      className="workspace-module-panel system-launcher-card"
    />
  );
}

function visibleControlCards(controlProps) {
  const cards = Array.isArray(controlProps?.controlUiSpec?.cards) ? controlProps.controlUiSpec.cards : [];
  return cards.filter((card) => Array.isArray(card?.controls) && card.controls.length > 0);
}

function controlCardType(card) {
  const rawId = String(card?.card_id || `${card?.kind || 'card'}-${card?.title || 'device'}`).trim();
  return `control-card:${rawId}`;
}

function encodeModuleToken(value) {
  return encodeURIComponent(String(value || '').trim());
}

function controlFieldType(card, control) {
  const rawCardId = String(card?.card_id || `${card?.kind || 'card'}-${card?.title || 'device'}`).trim();
  const rawControlId = String(control?.id || control?.target || control?.label || 'control').trim();
  return `control-field:${encodeModuleToken(rawCardId)}:${encodeModuleToken(rawControlId)}`;
}

function findControlCardByType(type, controlProps) {
  const rawType = String(type || '');
  if (!rawType.startsWith('control-card:')) return null;
  const wantedId = rawType.slice('control-card:'.length);
  return visibleControlCards(controlProps).find((card) => {
    const cardId = String(card?.card_id || `${card?.kind || 'card'}-${card?.title || 'device'}`).trim();
    return cardId === wantedId;
  }) || null;
}

function ControlCardWidget({ type, controlProps }) {
  const card = findControlCardByType(type, controlProps);

  if (!card) {
    return (
      <div className="workspace-module-panel workspace-module-panel-control control-device-card">
        <div className="card-header-row">
          <h3>Control Card</h3>
          <span className="pill pill-warn">unavailable</span>
        </div>
        <p className="muted">This control module is not currently available for the selected fermenter.</p>
      </div>
    );
  }

  return (
    <BackendControlCard
      card={card}
      controlDrafts={controlProps?.controlDrafts}
      controlUiLoading={controlProps?.controlUiLoading}
      controlWriteTarget={controlProps?.controlWriteTarget}
      controlWriteError={controlProps?.controlWriteError}
      onDraftChange={controlProps?.onDraftChange}
      onWrite={controlProps?.onWrite}
    />
  );
}

function findControlFieldByType(type, controlProps) {
  const rawType = String(type || '');
  if (!rawType.startsWith('control-field:')) return null;
  const [, encodedCardId = '', encodedControlId = ''] = rawType.split(':');
  const wantedCardId = decodeURIComponent(encodedCardId);
  const wantedControlId = decodeURIComponent(encodedControlId);

  const card = visibleControlCards(controlProps).find((item) => {
    const cardId = String(item?.card_id || `${item?.kind || 'card'}-${item?.title || 'device'}`).trim();
    return cardId === wantedCardId;
  }) || null;

  if (!card) return null;

  const controls = Array.isArray(card?.controls) ? card.controls : [];
  const control = controls.find((item) => {
    const itemId = String(item?.id || item?.target || item?.label || '').trim();
    return itemId === wantedControlId;
  }) || null;

  return control ? { card, control } : null;
}

function controlHasDraft(controlDrafts, target) {
  return Object.prototype.hasOwnProperty.call(controlDrafts || {}, target);
}

function controlTextValue(value) {
  if (value === undefined) return '-';
  if (value === null) return 'null';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function controlBoolValue(value) {
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (normalized === 'true' || normalized === '1' || normalized === 'on') return true;
    if (normalized === 'false' || normalized === '0' || normalized === 'off' || normalized === '') return false;
  }
  return Boolean(value);
}

function ControlFieldWidget({ type, controlProps }) {
  const match = findControlFieldByType(type, controlProps);

  if (!match) {
    return (
      <div className="workspace-module-panel workspace-module-panel-control control-device-card">
        <p className="muted">This control field is not currently available for the selected fermenter.</p>
      </div>
    );
  }

  const { card, control } = match;
  const target = String(control?.target || '').trim();
  const writeKind = String(control?.write?.kind || '');
  const widget = String(control?.widget || '');
  const isWriting = controlProps?.controlWriteTarget === target;
  const inlineError = controlProps?.controlWriteError?.target === target ? controlProps.controlWriteError.message : '';
  const valueTarget = widget === 'number_button' ? String(control?.value_target || '').trim() : '';
  const draftValue = target && controlHasDraft(controlProps?.controlDrafts, target)
    ? controlProps.controlDrafts[target]
    : control?.current_value;
  const valueDraft = valueTarget && controlHasDraft(controlProps?.controlDrafts, valueTarget)
    ? controlProps.controlDrafts[valueTarget]
    : control?.value_target_current_value;
  const currentOwner = String(control?.current_owner || '').trim();
  const normalizedOwner = currentOwner.toLowerCase();
  const safetyLocked = Boolean(control?.safety_locked) || normalizedOwner === 'safety';
  const isServiceOwned = Boolean(currentOwner && currentOwner !== 'operator');
  const canTakeControl = Boolean(target && widget !== 'button' && widget !== 'number_button' && writeKind !== 'pulse' && !safetyLocked);
  const requiresTakeover = isServiceOwned;
  const actionLabel = widget === 'number_button'
    ? 'Calibrate'
    : widget === 'button' || writeKind === 'pulse'
      ? 'Run'
      : widget === 'toggle' || writeKind === 'bool'
        ? (controlBoolValue(control?.current_value) ? 'Turn off' : 'Turn on')
        : 'Apply';

  return (
    <div className="workspace-module-panel workspace-module-panel-control control-device-card">
      <div className={`control-item-row control-item-row--stacked${isServiceOwned ? ' control-item-row--service-owned' : ''}`}>
        <div className="control-item-meta">
          <strong>{String(control?.label || target || 'Control')}</strong>
          <div className="small-text control-item-target">{target || '-'}</div>
          <div className="small-text">
            Current: {controlTextValue(widget === 'number_button' ? (control?.value_target_current_value ?? control?.current_value) : control?.current_value)}
            {control?.unit ? ` ${control.unit}` : ''}
          </div>
          {isServiceOwned ? (
            <div className="control-owner-banner" role="status" aria-live="polite">
              <strong>Owned: {currentOwner}</strong>
            </div>
          ) : null}
        </div>
        <div className="control-item-inputs">
          {!requiresTakeover && (widget === 'number_button') ? (
            <>
              <input
                className="data-control"
                type="number"
                step={control?.value_write?.step ?? 'any'}
                min={control?.value_write?.min}
                max={control?.value_write?.max}
                value={valueDraft ?? ''}
                onChange={(event) => controlProps?.onDraftChange?.(valueTarget, event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    controlProps?.onWrite?.(control);
                  }
                }}
              />
              <button className="warning-button" disabled={!target || !valueTarget || isWriting || controlProps?.controlUiLoading} onClick={() => controlProps?.onWrite?.(control)}>
                {isWriting ? 'Sending…' : actionLabel}
              </button>
            </>
          ) : !requiresTakeover && (widget === 'button' || writeKind === 'pulse') ? (
            <button className="warning-button" disabled={!target || isWriting || controlProps?.controlUiLoading} onClick={() => controlProps?.onWrite?.(control, true)}>
              {isWriting ? 'Sending…' : actionLabel}
            </button>
          ) : !requiresTakeover && (widget === 'toggle' || writeKind === 'bool') ? (
            <button className={`toggle-button ${controlBoolValue(control?.current_value) ? 'is-resume' : 'is-pause'}`} disabled={!target || isWriting || controlProps?.controlUiLoading} onClick={() => controlProps?.onWrite?.(control, !controlBoolValue(control?.current_value))}>
              {isWriting ? 'Writing…' : actionLabel}
            </button>
          ) : !requiresTakeover ? (
            <>
              <input
                className="data-control"
                type={widget === 'number' || writeKind === 'number' ? 'number' : 'text'}
                step={control?.write?.step ?? 'any'}
                min={control?.write?.min}
                max={control?.write?.max}
                value={draftValue ?? ''}
                onChange={(event) => controlProps?.onDraftChange?.(target, event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    controlProps?.onWrite?.(control);
                  }
                }}
              />
              <button className="primary-button" disabled={!target || isWriting || controlProps?.controlUiLoading} onClick={() => controlProps?.onWrite?.(control)}>
                {isWriting ? 'Writing…' : actionLabel}
              </button>
            </>
          ) : null}
          {requiresTakeover && canTakeControl ? (
            <button
              className="warning-button control-takeover-button"
              disabled={!target || isWriting || controlProps?.controlUiLoading}
              onClick={() => controlProps?.onWrite?.(control, control?.current_value)}
            >
              {isWriting ? 'Taking…' : 'Take control'}
            </button>
          ) : null}
          {requiresTakeover && !canTakeControl ? (
            <div className="small-text warning">
              {control?.safety_locked
                ? 'Safety lock active; takeover disabled.'
                : normalizedOwner === 'safety'
                  ? 'This control is owned by safety and cannot be taken over from this widget.'
                  : 'This control is owned and cannot be taken over from this widget.'}
            </div>
          ) : null}
          {inlineError ? <div className="small-text warning">Write failed: {inlineError}</div> : null}
        </div>
      </div>
    </div>
  );
}

const MODULE_CATEGORY_ORDER = ['Control', 'Data', 'Scenario', 'Archive', 'System'];

function moduleCategoryRank(category) {
  const index = MODULE_CATEGORY_ORDER.indexOf(String(category || ''));
  return index >= 0 ? index : MODULE_CATEGORY_ORDER.length;
}

function compareWorkspaceModules(left, right) {
  const categoryDelta = moduleCategoryRank(left?.category) - moduleCategoryRank(right?.category);
  if (categoryDelta !== 0) return categoryDelta;

  const orderDelta = Number(left?.sortOrder || 0) - Number(right?.sortOrder || 0);
  if (orderDelta !== 0) return orderDelta;

  return String(left?.label || '').localeCompare(String(right?.label || ''));
}

const BASE_WORKSPACE_MODULES = [
  {
    type: 'data-recording',
    label: 'Data Recording',
    description: 'Recording controls and frequency setup.',
    category: 'Data',
    sortOrder: 10,
    defaultCols: 8,
    defaultRows: 1,
    render: (props) => <DataRecordingCard {...props.dataProps} />,
  },
  {
    type: 'data-loadstep',
    label: 'Loadstep Status',
    description: 'Latest loadstep summary and readiness.',
    category: 'Data',
    sortOrder: 20,
    defaultCols: 4,
    defaultRows: 1,
    render: (props) => <DataLoadstepStatusCard {...props.dataProps} />,
  },
  {
    type: 'data-snapshot',
    label: 'Data Snapshot',
    description: 'Searchable live parameter table.',
    category: 'Data',
    sortOrder: 30,
    defaultCols: 12,
    defaultRows: 3,
    render: (props) => <DataSnapshotBrowserCard {...props.dataProps} />,
  },
  {
    type: 'scenario-controls',
    label: 'Run Controls',
    description: 'Start, stop, pause, and step the active run.',
    category: 'Scenario',
    sortOrder: 10,
    defaultCols: 8,
    defaultRows: 1,
    render: (props) => (
      <div className="workspace-module-panel">
        <ScenarioControlsBar {...props.scenarioProps} />
      </div>
    ),
  },
  {
    type: 'scenario-summary',
    label: 'Run Summary',
    description: 'Current run phase, step, and package.',
    category: 'Scenario',
    sortOrder: 20,
    defaultCols: 4,
    defaultRows: 1,
    render: (props) => <ScenarioSummaryCard scenario={props.scenarioProps?.scenario} scenarioPackage={props.scenarioProps?.scenarioPackage} />,
  },
  {
    type: 'scenario-events',
    label: 'Event Log',
    description: 'Recent scenario run event stream.',
    category: 'Scenario',
    sortOrder: 40,
    defaultCols: 12,
    defaultRows: 3,
    render: (props) => <ScenarioEventLogCard scenario={props.scenarioProps?.scenario} />,
  },
  {
    type: 'scenario-package',
    label: 'Package Editor',
    description: 'Import, edit, and manage scenario packages.',
    category: 'Scenario',
    sortOrder: 30,
    defaultCols: 8,
    defaultRows: 2,
    render: (props) => <ScenarioPackageCard {...props.scenarioProps} />,
  },
  {
    type: 'archive-summary',
    label: 'Archive Summary',
    description: 'Disk and bundle totals.',
    category: 'Archive',
    sortOrder: 10,
    defaultCols: 4,
    defaultRows: 1,
    render: (props) => <ArchiveSummaryCard archivePayload={props.archiveProps?.archivePayload} />,
  },
  {
    type: 'archive-files',
    label: 'Archive Files',
    description: 'Browse, view, download, and delete archives.',
    category: 'Archive',
    sortOrder: 20,
    defaultCols: 12,
    defaultRows: 3,
    render: (props) => <ArchiveFilesCard {...props.archiveProps} />,
  },
  {
    type: 'system-actions',
    label: 'System Launchers',
    description: 'ParameterDB and storage manager shortcuts.',
    category: 'System',
    sortOrder: 10,
    defaultCols: 8,
    defaultRows: 1,
    render: (props) => <SystemActionsWidget systemProps={props.systemProps} />,
  },
  {
    type: 'system-node',
    label: 'Node Info',
    description: 'Fermenter identity and address.',
    category: 'System',
    sortOrder: 20,
    defaultCols: 4,
    defaultRows: 1,
    render: (props) => <SystemNodeWidget systemProps={props.systemProps} />,
  },
  {
    type: 'system-persistence',
    label: 'Persistence Status',
    description: 'Backend health for snapshots, sources, and rules.',
    category: 'System',
    sortOrder: 30,
    defaultCols: 6,
    defaultRows: 2,
    render: (props) => <SystemPersistenceWidget systemProps={props.systemProps} />,
  },
  {
    type: 'system-services',
    label: 'Healthy Services',
    description: 'Live service availability list.',
    category: 'System',
    sortOrder: 40,
    defaultCols: 6,
    defaultRows: 2,
    render: (props) => <SystemServicesWidget systemProps={props.systemProps} />,
  },
];

export function getWorkspaceModules(props = {}) {
  const controlCardModules = visibleControlCards(props?.controlProps)
    .map((card) => {
      const controls = Array.isArray(card?.controls) ? card.controls : [];
      const moduleType = controlCardType(card);
      const cardTitle = String(card?.title || 'Control Card').trim() || 'Control Card';
      return {
        type: moduleType,
        label: cardTitle,
        description: `${controls.length} control${controls.length === 1 ? '' : 's'}`,
        category: 'Control',
        sortOrder: 10,
        defaultCols: controls.length > 5 ? 12 : controls.length > 2 ? 8 : 6,
        defaultRows: controls.length > 5 ? 3 : 2,
        render: (renderProps) => <ControlCardWidget type={moduleType} controlProps={renderProps.controlProps} />,
      };
    });

  const controlFieldModules = visibleControlCards(props?.controlProps)
    .flatMap((card) => {
      const controls = Array.isArray(card?.controls) ? card.controls : [];
      const cardTitle = String(card?.title || 'Control Card').trim() || 'Control Card';
      return controls.map((control) => {
        const moduleType = controlFieldType(card, control);
        const label = String(control?.label || control?.target || 'Control').trim() || 'Control';
        const widget = String(control?.widget || '');
        const writeKind = String(control?.write?.kind || '');
        const target = String(control?.target || '').trim();
        const kindLabel = widget || writeKind || 'action';
        const isNumeric = widget === 'number' || widget === 'number_button' || writeKind === 'number';
        const isText = !widget || widget === 'text';
        return {
          type: moduleType,
          label: `${cardTitle} · ${label}`,
          description: [kindLabel, target].filter(Boolean).join(' · '),
          category: 'Control',
          sortOrder: 20,
          defaultCols: isNumeric || isText ? 6 : 4,
          defaultRows: 1,
          render: (renderProps) => <ControlFieldWidget type={moduleType} controlProps={renderProps.controlProps} />,
        };
      });
    });

  return [...BASE_WORKSPACE_MODULES, ...controlCardModules, ...controlFieldModules].sort(compareWorkspaceModules);
}

export function getWorkspaceModule(type, props = {}) {
  const rawType = String(type || '');
  const legacyTypeMap = {
    'schedule-controls': 'scenario-controls',
    'schedule-summary': 'scenario-summary',
    'schedule-events': 'scenario-events',
    'schedule-workbook': 'scenario-package',
  };
  const resolvedType = legacyTypeMap[rawType] || rawType;
  const found = getWorkspaceModules(props).find((item) => item.type === resolvedType);
  if (found) return found;
  if (rawType.startsWith('control-card:')) {
    return {
      type: rawType,
      label: 'Control Card',
      description: 'Device-level control widget.',
      category: 'Control',
      defaultCols: 6,
      defaultRows: 2,
      render: (renderProps) => <ControlCardWidget type={rawType} controlProps={renderProps.controlProps} />,
    };
  }
  if (rawType.startsWith('control-field:')) {
    return {
      type: rawType,
      label: 'Control Field',
      description: 'Single control widget.',
      category: 'Control',
      defaultCols: 6,
      defaultRows: 1,
      render: (renderProps) => <ControlFieldWidget type={rawType} controlProps={renderProps.controlProps} />,
    };
  }
  return null;
}
